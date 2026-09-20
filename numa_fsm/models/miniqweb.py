# -*- coding: utf-8 -*-
"""
miniqweb: the subset of QWeb with which numa_fsm renders portal pages and mails.

The template may be a fragment: plain text, several elements at the root, or the HTML stored by
an Html field (``<br>``, ``&nbsp;``). The output is serialized as HTML.

Directives:

- ``t-if`` / ``t-elif`` / ``t-else``, on consecutive sibling elements.
- ``t-foreach`` + ``t-as``: repeats the element. Defines ``<as>``, ``<as>_value``, ``<as>_index``,
  ``<as>_size``, ``<as>_first``, ``<as>_last``, ``<as>_parity``, ``<as>_even``, ``<as>_odd`` and
  ``<as>_all``, which do not leave the loop. An integer iterates ``range(n)``; a dict, its keys.
- ``t-while``: repeats the element while the expression is true, with a cap on the iterations.
- ``t-set`` with ``t-value``, or with its content rendered as the value.
- ``t-esc`` (escaped text) and ``t-raw`` (markup inserted as is, without evaluating directives):
  they replace the content of the element. ``None`` and ``False`` emit nothing.
- ``t-att-<name>`` (omitted when ``None`` or ``False``), ``t-att`` (dict or pairs) and
  ``t-attf-<name>`` (``#{expr}``, ``{{ expr }}`` or ``{variable}``).
- The ``<t-break/>`` and ``<t-continue/>`` elements, inside a loop.

``<t>`` generates no element: it contributes its text and its content. Comments are not emitted. A
directive that is not in this list is an error, not just another attribute.
"""
import html
import html.entities
import logging
import re

import lxml.etree
from lxml.etree import LxmlError
from markupsafe import Markup

from odoo import exceptions, _
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

MAX_WHILE_ITERATIONS = 10000


class TBreak(Exception):
    pass


class TContinue(Exception):
    pass


xml_parser = lxml.etree.XMLParser(encoding='UTF-8',
                                  resolve_entities=False,
                                  strip_cdata=False,
                                  recover=True,
                                  ns_clean=True)

_FRAGMENT = 'miniqweb-fragment'
_VOID_ELEMENTS = ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param',
                  'source', 'track', 'wbr')
_VOID_CLOSE = re.compile(r'</(?:%s)\s*>' % '|'.join(_VOID_ELEMENTS), re.IGNORECASE)
_ATTRIBUTE_VALUE = r'"[^"]*"|\'[^\']*\'|[^\s"\'=<>`]+'
_START_TAG = re.compile(r'<([A-Za-z][\w:.-]*)((?:\s+[^\s"\'<>/=]+(?:\s*=\s*(?:%s))?)*)\s*(/?)>' % _ATTRIBUTE_VALUE)
_ATTRIBUTE = re.compile(r'\s+([^\s"\'<>/=]+)(?:\s*=\s*(%s))?' % _ATTRIBUTE_VALUE)
_XML_DECLARATION = re.compile(r'^\s*<\?xml[^>]*\?>')
_NAMED_ENTITY = re.compile(r'&([A-Za-z][A-Za-z0-9]*);')
_XML_ENTITIES = frozenset(('amp', 'lt', 'gt', 'quot', 'apos'))
_BARE_AMPERSAND = re.compile(r'&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);)')
_ATTF_PLACEHOLDER = re.compile(r'#\{(.+?)\}|\{\{(.+?)\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}')
_DIRECTIVES = frozenset(('t-if', 't-elif', 't-else', 't-foreach', 't-as', 't-while', 't-set', 't-value',
                         't-esc', 't-raw', 't-att'))


def _start_tag(match):
    name, attributes, closed = match.groups()

    def attribute(attribute_match):
        key, value = attribute_match.groups()
        if value is None:
            value = '"%s"' % key  # HTML boolean attribute: multiple, checked, disabled…
        elif value[0] in '"\'':
            # XML rejects '<' in a value: an expression like t-att-title="'<br>'" was truncated.
            value = value[0] + value[1:-1].replace('<', '&lt;') + value[-1]
        else:
            value = '"%s"' % value
        return ' %s=%s' % (key, value)

    if not closed and name.lower() in _VOID_ELEMENTS:
        closed = '/'
    return '<%s%s%s>' % (name, _ATTRIBUTE.sub(attribute, attributes), closed)


def _as_xml(template):
    """The HTML of an Html field, as XML that lxml can parse: without declaration, with the empty
    elements closed, the attribute values quoted and the named entities as numeric
    references. An attribute without a value is not valid XML, and the tolerant parser
    dropped it: the ``multiple`` of the portal file input was lost."""
    text = _XML_DECLARATION.sub('', template)
    text = _VOID_CLOSE.sub('', text)
    text = _START_TAG.sub(_start_tag, text)

    def entity(match):
        name = match.group(1)
        if name in _XML_ENTITIES or name not in html.entities.name2codepoint:
            return match.group(0)
        return '&#%d;' % html.entities.name2codepoint[name]

    # A bare '&' (a URL with several parameters, "a & b") is not valid XML.
    return _BARE_AMPERSAND.sub('&amp;', _NAMED_ENTITY.sub(entity, text))


def _parse(template):
    """Parses a fragment inside a container element. Returns the container or None."""
    source = '<%s>%s</%s>' % (_FRAGMENT, _as_xml(str(template)), _FRAGMENT)
    try:
        return lxml.etree.fromstring(source.encode('UTF-8'), parser=xml_parser)
    except LxmlError:
        _logger.exception('miniqweb: unexpected parsing error in template %r', template)
        raise


def _evaluate(expression, params):
    # [fsm][20.0] safe_eval(expr, /, context=None, *, mode, filename): the namespace
    # is passed positionally, and the locals_dict keyword no longer exists
    # (tools/safe_eval/evaluation.py:388).
    return safe_eval(expression, params)


def _text(value):
    return '' if value is None or value is False else str(value)


def _append_text(target, text):
    """Appends text at the end of what was already emitted into ``target``: to the tail of the
    last child, or to its text."""
    if not text:
        return
    if len(target):
        last = target[-1]
        last.tail = (last.tail or '') + text
    else:
        target.text = (target.text or '') + text


def _append_markup(target, value):
    """Inserts markup at the end of ``target``, as is: its directives are not evaluated."""
    if value is None or value is False:
        return
    fragment = _parse(value)
    if fragment is None:
        return
    _append_text(target, fragment.text)
    for child in list(fragment):
        target.append(child)


def _serialize_children(element):
    parts = [html.escape(element.text or '', quote=False)]
    parts.extend(lxml.etree.tostring(child, method='html', encoding='unicode') for child in element)
    return ''.join(parts)


def _check_directives(node, attributes):
    for name in attributes:
        if name.startswith('t-') and name not in _DIRECTIVES and not name.startswith(('t-att-', 't-attf-')):
            raise exceptions.UserError(_('Unsupported template directive %s in <%s>') % (name, node.tag))


def _render_children(source, target, params):
    """Renders the text and the children of ``source`` at the end of ``target``."""
    _append_text(target, source.text)
    chain = None
    for child in source:
        if isinstance(child.tag, str):
            chain = _render_node(child, target, params, chain)
        # A comment or a processing instruction is not emitted, but its tail is.
        _append_text(target, child.tail)


def _render_node(node, target, params, chain, attributes=None):
    """Renders ``node`` at the end of ``target``.

    Returns the state of the t-if / t-elif / t-else chain for the next sibling: None outside of
    a chain, True if a branch was already taken, False if not yet."""
    if node.tag == 't-break':
        raise TBreak()
    if node.tag == 't-continue':
        raise TContinue()
    if attributes is None:
        attributes = dict(node.attrib)
        _check_directives(node, attributes)

    if 't-foreach' in attributes:
        _render_foreach(node, attributes, target, params)
        return None
    if 't-while' in attributes:
        _render_while(node, attributes, target, params)
        return None

    if 't-if' in attributes:
        if not _evaluate(attributes['t-if'], params):
            return False
        following = True
    elif 't-elif' in attributes:
        if chain is None:
            raise exceptions.UserError(_('t-elif without a preceding t-if in <%s>') % node.tag)
        if chain or not _evaluate(attributes['t-elif'], params):
            return chain
        following = True
    elif 't-else' in attributes:
        if chain is None:
            raise exceptions.UserError(_('t-else without a preceding t-if in <%s>') % node.tag)
        if chain:
            return None
        following = None
    else:
        following = None

    _render_body(node, attributes, target, params)
    return following


def _render_foreach(node, attributes, target, params):
    name = attributes.get('t-as')
    if not name:
        raise exceptions.UserError(_('t-foreach without t-as in <%s>') % node.tag)
    collection = _evaluate(attributes['t-foreach'], params)
    if collection is None or isinstance(collection, bool):
        items = []
    elif isinstance(collection, int):
        items = list(range(collection))
    else:
        items = list(collection)
    rest = {key: value for key, value in attributes.items() if key not in ('t-foreach', 't-as')}
    size = len(items)
    loop_params = dict(params)
    for index, item in enumerate(items):
        parity = 'odd' if index % 2 else 'even'
        loop_params.update({
            name: item,
            name + '_value': collection[item] if isinstance(collection, dict) else item,
            name + '_index': index,
            name + '_size': size,
            name + '_first': index == 0,
            name + '_last': index == size - 1,
            name + '_parity': parity,
            name + '_even': parity == 'even',
            name + '_odd': parity == 'odd',
            name + '_all': collection,
        })
        try:
            _render_node(node, target, loop_params, None, rest)
        except TContinue:
            continue
        except TBreak:
            break


def _render_while(node, attributes, target, params):
    rest = {key: value for key, value in attributes.items() if key != 't-while'}
    iterations = 0
    while _evaluate(attributes['t-while'], params):
        iterations += 1
        if iterations > MAX_WHILE_ITERATIONS:
            raise exceptions.UserError(
                _('t-while exceeded %s iterations in <%s>') % (MAX_WHILE_ITERATIONS, node.tag))
        try:
            _render_node(node, target, params, None, rest)
        except TContinue:
            continue
        except TBreak:
            break


def _render_body(node, attributes, target, params):
    if 't-set' in attributes:
        if 't-value' in attributes:
            value = _evaluate(attributes['t-value'], params)
        else:
            holder = lxml.etree.Element(_FRAGMENT)
            _render_children(node, holder, params)
            value = Markup(_serialize_children(holder))
        params[attributes['t-set']] = value
        return

    if node.tag == 't':
        container = target
    else:
        container = lxml.etree.SubElement(target, node.tag)
        _set_attributes(container, attributes, params)

    if 't-esc' in attributes:
        _append_text(container, _text(_evaluate(attributes['t-esc'], params)))
    elif 't-raw' in attributes:
        _append_markup(container, _evaluate(attributes['t-raw'], params))
    else:
        _render_children(node, container, params)


def _set_attributes(element, attributes, params):
    for name, value in attributes.items():
        if name.startswith('t-attf-'):
            element.set(name[len('t-attf-'):], _format(value, params))
        elif name.startswith('t-att-'):
            _set_attribute(element, name[len('t-att-'):], _evaluate(value, params))
        elif name == 't-att':
            values = _evaluate(value, params)
            for key, val in (values.items() if isinstance(values, dict) else values or ()):
                _set_attribute(element, key, val)
        elif not name.startswith('t-'):
            element.set(name, value)


def _set_attribute(element, name, value):
    if value is None or value is False:
        element.attrib.pop(name, None)
    else:
        element.set(name, str(value))


def _format(template, params):
    def placeholder(match):
        expression, jinja_expression, variable = match.groups()
        if variable is not None:
            return _text(params[variable]) if variable in params else match.group(0)
        return _text(_evaluate(expression or jinja_expression, params))

    return _ATTF_PLACEHOLDER.sub(placeholder, template)


def render(template: str, **params) -> str:
    """Renders ``template`` with ``params``. Returns HTML, without leading or trailing spaces."""
    if template is None or template is False:
        return ''
    fragment = _parse(template)
    if fragment is None:
        return ''
    output = lxml.etree.Element(_FRAGMENT)
    try:
        _render_children(fragment, output, params)
    except TBreak:
        trace_msg = _('<t-break> out of loop construction!')
        _logger.error(trace_msg)
        raise exceptions.UserError(trace_msg)
    except TContinue:
        trace_msg = _('<t-continue> out of loop construction!')
        _logger.error(trace_msg)
        raise exceptions.UserError(trace_msg)
    return _serialize_children(output).strip()
