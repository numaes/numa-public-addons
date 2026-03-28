from odoo.addons.numa_fsm_crm.models.crm_lead import CrmLead
print(f"--- Importación directa de CrmLead ---")
print(f"CrmLead: {CrmLead}")
print(f"_depend_models in CrmLead.__dict__: {'_depend_models' in CrmLead.__dict__}")
print(f"Valor: {CrmLead.__dict__.get('_depend_models', 'NOT_FOUND')}")

print(f"\nMRO de CrmLead: {CrmLead.mro()}")
for b in CrmLead.mro():
    if '_depend_models' in b.__dict__:
        print(f"Base {b.__name__} tiene _depend_models: {b.__dict__['_depend_models']}")

# Ver si fsm.instance tiene algo
try:
    from odoo.addons.numa_fsm.models.fsm import FSMInstance
    print(f"\nFSMInstance: {FSMInstance}")
    print(f"_depend_models in FSMInstance.__dict__: {'_depend_models' in FSMInstance.__dict__}")
    print(f"Valor: {FSMInstance.__dict__.get('_depend_models', 'NOT_FOUND')}")
except Exception as e:
    print(f"Error importando FSMInstance: {e}")
