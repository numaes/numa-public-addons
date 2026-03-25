model_name = 'conversation.driver.facebook'
if model_name in env:
    model = env[model_name]
    print(f"--- Inspeccionando {model_name} ---")
    print(f"Campos en _fields: {list(model._fields.keys())}")
    
    if 'driver_id' in model._fields:
        f = model._fields['driver_id']
        print(f"Detalle de driver_id: model={f.model_name}, related={f.related}, store={f.store}")
    
    # Probar creación mínima para ver qué campos acepta el ORM
    try:
        # Intentamos con un campo que NO debería estar pero está en _fields
        vals = {'id': 999999, 'driver_id': 1}
        print(f"Probando create con {vals}...")
        # Esto debería fallar con el error que estamos viendo
        model.create([vals])
    except Exception as e:
        print(f"Error esperado en create: {e}")
else:
    print(f"Modelo {model_name} no encontrado.")
