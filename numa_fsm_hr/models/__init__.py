# Import order is critical for polymorphic inheritance
# hr_employee must be imported first to set up _depend_models before fsm.instance is used
from . import hr_employee
from . import hr_bot
