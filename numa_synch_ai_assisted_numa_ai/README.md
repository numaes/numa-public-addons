# Numa Synch AI Assisted — numa_ai bridge

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

One method. That is the whole module.

`numa_synch_ai_assisted` knows what to ask an AI and what to do with the answer: which
schema to read, which prompt to build, which transformation map to cache, which gap
report to log. It does not know **who** answers, and it does not depend on any
particular provider — a database without one still installs it and uses its cached and
hand-written maps.

This module implements the seam:

```python
def _ask_llm(self, prompt):
    return self.env['numa.ai.engine'].ask_llm(prompt, json_mode=True)
```

It declares both sides in `depends` and sets `auto_install`, so it appears by itself the
moment `numa_synch_ai_assisted` and `numa_ai` are both present, and disappears from the
question entirely when they are not.

## Why it is separate

`numa_ai` used to be a hard dependency of `numa_synch_ai_assisted`. That made a whole
feature — cached schema adaptation, gap analysis, manual maps — unavailable to any
database that did not want an LLM, for the sake of one call.

Splitting it also puts the provider in exactly one file, which is where a second
provider would be added: another bridge, another `_ask_llm`, no change to the module
that does the work.

## License and Author

- **Copyright:** NUMA Extreme Systems
- **License:** LGPL-3
- **Website:** [http://www.numaes.com](http://www.numaes.com)
