from . import common
from . import test_miniqweb
from . import test_fsm_live
from . import test_fsm_template_mail

from . import test_fsm_instance_filters

# The note that used to sit here named five files as "dead API" and kept them in the
# directory as reference. Seven files were actually unimported, and running them was
# the only way to find out that they were not all in the same situation.
#
# Six targeted an API that no longer exists and are deleted; git has them if the old
# behaviour ever needs reading, and the live engine is covered by test_fsm_live:
#   test_fsm, test_fsm_instance, test_fsm_timer, test_fsm_debug, test_fsm_engine
#     -> onchange_text_definition / json_logic_schema / consume_event
#   test_fsm_form_input
#     -> an `fsm.form_input` with `instance_id` and `unrelated_identifier`; the model
#        has `name` and `json_event` and nothing else
#
# test_fsm_templates is the one that was worth keeping: `render_page` and
# `action_send_template_mail` are live, and two of its six tests pass. The other four
# are skipped with the reason on each — they need a complete `fsm.definition` fixture,
# which `common.py` does not build.
from . import test_fsm_templates
