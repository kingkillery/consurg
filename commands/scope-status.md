---
name: scope-status
description: Show the current Context Surgeon scope status with tier counts and drift info
allowed-tools: Read, Bash
---

Run `python -m consurg status` in the current project directory and present the output.

If no scope is active, suggest running `consurg init <name>` to create one.

Include drift information if metadata.original_count is set in .consurg.yaml.
