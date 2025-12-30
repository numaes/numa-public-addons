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
    pln_effort_hours = fields.Float('Effort Hours', compute='_compute_pln_dates', store=True)

    # Calculated Dates (Engine Output)
    # pln_calc_start is derived from the active Allocations of the official scenario.
    pln_calc_start = fields.Datetime('Calculated Start', compute='_compute_pln_dates', inverse='_inverse_pln_dates', store=True)
    pln_calc_end = fields.Datetime('Calculated End', compute='_compute_pln_dates', inverse='_inverse_pln_dates', store=True)
    pln_free_float = fields.Float('Free Float')
    pln_total_float = fields.Float('Total Float')
    pln_is_critical = fields.Boolean('Is Critical')

    pln_allocation_ids = fields.One2many('numa.planning.allocation', 'node_id', string='Allocations')

    @api.depends('pln_allocation_ids.start_date', 'pln_allocation_ids.end_date', 'pln_allocation_ids.scenario_id.is_official')
    def _compute_pln_dates(self):
        for node in self:
            official_allocations = node.pln_allocation_ids.filtered(lambda a: a.scenario_id.is_official)
            if official_allocations:
                node.pln_calc_start = min(official_allocations.mapped('start_date'))
                node.pln_calc_end = max(official_allocations.mapped('end_date'))
                effort = sum((a.end_date - a.start_date).total_seconds() / 3600.0 for a in official_allocations)
                node.pln_effort_hours = effort
            else:
                node.pln_calc_start = False
                node.pln_calc_end = False
                node.pln_effort_hours = 0.0

    def _inverse_pln_dates(self):
        for node in self:
            official_scenario = self.env['numa.planning.scenario'].search([('is_official', '=', True)], limit=1)
            if not official_scenario:
                continue

            allocations = node.pln_allocation_ids.filtered(lambda a: a.scenario_id == official_scenario)
            
            if not allocations:
                # Create a default allocation if dates are provided and we can find a resource
                resource = self.env['numa.planning.resource'].search([], limit=1)
                if resource and node.pln_calc_start and node.pln_calc_end:
                    self.env['numa.planning.allocation'].create({
                        'node_id': node.id,
                        'resource_id': resource.id,
                        'scenario_id': official_scenario.id,
                        'start_date': node.pln_calc_start,
                        'end_date': node.pln_calc_end,
                    })
                continue

            # Check for delta shift based on pln_calc_start
            old_start = node._origin.pln_calc_start
            if old_start and node.pln_calc_start and node.pln_calc_start != old_start:
                delta = node.pln_calc_start - old_start
                for allocation in allocations:
                    allocation.start_date += delta
                    allocation.end_date += delta
            
            # Check for resize based on pln_calc_end if it wasn't just shifted
            # If it was shifted, pln_calc_end should have moved by the same delta.
            # If it's different, it's a resize.
            old_end = node._origin.pln_calc_end
            if old_end and node.pln_calc_end and node.pln_calc_end != old_end:
                # If we already shifted, the current allocations' max end_date might be different from node.pln_calc_end
                # if the user intended to resize.
                current_max_end = max(allocations.mapped('end_date'))
                if current_max_end != node.pln_calc_end:
                    # Adjust the last allocation
                    last_alloc = allocations.sorted('end_date')[-1]
                    last_alloc.end_date = node.pln_calc_end

    def action_freeze_baseline(self):
        """
        Placeholder for freezing the baseline.
        """
        self.ensure_one()
        return True

    def action_simulate(self):
        """
        Placeholder for simulation logic.
        """
        self.ensure_one()
        return True

    def pln_action_auto_schedule(self):
        """
        Placeholder for basic scheduling logic.
        """
        self.ensure_one()
        return True

    def pln_get_allocations_view(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Allocations'),
            'res_model': 'numa.planning.allocation',
            'view_mode': 'list,form',
            'domain': [('node_id', '=', self.id)],
            'context': {'default_node_id': self.id},
        }

    def pln_get_gantt_data(self):
        self.ensure_one()
        links = self.env['numa.planning.link'].search([('source_node_id', '=', self.id)])
        return {
            'id': self.id,
            'name': self.display_name,
            'pln_calc_start': self.pln_calc_start,
            'pln_calc_end': self.pln_calc_end,
            'allocations': [{
                'resource_id': a.resource_id.id,
                'start': a.start_date,
                'end': a.end_date,
                'state': a.pln_state
            } for a in self.pln_allocation_ids.filtered(lambda x: x.scenario_id.is_official)],
            'dependencies': links.mapped('target_node_id').ids
        }

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
