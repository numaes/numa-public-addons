# -*- coding: utf-8 -*-
from odoo.addons.numa_fsm.tests.common import TestFSMCommon
from datetime import timedelta
import json
from freezegun import freeze_time


class TestFSMTimer(TestFSMCommon):
    """
    Test class for FSM Timer functionality.
    This class tests the timer-related functionality of the FSM module.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up the test environment.
        This method is called before any tests are run.
        It initializes the test environment and creates test data specific to timer tests.
        """
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context,
            test_queue_job_no_delay=True,  # no jobs thanks
        ))

    def test_timer_creation(self):
        """
        Test the creation of an FSM timer.
        This test verifies that an FSM timer can be created with the correct parameters.
        """
        # Create a test FSM definition with a timer
        fsmd = self.env['fsm.definition'].create({
            'name': 'Timer Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
        @states
            @state initialState
                @event startTimer
                    fsm_instance.start_timer({'name': 'timerEvent'}, delay=10)
                @event timerEvent
                    fsm_instance.change_state('timerTriggered')
            @state timerTriggered
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
        
        # Trigger the startTimer event
        fsmi.process_event({'name': 'startTimer'}, {})
        
        # Check that a timer was created
        timer = self.env['fsm.timer'].search([('fsm_instance_id', '=', fsmi.id)])
        self.assertTrue(timer, "Timer was not created")
        self.assertEqual(timer.name, 'timerEvent', "Timer has incorrect event name")

    def test_timer_trigger(self):
        """
        Test the triggering of an FSM timer.
        This test verifies that an FSM timer triggers the correct event when its time is reached.
        """
        # Create a test FSM definition with a timer
        fsmd = self.env['fsm.definition'].create({
            'name': 'Timer Trigger Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
        @states
            @state initialState
                @event startTimer
                    fsm_instance.start_timer({'name': 'timerEvent'}, delay=10)
                @event timerEvent
                    fsm_instance.change_state('timerTriggered')
            @state timerTriggered
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
        
        # Trigger the startTimer event
        fsmi.process_event({'name': 'startTimer'}, {})
        
        # Check that a timer was created
        timer = self.env['fsm.timer'].search([('fsm_instance_id', '=', fsmi.id)])
        self.assertTrue(timer, "Timer was not created")
        
        # Move time forward to trigger the timer
        with freeze_time(timer.trigger_at + timedelta(seconds=1)):
            # Schedule timers (this would normally be done by a cron job)
            self.env['fsm.timer'].schedule_timers()
            
            # Check that the FSM instance state has changed
            self.assertEqual(fsmi.current_state, 'timerTriggered', 
                             "FSM instance state did not change after timer trigger")

    def test_stop_timer(self):
        """
        Test stopping an FSM timer.
        This test verifies that an FSM timer can be stopped before it triggers.
        """
        # Create a test FSM definition with a timer
        fsmd = self.env['fsm.definition'].create({
            'name': 'Stop Timer Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
        @states
            @state initialState
                @event startTimer
                    fsm_instance.start_timer({'name': 'timerEvent'}, delay=10)
                @event stopTimer
                    fsm_instance.stop_timer('timerEvent')
                @event timerEvent
                    fsm_instance.change_state('timerTriggered')
            @state timerTriggered
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
        
        # Trigger the startTimer event
        fsmi.process_event({'name': 'startTimer'}, {})
        
        # Check that a timer was created
        timer = self.env['fsm.timer'].search([('fsm_instance_id', '=', fsmi.id)])
        self.assertTrue(timer, "Timer was not created")
        
        # Stop the timer
        fsmi.process_event({'name': 'stopTimer'}, {})
        
        # Check that the timer was deleted
        timer = self.env['fsm.timer'].search([('fsm_instance_id', '=', fsmi.id)])
        self.assertFalse(timer, "Timer was not stopped")
        
        # Move time forward to when the timer would have triggered
        with freeze_time(timer.trigger_at + timedelta(seconds=1)):
            # Schedule timers (this would normally be done by a cron job)
            self.env['fsm.timer'].schedule_timers()
            
            # Check that the FSM instance state has not changed
            self.assertEqual(fsmi.current_state, 'initialState', 
                             "FSM instance state changed after stopped timer")

    def test_stop_all_timers(self):
        """
        Test stopping all FSM timers for an instance.
        This test verifies that all FSM timers for an instance can be stopped at once.
        """
        # Create a test FSM definition with multiple timers
        fsmd = self.env['fsm.definition'].create({
            'name': 'Stop All Timers Test',
        })
        
        fsmd.text_definition = '''
        @start
            fsm_instance.change_state('initialState')
        @states
            @state initialState
                @event startTimers
                    fsm_instance.start_timer({'name': 'timerEvent1'}, delay=10)
                    fsm_instance.start_timer({'name': 'timerEvent2'}, delay=20)
                @event stopAllTimers
                    fsm_instance.stop_all_timers()
                @event timerEvent1
                    fsm_instance.change_state('timer1Triggered')
                @event timerEvent2
                    fsm_instance.change_state('timer2Triggered')
            @state timer1Triggered
                @event all
                    pass
            @state timer2Triggered
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
        
        # Trigger the startTimers event
        fsmi.process_event({'name': 'startTimers'}, {})
        
        # Check that timers were created
        timers = self.env['fsm.timer'].search([('fsm_instance_id', '=', fsmi.id)])
        self.assertEqual(len(timers), 2, "Not all timers were created")
        
        # Stop all timers
        fsmi.process_event({'name': 'stopAllTimers'}, {})
        
        # Check that all timers were deleted
        timers = self.env['fsm.timer'].search([('fsm_instance_id', '=', fsmi.id)])
        self.assertEqual(len(timers), 0, "Not all timers were stopped")