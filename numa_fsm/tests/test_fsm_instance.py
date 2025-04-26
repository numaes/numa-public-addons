# -*- coding: utf-8 -*-
from odoo.addons.numa_fsm.tests.common import TestFSMCommon
import json
from odoo import exceptions
from markupsafe import Markup


class TestFSMInstance(TestFSMCommon):
    """
    Test class for FSM Instance functionality.
    This class tests the instance-related functionality of the FSM module.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up the test environment.
        This method is called before any tests are run.
        It initializes the test environment and creates test data specific to instance tests.
        """
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context,
            test_queue_job_no_delay=True,  # no jobs thanks
        ))

    def test_instance_creation(self):
        """
        Test the creation of an FSM instance.
        This test verifies that an FSM instance can be created with the correct parameters.
        """
        # Create a test FSM definition
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Creation Test',
        })
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
            'name': 'test_creation_instance',
        })
        
        # Check that the instance was created correctly
        self.assertTrue(fsmi, "FSM instance was not created")
        self.assertEqual(fsmi.definition_id.id, fsmd.id, "FSM instance has incorrect definition")
        self.assertEqual(fsmi.name, 'test_creation_instance', "FSM instance has incorrect name")
        self.assertEqual(fsmi.state, 'init', "FSM instance has incorrect initial state")

    def test_instance_start(self):
        """
        Test starting an FSM instance.
        This test verifies that an FSM instance can be started and executes the start code.
        """
        # Create a test FSM definition with start code
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Start Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
            v = 42
        @states
            @state initialState
                @event testEvent
                    pass
        '''
        fsmd.onchange_text_definition()
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Check that the instance was started correctly
        self.assertEqual(fsmi.state, 'running', "FSM instance was not started")
        self.assertEqual(fsmi.current_state, 'initialState', 
                         "FSM instance did not execute start code correctly")
        
        # Check that the environment was initialized correctly
        env = json.loads(fsmi.json_instance_values)
        self.assertEqual(env.get('v'), 42, "FSM instance environment was not initialized correctly")

    def test_instance_end(self):
        """
        Test ending an FSM instance.
        This test verifies that an FSM instance can be ended.
        """
        # Create a test FSM definition
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance End Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
        @states
            @state initialState
                @event endEvent
                    fsm_instance.end()
        '''
        fsmd.onchange_text_definition()
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Check that the instance was started correctly
        self.assertEqual(fsmi.state, 'running', "FSM instance was not started")
        
        # End the FSM instance
        fsmi.process_event({'name': 'endEvent'}, {})
        
        # Check that the instance was ended correctly
        self.assertEqual(fsmi.state, 'ended', "FSM instance was not ended")

    def test_instance_logging(self):
        """
        Test FSM instance logging.
        This test verifies that logging can be enabled and disabled for an FSM instance.
        """
        # Create a test FSM definition
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Logging Test',
        })
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Check that logging is initially disabled
        self.assertFalse(fsmi.logging, "FSM instance logging should be disabled by default")
        
        # Enable logging
        fsmi.start_logging()
        
        # Check that logging is enabled
        self.assertTrue(fsmi.logging, "FSM instance logging was not enabled")
        
        # Disable logging
        fsmi.stop_logging()
        
        # Check that logging is disabled
        self.assertFalse(fsmi.logging, "FSM instance logging was not disabled")

    def test_instance_change_state(self):
        """
        Test changing the state of an FSM instance.
        This test verifies that the state of an FSM instance can be changed.
        """
        # Create a test FSM definition
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Change State Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
        @states
            @state initialState
                @event changeStateEvent
                    fsm_instance.change_state('secondState')
            @state secondState
                @event all
                    pass
        '''
        fsmd.onchange_text_definition()
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Check that the instance is in the initial state
        self.assertEqual(fsmi.current_state, 'initialState', 
                         "FSM instance is not in the initial state")
        
        # Change the state
        fsmi.process_event({'name': 'changeStateEvent'}, {})
        
        # Check that the state was changed
        self.assertEqual(fsmi.current_state, 'secondState', 
                         "FSM instance state was not changed")

    def test_instance_set_page(self):
        """
        Test setting the current page of an FSM instance.
        This test verifies that the current page of an FSM instance can be set.
        """
        # Create a page template
        page_template = self.env['fsm.wf.page_template'].create({
            'name': 'Test Page',
            'body': '<div>This is a test page</div>',
        })
        
        # Create a test FSM definition with the page template
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Set Page Test',
            'pages': [(4, page_template.id)],
        })
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Set the current page
        fsmi.set_page('Test Page')
        
        # Check that the current page was set correctly
        self.assertEqual(fsmi.current_page.id, page_template.id, 
                         "FSM instance current page was not set correctly")
        
        # Try to set a non-existent page
        with self.assertRaises(exceptions.UserError):
            fsmi.set_page('Non-existent Page')

    def test_instance_render_dynamic_html(self):
        """
        Test rendering dynamic HTML in an FSM instance.
        This test verifies that dynamic HTML can be rendered in an FSM instance.
        """
        # Create a test FSM definition
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Render HTML Test',
        })
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
            'name': 'test_render_html_instance',
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Render dynamic HTML
        template = '<div>This is a test for {{ instance.name }}</div>'
        rendered_html = fsmi.render_dynamic_html(template)
        
        # Check that the HTML was rendered correctly
        self.assertTrue(rendered_html, "Dynamic HTML was not rendered")
        self.assertIn('test_render_html_instance', rendered_html, 
                      "Rendered HTML does not contain instance name")

    def test_instance_prepare_env(self):
        """
        Test preparing the environment of an FSM instance.
        This test verifies that the environment of an FSM instance can be prepared.
        """
        # Create a test FSM definition
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Prepare Env Test',
        })
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Set some data in the instance environment
        env = {'test_var': 'test_value'}
        fsmi.flush_env(env)
        
        # Prepare the environment
        prepared_env = fsmi.prepare_env()
        
        # Check that the environment was prepared correctly
        self.assertTrue(prepared_env, "FSM instance environment was not prepared")
        self.assertEqual(prepared_env.get('test_var'), 'test_value', 
                         "FSM instance environment was not prepared correctly")

    def test_instance_flush_env(self):
        """
        Test flushing the environment of an FSM instance.
        This test verifies that the environment of an FSM instance can be flushed.
        """
        # Create a test FSM definition
        fsmd = self.env['fsm.definition'].create({
            'name': 'Instance Flush Env Test',
        })
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Set some data in the instance environment
        env = {'test_var': 'test_value'}
        fsmi.flush_env(env)
        
        # Check that the environment was flushed correctly
        stored_env = json.loads(fsmi.json_instance_values)
        self.assertEqual(stored_env.get('test_var'), 'test_value', 
                         "FSM instance environment was not flushed correctly")
        
        # Flush an empty environment
        fsmi.flush_env({})
        
        # Check that the environment was cleared
        stored_env = json.loads(fsmi.json_instance_values)
        self.assertEqual(stored_env, {}, "FSM instance environment was not cleared")

    def test_error_handling(self):
        """
        Test error handling in FSM instances.
        This test verifies that errors are handled correctly in FSM instances.
        """
        # Create a test FSM definition with code that will raise an error
        fsmd = self.env['fsm.definition'].create({
            'name': 'Error Handling Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
        @states
            @state initialState
                @event errorEvent
                    # This will raise a NameError
                    undefined_variable = 42
        '''
        fsmd.onchange_text_definition()
        
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Enable logging to capture error messages
        fsmi.start_logging()
        
        # Trigger the error event and check that it's handled correctly
        with self.assertRaises(exceptions.UserError):
            fsmi.process_event({'name': 'errorEvent'}, {})