model_name = 'crm.lead'
if model_name in env:
    model = env[model_name]
    model_class = type(model)
    print(f"--- Inspeccionando {model_name} ---")
    print(f"Clase: {model_class}")
    # print(f"MRO: {model_class.mro()}")
    for base in model_class.mro():
        has_attr = '_depend_models' in base.__dict__
        val = base.__dict__.get('_depend_models', 'NOT_IN_DICT')
        print(f"Base: {base.__name__}, has_attr: {has_attr}, val: {val}")
    
    if hasattr(model_class, '_poly_get_depend_models'):
        print(f"Result: {model_class._poly_get_depend_models()}")
else:
    print(f"Modelo {model_name} no encontrado.")
