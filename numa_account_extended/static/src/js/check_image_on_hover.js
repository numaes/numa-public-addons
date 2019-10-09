odoo.define("check_image_on_hover.ListView", function (require) {
"use strict";

    var ListView = require("web.ListView");
    var KanbanView = require("web_kanban.KanbanView");
    var FormView = require("web.FormView");
    // var Model = require('web.DataModel');
    // var Product = new Model('product.template');
    ListView.include({
        // do something 
        do_show: function () {
            // var product = this.records.records
            if (this.dataset.model == 'account.own_check' || this.dataset.model == 'account.third_party_check'){
                    var model = this.dataset.model;
                    this.$el.find('tbody').find('tr').popover(
                        {
                            'content': function(e){
                                if (typeof($(this).attr('data-id')) == 'string') {
                                    return '<img src="/web/image?model=' + model + '&id='+ $(this).attr('data-id') +'&field=front_image" class="img-responsive"/>';
                                } else {
                                    return '';
                                }
                            },
                            'html': true,
                            'placement':  function(c,s){
                                return $(s).position().top < 200 ?'bottom':'top'
                            },
                            'trigger': 'hover',
                        });
            }
            return this._super();
        }
    })
});
