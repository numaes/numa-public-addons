# Buscar la clase original cargada por Odoo
for name, model in env.registry.items():
    if name == 'crm.lead':
        # Intentar encontrar de qué módulo viene
        print(f"Model: {name}, Class: {type(model)}")
        # Si model es una instancia de MetaModel (la clase del modelo en el registro), 
        # su tipo es MetaModel. Para obtener el MRO de la clase misma:
        mro = model.mro() if hasattr(model, 'mro') else type(model).mro()
        for base in mro:
             if hasattr(base, '_depend_models'):
                 val = getattr(base, '_depend_models')
                 # Ver si está en el __dict__ de la clase base real (no la clase proxy de Odoo)
                 in_dict = '_depend_models' in base.__dict__
                 print(f"Base: {base.__name__}, has_attr: True, in_dict: {in_dict}, val: {val}")
