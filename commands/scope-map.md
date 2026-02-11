---
name: scope-map
description: Visualize the project file tree with Context Surgeon tier annotations
allowed-tools: Read, Bash
---

Run `python -m consurg map` in the current project directory and present the tier-annotated file tree.

Legend:
- [RW] Green = Tier 4 READ-WRITE (full access)
- [RO] Yellow = Tier 3 READ-ONLY
- [SIG] Blue = Tier 2 SIGNATURE (type info only)
- [--] Gray = Tier 0-1 BLOCKED/EXISTENCE
