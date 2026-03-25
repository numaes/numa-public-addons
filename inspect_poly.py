import pprint
poly_models = []
for name, model in env.registry.items():
    model_class = type(model)
    if hasattr(model_class, '_poly_get_depend_models'):
        deps = model_class._poly_get_depend_models()
        if deps:
            poly_models.append(name)

print(f"Modelos polimórficos detectados ({len(poly_models)}):")
pprint.pprint(poly_models)

if poly_models:
    test_model = poly_models[0]
    m = env[test_model]
    print(f"\n--- Detalle del modelo {test_model} ---")
    print(f"Depend models: {type(m)._poly_get_depend_models()}")
    print(f"Campos en _fields: {[f for f in m._fields if f.startswith('poly_') or f.startswith('related_')]}")
    if 'poly_base_id' in m._fields:
        f = m._fields['poly_base_id']
        print(f"poly_base_id info: type={f.type}, store={f.store}")
    
    # Probar acceso a un registro si existe
    record = m.search([], limit=1)
    if record:
        print(f"Registro ID {record.id} encontrado.")
        if 'poly_base_id' in record._fields:
            print(f"poly_base_id ID: {record.poly_base_id.id}")
