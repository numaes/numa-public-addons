# 🚀 Numa Poly: Unlocking True Polymorphic Inheritance for Odoo 18

**Numa Poly** is not just another Odoo module; it is a fundamental infrastructure breakthrough that shatters the historical limitations of Odoo's inheritance system. It enables **True Polymorphic Inheritance**, allowing a single physical business record to coexist across multiple models simultaneously, sharing the same identity (ID) and data space.

This is the bedrock for high-tier enterprise software where complexity meets performance.

---

## 😫 The "Why": Beyond the Limits of Odoo Inheritance

Standard Odoo offers two paths for inheritance, both with architectural bottlenecks:
1.  **`_inherit` (Extension):** Great for adding fields, but limited to a linear hierarchy. You cannot easily have a record that is "partially" multiple things without creating messy Many2one chains.
2.  **`_inherits` (Delegation):** Creates "Russian Doll" tables. Every parent is a separate record with a different ID, leading to massive JOIN costs, fragmented metadata, and nightmare referential integrity.

**The Cost:** In complex systems (Healthcare, Fintech, Multi-Industry Assets), these patterns lead to data duplication, sluggish queries, and rigid models that break under the weight of real-world business requirements.

---

## ⚡ The Breakthrough: One Identity, Multiple Personalities

**Numa Poly** introduces a unified ID space. A record with ID `100` exists in the central registry (`ir.poly_base`) and can simultaneously exist in any number of base models and its concrete implementation.

When you define a polymorphic model, Odoo no longer sees separate entities; it sees **one unified record** that exposes all fields and methods from its entire hierarchy transparently.

---

## 🔥 Key Brutal Features

*   **🧬 Multiple Polymorphic Inheritance:** Inherit from multiple parents simultaneously using `_depend_models`. No intermediate tables, no boilerplate.
*   **🆔 Shared ID Space:** One ID to rule them all. Absolute referential integrity across the entire stack.
*   **🏎️ SQL-Level Performance:** By patching the core ORM, searches and filtering across complex hierarchies are processed at the database layer with near-zero overhead.
*   **🔌 Backward Compatibility:** Adopt it today. It handles "legacy" records (pre-poly) gracefully and is completely transparent to standard Odoo models.
*   **🛠️ Architectural Foundation:** It is the power engine behind **`numa_fsm`**, proving its stability in managing complex State Machines and dynamic UI schemas.

---

## 🏛️ Showcase: The "Universal Identity" Pattern

Imagine a system where a single person is a **Partner**, an **Employee**, and a **Doctor**—all at once, with the same ID.

```python
class Doctor(models.Model):
    _name = 'hospital.doctor'
    # Multiple inheritance: inherit identity from Partner and behavior from Employee
    _depend_models = OrderedDict([
        ('res.partner', 'partner_id'),
        ('hr.employee', 'employee_id'),
    ])
    
    specialty = fields.Char("Medical Specialty")

# Now, Doctor ID 500 IS Partner ID 500 and Employee ID 500.
# Any change to 'name' (from Partner) or 'work_email' (from Employee) 
# is instant and native on the Doctor record.
```

---

## 🛡️ Guarantee of Stability: Why Monkey Patching?

We chose to monkey patch `BaseModel` not out of convenience, but out of a **pragmatic design philosophy**. By injecting polymorphic logic directly into the ORM core:
1.  The implementation remains **transparent** to the end-user and other developers.
2.  Standard Odoo features (Studio, Import/Export, API) work out-of-the-box.
3.  We avoid the "lock-in" of custom base classes that would force you to rewrite your entire codebase.

The patch is guarded with strict checks: if a model doesn't define `_depend_models`, **Numa Poly** stays silent, consuming zero resources.

---

## 🧐 FAQ for the Skeptics

**"Isn't monkey patching dangerous?"**  
Only if done blindly. **Numa Poly** is designed for Odoo 18's specific internals, with recursion guards and metadata synchronization. It's been battle-tested in large-scale implementations.

**"What happens to my old data?"**  
Nothing. **Numa Poly** detects records without a `poly_base` entry and treats them as "Self-Concrete" models. Migration is incremental, not mandatory.

**"Does it affect performance?"**  
It improves it. By avoiding the JOIN-heavy patterns of standard delegation, you get a flatter, faster database structure.

---

## 🌐 Open Source & Community

We believe in taking Odoo to the next level. **Numa Poly** is our contribution to making Odoo the most flexible ERP platform on the planet. Use it, break it, and help us build the future of polymorphic business logic.

Developed and maintained with ❤️ by **NUMA Extreme Systems**.
[info@numaes.com](mailto:info@numaes.com)
