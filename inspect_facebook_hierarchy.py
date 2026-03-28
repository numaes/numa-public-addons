def inspect_poly_hierarchy(model_name):
    if model_name not in env:
        print(f"Modelo {model_name} no encontrado.")
        return
    
    model = env[model_name]
    print(f"\n{'='*60}")
    print(f"INSPECCIONANDO MODELO: {model_name}")
    print(f"{'='*60}")
    
    # 1. Depend models (lo que el modelo declara como sus bases)
    if hasattr(type(model), '_poly_get_depend_models'):
        deps = type(model)._poly_get_depend_models()
        print(f"Dependencias polimórficas (_depend_models): {deps}")
    
    # 2. MRO (para ver la jerarquía real de Python)
    print("\nJerarquía de clases (MRO):")
    for cls in type(model).mro():
        if 'odoo' in str(cls) or 'numa' in str(cls):
            print(f"  - {cls}")

    # 3. Inspección de campos críticos
    print("\nInspección de campos en _fields:")
    # Campos a seguir en la jerarquía
    fields_to_check = ['id', 'poly_base_id', 'concrete_model_id', 'name', 'driver_id']
    
    # Añadir los campos de enlace de las dependencias
    if hasattr(type(model), '_poly_get_depend_models'):
        fields_to_check.extend(type(model)._poly_get_depend_models().values())

    unique_fields = sorted(list(set(fields_to_check)))
    
    print(f"{'Campo':<25} | {'Model Name':<30} | {'Store':<5} | {'Related'}")
    print("-" * 100)
    
    for fname in unique_fields:
        if fname in model._fields:
            f = model._fields[fname]
            m_name = getattr(f, 'model_name', 'N/A')
            store = getattr(f, 'store', 'N/A')
            related = getattr(f, 'related', 'None')
            print(f"{fname:<25} | {m_name:<30} | {str(store):<5} | {related}")
        else:
            print(f"{fname:<25} | {'N/A (No en _fields)':<30} | {'-':<5} | {'-'}")

    # 4. Verificar si hay contaminación (campos que NO deberían estar)
    # Por ejemplo, driver_id no debería ser un campo almacenado si es un related
    # o no debería estar en modelos que son bases.

# Jerarquía de facebook.account
inspect_poly_hierarchy('ir.poly_base')
inspect_poly_hierarchy('conversation.driver')
inspect_poly_hierarchy('conversation.driver.facebook')
inspect_poly_hierarchy('facebook.account')
