# Import order is critical for polymorphic inheritance
# crm_lead must be imported first to set up _depend_models before fsm.instance is used
from . import crm_lead
from . import crm_bot
