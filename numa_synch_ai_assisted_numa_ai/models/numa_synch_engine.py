# -*- coding: utf-8 -*-
"""The one place that names `numa_ai`."""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class NumaSynchEngine(models.AbstractModel):
    _inherit = 'numa.synch.engine'

    def _ask_llm(self, prompt):
        """Ask numa_ai's LLM service for a JSON answer.

        The seam is declared in `numa_synch_ai_assisted`, which raises a message telling
        the user no provider is installed. Installing `numa_ai` brings this bridge in by
        itself, and the message stops being true.

        The entry point is `numa_ai.llm_api_service.request_llm`. There is no JSON mode
        to ask for: the prompt says what shape it wants and the caller parses what comes
        back, which is what every other caller in `numa_ai` does. `purpose='utility'`
        picks the cheaper model, and temperature 0 because a schema mapping is not a
        place for invention.
        """
        _logger.debug("Asking numa_ai's LLM service to analyse a schema mismatch.")
        return self.env['numa_ai.llm_api_service'].request_llm(
            prompt=prompt,
            purpose='utility',
            temperature=0.0,
        )
