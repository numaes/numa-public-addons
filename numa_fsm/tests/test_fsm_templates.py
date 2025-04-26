# -*- coding: utf-8 -*-
from odoo.addons.numa_fsm.tests.common import TestFSMCommon
import json
from markupsafe import Markup


class TestFSMTemplates(TestFSMCommon):
    """
    Test class for FSM Template functionality.
    This class tests the mail and page template functionality of the FSM module.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up the test environment.
        This method is called before any tests are run.
        It initializes the test environment and creates test data specific to template tests.
        """
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context,
            test_queue_job_no_delay=True,  # no jobs thanks
        ))
        
        # Create test templates
        cls.setup_templates()
        
    @classmethod
    def setup_templates(cls):
        """
        Set up test templates.
        This method creates mail and page templates for testing.
        """
        # Create a mail template
        cls.mail_template = cls.env['fsm.wf.mail_template'].create({
            'name': 'Test Mail Template',
            'subject': 'Test Subject for {{ instance.name }}',
            'body_html': '<p>This is a test email for {{ instance.name }}</p>',
        })
        
        # Create a page template
        cls.page_template = cls.env['fsm.wf.page_template'].create({
            'name': 'Test Page Template',
            'body': '<div>This is a test page for {{ instance.name }}</div>',
        })
        
        # Update the FSM definition to include the templates
        cls.basic_fsm_definition.write({
            'pages': [(4, cls.page_template.id)],
            'mail_templates': [(4, cls.mail_template.id)],
        })

    def test_mail_template_creation(self):
        """
        Test the creation of a mail template.
        This test verifies that a mail template can be created with the correct parameters.
        """
        # Create a new mail template
        mail_template = self.env['fsm.wf.mail_template'].create({
            'name': 'New Test Mail Template',
            'subject': 'New Test Subject',
            'body_html': '<p>This is a new test email</p>',
        })
        
        # Check that the mail template was created correctly
        self.assertTrue(mail_template, "Mail template was not created")
        self.assertEqual(mail_template.name, 'New Test Mail Template', 
                         "Mail template has incorrect name")
        self.assertEqual(mail_template.subject, 'New Test Subject', 
                         "Mail template has incorrect subject")
        self.assertEqual(mail_template.body_html, '<p>This is a new test email</p>', 
                         "Mail template has incorrect body")

    def test_page_template_creation(self):
        """
        Test the creation of a page template.
        This test verifies that a page template can be created with the correct parameters.
        """
        # Create a new page template
        page_template = self.env['fsm.wf.page_template'].create({
            'name': 'New Test Page Template',
            'body': '<div>This is a new test page</div>',
        })
        
        # Check that the page template was created correctly
        self.assertTrue(page_template, "Page template was not created")
        self.assertEqual(page_template.name, 'New Test Page Template', 
                         "Page template has incorrect name")
        self.assertEqual(page_template.body, '<div>This is a new test page</div>', 
                         "Page template has incorrect body")

    def test_render_page(self):
        """
        Test rendering a page template.
        This test verifies that a page template can be rendered with the correct context.
        """
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': self.basic_fsm_definition.id,
            'name': 'test_render_instance',
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Render the page template
        rendered_page = fsmi.render_page('Test Page Template')
        
        # Check that the page was rendered correctly
        self.assertTrue(rendered_page, "Page was not rendered")
        self.assertIn('test_render_instance', rendered_page, 
                      "Rendered page does not contain instance name")

    def test_send_template_mail(self):
        """
        Test sending a mail using a template.
        This test verifies that a mail can be sent using a template with the correct context.
        """
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': self.basic_fsm_definition.id,
            'name': 'test_mail_instance',
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Create a target object to send the mail to (using the instance itself for simplicity)
        target_object = fsmi
        
        # Send the mail
        # Note: In a real test, we would check that the mail was sent correctly
        # Here we just verify that the method can be called without errors
        try:
            fsmi.action_send_template_mail(fsmi, target_object, 'Test Mail Template')
            # If we get here, the method was called without errors
            success = True
        except Exception as e:
            success = False
            self.fail(f"Failed to send template mail: {e}")
        
        self.assertTrue(success, "Failed to send template mail")

    def test_template_with_dynamic_content(self):
        """
        Test templates with dynamic content.
        This test verifies that templates can include dynamic content that is correctly rendered.
        """
        # Create an FSM instance with some data
        fsmi = self.env['fsm.instance'].create({
            'definition_id': self.basic_fsm_definition.id,
            'name': 'test_dynamic_instance',
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Set some data in the instance environment
        env = {'test_var': 'dynamic_value'}
        fsmi.flush_env(env)
        
        # Create a template with dynamic content
        dynamic_template = self.env['fsm.wf.page_template'].create({
            'name': 'Dynamic Test Template',
            'body': '<div>This is a test with <span t-esc="test_var"></span></div>',
        })
        
        # Add the template to the FSM definition
        self.basic_fsm_definition.write({
            'pages': [(4, dynamic_template.id)],
        })
        
        # Render the template
        rendered_page = fsmi.render_page('Dynamic Test Template', test_var='dynamic_value')
        
        # Check that the dynamic content was rendered correctly
        self.assertTrue(rendered_page, "Page with dynamic content was not rendered")
        self.assertIn('dynamic_value', rendered_page, 
                      "Rendered page does not contain dynamic content")

    def test_template_not_found(self):
        """
        Test error handling when a template is not found.
        This test verifies that appropriate errors are raised when a template is not found.
        """
        # Create an FSM instance
        fsmi = self.env['fsm.instance'].create({
            'definition_id': self.basic_fsm_definition.id,
            'name': 'test_not_found_instance',
        })
        
        # Start the FSM instance
        fsmi.start()
        
        # Try to render a non-existent page template
        with self.assertRaises(Exception):
            fsmi.render_page('Non-existent Template')
        
        # Try to send a mail with a non-existent mail template
        with self.assertRaises(Exception):
            fsmi.action_send_template_mail(fsmi, fsmi, 'Non-existent Template')