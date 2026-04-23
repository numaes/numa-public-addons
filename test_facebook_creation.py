try:
    model = env['facebook.account']
    print("--- Probando creación de facebook.account ---")
    
    # facebook.account requiere name (heredado de conversation.driver)
    # y otros campos de facebook.account mismo
    vals = {
        'name': 'Test Facebook Account Poly',
        'account_id': '123456789',
        'app_id': '987654321',
        'app_secret': 'secret',
    }
    
    # La creación debería crear automáticamente el registro en conversation.driver
    # y este a su vez en ir.poly_base (si la jerarquía es correcta).
    record = model.create(vals)
    print(f"Registro creado exitosamente ID {record.id}")
    print(f"poly_base_id: {record.poly_base_id.id if record.poly_base_id else 'None'}")
    print(f"driver_id: {record.driver_id.id if record.driver_id else 'None'}")
    print(f"Nombre (desde driver): {record.name}")
    
    # Verificar que el ID de facebook.account es el mismo que el de driver_id (herencia polimórfica)
    if record.id == record.driver_id.id:
        print("Sincronización de IDs exitosa (Herencia polimórfica).")
    else:
        print(f"IDs NO coinciden: facebook={record.id}, driver={record.driver_id.id}")

    env.cr.rollback()
    print("Rollback realizado.")

except Exception as e:
    print(f"Error en creación: {e}")
    import traceback
    traceback.print_exc()
    env.cr.rollback()
