odoo.define('prt_mail_messages.list_controller', function(require) {
    "use strict";
    var ListController = require('web.ListController');
    ListController.include({
        renderPager: function ($node, options) {
            if (this.modelName === 'mail.message') {
                options = {can_edit:false};
            }
            return this._super($node, options);
        },
    });
});