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

    # CPM / PDM Calculated Dates
    pln_calc_early_start = fields.Datetime('Early Start', readonly=True)
    pln_calc_early_end = fields.Datetime('Early End', readonly=True)
    pln_calc_late_start = fields.Datetime('Late Start', readonly=True)
    pln_calc_late_end = fields.Datetime('Late End', readonly=True)

    pln_free_float = fields.Float('Free Float', readonly=True)
    pln_total_float = fields.Float('Total Float', readonly=True)
    pln_is_critical = fields.Boolean('Is Critical', readonly=True)

    pln_allocation_ids = fields.One2many('numa.planning.allocation', 'node_id', string='Allocations')
    pln_availability_period_ids = fields.One2many('numa.planning.availability.period', string='Related Availability',
                                                  compute='_compute_pln_availability_period_ids')

    def _compute_pln_availability_period_ids(self):
        """
        Calculates availability periods related to this node based on its resources.
        """
        for node in self:
            resource_ids = node.pln_allocation_ids.mapped('resource_id').ids
            if resource_ids:
                node.pln_availability_period_ids = self.env['numa.planning.availability.period'].search([
                    ('resource_id', 'in', resource_ids),
                    ('start_date', '<=', node.pln_calc_end),
                    ('end_date', '>=', node.pln_calc_start)
                ])
            else:
                node.pln_availability_period_ids = False

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
        Trigger for the complete scheduling engine.
        Calculates CPM first, then performs Resource Leveling.
        """
        self.action_pln_compute_cpm()
        self.action_pln_resource_leveling()
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

    def pln_gantt_update_batch(self, changes):
        """
        Accepts a list of changes: [{'id': node_id, 'start': datetime, 'end': datetime}, ...]
        Applies changes to allocations in the official scenario.
        """
        official_scenario = self.env['numa.planning.scenario'].search([('is_official', '=', True)], limit=1)
        if not official_scenario:
            return False
            
        for change in changes:
            node = self.browse(change['id'])
            if not node.exists():
                continue
                
            allocations = node.pln_allocation_ids.filtered(lambda a: a.scenario_id == official_scenario)
            if not allocations:
                continue
                
            new_start = fields.Datetime.to_datetime(change['start'])
            new_end = fields.Datetime.to_datetime(change['end'])
            
            # Simple shift logic for batch updates
            old_start = node.pln_calc_start
            if old_start and new_start != old_start:
                delta = new_start - old_start
                for alloc in allocations:
                    alloc.start_date += delta
                    alloc.end_date += delta
            
            # Adjust end date of the last allocation if it was a resize
            if new_end:
                last_alloc = allocations.sorted('end_date')[-1]
                if last_alloc.end_date != new_end:
                    last_alloc.end_date = new_end
                    
        return True

    def pln_get_resource_load_data(self, start_date, end_date):
        """
        Returns resource load data for the histogram.
        [{'resource_id': id, 'name': name, 'load': [{'date': d, 'value': v}, ...]}]
        """
        resources = self.env['numa.planning.resource'].search([])
        official_scenario = self.env['numa.planning.scenario'].search([('is_official', '=', True)], limit=1)
        
        # Convert JS dates to Python datetimes if necessary
        if isinstance(start_date, str):
            start_date = fields.Datetime.to_datetime(start_date)
        if isinstance(end_date, str):
            end_date = fields.Datetime.to_datetime(end_date)

        result = []
        for res in resources:
            allocs = self.env['numa.planning.allocation'].search([
                ('resource_id', '=', res.id),
                ('scenario_id', '=', official_scenario.id),
                ('start_date', '<=', end_date),
                ('end_date', '>=', start_date)
            ])
            
            # Simple daily aggregation
            load_by_day = defaultdict(float)
            for alloc in allocs:
                curr = max(alloc.start_date, start_date)
                stop = min(alloc.end_date, end_date)
                while curr < stop:
                    day_str = curr.strftime('%Y-%m-%d')
                    day_end = (curr + timedelta(days=1)).replace(hour=0, minute=0, second=0)
                    overlap_end = min(day_end, stop)
                    hours = (overlap_end - curr).total_seconds() / 3600.0
                    load_by_day[day_str] += hours
                    curr = day_end

            result.append({
                'id': res.id,
                'name': res.name,
                'load': [{'date': d, 'value': v} for d, v in load_by_day.items()]
            })
        return result

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

    def action_pln_compute_cpm(self):
        """
        Implementation of the Critical Path Method (CPM) and Precedence Diagramming Method (PDM).
        Uses the 'Load-Process-Dump' pattern for high performance on large graphs.
        """
        if not self:
            return

        # Step A: Identify the connected graph context
        # We find all nodes sharing the same pln_root_id as any node in self
        root_ids = self.mapped('pln_root_id').ids
        if not root_ids:
            # If no root, we just use self and nodes connected via links
            context_nodes = self
        else:
            context_nodes = self.search([('pln_root_id', 'in', root_ids)])

        # Fetch graph data into memory
        graph = self._pln_fetch_graph_data(context_nodes)
        if not graph:
            return

        # Step B: Topological Sort & Cycle Detection (Kahn's Algorithm)
        sorted_node_ids = self._pln_topological_sort(graph)

        # Step C: Forward Pass (Early Dates)
        # Determine base time (min of constraints or current time)
        min_start = fields.Datetime.now()
        for node_id in sorted_node_ids:
            node_data = graph[node_id]
            
            # Base ES comes from predecessors or default start
            es = min_start
            for pred_id, link_type, lag in node_data['predecessors']:
                pred = graph[pred_id]
                # PDM Logic:
                # FS: Finish-to-Start (Pred.EF + Lag)
                # SS: Start-to-Start (Pred.ES + Lag)
                # FF: Finish-to-Finish (Pred.EF + Lag - Duration)
                # SF: Start-to-Finish (Pred.ES + Lag - Duration)
                if link_type == 'fs':
                    val = pred['early_end'] + timedelta(hours=lag)
                elif link_type == 'ss':
                    val = pred['early_start'] + timedelta(hours=lag)
                elif link_type == 'ff':
                    val = pred['early_end'] + timedelta(hours=lag - node_data['duration'])
                elif link_type == 'sf':
                    val = pred['early_start'] + timedelta(hours=lag - node_data['duration'])
                else:
                    val = es
                
                if val > es:
                    es = val

            # Respect Constraints
            if node_data['constraint_type'] == 'must_start' and node_data['constraint_date']:
                es = node_data['constraint_date']
            elif node_data['constraint_type'] == 'asap' and node_data['constraint_date']:
                if node_data['constraint_date'] > es:
                    es = node_data['constraint_date']

            node_data['early_start'] = es
            node_data['early_end'] = es + timedelta(hours=node_data['duration'])

        # Step D: Backward Pass (Late Dates)
        project_end = max(n['early_end'] for n in graph.values())
        
        for node_id in reversed(sorted_node_ids):
            node_data = graph[node_id]
            
            # Base LF comes from successors or project end
            lf = project_end
            if node_data['constraint_type'] == 'must_finish' and node_data['constraint_date']:
                lf = node_data['constraint_date']

            for succ_id, link_type, lag in node_data['successors']:
                succ = graph[succ_id]
                # Backward PDM Logic (Inverted):
                # FS: LS = LF - D.  Target.LS = Source.LF + Lag => Source.LF = Target.LS - Lag
                # SS: Target.ES = Source.ES + Lag => Source.ES = Target.ES - Lag => Source.LF = Target.ES - Lag + D
                # FF: Target.EF = Source.EF + Lag => Source.EF = Target.EF - Lag => Source.LF = Target.EF - Lag
                # SF: Target.EF = Source.ES + Lag => Source.ES = Target.EF - Lag => Source.LF = Target.EF - Lag + D
                if link_type == 'fs':
                    val = succ['late_start'] - timedelta(hours=lag)
                elif link_type == 'ss':
                    val = succ['late_start'] - timedelta(hours=lag - node_data['duration'])
                elif link_type == 'ff':
                    val = succ['late_end'] - timedelta(hours=lag)
                elif link_type == 'sf':
                    val = succ['late_end'] - timedelta(hours=lag - node_data['duration'])
                else:
                    val = lf
                
                if val < lf:
                    lf = val

            node_data['late_end'] = lf
            node_data['late_start'] = lf - timedelta(hours=node_data['duration'])

        # Step E: Float Calculation & Critical Path
        for node_id, node_data in graph.items():
            # Total Float = Late Start - Early Start
            tf_delta = node_data['late_start'] - node_data['early_start']
            node_data['total_float'] = tf_delta.total_seconds() / 3600.0
            
            # Free Float = Min(Succ.ES) - Early End
            if not node_data['successors']:
                node_data['free_float'] = 0.0 # Or TF if project end is fixed
            else:
                min_succ_es = min(graph[s_id]['early_start'] for s_id, lt, lag in node_data['successors'] if lt == 'fs')
                # Simplifying FF calculation for FS dependencies
                ff_delta = min_succ_es - node_data['early_end'] if any(lt == 'fs' for sid, lt, lag in node_data['successors']) else tf_delta
                node_data['free_float'] = max(0.0, ff_delta.total_seconds() / 3600.0) if isinstance(ff_delta, timedelta) else node_data['total_float']

            node_data['is_critical'] = node_data['total_float'] <= 0.0001

        # Step F: Bulk Write (The Dump)
        for node_id in sorted_node_ids:
            node_data = graph[node_id]
            node_record = self.env['numa.planning.node'].browse(node_id)
            node_record.write({
                'pln_calc_early_start': node_data['early_start'],
                'pln_calc_early_end': node_data['early_end'],
                'pln_calc_late_start': node_data['late_start'],
                'pln_calc_late_end': node_data['late_end'],
                'pln_total_float': node_data['total_float'],
                'pln_free_float': node_data['free_float'],
                'pln_is_critical': node_data['is_critical'],
                'pln_topological_level': node_data['level'],
                'pln_recalc_status': 'clean'
            })

    def _pln_fetch_graph_data(self, nodes):
        """
        Loads the graph into memory.
        """
        # Batch fetch links
        node_ids = nodes.ids
        links = self.env['numa.planning.link'].search([
            '|', ('source_node_id', 'in', node_ids), ('target_node_id', 'in', node_ids)
        ])
        
        graph = {}
        for node in nodes:
            graph[node.id] = {
                'duration': node.pln_effort_hours or 0.0,
                'constraint_type': node.pln_constraint_type,
                'constraint_date': node.pln_constraint_date,
                'predecessors': [],
                'successors': [],
                'early_start': None, 'early_end': None,
                'late_start': None, 'late_end': None,
                'level': 0
            }

        for link in links:
            if link.source_node_id.id in graph and link.target_node_id.id in graph:
                graph[link.target_node_id.id]['predecessors'].append(
                    (link.source_node_id.id, link.link_type, link.lag_amount or 0.0)
                )
                graph[link.source_node_id.id]['successors'].append(
                    (link.target_node_id.id, link.link_type, link.lag_amount or 0.0)
                )
        return graph

    def action_pln_resource_leveling(self):
        """
        Resource Leveling Engine (Clipping).
        Converts theoretical CPM dates into real allocations respecting resource capacity.
        Uses a Greedy Heuristic (Serial Generation Scheme).
        """
        if not self:
            return

        # 1. Scope & Cleanup
        root_ids = self.mapped('pln_root_id').ids
        if root_ids:
            context_nodes = self.search([('pln_root_id', 'in', root_ids)])
        else:
            context_nodes = self

        # Identify official scenario
        official_scenario = self.env['numa.planning.scenario'].search([('is_official', '=', True)], limit=1)
        if not official_scenario:
            raise UserError(_("No official scenario found. Resource leveling requires an official target."))

        # Delete existing tentative or reserved allocations for these nodes in the official scenario
        self.env['numa.planning.allocation'].search([
            ('node_id', 'in', context_nodes.ids),
            ('scenario_id', '=', official_scenario.id),
            ('pln_state', 'in', ['reserved', 'tentative']),
            ('pln_is_locked', '=', False)
        ]).unlink()

        # 2. Prioritization (The Queue)
        # We sort by: Hard constraints, Early Start, Float, AI Score
        sorted_nodes = context_nodes.sorted(key=lambda n: (
            n.pln_constraint_date or fields.Datetime.now(),
            n.pln_calc_early_start or fields.Datetime.now(),
            n.pln_total_float,
            -n.pln_ai_score
        ))

        # 3. Scheduling Loop (The Tetris)
        # In-memory timeline to track resource consumption: {resource_id: [(start, end, load), ...]}
        resource_timeline = defaultdict(list)
        
        # Load existing 'wip' or 'history' or 'locked' allocations into timeline
        existing_allocs = self.env['numa.planning.allocation'].search([
            ('scenario_id', '=', official_scenario.id),
            '|', ('pln_state', 'in', ['history', 'wip']), ('pln_is_locked', '=', True)
        ])
        for alloc in existing_allocs:
            resource_timeline[alloc.resource_id.id].append((alloc.start_date, alloc.end_date, 1.0))

        allocations_to_create = []
        
        for node in sorted_nodes:
            effort = node.pln_effort_hours
            if effort <= 0:
                continue

            # For now, we assume a node needs ONE resource. 
            # We'll pick the first suggested resource or a default one.
            # In a more advanced version, we would check required_resource_ids.
            resource = node.pln_allocation_ids.mapped('resource_id')[:1] or \
                       self.env['numa.planning.resource'].search([], limit=1)
            
            if not resource:
                continue

            # Probe Time Slots
            probe_time = node.pln_calc_early_start or fields.Datetime.now()
            booked = False
            
            while not booked:
                # Calculate real duration based on resource efficiency at this time
                # For simplicity, we use the efficiency at probe_time
                efficiency = resource.get_capability_at(probe_time)
                if efficiency <= 0:
                    # Resource unavailable, move to next available period or +1 hour
                    probe_time += timedelta(hours=1)
                    continue
                
                real_duration_hours = effort / efficiency
                end_time = probe_time + timedelta(hours=real_duration_hours)
                
                # Check for conflicts in the timeline
                conflicts = [
                    slot for slot in resource_timeline[resource.id]
                    if not (end_time <= slot[0] or probe_time >= slot[1])
                ]
                
                if not conflicts:
                    # Book it!
                    alloc_vals = {
                        'node_id': node.id,
                        'resource_id': resource.id,
                        'scenario_id': official_scenario.id,
                        'start_date': probe_time,
                        'end_date': end_time,
                        'pln_state': 'reserved',
                    }
                    allocations_to_create.append(alloc_vals)
                    resource_timeline[resource.id].append((probe_time, end_time, 1.0))
                    booked = True
                else:
                    # Move probe time to the end of the first conflict and retry
                    next_start = max(c[1] for c in conflicts)
                    probe_time = next_start

        # 4. Bulk Create & Sync
        if allocations_to_create:
            self.env['numa.planning.allocation'].create(allocations_to_create)
            # Recompute Node dates (this is triggered by the depends on Node model)
            context_nodes._compute_pln_dates()

    def _pln_topological_sort(self, graph):
        """
        Kahn's Algorithm for Topological Sort and Cycle Detection.
        """
        in_degree = {node_id: 0 for node_id in graph}
        for node_id in graph:
            for succ_id, link_type, lag in graph[node_id]['successors']:
                in_degree[succ_id] += 1

        queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
        sorted_nodes = []
        
        while queue:
            u = queue.popleft()
            sorted_nodes.append(u)
            
            for v, lt, lag in graph[u]['successors']:
                in_degree[v] -= 1
                graph[v]['level'] = max(graph[v]['level'], graph[u]['level'] + 1)
                if in_degree[v] == 0:
                    queue.append(v)

        if len(sorted_nodes) != len(graph):
            raise UserError(_("Cycle detected in planning graph. Recalculation aborted."))
            
        return sorted_nodes


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

    def action_pln_generate_availability(self, start_date, end_date):
        """
        Generates discrete availability periods from Odoo's standard calendar.
        Check for existing 'history' or 'locked' periods in that range. Do NOT overwrite them.
        """
        self.ensure_one()
        # Find the calendar. Resources in Odoo usually have a resource_id which has a calendar_id.
        # numa.planning.resource might be linked to a user or workcenter.
        calendar = False
        if self.user_id and self.user_id.employee_id:
            calendar = self.user_id.employee_id.resource_calendar_id
        elif self.workcenter_id:
            calendar = self.workcenter_id.resource_calendar_id
        
        if not calendar:
            return False

        # Get work intervals from standard Odoo calendar
        # We use resource_id=False to get the general calendar intervals if no specific resource is linked
        resource = self.user_id.employee_id.resource_id if self.user_id and self.user_id.employee_id else False
        work_intervals = calendar._work_intervals_batch(start_date, end_date, resource)[resource.id if resource else False]

        # Get existing immutable periods
        immutable_states = ['history'] # Could include a 'locked' flag if added later
        existing_periods = self.env['numa.planning.availability.period'].search([
            ('resource_id', '=', self.id),
            ('start_date', '<', end_date),
            ('end_date', '>', start_date),
            ('pln_state', 'in', immutable_states)
        ])

        periods_to_create = []
        for interval in work_intervals:
            i_start, i_end, attendance = interval
            
            # Check if this interval overlaps with any immutable period
            is_blocked = False
            for existing in existing_periods:
                if i_start < existing.end_date and i_end > existing.start_date:
                    is_blocked = True
                    break
            
            if not is_blocked:
                periods_to_create.append({
                    'resource_id': self.id,
                    'start_date': i_start,
                    'end_date': i_end,
                    'pln_type': 'standard',
                    'pln_state': 'planned',
                    'pln_efficiency': 1.0,
                    'pln_priority': 1,
                    'pln_calendar_attendance_id': attendance.id if attendance else False,
                })

        if periods_to_create:
            # Clear existing non-immutable periods in range before recreating
            self.env['numa.planning.availability.period'].search([
                ('resource_id', '=', self.id),
                ('start_date', '<', end_date),
                ('end_date', '>', start_date),
                ('pln_state', 'not in', immutable_states)
            ]).unlink()
            
            self.env['numa.planning.availability.period'].create(periods_to_create)
        
        return True

    def get_capability_at(self, timestamp):
        """
        Query numa.planning.availability.period to find effective capacity at a given time.
        Pick the one with the highest priority if there are overlaps.
        """
        self.ensure_one()
        periods = self.env['numa.planning.availability.period'].search([
            ('resource_id', '=', self.id),
            ('start_date', '<=', timestamp),
            ('end_date', '>=', timestamp)
        ], order='pln_priority desc', limit=1)
        
        if periods:
            return periods.pln_efficiency
        return 0.0


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


class NumaPlanningAvailabilityPeriod(models.Model):
    """
    Availability Ledger: Represents a discrete time slot of resource capacity (or incapacity).
    This Ledger allows modifying a specific Tuesday's capacity without changing the global recurring rule.
    """
    _name = 'numa.planning.availability.period'
    _description = 'Planning Availability Period'

    resource_id = fields.Many2one('numa.planning.resource', string='Resource', required=True, ondelete='cascade')
    start_date = fields.Datetime('Start Date', required=True)
    end_date = fields.Datetime('End Date', required=True)
    duration = fields.Float('Duration (Hours)', compute='_compute_duration', store=True)

    # Type Logic (The Superset)
    pln_type = fields.Selection([
        ('standard', 'Standard Shift'),      # Derived from Odoo Calendar
        ('overtime', 'Overtime / Extra'),    # Added manually or by rules
        ('leave', 'Leave / Absence'),        # Derived from Odoo Leaves
        ('maintenance', 'Maintenance'),      # Derived from FSM or Manual
        ('breakdown', 'Unplanned Breakdown') # History only
    ], string='Type', default='standard', required=True)

    # Capacity Logic
    pln_efficiency = fields.Float('Efficiency', default=1.0, help="0.0 = Unavailable, 1.0 = Normal, 0.5 = Reduced Speed")
    pln_priority = fields.Integer('Priority', default=1, help="Higher number wins overlaps. E.g., Maintenance(10) blocks Standard Shift(1)")

    # Lifecycle (History vs Planning)
    pln_state = fields.Selection([
        ('history', 'History / Immutable'),  # What actually happened
        ('active', 'Active / Today'),        # Current status
        ('planned', 'Committed Future'),     # Hard schedule
        ('forecast', 'Theoretical')          # Derived from recurring rules, not instantiated yet
    ], string='State', default='planned', required=True)

    # Links (Traceability)
    pln_calendar_attendance_id = fields.Many2one('resource.calendar.attendance', string='Original Rule')
    pln_fsm_state_ref = fields.Reference(selection=[
        ('fsm.instance', 'FSM Instance'),
    ], string='FSM State Reference')

    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for period in self:
            if period.start_date and period.end_date:
                period.duration = (period.end_date - period.start_date).total_seconds() / 3600.0
            else:
                period.duration = 0.0


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
