print("--- Verificando IrPolyBase en el registro ---")
model = env['ir.poly_base']
print(f"Campos: {list(model._fields.keys())}")
if 'concrete_model_id' in model._fields:
    f = model._fields['concrete_model_id']
    print(f"concrete_model_id info: type={f.type}, store={f.store}, required={f.required}")

# Probar creación directa simplificada
try:
    print("\nProbando creación directa en ir.poly_base...")
    model_id = env['ir.model']._get_id('res.partner')
    vals = {'concrete_model_id': model_id}
    print(f"Vals a pasar: {vals}")
    res = model.sudo().create(vals)
    print(f"Creado ID: {res.id}")
    env.cr.rollback()
except Exception as e:
    print(f"Error en creación directa: {e}")
    import traceback
    traceback.print_exc()
    env.cr.rollback()
