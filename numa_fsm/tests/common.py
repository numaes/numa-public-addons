from odoo.addons.base.tests.common import TransactionCase


class TestFSMCommon(TransactionCase):
    '''
    Common setup for FSM tests.
    This class provides common setup functionality for testing the FSM module.
    It extends TransactionCase to provide transaction management for tests.
    '''

    @classmethod
    def setUpClass(cls):
        '''
        Set up the test environment.
        This method is called before any tests are run.
        It initializes the test environment and creates common test data.
        '''
        super().setUpClass()
        # Initialize common test data
        cls.setup_data()

    @classmethod
    def setup_data(cls, **kwargs):
        '''
        Set up test data for FSM tests.
        This method creates common test data that can be used across multiple tests.
        It can be overridden by subclasses to provide specific test data.

        Args:
            **kwargs: Additional parameters for test data setup

        Returns:
            dict: A dictionary containing the created test data
        '''
        # Create a basic FSM definition for testing
        cls.basic_fsm_definition = cls.env['fsm.definition'].create({
            'name': 'Test FSM Definition',
        })

        # Create a basic FSM instance for testing
        cls.basic_fsm_instance = cls.env['fsm.instance'].create({
            'definition_id': cls.basic_fsm_definition.id,
        })

        return {
            'basic_fsm_definition': cls.basic_fsm_definition,
            'basic_fsm_instance': cls.basic_fsm_instance,
        }
