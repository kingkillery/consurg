## 2026-02-12 - [CLI Pattern Validation]
**Learning:** `fnmatch` does not match directory contents recursively unless the pattern explicitly includes `*`. Users often confuse adding a directory path with adding its contents.
**Action:** Detect directory paths in `add` commands and suggest appending `/*` or `/**/*` to clarify intent.
