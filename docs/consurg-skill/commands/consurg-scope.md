---
name: consurg-scope
description: Show the active Context Surgeon scope with files organized by tier
allowed-tools: Read, Glob
---

Read the `.consurg.yaml` file in the current project root. If it does not exist, respond with "No scope active."

If it exists, generate a structured scope block in this format:

```
## Active Scope: {scope_name}
Status: {ACTIVE or INACTIVE}

### Tier 4 - READ-WRITE (full access)
{list each pattern in working_set}

### Tier 3 - READ-ONLY
{list each pattern in reference}

### Tier 2 - SIGNATURE (type info only)
{list each pattern in signatures}

### Tier 1 - EXISTENCE (name only)
{list each pattern in visible}
```

If `active` is false, note that enforcement is paused.
If `explorer` is true, note that all reads are allowed regardless of tier.
