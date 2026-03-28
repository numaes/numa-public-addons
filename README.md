<div align="center">
  <!-- You can replace the placeholder below with your actual company logo URL -->
  <h1>Odoo 18.0 Advanced Architecture & Business Addons</h1>
  
  <p>
    <em>A collection of enterprise-grade, highly scalable architectural modules and business extensions for Odoo 18.0, proudly developed by <strong>NUMA EXTREME SYSTEMS</strong>.</em>
  </p>

  <p>
    <a href="https://www.numaes.com">Website</a> •
    <a href="mailto:info@numaes.com">Contact Us for Enterprise Support</a>
  </p>

  <p>
    <img alt="Odoo Version" src="https://img.shields.io/badge/Odoo-18.0-blueviolet?style=for-the-badge&logo=odoo" />
    <img alt="License" src="https://img.shields.io/badge/License-LGPL_v3-blue?style=for-the-badge" />
    <img alt="Maintained" src="https://img.shields.io/badge/Maintained%3F-Yes-green.svg?style=for-the-badge" />
  </p>
</div>

---

## 🚀 About This Repository

Welcome to the public repository of **NUMA EXTREME SYSTEMS**. We are a team of senior software engineers and architects specializing in extreme performance, infinite scalability, and complex integrations within the Odoo ecosystem. 

This repository houses our public, open-source modules designed to solve hard engineering problems in Odoo 18.0. Whether you need offline-first synchronization, event-driven architectures, real-time observability, or to break Odoo's integer limits with BIGINTs, you will find foundational tools here to take your Odoo instances to the next level.

---

## 💼 Enterprise Support & Consulting

**Are you building a mission-critical system on Odoo?**

While these modules are open-source, implementing complex architectural patterns (like Pub/Sub, Offline-First Synchronization, or Asynchronous Execution) requires deep expertise. 

At **NUMA EXTREME SYSTEMS**, we offer:
- **Architectural Consulting:** Design scalable, high-performance Odoo infrastructures.
- **Custom Development:** Tailor-made modules, advanced workflows, and robust integrations.
- **Enterprise Support & Maintenance:** SLA-backed support for your production environments.
- **Performance Tuning:** Optimize slow queries, manage high concurrency, and implement BIGINT scalability.

👉 **[Contact us today to discuss your project requirements: info@numaes.com](mailto:info@numaes.com)** or visit **[www.numaes.com](https://www.numaes.com)**.

---

## 📦 Module Ecosystem

Our modules are categorized into distinct domains of expertise:

### 🏗️ Architecture & Core Engineering
Modules designed to bypass standard Odoo limitations and introduce enterprise software patterns.
- **`numa_synch`** / **`numa_synch_master`** / **`numa_synch_slave`**: Foundational core modules for a robust, offline-first synchronization system across distributed Odoo nodes.
- **`numa_synch_ai_assisted`**: AI-assisted schema adaptation for seamless synchronization with non-Odoo external systems.
- **`numa_asynch_exec`**: Robust, persistent, and traceable asynchronous execution infrastructure for Odoo 18.
- **`numa_background_job`**: Advanced background job scheduling and execution.
- **`numa_real_time_observability`**: Real-time observability mixin for Odoo models via bus notifications, bringing modern APM capabilities to your custom models.
- **`numa_big_id`**: **(Extreme Scalability)** Automatically convert all integer IDs and foreign keys to BIGINT (int8) for infinite scalability in massive deployments.
- **`numa_exceptions`**: Advanced Exception Logging, handling, and traceability.
- **`numa_poly`**: Introduces true Polymorphic model inheritance for Odoo, solving complex data modeling challenges.

### ⚙️ Automation & Event-Driven Workflows (FSM)
A comprehensive suite for Finite State Machine process automation.
- **`numa_fsm`**: Powerful Finite State Machine engine for process automation and strict state control.
- **`numa_fsm_pubsub`**: Event-Driven Architecture for FSM Instances utilizing the robust Pub/Sub pattern.
- **`numa_fsm_crm`**: Integrates FSM capabilities directly into CRM Leads.
- **`numa_fsm_hr`**: Integrates FSM capabilities into HR Employees.

### 🏢 Business, Security & Domain Extensions
- **`numa_roles`**: Advanced RBAC (Role-Based Access Control) system for Odoo, providing granular security beyond standard groups.
- **`numa_physical_product`** (and related `_purchase`, `_sale`, `_stock`, `_invoice`): Comprehensive suite for strict physical product management.
- **`numa_periodic_services`**: Administration and billing of recurring and periodic services.
- **`numa_product_variant`**: Enhancements to the standard product variants logic.
- **`numa_imap`**: Advanced IMAP integration and email handling extensions.

---

## 🛠️ Installation

1. Clone this repository into your Odoo 18.0 addons path:
   ```bash
   git clone -b 18.0 https://github.com/[your-org]/numa-public-addons-18.0.git /path/to/your/addons/numa-public-addons
   ```
   *(Note: replace `[your-org]` with your actual GitHub organization or username).*
2. Update your `odoo.conf` to include the new path in `addons_path`.
3. Restart your Odoo server.
4. Enable **Developer Mode** in Odoo.
5. Go to **Apps** > **Update Apps List**.
6. Search for `Numa` and install the desired modules.

---

## 🤝 Contributing & Support

We welcome contributions from the community! If you'd like to improve these modules or submit bug fixes, please open a Pull Request.

For bug reports, please use the GitHub Issues tracker. 

**For production support, architectural changes, or feature additions**, please contact our core engineering team directly at [info@numaes.com](mailto:info@numaes.com) to discuss commercial arrangements.

---

## 📄 License

All modules in this repository are licensed under the **GNU LESSER GENERAL PUBLIC LICENSE, Version 3 (LGPLv3)**. Please see the [LICENSE](./LICENSE) and [COPYRIGHT](./COPYRIGHT) files for more information.

<div align="center">
  <br/>
  <b>Engineered with passion by <a href="https://www.numaes.com">NUMA EXTREME SYSTEMS</a></b>
</div>