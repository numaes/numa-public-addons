import lxml.etree
from lxml import etree
from lxml.etree import LxmlError
from lxml.etree import Element as E
from odoo.tools.safe_eval import safe_eval
from odoo import exceptions, _
import html

import logging
_logger = logging.getLogger(__name__)


class TBreak(Exception):
    pass


class TContinue(Exception):
    pass


xml_parser = lxml.etree.XMLParser(encoding='UTF-8',
                                  resolve_entities=False,
                                  strip_cdata=False,
                                  recover=True,
                                  ns_clean=True)


def render_node(node: E, parent: E = None, template=None, params: dict = None) -> E:
    if params is None:
        params = {}

    if isinstance(node, lxml.etree._ProcessingInstruction):
        return None

    copied_node = E(node.tag)
    copied_node.text = node.text
    copied_node.tail = node.tail

    if node.tag == 't-break':
        raise TBreak(_('At node %s, t-break') % (parent.tag if parent else 'root'))
    elif node.tag == 't-continue':
        raise TContinue(_('At node %s, t-continue') % (parent.tag if parent else 'root'))

    variable_name = None
    variable_value = None
    iterable_collection = None
    iterable_as = None
    while_expression = None
    for a_name, a_value in node.items():
        if a_name == 't-set':
            variable_name = a_value
        elif a_name == 't-value':
            variable_value = safe_eval(a_value, locals_dict=params)
        elif a_name == 't-foreach':
            iterable_collection = safe_eval(a_value, locals_dict=params)
        elif a_name == 't-as':
            iterable_as = a_value
        elif a_name == 't-esc':
            copied_node.text = str(safe_eval(a_value, locals_dict=params))
        elif a_name == 't-raw':
            if a_value == '0':
                inner_tree = lxml.etree.fromstring(
                    ('<div>' + params.get('p0', '') + '</div>').encode('UTF-8'),
                    parser=xml_parser
                )
            else:
                inner_tree = lxml.etree.fromstring(
                    ('<div>' + str(safe_eval(a_value, locals_dict=params)) + '</div>').encode('UTF-8'),
                    parser=xml_parser
                )
            copied_node.text = inner_tree.text
            for element in inner_tree:
                new_node = render_node(element, node, template, params)
                if new_node is not None:
                    copied_node.append(new_node)
        elif a_name == 't-while':
            while_expression = a_value
        elif a_name == 't-if':
            if not safe_eval(a_value, locals_dict=params):
                return None
        elif a_name.startswith('t-att-'):
            copied_node.attrib[a_name[len('t-att-'):]] = str(safe_eval(a_value, locals_dict=params))
        elif a_name.startswith('t-attf-'):
            copied_node.attrib[a_name[len('t-attf-'):]] = a_value.format(**params)
        elif a_name == 't-call':
            called_template = template.env.ref(a_value)
            if called_template:
                inner_node = E(node.tag)
                inner_node.text = node.text
                inner_node.tail = node.tail
                for element in node:
                    inner_node.append(element)
                saved_0 = params.get('p0')
                params['p0'] = lxml.etree.tostring(inner_node, encoding='UTF-8').decode('UTF-8')
                
                called_tree = lxml.etree.fromstring(called_template.arch_db, parser=xml_parser)
                copied_node.text = called_tree.text
                copied_node.tail = called_tree.tail
                for element in called_tree:
                    new_node = render_node(element, copied_node, template, params)
                    if new_node is not None:
                        copied_node.append(new_node)

                params['p0'] = saved_0
                return copied_node
            else:
                raise exceptions.ValidationError(_('t-call to undefined template %s') % a_value)
        else:
            copied_node.attrib[a_name] = a_value

    if variable_name:
        params[variable_name] = variable_value

    if iterable_collection and iterable_as:
        loop_index = 0
        params['$as_all'] = iterable_collection
        params['$as_size'] = len(iterable_collection)
        for loop_as in iterable_collection:
            params['$as_index'] = loop_index
            params['$as_first'] = loop_index == 0
            params['$as_last'] = loop_index == (len(iterable_collection) - 1)
            parity = 'odd' if loop_index % 2 else 'even'
            params['$as_parity'] = parity
            params['$as_even'] = parity == 'even'
            params['$as_odd'] = parity == 'odd'
            loop_index += 1
            params[iterable_as] = loop_as
            try:
                for element in node:
                    new_node = render_node(element, node, template, params)
                    if parent is not None and new_node is not None:
                        parent.append(new_node)
            except TContinue:
                pass
            except TBreak:
                break
        return None

    elif while_expression:
        loop_index = 0
        while safe_eval(while_expression, locals_dict=params):
            params['$as_index'] = loop_index
            params['$as_first'] = loop_index == 0
            parity = 'odd' if loop_index % 2 else 'even'
            params['$as_parity'] = parity
            params['$as_even'] = parity == 'even'
            params['$as_odd'] = parity == 'odd'
            loop_index += 1
            try:
                for element in node:
                    new_node = render_node(element, node, template, params)
                    if parent is not None and new_node is not None:
                        parent.append(new_node)
            except TContinue:
                pass
            except TBreak:
                break
        return None

    else:
        if node.tag == 't':
            for element in node:
                new_node = render_node(element, parent, template, params)
                if parent is not None and new_node is not None:
                    parent.append(new_node)
            return None

        for element in node:
            new_node = render_node(element, copied_node, template, params)
            if new_node is not None:
                copied_node.append(new_node)

    return copied_node


def render(template_string: str, template,  **params) -> str:
    try:
        xml_parser = lxml.etree.XMLParser(encoding='UTF-8',
                                      resolve_entities=False,
                                      strip_cdata=False,
                                      recover=True,
                                      ns_clean=True)
        template_tree = lxml.etree.fromstring(template_string.encode('UTF-8'), parser=xml_parser)
        output_tree = render_node(template_tree, template=template, params=params)
        return lxml.etree.tostring(output_tree, encoding='UTF-8').decode('UTF-8') \
            if output_tree is not None else ''

    except TBreak:
        trace_msg = _('<t-break> out of loop construction!')
        _logger.exception(trace_msg, exc_info=True)
        raise exceptions.UserError(trace_msg, )

    except TContinue:
        trace_msg = _('<t-continue> out of loop construction!')
        _logger.exception(trace_msg, exc_info=True)
        raise exceptions.UserError(trace_msg)

    except LxmlError as tree_exception:
        _logger.exception(_(f'While processing {template_string}\nwith params {params}, '
                            'unexpected parsing exception {tree_exception}') %
                          dict(template=template_string, params=params, tree_exception=tree_exception),
                          exc_info=True)
        raise tree_exception
