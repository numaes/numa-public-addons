odoo.define('prt_mail_messages.list_renderer', function(require) {
    "use strict";
    var field_utils = require('web.field_utils');
    var ListRenderer = require('web.ListRenderer');

    // Simplify renderer and skip adding title
    ListRenderer.include({
        _renderBodyCell: function (record, node, colIndex, options) {
            if (!(record.model === 'mail.message' || record.model === 'cetmix.conversation')) {
                return  this._super.apply(this, arguments);
            }
            var tdClassName = 'o_data_cell oe_read_only';
            var $td = $('<td>', { class: tdClassName, tabindex: -1 });

            // We register modifiers on the <td> element so that it gets the correct
            // modifiers classes (for styling)
            var modifiers = this._registerModifiers(node, record, $td, _.pick(options, 'mode'));
            // If the invisible modifiers is true, the <td> element is left empty.
            // Indeed, if the modifiers was to change the whole cell would be
            // rerendered anyway.
            if (modifiers.invisible && !(options && options.renderInvisible)) {
                return $td;
            }

            this._handleAttributes($td, node);
            var name = node.attrs.name;
            var field = this.state.fields[name];
            var value = record.data[name];
            var formatter = field_utils.format[field.type];
            var formatOptions = {
                escape: true,
                data: record.data,
                isPassword: false,
                digits: false,
            };
            var formattedValue = formatter(value, field, formatOptions);
            return $td.html(formattedValue);
        },
    });
});