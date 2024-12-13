====================================
Odoo 18 Polymorphic Inheritance
====================================

This Module will provide the basic modifications to core Odoo ORM to implement
multiple polymorphic inheritance

Installation
============

To install this module, you need to:

Download the module and add it to your Odoo addons folder. Afterward, log on to
your Odoo server and go to the Apps menu. Trigger the debug mode and update the
list by clicking on the "Update Apps List" link. Now install the module by
clicking on the install button.

Upgrade
============

To upgrade this module, you need to:

Download the module and add it to your Odoo addons folder. Restart the server
and log on to your Odoo server. Select the Apps menu and upgrade the module by
clicking on the upgrade button.


Configuration
=============

There is Nothing to Configure

Usage
=====
In order to use multiple inheritance in your classes you could add an special field
in your model declaration to indicate your are using it:
For example, from the tests:

class Test1(models.TransientModel):
    _name = 'test.test1'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict()

    a1 = fields.Char('A1')
    a2 = fields.Char('A2')


class Test2(models.TransientModel):
    _name = 'test.test2'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a3 = fields.Char('A3')


class Test3(models.TransientModel):
    _name = 'test.test3'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a4 = fields.Char('A4')


class Test4(models.TransientModel):
    _name = 'test.test4'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict([
        ('test.test2', 'test2_id'),
        ('test.test3', 'test3_id'),
    ])

    a3 = fields.Char('A3 test 4')

In this case Test2 and Test3 implements multiple inheritance on Test1. Test4 inherits both Test2 and Test3
and thus implicitally Test1

Inheritance is implemented using the one model per concrete class strategy. That means
an instance will be composed by components of different models, all sharing the same id

For example, in tests after running several instances will be created. In the database
you will see:

demo-18.0=# select * from ir_poly_base;
  id  | concrete_model_id | create_uid | write_uid |        create_date         |         write_date
------+-------------------+------------+-----------+----------------------------+----------------------------
 1244 |              1593 |          2 |         2 | 2024-12-13 15:31:51.085711 | 2024-12-13 15:31:51.085711
 1245 |              1594 |          2 |         2 | 2024-12-13 15:31:51.085711 | 2024-12-13 15:31:51.085711
 1246 |              1595 |          2 |         2 | 2024-12-13 15:31:51.085711 | 2024-12-13 15:31:51.085711
 1247 |              1594 |          2 |         2 | 2024-12-13 15:31:51.085711 | 2024-12-13 15:31:51.085711
 1248 |              1596 |          2 |         2 | 2024-12-13 15:31:51.085711 | 2024-12-13 15:31:51.085711
(5 rows)

demo-18.0=# select * from test_test1;
  id  | create_uid | write_uid | a1 | a2 | create_date | write_date
------+------------+-----------+----+----+-------------+------------
 1244 |            |           | A1 | A2 |             |
 1245 |            |           |    |    |             |
 1246 |            |           |    |    |             |
 1247 |            |           | B1 | B2 |             |
 1248 |            |           | C1 | C2 |             |
(5 rows)

demo-18.0=# select * from test_test2;
  id  | create_uid | write_uid | a3 | create_date | write_date
------+------------+-----------+----+-------------+------------
 1245 |            |           | A3 |             |
 1247 |            |           | B3 |             |
 1248 |            |           | C3 |             |
(3 rows)

demo-18.0=# select * from test_test3;
  id  | create_uid | write_uid | a4 | create_date | write_date
------+------------+-----------+----+-------------+------------
 1246 |            |           | A4 |             |
 1248 |            |           |    |             |
(2 rows)

demo-18.0=# select * from test_test4;
  id  | partner_id | create_uid | write_uid | a3 | create_date | write_date
------+------------+------------+-----------+----+-------------+------------
 1248 |         47 |            |           | D3 |             |
(1 row)

Note that a single instance has just one id, shared among several base models.
For example a Test4 instance will have Test2, Test3 and Test1 components

ir_poly_base is also created for every polymorphic instance. This model will
have the minimum metadata for the instance, its id, its concrete model, and
all the log fields

In order to implement this strategy, under the hood it is implemented using related
fields using special Many2one references created with the record id (all components
share the id, it is not necessary to store nothing to reference the other parts)

The implementation support several layers of inheritance. The inheritance tree is
flatten in order to construct the relation fields. Thus, speed is independent of
of inheritance tree depth.

Also search expressions are adapted to generate proper LEFT JOINS to access all
instance fields

These expanded feature replace the use of type fields and convoluted condicional
logic to get similar behaviour. As examples, take sale.order.line with different
line types selected for display purposes and several more conflicting cases like
the all propose account.move, where the spaghetti code makes really hard to customize
or modify the standard behaviour

In fact, UML modelled systems can now be easily implemented in Odoo, where the
modeled classes can be converted into models directly (why not in the future with
automated UML class diagrams convertion!)

The implementation does not change Odoo behaviour for non polymorphic models, so
it can be safely used in existing databases. Only new modules, depending on
numa_poly could taken advantage of the new functionality

This module is a proof of concept. Use in production under your own risk or
test seriously your app. No commitment on reliability or correctness is made,
out of our best effort to cover common cases.

In the future we hope this functionality will be added to the core Odoo. It
enables the system to support complex enterprise cases and it makes Odoo a
better system to develop enterprise applications


Credits
=======

Contributors
------------
Gustavo Marino <gamarino@numaes.com>

* NUMA Extreme Systems <info@numaes.com>


Author & Maintainer
-------------------

This module is maintained by NUMA Extreme Systems
