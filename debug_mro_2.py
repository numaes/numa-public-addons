from odoo.addons.numa_fsm_crm.models.crm_lead import CrmLead
print(f"CrmLead class: {CrmLead}")
print(f"CrmLead __dict__ _depend_models: {CrmLead.__dict__.get('_depend_models')}")
print(f"CrmLead mro: {CrmLead.mro()}")
for b in CrmLead.mro():
    print(f"Base {b.__name__} in dict: {'_depend_models' in b.__dict__}, val: {b.__dict__.get('_depend_models')}")
