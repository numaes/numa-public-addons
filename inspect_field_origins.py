def inspect_model_fields(model_name):
    if model_name not in env:
        print(f"Modelo {model_name} no encontrado.")
        return
    model = env[model_name]
    print(f"\n--- Inspeccionando campos de {model_name} ---")
    fields_to_check = ['concrete_model_id', 'poly_base_id', 'id', 'name', 'driver_id']
    for fname in fields_to_check:
        if fname in model._fields:
            field = model._fields[fname]
            # En Odoo 18, el modelo se guarda en 'model_name'
            origin = getattr(field, 'model_name', 'N/A')
            is_related = bool(getattr(field, 'related', False))
            related_path = getattr(field, 'related', '')
            print(f"Campo: {fname:20} | Origin Model: {origin:30} | Related: {str(is_related):5} | Path: {related_path}")
        else:
            # print(f"Campo: {fname:20} | NO PRESENTE")
            pass

inspect_model_fields('ir.poly_base')
inspect_model_fields('conversation.driver')
inspect_model_fields('facebook.account')
inspect_model_fields('conversation.driver.facebook')
