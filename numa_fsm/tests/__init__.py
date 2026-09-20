from . import common
from . import test_miniqweb
from . import test_fsm_live
from . import test_fsm_template_mail

# NOTE: test_fsm / test_fsm_instance / test_fsm_templates / test_fsm_timer / test_fsm_form_input
# targeted a DEAD API of fsm.definition/fsm.instance (text_definition /
# onchange_text_definition / json_logic_schema / consume_event) and raised errors. The live API
# (json_ui_schema → compiled, start/_process_event_sync, current_state_id, instance_variables,
# polymorphic timers) is covered in test_fsm_live.py. The old files are kept in the repo as a
# reference but are NOT imported.
from . import test_fsm_instance_filters
