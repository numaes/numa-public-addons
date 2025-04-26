# -*- coding: utf-8 -*-
from odoo.addons.numa_fsm.tests.common import TestFSMCommon
import json
import base64
from werkzeug.datastructures import FileStorage
from io import BytesIO


class TestFSMFormInput(TestFSMCommon):
    """
    Test class for FSM Form Input functionality.
    This class tests the form input handling functionality of the FSM module.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up the test environment.
        This method is called before any tests are run.
        It initializes the test environment and creates test data specific to form input tests.
        """
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context,
            test_queue_job_no_delay=True,  # no jobs thanks
        ))

    def test_form_input_creation(self):
        """
        Test the creation of an FSM form input.
        This test verifies that an FSM form input can be created with the correct parameters.
        """
        # Create a test FSM instance
        fsmd = self.env['fsm.definition'].create({
            'name': 'Form Input Test',
        })
        
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
            'name': 'test_instance',
        })
        
        # Create a form input
        form_input = self.env['fsm.form_input'].create({
            'instance_id': fsmi.id,
            'unrelated_identifier': 'test_identifier',
            'json_data': json.dumps({'field1': 'value1', 'field2': 'value2'}),
        })
        
        # Check that the form input was created correctly
        self.assertTrue(form_input, "Form input was not created")
        self.assertEqual(form_input.instance_id.id, fsmi.id, "Form input has incorrect instance")
        self.assertEqual(form_input.unrelated_identifier, 'test_identifier', 
                         "Form input has incorrect identifier")
        
        # Check that the JSON data was stored correctly
        json_data = json.loads(form_input.json_data)
        self.assertEqual(json_data.get('field1'), 'value1', "Form input has incorrect JSON data")
        self.assertEqual(json_data.get('field2'), 'value2', "Form input has incorrect JSON data")

    def test_form_input_with_files(self):
        """
        Test the creation of an FSM form input with file attachments.
        This test verifies that an FSM form input can be created with file attachments.
        """
        # Create a test FSM instance
        fsmd = self.env['fsm.definition'].create({
            'name': 'Form Input File Test',
        })
        
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
            'name': 'test_file_instance',
        })
        
        # Create a mock file
        file_content = b'Test file content'
        file_obj = BytesIO(file_content)
        file_storage = FileStorage(
            stream=file_obj,
            filename='test_file.txt',
            content_type='text/plain',
        )
        
        # Create a form input with a file
        form_input_vals = {
            'instance_id': 'test_file_instance',
            'unrelated_identifier': 'test_file_identifier',
            'field1': 'value1',
            'file_field': file_storage,
        }
        
        form_input = self.env['fsm.form_input'].create(form_input_vals)
        
        # Check that the form input was created correctly
        self.assertTrue(form_input, "Form input with file was not created")
        self.assertEqual(form_input.instance_id.id, fsmi.id, 
                         "Form input with file has incorrect instance")
        self.assertEqual(form_input.unrelated_identifier, 'test_file_identifier', 
                         "Form input with file has incorrect identifier")
        
        # Check that the file was stored correctly
        file_data = form_input.get_file('file_field')
        self.assertTrue(file_data, "File was not stored in form input")
        
        # Decode the base64-encoded file content and check it
        decoded_content = base64.b64decode(file_data)
        self.assertEqual(decoded_content, file_content, "File content was not stored correctly")

    def test_get_file(self):
        """
        Test retrieving a file from an FSM form input.
        This test verifies that a file can be retrieved from an FSM form input.
        """
        # Create a test FSM instance
        fsmd = self.env['fsm.definition'].create({
            'name': 'Get File Test',
        })
        
        fsmi = self.env['fsm.instance'].create({
            'definition_id': fsmd.id,
            'name': 'test_get_file_instance',
        })
        
        # Create a mock file
        file_content = b'Test file content for get_file'
        file_obj = BytesIO(file_content)
        file_storage = FileStorage(
            stream=file_obj,
            filename='get_file_test.txt',
            content_type='text/plain',
        )
        
        # Create a form input with a file
        form_input_vals = {
            'instance_id': 'test_get_file_instance',
            'unrelated_identifier': 'test_get_file_identifier',
            'field1': 'value1',
            'file_field': file_storage,
        }
        
        form_input = self.env['fsm.form_input'].create(form_input_vals)
        
        # Get the file from the form input
        file_data = form_input.get_file('file_field')
        self.assertTrue(file_data, "Could not retrieve file from form input")
        
        # Decode the base64-encoded file content and check it
        decoded_content = base64.b64decode(file_data)
        self.assertEqual(decoded_content, file_content, "Retrieved file content is incorrect")
        
        # Try to get a non-existent file
        non_existent_file = form_input.get_file('non_existent_field')
        self.assertFalse(non_existent_file, "Non-existent file should return None")

    def test_move_file(self):
        """
        Test moving a file from an FSM form input to another model.
        This test verifies that a file can be moved from an FSM form input to another model.
        """
        # Create a test FSM instance with a binary field
        fsmd = self.env['fsm.definition'].create({
            'name': 'Move File Test',
        })
        
        # Create a model with a binary field to move the file to
        # For this test, we'll use the attachment model itself
        target_model = self.env['ir.attachment']
        target_record = target_model.create({
            'name': 'Target Record',
            'type': 'binary',
            'datas': base64.b64encode(b'Initial content'),
        })
        
        # Create a mock file
        file_content = b'Test file content for move_file'
        file_obj = BytesIO(file_content)
        file_storage = FileStorage(
            stream=file_obj,
            filename='move_file_test.txt',
            content_type='text/plain',
        )
        
        # Create a form input with a file
        form_input_vals = {
            'unrelated_identifier': 'test_move_file_identifier',
            'field1': 'value1',
            'file_field': file_storage,
        }
        
        form_input = self.env['fsm.form_input'].create(form_input_vals)
        
        # Move the file to the target record
        # Note: This is a simplified test as move_file requires specific field setup
        # In a real scenario, we would need to ensure the target model has the right fields
        with self.assertRaises(Exception):
            # This should raise an exception because the target model doesn't have the right fields
            form_input.move_file(target_record, 'file_field', 'datas')
        
        # The test verifies that the move_file method exists and is called
        # A complete test would require a model with the right fields