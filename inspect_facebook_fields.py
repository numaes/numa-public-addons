model_name = 'facebook.account'
if model_name in env:
    model = env[model_name]
    print(f"--- Inspeccionando campos de {model_name} ---")
    
    driver_id_present = 'driver_id' in model._fields
    print(f"Campo 'driver_id' presente: {driver_id_present}")
    
    if driver_id_present:
        f = model._fields['driver_id']
        print(f"driver_id info: type={f.type}, comodel={f.comodel_name}")
        
    # Buscar campos de la base conversation.driver
    if 'conversation.driver' in env:
        driver_fields = env['conversation.driver']._fields.keys()
        print(f"Campos en conversation.driver (primeros 5): {list(driver_fields)[:5]}")
        
        # Verificar si alguno está inyectado en facebook.account
        injected = [f for f in driver_fields if f in model._fields and f not in ('id', 'create_uid', 'create_date', 'write_uid', 'write_date')]
        print(f"Campos de driver inyectados en facebook.account: {injected}")
        
        if injected:
            test_f = injected[0]
            f_obj = model._fields[test_f]
            print(f"Detalle de {test_f}: related={f_obj.related}, store={f_obj.store}, auto_join={getattr(f_obj, 'auto_join', 'N/A')}")
    else:
        print("Modelo conversation.driver no encontrado.")
else:
    print(f"Modelo {model_name} no encontrado.")
