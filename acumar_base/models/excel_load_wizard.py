from odoo import models, fields, api
from odoo import exceptions, _
from datetime import datetime, timedelta, date
import base64
import openpyxl
import tempfile
import logging
_logger = logging.getLogger(__name__)


TITLES = [
    # ('row_name', 'integer|float|date|datetime|string|boolean'),
    ('N° orden', 'integer'),
    ('Temática', 'string'),
    ('Título', 'string'),
    ('Fecha de Suscripción', 'date'),
    ('Identificación de la/s contrapartes', 'string'),
    ('Objeto', 'string'),
    ('Monto convenido', 'string'),
    ('Renovacion Automatica', 'boolean'),
    ('Fecha de Vencimiento', 'string'),
    ('ESTADO', 'string'),
    ('ALERTA', 'string'),
    ('Vigencia', 'string'),
    ('Orden/año', 'string'),
    ('Aprobación CD', 'string'),
    ('Expediente', 'string'),
    ('Obs1', 'string'),
    ('Obs2', 'string'),
]


date_base = datetime(1899, 12, 30, 0, 0, 0)


class ExcelLoadWizard(models.TransientModel):
    _name = 'acumar.excel_load_wizard'
    _description = 'Importar desde planilla de Acumar'

    filedata = fields.Binary('Archivo')
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        'Estado',
        default='draft',
    )
    error_msgs = fields.Text('Mensajes de error')

    def get_titles(self, sheet, title_definition, double_titles=False):
        found_titles = set()
        title_catalog = {}
        column = 0
        row1 = sheet[3]
        row2 = sheet[4]
        for col_nbr in range(len(row1)):
            if double_titles:
                if row2[col_nbr].value:
                    value = row2[col_nbr].value
                elif row1[col_nbr].value:
                    value = row1[col_nbr].value
                else:
                    value = ''
            else:
                value = row1[col_nbr].value

            for name, ttype in title_definition:
                title = str(value).strip().lower()
                if name.lower() == title:
                    found_titles.add(name)
                    counter = 2
                    name_expanded = None
                    while name_expanded in title_catalog:
                        name_expanded = name + str(counter)
                        counter += 1
                    title_catalog[name if not name_expanded else name_expanded] = column, ttype
            column += 1

        not_found_titles = []
        for name, ttype in title_definition:
            if name not in found_titles:
                not_found_titles.append(name)
        if not_found_titles:
            raise exceptions.ValidationError(_('No se han encontrado los siguientes títulos %s') %
                                             (tuple(not_found_titles),))

        return title_catalog

    def get_rows(self, sheet, titles, double_titles=False):
        rows = []
        row_number = 4 if double_titles else 5
        for current_row in sheet.iter_rows(min_row=5 if double_titles else 4,
                                           values_only=True):
            row_data = {}
            for column_name, column_definition in titles.items():
                column_nbr, column_type = column_definition

                raw_data = current_row[column_nbr]

                if column_type == 'date':
                    try:
                        if isinstance(raw_data, (int, float)):
                            if float(raw_data) > 2:
                                dt = date_base + timedelta(days=float(raw_data))
                                converted_data = dt.date()
                            else:
                                converted_data = False
                        elif not raw_data:
                            converted_data = False
                        elif isinstance(raw_data, str):
                            converted_data = False
                            if raw_data.upper() not in ('A REVISAR', 'S/D') \
                               and raw_data[2] == '/' and raw_data[5] == '/':
                                converted_data = date(
                                    year=int(raw_data[6:10]),
                                    month=int(raw_data[3:5]),
                                    day=int(raw_data[0:2])
                                )
                        elif isinstance(raw_data, datetime):
                            converted_data = raw_data.date()
                        elif isinstance(raw_data, date):
                            converted_data = raw_data
                        else:
                            raise exceptions.ValidationError(_('No es una fecha'))
                    except Exception:
                        raise exceptions.ValidationError(
                            _(f"En la fila {row_number}, el campo {column_name} debe ser una fecha!")
                        )
                elif column_type == 'datetime':
                    try:
                        if isinstance(raw_data, (int, float)):
                            converted_data = date_base + timedelta(days=float(raw_data))
                        elif not raw_data:
                            converted_data = None
                        else:
                            raise exceptions.ValidationError('No es fecha y hora')
                    except Exception:
                        raise exceptions.ValidationError(
                            _(f"En la fila {row_number}, el campo {column_name} debe ser fecha y hora!")
                        )
                elif column_type == 'integer':
                    try:
                        if isinstance(raw_data, (int, float)):
                            converted_data = int(raw_data)
                        elif not raw_data:
                            converted_data = 0
                        elif isinstance(raw_data, str):
                            converted_data = int(raw_data)
                        else:
                            raise exceptions.ValidationError('No es un entero')
                    except Exception:
                        raise exceptions.ValidationError(
                            _(f"En la fila {row_number}, el campo {column_name} debe ser un entero!")
                        )
                elif column_type == 'float':
                    try:
                        if isinstance(raw_data, (int, float)):
                            converted_data = int(raw_data)
                        elif not raw_data or raw_data == ' ':
                            converted_data = 0.0
                        elif isinstance(raw_data, str) and raw_data.endswith('%'):
                            just_number = raw_data[:-1]
                            just_number = just_number.replace('.', '')
                            just_number = just_number.replace(',', '.')
                            converted_data = float(just_number) / 100.0
                        elif isinstance(raw_data, str):
                            converted_data = float(raw_data)
                        else:
                            raise exceptions.ValidationError('No es un número pto flotante')
                    except Exception:
                        raise exceptions.ValidationError(
                            _(f"En la fila {row_number}, el campo {column_name} debe ser un float!")
                        )
                elif column_type == 'boolean':
                    try:
                        if isinstance(raw_data, (int, float)):
                            converted_data = True if int(raw_data) else False
                        elif not raw_data or raw_data == ' ':
                            converted_data = False
                        elif isinstance(raw_data, str):
                            converted_data = False if raw_data.upper not in ('S', 'SI', 'SÍ', 'YES', 'Y') else False
                        else:
                            raise exceptions.ValidationError('No es un booleano')
                    except Exception:
                        raise exceptions.ValidationError(
                            _(f"En la fila {row_number}, el campo {column_name} debe ser Si o No!")
                        )
                else:
                    # Anything else including string
                    if not raw_data or (isinstance(raw_data, (int, float)) and raw_data == 0):
                        converted_data = ''
                    else:
                        converted_data = str(raw_data).strip()

                row_data[column_name] = converted_data
            rows.append(row_data)
            row_number += 1
        return rows

    def get_datos(self, sheet):
        agreement_model = self.env['acumar.acuerdo']
        contraparte_model = self.env['acumar.contraparte']
        tematica_model = self.env['acumar.tematica']

        titles = self.get_titles(sheet, TITLES)

        error_msgs = []

        row_count = 3
        for row in self.get_rows(sheet, titles):
            row_count += 1
            if not row['N° orden']:
                continue

            try:
                _logger.info('Leyendo %s' % row['Título'])

                nro_de_orden = row['N° orden']

                tematica_id = tematica_model.search(
                    [('name', '=', row['Temática'])],
                    limit=1,
                )
                if not tematica_id:
                    tematica_id = tematica_model.create({
                        'name': row['Temática'],
                    })

                titulo = row['Título']
                fecha_de_suscripcion = row['Fecha de Suscripción']

                contrapartes = contraparte_model
                for nombre in (row['Identificación de la/s contrapartes'] or '').split('-'):
                    nombre = nombre.strip()
                    if not nombre:
                        continue
                    if nombre == 'ACUMAR':
                        continue
                    contraparte = contraparte_model.search(
                        [('name', '=', nombre)],
                        limit=1,
                    )
                    if not contraparte:
                        contraparte = contraparte_model.create(dict(
                            name=nombre,
                        ))
                    contrapartes |= contraparte

                objeto = row['Objeto']
                monto_convenido = row['Monto convenido']
                obs2 = ''
                if isinstance(monto_convenido, str):
                    try:
                        monto_convenido = float(monto_convenido.upper())
                    except Exception:
                        monto_convenido = 0.0
                        obs2 = f'Monto: {monto_convenido}'
                renovacion_automatica = row['Renovacion Automatica']
                fecha_de_vencimiento = row['Fecha de Vencimiento']
                if isinstance(fecha_de_vencimiento, str):
                    try:
                        fecha_de_vencimiento = datetime.strptime(fecha_de_vencimiento, '%Y-%m-%d %H:%M:%S').date()
                    except Exception:
                        obs2 += '\nFecha de vencimiento: %s' % fecha_de_vencimiento
                        fecha_de_vencimiento = False
                elif isinstance(fecha_de_vencimiento, date):
                    pass
                elif isinstance(fecha_de_vencimiento, datetime):
                    fecha_de_vencimiento = fecha_de_vencimiento.date()
                else:
                    fecha_de_vencimiento = False

                estado = row['ESTADO']
                if estado in ('VENCIDO', 'A REVISAR', 'RENOVACION AUTOMATICA', 'S/D'):
                    estado = {
                        'VENCIDO': 'terminated',
                        'A REVISAR': 'draft',
                        'RENOVACION AUTOMATICA': 'running',
                        'S/D': 'sd'
                    }[estado]
                elif isinstance(estado, float):
                    estado = 'running'
                else:
                    obs2 = obs2 + ('\nEstado: %s' % estado)
                    estado = 'draft'

                alerta = row['ALERTA']
                vigencia = row['Vigencia']
                orden_anio = row['Orden/año']
                aprobacion_cd = row['Aprobación CD']
                expediente = row['Expediente']
                obs1 = row['Obs1']
                if row['Obs2']:
                    obs2 = row['Obs2'] + ('\n%s' % obs2)

                vals = dict(
                    name=titulo,
                    state=estado,
                    suscription_date=fecha_de_suscripcion,
                    tematica_id=tematica_id.id if tematica_id else False,
                    partners=[(4, c.id) for c in contrapartes],
                    goal=objeto,
                    agreed_amount=monto_convenido,
                    due_date=fecha_de_vencimiento,
                    to_be_checked=row['ESTADO'] == 'A REVISAR',
                    renovation_description=vigencia,
                    dc_approval=aprobacion_cd,
                    expediente=expediente,
                    order_year=orden_anio,
                    notes_1=obs1,
                    notes_2=obs2,
                    automatic_renovation=renovacion_automatica,
                    alert=alerta,
                )

                current_agreement = agreement_model.search(
                    [('sequence', '=', nro_de_orden)],
                    limit=1
                )
                if current_agreement:
                    current_agreement.write(vals)
                else:
                    agreement_model.create(dict(sequence=nro_de_orden, **vals))
            except Exception as e:
                error_msgs.append(f'Excepción inesperada en fila {row_count}: {str(e)}')

        self.error_msgs = '\n'.join(error_msgs)
        self.state = 'generated'

    def action_import(self):
        agreement_model = self.env['acumar.acuerdo']

        os_file, tmp_name = tempfile.mkstemp(suffix=".xlsx")
        tmp_file = open(os_file, 'wb')
        tmp_file.write(base64.b64decode(self.filedata))
        tmp_file.close()

        wb = openpyxl.load_workbook(tmp_name, data_only=True)

        sheet_names = wb.get_sheet_names()

        self.get_datos(wb.get_sheet_by_name(sheet_names[0]))

        if not self.error_msgs:
            agreement_model.recompute_all()
            return True

        return {
            "type": "ir.actions.act_window",
            "name": "Carga de excel",
            "res_model": "acumar.excel_load_wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
