# -*- coding: utf-8 -*-
from odoo.addons.numa_fsm.tests.common import TestFSMCommon
import json


class TestFSMDefinition(TestFSMCommon):
    """ Test running at-install to test flows independently to other modules """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context,
            test_queue_job_no_delay=True,  # no jobs thanks
        ))

    def test_fsm_definition_creation(self):
        fsmd = self.env['fsm.definition'].create(dict(
            name='Test01',
        ))
        fsmd.unlink()

    def test_fsm_definition_compiler(self):
        otherFSM = self.env['fsm.definition'].create(dict(
            name='otherFSM',
        ))
        fsmd = self.env['fsm.definition'].create(dict(
            name='Test01',
        ))

        # Test empty definition
        fsmd.text_definition = '''
        '''
        fsmd.onchange_text_definition()
        compiled_definition = json.loads(fsmd.json_compiled_definition)

        self.assertTrue(isinstance(compiled_definition, dict), 'Invalid JSON Compiled Definition')
        self.assertTrue('start_code' in compiled_definition, 'Invalid JSON Compiled Definition - No start_code')
        self.assertTrue('states' in compiled_definition, 'Invalid JSON Compiled Definition - No states dictionary')
        self.assertTrue(isinstance(compiled_definition['states'], dict),
                        'Invalid JSON Compiled Definition - States is not a dictionary')

        # Test trivial definition
        fsmd.text_definition = '''
        @extends otherFSM
        @start
            logger.info('Starting')
        @states
            @state initialState
                @event e1
                    logger.info('initialState - e1')
                @event e2
                    logger.info('initialState - e2')
            @state secondState
                @event e1,e2 pospone
                    logger.info('secondState - e1,e2')
                @event all
                    logger.info('secondState - all others')
        '''
        fsmd.onchange_text_definition()

        compiled_definition = json.loads(fsmd.json_compiled_definition)

        states = compiled_definition['states']
        self.assertTrue(len(states) == 2, 'Invalid States - Not recognized')
        self.assertTrue('initialState' in states, 'No initialState recognized')
        initialState = states['initialState']
        self.assertTrue(len(initialState) == 2, 'Not all events recognized')
        self.assertTrue('e1' in initialState, 'Event e1 not recognized in initialState')
        is_e1 = initialState['e1']
        self.assertTrue('code' in is_e1, 'Event e1 no code in initialState')
        self.assertTrue('pospone' in is_e1, 'Event e1 no pospone in initialState')
        is_e1_code = is_e1['code']
        self.assertTrue(is_e1_code == """logger.info('initialState - e1')""",
                        'Code for initialState, e1 not right')

        self.assertTrue('secondState' in states, 'No secondState recognized')
        secondState = states['secondState']
        self.assertTrue(len(secondState) == 3, 'Multiple events not recognized')
        self.assertTrue('e1' in secondState, 'Event e1 not recognized in secondState')
        ss_e1 = secondState['e1']
        self.assertTrue('code' in ss_e1, 'Event e1 no code in secondState')
        self.assertTrue(ss_e1['pospone'], 'Event e1 pospone wast not recognized secondState')
        ss_e1_code = ss_e1['code']
        self.assertTrue(ss_e1_code == """logger.info('secondState - e1,e2')""",
                        'Code for secondState, e1 not right')
        ss_e2_code = secondState['e2']['code']
        self.assertTrue(ss_e1_code == ss_e2_code, 'Code for e2 was not the same as e1 in second state')

        fsmd.unlink()

    def test_fsm_instance(self):
        otherFSM = self.env['fsm.definition'].create(dict(
            name='otherFSM',
        ))
        fsmd = self.env['fsm.definition'].create(dict(
            name='Test01',
        ))

        # Test empty definition
        fsmd.text_definition = '''
        '''
        fsmd.onchange_text_definition()
        compiled_definition = json.loads(fsmd.json_compiled_definition)

        self.assertTrue(isinstance(compiled_definition, dict), 'Invalid JSON Compiled Definition')
        self.assertTrue('start_code' in compiled_definition, 'Invalid JSON Compiled Definition - No start_code')
        self.assertTrue('states' in compiled_definition, 'Invalid JSON Compiled Definition - No states dictionary')
        self.assertTrue(isinstance(compiled_definition['states'], dict),
                        'Invalid JSON Compiled Definition - States is not a dictionary')

        #
        otherFSM.text_definition = '''
        @start
            v = 1
        @states
            @state initialState
                @event e1
                    v = 2
                @event e2
                    v = 3
                    fsm_instance.change_state('secondState')
            @state secondState
                @event e1,e2
                    v = 4
        '''
        otherFSM.onchange_text_definition()

        #
        fsmd.text_definition = '''
        @extends otherFSM
        @start
            v = 6
            fsm_instance.change_state('initialState')
            logger.info('Estamos en el start')
        @states
            @state initialState
                @event e1
                    v = 7
            @state secondState
                @event e1
                    v = 9
            @state all
                @event endMachine
                    fsm_instance.end()
        '''
        fsmd.onchange_text_definition()

        fsmi = self.env['fsm.instance'].create(dict(
            definition_id=fsmd.id,
        ))
        locals = json.loads(fsmi.json_instance_values)
        self.assertTrue('v' in locals, 'No locals collected on start')
        self.assertTrue(locals['v'] == 6, 'After start, wrong locals')
        self.assertTrue(fsmi.current_state == 'initialState', 'After start, wrong state')
        self.assertTrue(fsmi.fsm_state == 'running', 'FSM Instance not running after start')

        locals = fsmi.process_event(dict(name='e1'), locals)
        self.assertTrue('v' in locals, 'After first event, locals are lost')
        self.assertTrue(locals['v'] == 7, 'Wrong processing of e1 on initialState')

        locals = fsmi.process_event(dict(name='e2'), locals)
        self.assertTrue(locals['v'] == 3, 'Wrong processing of delegated event to parent on initialState')

        locals = fsmi.process_event(dict(name='e1'), locals)
        self.assertTrue(locals['v'] == 9, 'Wrong processing of delegated event to parent on secondState')

        locals = fsmi.process_event(dict(name='endMachine'), locals)
        self.assertTrue(fsmi.fsm_state == 'ended', 'FSM Instance cannot be ended')


