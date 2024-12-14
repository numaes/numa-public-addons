Here is the improved English version of your text:

---

# Odoo 18 Polymorphic Inheritance

This module introduces core modifications to the Odoo ORM, enabling support for multiple polymorphic inheritance.

## Installation

To install this module:

1. Download the module and place it in your Odoo addons folder.
2. Log in to your Odoo server and navigate to the **Apps** menu.
3. Enable debug mode and update the app list by clicking on the **Update Apps List** link.
4. Finally, install the module by clicking the **Install** button.

## Upgrade

To upgrade this module:

1. Download the updated version and place it in your Odoo addons folder.
2. Restart the server and log in to your Odoo server.
3. Go to the **Apps** menu and click the **Upgrade** button to update the module.

## Configuration

No configuration is required.

## Usage

To utilize multiple inheritance in your classes, add a special field in your model declaration to indicate its usage. For instance, consider the following examples from the tests:

```python
class Test1(models.TransientModel):
    _name = 'test.test1'
    _description = 'Polymorphic Test1'

    _depend_models = OrderedDict()

    a1 = fields.Char('A1')
    a2 = fields.Char('A2')


class Test2(models.TransientModel):
    _name = 'test.test2'
    _description = 'Polymorphic Test2'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a3 = fields.Char('A3')


class Test3(models.TransientModel):
    _name = 'test.test3'
    _description = 'Polymorphic Test3'

    _depend_models = OrderedDict([
        ('test.test1', 'test1_id'),
    ])

    a4 = fields.Char('A4')


class Test4(models.TransientModel):
    _name = 'test.test4'
    _description = 'Polymorphic Test4'

    _depend_models = OrderedDict([
        ('test.test2', 'test2_id'),
        ('test.test3', 'test3_id'),
    ])

    a3 = fields.Char('A3 test 4')
```

In this example:
- `Test2` and `Test3` both inherit from `Test1`.
- `Test4` inherits from `Test2` and `Test3`, thus implicitly inheriting from `Test1` as well.

Inheritance is implemented using the "one model per concrete class" strategy. This means an instance consists of components from various models, all sharing the same ID.

For example, after running tests, several instances are created. In the database, you will see:

```sql
demo-18.0=# select * from ir_poly_base;
 id | concrete_model_id | create_uid | write_uid | create_date | write_date 
----+-------------------+------------+-----------+-------------+------------
(0 rows)

demo-18.0=# select * from test_test1;
 id | a1 | a2 
----+----+----
(0 rows)

demo-18.0=# select * from test_test2;
 id | a3 
----+----
(0 rows)

demo-18.0=# select * from test_test3;
 id | a4 
----+----
(0 rows)

demo-18.0=# select * from test_test4;
 id | partner_id | a3 
----+------------+----
(0 rows)

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

```

Additional details of other models (`test_test1`, `test_test2`, etc.) would reflect similar relationships.

## Key Points

1. **Shared IDs**: A single instance shares one ID across several base models. For example, a `Test4` instance includes components from `Test2`, `Test3`, and `Test1`.
2. **Metadata Management**: A polymorphic instance generates an entry in the `ir_poly_base` table, containing minimal metadata like ID, concrete model, and log fields.
3. **Inheritance Strategy**: Related fields (special Many2one references) handle relationships internally, allowing for efficient storage and lookups.

## Performance and Scalability

The implementation supports deep inheritance trees by flattening them to construct relation fields, making performance independent of tree depth. Search expressions automatically generate optimized LEFT JOINs to access instance fields.

## Benefits

These features replace complex type fields and convoluted conditional logic previously needed to achieve similar functionality. For example:
- `sale.order.line` uses different line types for display purposes.
- `account.move` struggles with customization due to its tightly coupled code.

With this module, UML-modeled systems can now be implemented directly in Odoo. Modeled classes can be transformed into models, potentially leading to automated UML class diagram conversion in the future.

## Limitations and Future Potential

This module does not alter Odoo's behavior for non-polymorphic models, ensuring compatibility with existing databases. New modules dependent on `numa_poly` can leverage these features.

**Note**: This module is a proof of concept. Use it in production at your own risk and thoroughly test your applications. While we have made every effort to cover common cases, no guarantees are made regarding reliability or correctness.

We hope this functionality will eventually be incorporated into Odoo's core, enabling it to support complex enterprise cases and enhancing its suitability for developing robust enterprise applications.

--- 

Let me know if you need further refinements!


Credits
=======

Contributors
------------
Gustavo Marino <gamarino@numaes.com>

* NUMA Extreme Systems <info@numaes.com>


Author & Maintainer
-------------------

This module is maintained by NUMA Extreme Systems
