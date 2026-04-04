import logging
_logger = logging.getLogger(__name__)

# Modelos a probar
# crm.lead parece ser una base para numa_fsm_crm
# hr.employee parece ser una base para numa_fsm_hr
# fsm.definition parece ser una base para crm.bot y hr.bot

models_to_test = ['crm.lead', 'hr.employee', 'fsm.definition']

for model_name in models_to_test:
    if model_name not in env:
        print(f"Modelo {model_name} no encontrado en el entorno.")
        continue
    
    model = env[model_name]
    print(f"\n--- Probando Modelo: {model_name} ---")
    
    # Verificar si es polimórfico según nuestra lógica
    model_class = type(model)
    is_poly = hasattr(model_class, '_poly_get_depend_models') and model_class._poly_get_depend_models()
    print(f"¿Es polimórfico (depend_models)? {bool(is_poly)}")
    
    # Verificar campos inyectados
    # poly_base_id es un campo base de numa_poly
    if 'poly_base_id' in model._fields:
        print("Campo 'poly_base_id' encontrado (Correcto).")
    else:
        print("Campo 'poly_base_id' NO encontrado.")

    # Verificar si tiene campos inyectados (si es polimórfico)
    if is_poly:
        deps = model_class._poly_get_depend_models()
        print(f"Dependencias: {deps}")
        for base_model, field_name in deps.items():
            if field_name in model._fields:
                print(f"Campo de relación '{field_name}' a '{base_model}' encontrado.")
                # Probar acceso
                try:
                    record = model.search([], limit=1)
                    if record:
                        val = getattr(record, field_name)
                        print(f"Acceso a '{field_name}' exitoso.")
                except Exception as e:
                    print(f"Error accediendo a '{field_name}': {e}")
            else:
                print(f"Campo de relación '{field_name}' a '{base_model}' NO encontrado.")

    # Verificar un campo no polimórfico estándar
    if 'name' in model._fields:
        print("Campo 'name' encontrado (Estándar).")

# Probar creación básica
def test_creation(model_name):
    if model_name not in env: return
    try:
        model = env[model_name]
        print(f"\nProbando creación en {model_name}...")
        # Intentamos crear un registro simple si es posible
        # Para crm.lead, name es requerido
        vals = {'name': 'Test Poly Creation'}
        # Si es polimórfico, Odoo debería manejar la creación de poly_base_id vía el mixin/clase base
        record = model.create(vals)
        print(f"Registro creado exitosamente ID {record.id}")
        if 'poly_base_id' in record._fields:
            print(f"poly_base_id: {record.poly_base_id.id}")
        # Intentamos rollback para no ensuciar
        env.cr.rollback()
        print("Rollback realizado.")
    except Exception as e:
        print(f"Error en creación para {model_name}: {e}")
        env.cr.rollback()

test_creation('crm.lead')
