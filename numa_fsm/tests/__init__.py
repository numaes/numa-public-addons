from . import common
from . import test_miniqweb
from . import test_fsm_live

# NOTA: test_fsm / test_fsm_instance / test_fsm_templates / test_fsm_timer / test_fsm_form_input
# apuntaban a una API MUERTA de fsm.definition/fsm.instance (text_definition /
# onchange_text_definition / json_logic_schema / consume_event) y daban errores. La API viva
# (json_ui_schema → compilado, start/_process_event_sync, current_state_id, instance_variables,
# timers polimórficos) se cubre en test_fsm_live.py. Los archivos viejos se dejan en el repo como
# referencia pero NO se importan.
