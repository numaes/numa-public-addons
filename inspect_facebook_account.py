model_name = 'facebook.account'
if model_name in env:
    model = env[model_name]
    model_class = type(model)
    print(f"--- Inspeccionando {model_name} ---")
    
    # Verificar si el helper está presente y qué devuelve
    if hasattr(model_class, '_poly_get_depend_models'):
        deps = model_class._poly_get_depend_models()
        print(f"Dependencias detectadas (_poly_get_depend_models): {deps}")
    else:
        print("El modelo NO tiene el método _poly_get_depend_models (No es polimórfico o no heredó de PolyBase)")

    # Verificar __dict__ de las bases para _depend_models
    for base in model_class.mro():
        d_models = base.__dict__.get('_depend_models')
        if d_models is not None:
             print(f"Base: {base.__name__}, _depend_models en __dict__: {d_models}")

    # Verificar campos inyectados
    poly_fields = [f for f in model._fields if f.startswith('poly_') or f.startswith('related_')]
    print(f"Campos polimórficos inyectados: {poly_fields}")
    
    if 'poly_base_id' in model._fields:
        print("Campo 'poly_base_id' presente.")
    
    # Intentar búsqueda básica
    try:
        count = model.search_count([])
        print(f"Registros encontrados: {count}")
    except Exception as e:
        print(f"Error en búsqueda: {e}")
else:
    print(f"Modelo {model_name} no encontrado en el registro.")
