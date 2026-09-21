# -*- coding: utf-8 -*-
"""The one place that names `numa_ai`."""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class NumaSynchEngine(models.AbstractModel):
    _inherit = 'numa.synch.engine'

    def _ask_llm(self, prompt):
        """Ask `numa.ai.engine` for a JSON answer.

        The seam is declared in `numa_synch_ai_assisted`, which raises a message telling
        the user no provider is installed. Installing `numa_ai` brings this bridge in by
        itself, and the message stops being true.
        """
        _logger.debug("Asking numa.ai.engine to analyse a schema mismatch.")
        return self.env['numa.ai.engine'].ask_llm(prompt, json_mode=True)
