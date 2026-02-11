---
name: consurg-scope-status
description: Show the current Context Surgeon scope status with tier counts and drift info
allowed-tools: Read, Bash
---

Run `consurg status` in the current project directory and present the output.

If the command fails or no scope is active, suggest running `consurg init <name>` to create one.

Include drift information if the current pattern count exceeds 2x the original count.
