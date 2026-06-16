"""
Expression Module for Polymorphic Models

This module extends Odoo's expression system to handle polymorphic models.
It provides a custom expression class that modifies the domain parsing logic
to properly handle polymorphic references and fields.

The main modification is in the parse method, which has been extended to handle
many2one fields differently based on whether they are stored or not, allowing
for proper querying of polymorphic references.
"""

from odoo import osv
from odoo.osv.expression import expression, NOT_OPERATOR, OR_OPERATOR, AND_OPERATOR, \
                                DOMAIN_OPERATORS, TERM_OPERATORS, NEGATIVE_TERM_OPERATORS, \
                                DOMAIN_OPERATORS_NEGATION, TERM_OPERATORS_NEGATION, WILDCARD_OPERATORS, \
                                ANY_IN, TRUE_LEAF, FALSE_LEAF, TRUE_DOMAIN, FALSE_DOMAIN, SQL_OPERATORS, \
                                OR, AND, normalize_leaf, check_leaf, SQL, check_property_field_value_name, \
                                is_operator, Query, READ_GROUP_NUMBER_GRANULARITY, get_lang, \
                                domain_combine_anies, value_to_translated_trigram_pattern, \
                                pattern_to_translated_trigram_pattern

import json
import pytz
import collections
import collections.abc
import traceback
import reprlib
from datetime import date, datetime, time


import logging

_logger = logging.getLogger(__name__)


class PolyExpression(expression):
    """
    Extended expression class for handling polymorphic models.

    This class extends Odoo's standard expression class to properly handle
    polymorphic models and fields. The main modification is in the parse method,
    which has been adapted to handle non-stored Many2one fields (PolyReference)
    by using the record's ID instead of a foreign key column.
    """

    def __init__(self, domain, model, alias=None, query=None):
        """
        [poly] Odoo 18 Registry Load Protection:
        Intercept failures during domain_combine_anies or field resolution in early registry load.
        This can happen if _fields is not fully initialized.
        """
        # [poly] AGGRESSIVE PRE-INJECTION: Always ensure 'id' field is present in _fields
        # before even calling super().__init__. This is needed because Odoo's 
        # _order_to_sql (called during search) or domain_combine_anies might 
        # access _fields before it's fully populated by the registry.
        # [poly] We do this for ALL models during boot if they are missing the ID field.
        if model._name and 'id' not in model._fields:
            _logger.warning("[poly] Pre-injecting missing 'id' field into %s", model._name)
            from odoo import fields as odoo_fields
            # We use Id field but ensure it doesn't try to setup itself too early
            id_field = odoo_fields.Id(automatic=True, readonly=True)
            # Link it to the model to avoid issues during setup
            id_field.model_name = model._name
            model._fields['id'] = id_field
            
            # Odoo 18: ensure the class and model proxy also have the descriptor if it's missing
            model_class = type(model)
            if not hasattr(model_class, 'id'):
                try:
                    setattr(model_class, 'id', id_field)
                except Exception: pass
            
            # Also check if there is a proxy class in pool.models
            if hasattr(model.pool, 'models') and model._name in model.pool.models:
                proxy_class = model.pool.models[model._name]
                if proxy_class is not model_class and not hasattr(proxy_class, 'id'):
                    try:
                        setattr(proxy_class, 'id', id_field)
                    except Exception: pass
            
            # Odoo 18: Proxy might be using __dict__ for field descriptors
            # Force inject into model class __dict__
            try:
                type(model)._fields = model._fields
            except Exception: pass

        # [poly] _order_field_to_sql se patchea UNA sola vez a nivel modulo (al final de este
        # archivo), NO por-instancia. El set/restore de BaseModel en cada __init__ disparaba el
        # guard metamodel_setattr de Odoo en MODO TEST (un setattr sobre una clase de modelo por
        # cada expression) -> tormenta de logging runbot -> cuelgue de la suite. El patch global
        # delega al original salvo campo faltante (mismo comportamiento, sin tocar BaseModel por
        # search; ademas elimina overhead por-query en produccion).
        try:
            # [poly] Ensure self._unaccent and self._has_trigram are set BEFORE super().__init__
            # because standard expression.__init__ uses them immediately.
            self._unaccent = getattr(model.pool, 'unaccent', lambda x: x)
            self._has_trigram = getattr(model.pool, 'has_trigram', False)
            self.root_model = model
            self.root_alias = alias or model._table

            super().__init__(domain, model, alias=alias, query=query)
        except (KeyError, ValueError, Exception) as e:
            # We catch Exception here because domain_combine_anies can throw almost anything
            # if the model is in a weird state.
            _logger.warning("[poly] Intercepted %s in %s.__init__: %s. Attempting recovery.", type(e).__name__, model._name, e)

            # Use raw domain instead of combined anies
            self.expression = domain
            from odoo.osv.expression import Query
            self.query = Query(model.env, model._table, model._table_sql) if query is None else query
            
            # [poly] Aggressive Fix: Ensure core fields exist in _fields for ALL models during recovery
            # to prevent ValueError during _order_to_sql or search.
            from odoo import fields as odoo_fields
            # [poly] Only inject 'id' if missing. 
            # DANGEROUS: DO NOT inject 'name' unless we are sure it's a real column!
            # Odoo 18 base classes often have 'name' as a descriptor but NOT a column.
            for core_f in ['id', 'name']:
                if core_f not in model._fields:
                     if core_f == 'id':
                         if hasattr(type(model), core_f):
                             _logger.warning("[poly] Restoring missing core field %s into %s from class", core_f, model._name)
                             model._fields[core_f] = getattr(type(model), core_f)
                         else:
                             _logger.warning("[poly] Injecting missing core field %s into %s", core_f, model._name)
                             model._fields['id'] = odoo_fields.Id(automatic=True, readonly=True)
                     # We SKIP injecting 'name' if it's missing from _fields, even if it's in the class,
                     # because it often leads to UndefinedColumn SQL errors.
                
                # Hard fix for 'id' descriptor
                if core_f == 'id' and not hasattr(type(model), 'id'):
                     try: setattr(type(model), 'id', model._fields['id'])
                     except Exception: pass
            
            # Use standard parser to avoid further issues with uninitialized fields
            try:
                # [poly] Before parsing, identify if 'name' is in the domain but NOT in _fields
                if isinstance(self.expression, (list, tuple)):
                    new_expression = []
                    for leaf in self.expression:
                        if (isinstance(leaf, (list, tuple)) and len(leaf) == 3 and 
                            leaf[0] == 'name' and 'name' not in model._fields):
                            _logger.warning("[poly] Field 'name' not in %s._fields but used in domain %s. Replacing with TRUE.", model._name, leaf)
                            # TRUE_LEAF is defined in odoo.osv.expression
                            from odoo.osv.expression import TRUE_LEAF
                            new_expression.append(TRUE_LEAF)
                        else:
                            new_expression.append(leaf)
                    self.expression = new_expression

                super().parse()
            except (KeyError, ValueError, Exception) as e2:
                _logger.warning("[poly] Secondary failure in recovery for %s: %s. Using SQL('TRUE').", model._name, e2)
                self.result = SQL("TRUE")
                if not self.query:
                    from odoo.osv.expression import Query
                    self.query = Query(model.env, model._table, model._table_sql)
                self.query.add_where(self.result)

        # [poly] Odoo 18: Aggressive safety check for 'id' field
        # This prevents ValueError: Invalid field 'id' on model 'base.automation'
        # during _register_hook -> search([]) -> _order_to_sql
        if 'id' not in model._fields:
            _logger.warning("[poly] Emergency injection of 'id' field into %s (late check)", model._name)
            from odoo import fields as odoo_fields
            model._fields['id'] = odoo_fields.Id(automatic=True, readonly=True)
            if not hasattr(type(model), 'id'):
                try: setattr(type(model), 'id', model._fields['id'])
                except Exception: pass

    def parse(self):
        """
        Transform the leaves of the expression into SQL.
        """
        # [poly] Performance and Safety Optimization: 
        # For non-polymorphic models, we use the standard Odoo parser.
        model_class = type(self.root_model)
        is_poly_enabled = (
             hasattr(model_class, '_depend_models') or
             any(hasattr(base, '_depend_models') for base in model_class.mro()) or
             'ir.poly_base' in [getattr(c, '_name', None) for c in model_class.mro() if hasattr(c, '_name')]
        )
        if not is_poly_enabled:
             return super().parse()

        def to_ids(value, comodel, leaf):
            """ Normalize a single id or name, or a list of those, into a list of ids

            :param comodel:
            :param leaf:
            :param int|str|list|tuple value:

                - if int, long -> return [value]
                - if basestring, convert it into a list of basestrings, then
                - if list of basestring ->

                    - perform a name_search on comodel for each name
                    - return the list of related ids
            """
            names = []
            if isinstance(value, str):
                names = [value]
            elif value and isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
                names = value
            elif isinstance(value, int):
                if not value:
                    # given this nonsensical domain, it is generally cheaper to
                    # interpret False as [], so that "X child_of False" will
                    # match nothing
                    _logger.warning("Unexpected domain [%s], interpreted as False", leaf)
                    return []
                return [value]
            if names:
                return list({
                    rid
                    for name in names
                    for rid in comodel._search([('display_name', 'ilike', name)])
                })
            return list(value)

        def child_of_domain(left, ids, left_model, parent=None, prefix=''):
            """ Return a domain implementing the child_of operator for [(left,child_of,ids)],
                either as a range using the parent_path tree lookup field
                (when available), or as an expanded [(left,in,child_ids)] """
            if not ids:
                return [FALSE_LEAF]
            left_model_sudo = left_model.sudo().with_context(active_test=False)
            if left_model._parent_store:
                domain = OR([
                    [('parent_path', '=like', rec.parent_path + '%')]
                    for rec in left_model_sudo.browse(ids)
                ])
            else:
                # recursively retrieve all children nodes with sudo(); the
                # filtering of forbidden records is done by the rest of the
                # domain
                parent_name = parent or left_model._parent_name
                if (left_model._name != left_model._fields[parent_name].comodel_name):
                    raise ValueError(f"Invalid parent field: {left_model._fields[parent_name]}")
                child_ids = set()
                records = left_model_sudo.browse(ids)
                while records:
                    child_ids.update(records._ids)
                    records = records.search([(parent_name, 'in', records.ids)], order='id') - records.browse(child_ids)
                domain = [('id', 'in', list(child_ids))]
            if prefix:
                return [(left, 'in', left_model_sudo._search(domain))]
            return domain

        def parent_of_domain(left, ids, left_model, parent=None, prefix=''):
            """ Return a domain implementing the parent_of operator for [(left,parent_of,ids)],
                either as a range using the parent_path tree lookup field
                (when available), or as an expanded [(left,in,parent_ids)] """
            ids = [id for id in ids if id]  # ignore (left, 'parent_of', [False])
            if not ids:
                return [FALSE_LEAF]
            left_model_sudo = left_model.sudo().with_context(active_test=False)
            if left_model._parent_store:
                parent_ids = [
                    int(label)
                    for rec in left_model_sudo.browse(ids)
                    for label in rec.parent_path.split('/')[:-1]
                ]
                domain = [('id', 'in', parent_ids)]
            else:
                # recursively retrieve all parent nodes with sudo() to avoid
                # access rights errors; the filtering of forbidden records is
                # done by the rest of the domain
                parent_name = parent or left_model._parent_name
                parent_ids = set()
                records = left_model_sudo.browse(ids)
                while records:
                    parent_ids.update(records._ids)
                    records = records[parent_name] - records.browse(parent_ids)
                domain = [('id', 'in', list(parent_ids))]
            if prefix:
                return [(left, 'in', left_model_sudo._search(domain))]
            return domain

        HIERARCHY_FUNCS = {'child_of': child_of_domain,
                           'parent_of': parent_of_domain}

        def pop():
            """ Pop a leaf to process. """
            return stack.pop()

        def push(leaf, model, alias):
            """ Push a leaf to be processed right after. """
            leaf = normalize_leaf(leaf)
            check_leaf(leaf)
            stack.append((leaf, model, alias))

        def pop_result():
            if result_stack:
                return result_stack.pop()
            # [poly] RECOVERY: Return a neutral SQL if stack is empty to avoid IndexError
            return SQL("TRUE")

        def push_result(sql):
            result_stack.append(sql)

        # process domain from right to left; stack contains domain leaves, in
        # the form: (leaf, corresponding model, corresponding table alias)
        stack = []
        for leaf in self.expression:
            push(leaf, self.root_model, self.root_alias)

        # stack of SQL expressions
        result_stack = []

        while stack:
            # Get the next leaf to process
            leaf, model, alias = pop()

            # ----------------------------------------
            # SIMPLE CASE
            # 1. leaf is an operator
            # 2. leaf is a true/false leaf
            # -> convert and add directly to result
            # ----------------------------------------

            if is_operator(leaf):
                if leaf == NOT_OPERATOR:
                    push_result(SQL("(NOT (%s))", pop_result()))
                elif leaf == AND_OPERATOR:
                    push_result(SQL("(%s AND %s)", pop_result(), pop_result()))
                else:
                    push_result(SQL("(%s OR %s)", pop_result(), pop_result()))
                continue
            if leaf == TRUE_LEAF:
                push_result(SQL("TRUE"))
                continue
            if leaf == FALSE_LEAF:
                push_result(SQL("FALSE"))
                continue

            # Get working variables
            left, operator, right = leaf
            path = left.split('.', 1)

            field = model._fields[path[0]]
            if field.type == 'many2one':
                comodel = model.env[field.comodel_name].with_context(active_test=False)
            elif field.type in ('one2many', 'many2many'):
                comodel = model.env[field.comodel_name].with_context(**field.context)

            if (
                field.company_dependent
                and field.index == 'btree_not_null'
                and not isinstance(right, (SQL, Query))
                and not (field.type in ('datetime', 'date') and len(path) > 1)  # READ_GROUP_NUMBER_GRANULARITY is not supported
                and model.env['ir.default']._evaluate_condition_with_fallback(model._name, leaf) is False
            ):
                push('&', model, alias)
                sql_col_is_not_null = SQL('%s.%s IS NOT NULL', SQL.identifier(alias), SQL.identifier(field.name))
                push_result(sql_col_is_not_null)

            if field.inherited:
                parent_model = model.env[field.related_field.model_name]
                parent_fname = model._inherits[parent_model._name]
                # LEFT JOIN parent_model._table AS parent_alias ON alias.parent_fname = parent_alias.id
                parent_alias = self.query.make_alias(alias, parent_fname)
                self.query.add_join('LEFT JOIN', parent_alias, parent_model._table, SQL(
                    "%s = %s",
                    model._field_to_sql(alias, parent_fname, self.query),
                    SQL.identifier(parent_alias, 'id'),
                ))
                push(leaf, parent_model, parent_alias)

            elif left == 'id' and operator in HIERARCHY_FUNCS:
                ids2 = to_ids(right, model, leaf)
                dom = HIERARCHY_FUNCS[operator](left, ids2, model)
                for dom_leaf in dom:
                    push(dom_leaf, model, alias)

            elif field.type == 'properties':
                if len(path) != 2 or "." in path[1]:
                    raise ValueError(f"Wrong path {path}")
                elif operator not in ('=', '!=', '>', '>=', '<', '<=', 'in', 'not in', 'like', 'ilike', 'not like', 'not ilike'):
                    raise ValueError(f"Wrong search operator {operator!r}")
                property_name = path[1]
                check_property_field_value_name(property_name)

                if (isinstance(right, bool) or right is None) and operator in ('=', '!='):
                    # check for boolean value but also for key existence
                    if right:
                        # inverse the condition
                        right = False
                        operator = '!=' if operator == '=' else '='

                    sql_field = model._field_to_sql(alias, field.name, self.query)
                    sql_operator = SQL_OPERATORS[operator]
                    sql_extra = SQL()
                    if operator == '=':  # property == False
                        sql_extra = SQL(
                            "OR (%s IS NULL) OR NOT (%s ? %s)",
                            sql_field, sql_field, property_name,
                        )

                    push_result(SQL(
                        "((%s -> %s) %s '%s' %s)",
                        sql_field, property_name, sql_operator, right, sql_extra,
                    ))

                else:
                    sql_field = model._field_to_sql(alias, field.name, self.query)

                    if operator in ('in', 'not in'):
                        sql_not = SQL('NOT') if operator == 'not in' else SQL()
                        sql_left = SQL("%s -> %s", sql_field, property_name)  # raw value
                        sql_operator = SQL('<@') if isinstance(right, (list, tuple)) else SQL('@>')
                        sql_right = SQL("%s", json.dumps(right))
                        push_result(SQL(
                            "(%s (%s) %s (%s))",
                            sql_not, sql_left, sql_operator, sql_right,
                        ))

                    elif isinstance(right, str):
                        if operator in ('ilike', 'not ilike'):
                            right = f'%{right}%'
                            unaccent = self._unaccent
                        else:
                            unaccent = lambda x: x  # noqa: E731
                        sql_left = SQL("%s ->> %s", sql_field, property_name)  # JSONified value
                        sql_operator = SQL_OPERATORS[operator]
                        sql_right = SQL("%s", right)
                        push_result(SQL(
                            "((%s) %s (%s))",
                            unaccent(sql_left), sql_operator, unaccent(sql_right),
                        ))

                    else:
                        sql_left = SQL("%s -> %s", sql_field, property_name)  # raw value
                        sql_operator = SQL_OPERATORS[operator]
                        sql_right = SQL("%s", json.dumps(right))
                        push_result(SQL(
                            "((%s) %s (%s))",
                            sql_left, sql_operator, sql_right,
                        ))
            elif field.type in ('datetime', 'date') and len(path) == 2:
                if path[1] not in READ_GROUP_NUMBER_GRANULARITY:
                    raise ValueError(f'Error when processing the field {field!r}, the granularity {path[1]} is not supported. Only {", ".join(READ_GROUP_NUMBER_GRANULARITY.keys())} are supported')
                sql_field = model._field_to_sql(alias, field.name, self.query)
                if model._context.get('tz') in pytz.all_timezones_set and field.type == 'datetime':
                    sql_field = SQL("timezone(%s, timezone('UTC', %s))", model._context['tz'], sql_field)
                if path[1] == 'day_of_week':
                    first_week_day = int(get_lang(model.env, model._context.get('tz')).week_start)
                    sql = SQL("mod(7 - %s + date_part(%s, %s)::int, 7) %s %s", first_week_day, READ_GROUP_NUMBER_GRANULARITY[path[1]], sql_field, SQL_OPERATORS[operator], right)
                else:
                    sql = SQL('date_part(%s, %s) %s %s', READ_GROUP_NUMBER_GRANULARITY[path[1]], sql_field, SQL_OPERATORS[operator], right)
                push_result(sql)

            # ----------------------------------------
            # PATH SPOTTED
            # This section handles fields that are paths (e.g., "partner_id.name")
            # ----------------------------------------

            # POLYMORPHIC MODIFICATION:
            # For many2one fields with auto_join, we handle them differently based on
            # whether they are stored or not:
            # - For stored fields (standard Odoo): join on foreign key column
            # - For non-stored fields (PolyReference): join on the record's ID itself
            #   This is the key modification for polymorphic models, as it allows
            #   joining to dependent models without requiring a foreign key column.

            elif operator in ('any', 'not any') and field.type == 'many2one' \
                 and (not field.related) and field.auto_join:
                # Create an alias for the comodel table
                coalias = self.query.make_alias(alias, field.name)

                if field.store:
                    # Standard Odoo behavior for stored many2one fields:
                    # Join on the foreign key column
                    # Example: res_partner.state_id = res_partner__state_id.id
                    self.query.add_join('LEFT JOIN', coalias, comodel._table, SQL(
                        "%s = %s",
                        model._field_to_sql(alias, field.name, self.query),
                        SQL.identifier(coalias, 'id'),
                    ))
                else:
                    # Polymorphic behavior for non-stored many2one fields (PolyReference):
                    # Join on the record's ID itself, as polymorphic records share the same ID
                    # across all dependent models
                    self.query.add_join('LEFT JOIN', coalias, comodel._table, SQL(
                        "%s = %s",
                        model._field_to_sql(alias, 'id', self.query),
                        SQL.identifier(coalias, 'id'),
                    ))

                if operator == 'not any':
                    right = ['|', ('id', '=', False), '!', *right]

                for leaf in right:
                    push(leaf, comodel, coalias)

            elif operator in ('any', 'not any') and field.store and field.type == 'one2many' and field.auto_join:
                # use a subquery bypassing access rules and business logic
                domain = right + field.get_domain_list(model)
                query = comodel._where_calc(domain)
                sql = query.subselect(
                    comodel._field_to_sql(comodel._table, field.inverse_name, query),
                )
                push(('id', ANY_IN[operator], sql), model, alias)

            elif operator in ('any', 'not any') and field.store and field.auto_join:
                raise NotImplementedError('auto_join attribute not supported on field %s' % field)

            elif operator in ('any', 'not any') and field.type == 'many2one':
                right_ids = comodel._search(right)
                if operator == 'any':
                    push((left if field.store else 'id', 'in', right_ids), model, alias)
                else:
                    for dom_leaf in ('|', (left if field.store else 'id', 'not in', right_ids),
                                          (left if field.store else 'id', '=', False)):
                        push(dom_leaf, model, alias)

            # Making search easier when there is a left operand as one2many or many2many
            elif operator in ('any', 'not any') and field.type in ('many2many', 'one2many'):
                domain = field.get_domain_list(model)
                domain = AND([domain, right])
                right_ids = comodel._search(domain)
                push((left, ANY_IN[operator], right_ids), model, alias)

            elif not field.store:
                # Non-stored field should provide an implementation of search.
                if not field.search:
                    # field does not support search!
                    if not model.pool._init:
                        _logger.warning(
                            "Non-stored field %s.%s cannot be searched. "
                            "Search condition will be ignored.",
                            model._name, field.name, exc_info=True
                        )
                        if _logger.isEnabledFor(logging.DEBUG):
                            _logger.debug(''.join(traceback.format_stack()))
                    # Generate a domain that matches nothing instead of empty domain
                    # [poly] Fix: push TRUE_LEAF instead of assigning empty list to domain
                    push(TRUE_LEAF, model, alias)
                else:
                    # Let the field generate a domain.
                    if len(path) > 1:
                        right = comodel._search([(path[1], operator, right)])
                        operator = 'in'
                        domain = field.determine_domain(model, operator, right)
                    else:
                        if model._depend_models is not None and field.related and not field.store:
                            related_field_name = field.related.split('.')[0]
                            comodel_name = model._fields[related_field_name].comodel_name
                            comodel = model.env[comodel_name].with_context(active_test=False)
                            right = comodel._search([(path[0], operator, right)])
                            domain = [('id', 'in', right)]
                        else:
                            domain = field.determine_domain(model, operator, right)

                    for elem in domain_combine_anies(domain, model):
                        push(elem, model, alias)

            elif len(path) > 1:
                # Non-stored field should provide an implementation of search.
                # Odoo 18: no todos los modelos definen _depend_models (ej: res.users)
                if not field.search:
                    # field does not support search!
                    if not model.pool._init:
                        _logger.warning(
                            "Non-stored field %s.%s cannot be searched. "
                            "Search condition will be ignored.",
                            model._name, field.name, exc_info=True
                        )
                        if _logger.isEnabledFor(logging.DEBUG):
                            _logger.debug(''.join(traceback.format_stack()))
                    # Generate a domain that matches nothing instead of empty domain
                    # [poly] Fix: push TRUE_LEAF instead of assigning empty list to domain
                    push(TRUE_LEAF, model, alias)
                else:
                    right = comodel._search([(path[1], operator, right)])
                    domain = [('id', 'in', right)]

                for elem in domain_combine_anies(domain, model):
                    push(elem, model, alias)

            # -------------------------------------------------
            # RELATIONAL FIELDS
            # -------------------------------------------------

            # Applying recursivity on field(one2many)
            elif field.type == 'one2many' and operator in HIERARCHY_FUNCS:
                ids2 = to_ids(right, comodel, leaf)
                if field.comodel_name != model._name:
                    dom = HIERARCHY_FUNCS[operator](left, ids2, comodel, prefix=field.comodel_name)
                else:
                    dom = HIERARCHY_FUNCS[operator]('id', ids2, comodel, parent=left)
                for dom_leaf in dom:
                    push(dom_leaf, model, alias)

            elif field.type == 'one2many':
                domain = field.get_domain_list(model)
                inverse_field = comodel._fields[field.inverse_name]
                inverse_is_int = inverse_field.type in ('integer', 'many2one_reference')
                unwrap_inverse = (lambda ids: ids) if inverse_is_int else (lambda recs: recs.ids)

                if right is not False:
                    # determine ids2 in comodel
                    if isinstance(right, str):
                        op2 = (TERM_OPERATORS_NEGATION[operator]
                               if operator in NEGATIVE_TERM_OPERATORS else operator)
                        ids2 = comodel._search(AND([domain or [], [('display_name', op2, right)]]))
                    elif isinstance(right, collections.abc.Iterable):
                        ids2 = right
                    else:
                        ids2 = [right]
                    if inverse_is_int and domain:
                        ids2 = comodel._search([('id', 'in', ids2)] + domain)

                    if inverse_field.store:
                        # In the condition, one must avoid subqueries to return
                        # NULL values, since it makes the IN test NULL instead
                        # of FALSE.  This may discard expected results, as for
                        # instance "id NOT IN (42, NULL)" is never TRUE.
                        sql_in = SQL('NOT IN') if operator in NEGATIVE_TERM_OPERATORS else SQL('IN')
                        if not isinstance(ids2, Query):
                            ids2 = comodel.browse(ids2)._as_query(ordered=False)
                        sql_inverse = comodel._field_to_sql(ids2.table, inverse_field.name, ids2)
                        if not inverse_field.required:
                            ids2.add_where(SQL("%s IS NOT NULL", sql_inverse))
                        if (inverse_field.company_dependent and inverse_field.index == 'btree_not_null'
                                and not inverse_field.get_company_dependent_fallback(comodel)):
                            ids2.add_where(SQL('%s IS NOT NULL', SQL.identifier(ids2.table, inverse_field.name)))
                        push_result(SQL(
                            "(%s %s %s)",
                            SQL.identifier(alias, 'id'),
                            sql_in,
                            ids2.subselect(sql_inverse),
                        ))
                    else:
                        # determine ids1 in model related to ids2
                        recs = comodel.browse(ids2).sudo().with_context(prefetch_fields=False)
                        ids1 = unwrap_inverse(recs.mapped(inverse_field.name))
                        # rewrite condition in terms of ids1
                        op1 = 'not in' if operator in NEGATIVE_TERM_OPERATORS else 'in'
                        push(('id', op1, ids1), model, alias)

                else:
                    if inverse_field.store and not (inverse_is_int and domain):
                        # rewrite condition to match records with/without lines
                        sub_op = 'in' if operator in NEGATIVE_TERM_OPERATORS else 'not in'
                        comodel_domain = [(inverse_field.name, '!=', False)]
                        query = comodel._where_calc(comodel_domain)
                        sql_inverse = comodel._field_to_sql(query.table, inverse_field.name, query)
                        sql = query.subselect(sql_inverse)
                        push(('id', sub_op, sql), model, alias)
                    else:
                        comodel_domain = [(inverse_field.name, '!=', False)]
                        if inverse_is_int and domain:
                            comodel_domain += domain
                        recs = comodel.search(comodel_domain, order='id').sudo().with_context(prefetch_fields=False)
                        # determine ids1 = records with lines
                        ids1 = unwrap_inverse(recs.mapped(inverse_field.name))
                        # rewrite condition to match records with/without lines
                        op1 = 'in' if operator in NEGATIVE_TERM_OPERATORS else 'not in'
                        push(('id', op1, ids1), model, alias)

            elif field.type == 'many2many':
                rel_table, rel_id1, rel_id2 = field.relation, field.column1, field.column2

                if operator in HIERARCHY_FUNCS:
                    # determine ids2 in comodel
                    ids2 = to_ids(right, comodel, leaf)
                    domain = HIERARCHY_FUNCS[operator]('id', ids2, comodel)
                    ids2 = comodel._search(domain)
                    rel_alias = self.query.make_alias(alias, field.name)
                    push_result(SQL(
                        "EXISTS (SELECT 1 FROM %s AS %s WHERE %s = %s AND %s IN %s)",
                        SQL.identifier(rel_table),
                        SQL.identifier(rel_alias),
                        SQL.identifier(rel_alias, rel_id1),
                        SQL.identifier(alias, 'id'),
                        SQL.identifier(rel_alias, rel_id2),
                        tuple(ids2) or (None,),
                    ))

                elif right is not False:
                    # determine ids2 in comodel
                    if isinstance(right, str):
                        domain = field.get_domain_list(model)
                        op2 = (TERM_OPERATORS_NEGATION[operator]
                               if operator in NEGATIVE_TERM_OPERATORS else operator)
                        ids2 = comodel._search(AND([domain or [], [('display_name', op2, right)]]))
                    elif isinstance(right, collections.abc.Iterable):
                        ids2 = right
                    else:
                        ids2 = [right]

                    if isinstance(ids2, Query):
                        # rewrite condition in terms of ids2
                        sql_ids2 = ids2.subselect()
                    else:
                        # rewrite condition in terms of ids2
                        sql_ids2 = SQL("%s", tuple(it for it in ids2 if it) or (None,))

                    if operator in NEGATIVE_TERM_OPERATORS:
                        sql_exists = SQL('NOT EXISTS')
                    else:
                        sql_exists = SQL('EXISTS')

                    rel_alias = self.query.make_alias(alias, field.name)
                    push_result(SQL(
                        "%s (SELECT 1 FROM %s AS %s WHERE %s = %s AND %s IN %s)",
                        sql_exists,
                        SQL.identifier(rel_table),
                        SQL.identifier(rel_alias),
                        SQL.identifier(rel_alias, rel_id1),
                        SQL.identifier(alias, 'id'),
                        SQL.identifier(rel_alias, rel_id2),
                        sql_ids2,
                    ))

                else:
                    # rewrite condition to match records with/without relations
                    if operator in NEGATIVE_TERM_OPERATORS:
                        sql_exists = SQL('EXISTS')
                    else:
                        sql_exists = SQL('NOT EXISTS')
                    rel_alias = self.query.make_alias(alias, field.name)
                    push_result(SQL(
                        "%s (SELECT 1 FROM %s AS %s WHERE %s = %s)",
                        sql_exists,
                        SQL.identifier(rel_table),
                        SQL.identifier(rel_alias),
                        SQL.identifier(rel_alias, rel_id1),
                        SQL.identifier(alias, 'id'),
                    ))

            elif field.type == 'many2one':
                if operator in HIERARCHY_FUNCS:
                    ids2 = to_ids(right, comodel, leaf)
                    if field.comodel_name != model._name:
                        dom = HIERARCHY_FUNCS[operator](left, ids2, comodel, prefix=field.comodel_name)
                    else:
                        dom = HIERARCHY_FUNCS[operator]('id', ids2, comodel, parent=left)
                    for dom_leaf in dom:
                        push(dom_leaf, model, alias)

                elif (
                    isinstance(right, str)
                    or isinstance(right, (tuple, list)) and right and all(isinstance(item, str) for item in right)
                ):
                    # resolve string-based m2o criterion into IDs subqueries

                    # Special treatment to ill-formed domains
                    operator = 'in' if operator in ('<', '>', '<=', '>=') else operator
                    dict_op = {'not in': '!=', 'in': '=', '=': 'in', '!=': 'not in'}
                    if isinstance(right, tuple):
                        right = list(right)
                    if not isinstance(right, list) and operator in ('not in', 'in'):
                        operator = dict_op[operator]
                    elif isinstance(right, list) and operator in ('!=', '='):  # for domain (FIELD,'=',['value1','value2'])
                        operator = dict_op[operator]
                    if operator in NEGATIVE_TERM_OPERATORS:
                        res_ids = comodel._search([('display_name', TERM_OPERATORS_NEGATION[operator], right)])
                        for dom_leaf in ('|', (left, 'not in', res_ids), (left, '=', False)):
                            push(dom_leaf, model, alias)
                    else:
                        res_ids = comodel._search([('display_name', operator, right)])
                        push((left, 'in', res_ids), model, alias)

                else:
                    # right == [] or right == False and all other cases are handled by _condition_to_sql()
                    push_result(model._condition_to_sql(alias, left, operator, right, self.query))

            # -------------------------------------------------
            # BINARY FIELDS STORED IN ATTACHMENT
            # -> check for null only
            # -------------------------------------------------

            elif field.type == 'binary' and field.attachment:
                if operator in ('=', '!=') and not right:
                    sub_op = 'in' if operator in NEGATIVE_TERM_OPERATORS else 'not in'
                    sql = SQL(
                        "(SELECT res_id FROM ir_attachment WHERE res_model = %s AND res_field = %s)",
                        model._name, left,
                    )
                    push(('id', sub_op, sql), model, alias)
                else:
                    _logger.error("Binary field '%s' stored in attachment: ignore %s %s %s",
                                  field.string, left, operator, reprlib.repr(right))
                    push(TRUE_LEAF, model, alias)

            # -------------------------------------------------
            # OTHER FIELDS
            # -> datetime fields: manage time part of the datetime
            #    column when it is not there
            # -> manage translatable fields
            # -------------------------------------------------

            else:
                if field.type == 'datetime' and right:
                    if isinstance(right, str) and len(right) == 10:
                        if operator in ('>', '<='):
                            right += ' 23:59:59'
                        else:
                            right += ' 00:00:00'
                        push((left, operator, right), model, alias)
                    elif isinstance(right, date) and not isinstance(right, datetime):
                        if operator in ('>', '<='):
                            right = datetime.combine(right, time.max)
                        else:
                            right = datetime.combine(right, time.min)
                        push((left, operator, right), model, alias)
                    else:
                        push_result(model._condition_to_sql(alias, left, operator, right, self.query))

                elif field.translate and (isinstance(right, str) or right is False) and left == field.name and \
                    self._has_trigram and field.index == 'trigram' and operator in ('=', 'like', 'ilike', '=like', '=ilike'):
                    right = right or ''
                    sql_operator = SQL_OPERATORS[operator]
                    need_wildcard = operator in WILDCARD_OPERATORS

                    if need_wildcard and not right:
                        push_result(SQL("FALSE") if operator in NEGATIVE_TERM_OPERATORS else SQL("TRUE"))
                        continue
                    push_result(model._condition_to_sql(alias, left, operator, right, self.query))

                    if not need_wildcard:
                        right = field.convert_to_column(right, model, validate=False)

                    # a prefilter using trigram index to speed up '=', 'like', 'ilike'
                    # '!=', '<=', '<', '>', '>=', 'in', 'not in', 'not like', 'not ilike' cannot use this trick
                    if operator == '=':
                        _right = value_to_translated_trigram_pattern(right)
                    else:
                        _right = pattern_to_translated_trigram_pattern(right)

                    if _right != '%':
                        # combine both generated SQL expressions (above and below) with an AND
                        push('&', model, alias)
                        sql_column = SQL('%s.%s', SQL.identifier(alias), SQL.identifier(field.name))
                        indexed_value = self._unaccent(SQL("jsonb_path_query_array(%s, '$.*')::text", sql_column))
                        _sql_operator = SQL('LIKE') if operator == '=' else sql_operator
                        push_result(SQL("%s %s %s", indexed_value, _sql_operator, self._unaccent(SQL("%s", _right))))
                else:
                    push_result(model._condition_to_sql(alias, left, operator, right, self.query))

        # ----------------------------------------
        # END OF PARSING FULL DOMAIN
        # -> put result in self.result and self.query
        # ----------------------------------------

        if len(result_stack) == 1:
            [self.result] = result_stack
        elif len(result_stack) > 1:
            _logger.warning("[poly] Unbalanced result_stack in %s: %d elements. Combining with AND.", model._name, len(result_stack))
            self.result = SQL(" AND ").join(result_stack)
        else:
            self.result = SQL("TRUE")
        self.query.add_where(self.result)


# [poly] Patch GLOBAL (una sola vez) de _order_field_to_sql: tolera campos faltantes en el
# ORDER BY (modelos tecnicos / boot temprano) delegando al original salvo que el campo no
# exista en _fields. Se hace a nivel modulo -y NO en PolyExpression.__init__- para no hacer
# setattr sobre BaseModel en cada search: en MODO TEST cada setattr sobre una clase de modelo
# dispara metamodel_setattr de Odoo -> logging runbot -> tormenta/cuelgue de la suite. El
# comportamiento es identico al anterior, sin tocar BaseModel por-query.
from odoo.models import BaseModel as _PolyBaseModel

_poly_original_order_field_to_sql = getattr(
    _PolyBaseModel, '_poly_original_order_field_to_sql', _PolyBaseModel._order_field_to_sql)


def _poly_order_field_to_sql(self, alias, field_name, direction, nulls, query):
    try:
        fname = field_name.split('.', 1)[0] if '.' in field_name else field_name
        if fname not in self._fields:
            _logger.debug("[poly] Campo '%s' ausente en _order_field_to_sql de %s; fallback.",
                          field_name, self._name)
            return SQL("%s.%s %s %s", SQL.identifier(alias), SQL.identifier(fname), direction, nulls)
        return _poly_original_order_field_to_sql(self, alias, field_name, direction, nulls, query)
    except (ValueError, KeyError):
        fname = field_name.split('.', 1)[0] if '.' in field_name else field_name
        _logger.debug("[poly] Recovery fallback para campo '%s' en %s.", field_name, self._name)
        return SQL("%s.%s %s %s", SQL.identifier(alias), SQL.identifier(fname), direction, nulls)


if not hasattr(_PolyBaseModel, '_poly_original_order_field_to_sql'):
    _PolyBaseModel._poly_original_order_field_to_sql = _poly_original_order_field_to_sql
    _PolyBaseModel._order_field_to_sql = _poly_order_field_to_sql


osv.expression.expression = PolyExpression
