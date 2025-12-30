# -*- coding: utf-8 -*-
from odoo import models, fields, api

class NumaPlanningScenario(models.Model):
    """
    The Sandbox: Manages plan versions.
    """
    _name = 'numa.planning.scenario'
    _description = 'Planning Scenario'

    name = fields.Char('Name', required=True)
    base_scenario_id = fields.Many2one('numa.planning.scenario', string='Base Scenario')
    is_active = fields.Boolean('Is Active', default=True)
    is_official = fields.Boolean('Is Official', default=False)


class NumaPlanningNode(models.Model):
    """
    The Abstract Core / Mixin: Foundation for polymorphic planning nodes.
    Uses pln_ prefix to avoid collisions with standard Odoo fields.
    """
    _name = 'numa.planning.node'
    _description = 'Planning Node'
    _inherit = ['numa.poly.mixin']

    # Core Logic
    pln_root_id = fields.Many2one('numa.planning.node', string='Root Project/Order')
    pln_constraint_type = fields.Selection([
        ('asap', 'ASAP'),
        ('alap', 'ALAP'),
        ('must_start', 'Must Start'),
        ('must_finish', 'Must Finish')
    ], string='Constraint Type', default='asap')
    pln_constraint_date = fields.Datetime('Constraint Date')
    pln_duration_type = fields.Selection([
        ('fixed_duration', 'Fixed Duration'),
        ('fixed_work', 'Fixed Work'),
        ('fixed_units', 'Fixed Units')
    ], string='Duration Type')
    pln_effort_hours = fields.Float('Effort Hours')

    # Calculated Dates (Engine Output)
    # pln_calc_start is derived from the active Allocations of the official scenario.
    pln_calc_start = fields.Datetime('Calculated Start', readonly=True)
    pln_calc_end = fields.Datetime('Calculated End', readonly=True)
    pln_free_float = fields.Float('Free Float')
    pln_total_float = fields.Float('Total Float')
    pln_is_critical = fields.Boolean('Is Critical')

    # Optimization (CPM)
    pln_topological_level = fields.Integer('Topological Level')
    pln_recalc_status = fields.Selection([
        ('clean', 'Clean'),
        ('dirty_forward', 'Dirty Forward'),
        ('dirty_backward', 'Dirty Backward'),
        ('dirty_all', 'Dirty All')
    ], string='Recalculation Status', default='clean')

    # Baseline (The Contract)
    pln_baseline_start = fields.Datetime('Baseline Start')
    pln_baseline_end = fields.Datetime('Baseline End')
    pln_baseline_effort = fields.Float('Baseline Effort')
    pln_variance = fields.Float('Variance')

    # AI Hooks
    pln_ai_score = fields.Float('AI Score')
    pln_ai_reasoning = fields.Text('AI Reasoning')


class NumaPlanningLink(models.Model):
    """
    The Dependencies: Connects nodes.
    """
    _name = 'numa.planning.link'
    _description = 'Planning Link'

    source_node_id = fields.Many2one('numa.planning.node', string='Source Node', required=True, ondelete='cascade')
    target_node_id = fields.Many2one('numa.planning.node', string='Target Node', required=True, ondelete='cascade')
    link_type = fields.Selection([
        ('fs', 'Finish to Start'),
        ('ss', 'Start to Start'),
        ('ff', 'Finish to Finish'),
        ('sf', 'Start to Finish')
    ], string='Link Type', default='fs', required=True)
    lag_amount = fields.Float('Lag Amount')


class NumaPlanningResource(models.Model):
    """
    The Capacity: Represents planable resources.
    """
    _name = 'numa.planning.resource'
    _description = 'Planning Resource'

    name = fields.Char('Name', required=True)
    capacity = fields.Float('Capacity', default=1.0)
    
    # Hooks
    pln_fsm_model = fields.Char('FSM Model Hook')
    pln_current_fsm_state = fields.Reference(selection=[
        ('fsm.instance', 'FSM Instance'),
        # Selection will be expanded by other modules
    ], string='Current FSM State')
    
    user_id = fields.Many2one('res.users', string='User')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center')


class NumaPlanningAllocation(models.Model):
    """
    The Booking: Source of Truth for resource assignments.
    Uses pln_ prefix for lifecycle fields.
    """
    _name = 'numa.planning.allocation'
    _description = 'Planning Allocation'

    node_id = fields.Many2one('numa.planning.node', string='Node', required=True, ondelete='cascade')
    resource_id = fields.Many2one('numa.planning.resource', string='Resource', required=True, ondelete='cascade')
    scenario_id = fields.Many2one('numa.planning.scenario', string='Scenario', required=True, ondelete='cascade')
    
    start_date = fields.Datetime('Start Date', required=True)
    end_date = fields.Datetime('End Date', required=True)

    # Lifecycle (The Scopes)
    pln_state = fields.Selection([
        ('history', 'History/Actuals'),
        ('wip', 'Execution'),
        ('reserved', 'Committed'),
        ('tentative', 'Hypothesis')
    ], string='Planning State', default='tentative')
    pln_is_locked = fields.Boolean('Is Locked', default=False)


class NumaResourceStatePlan(models.Model):
    """
    Availability Ledger: Tracks resource availability.
    """
    _name = 'numa.resource.state.plan'
    _description = 'Resource State Plan'

    resource_id = fields.Many2one('numa.planning.resource', string='Resource', required=True, ondelete='cascade')
    date_start = fields.Datetime('Date Start', required=True)
    date_end = fields.Datetime('Date End', required=True)
    pln_fsm_state_ref = fields.Reference(selection=[
        ('fsm.instance', 'FSM Instance'),
    ], string='FSM State Reference')


class NumaPlanningStrategy(models.Model):
    """
    The Brain: Logic for planning optimization.
    """
    _name = 'numa.planning.strategy'
    _description = 'Planning Strategy'

    name = fields.Char('Name', required=True)
    logic_type = fields.Selection([
        ('static', 'Static'),
        ('dynamic', 'Dynamic'),
        ('ai', 'AI')
    ], string='Logic Type', default='static')
    pln_ai_agent_ref = fields.Char('AI Agent Reference')
