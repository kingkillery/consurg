# pk-agent Audit Trace Integration

Status: Implemented for `consurg wrap` with opt-in persistence.

## Purpose

Define a safe integration model for persistent pk-agent tool-call audit traces that:
- keeps telemetry opt-in by default
- redacts sensitive material before persistence
- bounds local storage growth
- remains compatible with Consurg workflows

## Scope

Implemented scope:
- Data model for persisted trace files
- Redaction policy requirements
- Retention policy and pruning behavior
- Config and environment interface contract
- Acceptance criteria for current implementation

Out of scope:
- Upstream pk-agent PR merge actions
- Cross-machine aggregation/telemetry export

## Design Principles

1. Opt-in telemetry only
2. Store redacted data only (never raw secret-bearing payloads)
3. Bounded retention with automatic pruning
4. Best-effort persistence (never fail agent run due to trace write error)
5. Versioned schema for forward compatibility

## Interfaces

### Environment variables

- `CONSURG_AUDIT_PERSIST=1`: enable persistence (default disabled)
- `CONSURG_AUDIT_MAX_RUNS=200`
- `CONSURG_AUDIT_MAX_AGE_DAYS=14`
- `CONSURG_AUDIT_MAX_BYTES=104857600`

### Optional project config

File: `.consurg-audit.yaml`

```yaml
enabled: false
storage_path: ".pk-agent/runs"
max_runs: 200
max_age_days: 14
max_bytes: 104857600
redaction_profile: strict-v1
include_tool_names:
  - "*"
exclude_tool_names: []
```

Precedence:
1. Environment variables
2. `.consurg-audit.yaml`
3. Internal defaults

## Trace File Schema

Path:
- `.pk-agent/runs/<timestamp>/trace.json`

Schema:

```json
{
  "schema_version": "1.0",
  "run_id": "string",
  "started_at": "2026-02-12T00:00:00Z",
  "tool_calls": [
    {
      "name": "Read",
      "type": "tool",
      "start_time": 1739308800000,
      "duration_ms": 34,
      "success": true,
      "redacted_input": "string",
      "redacted_output": "string",
      "redaction_flags": ["rule_id_1"]
    }
  ],
  "retention_policy_snapshot": {
    "max_runs": 200,
    "max_age_days": 14,
    "max_bytes": 104857600
  }
}
```

## Redaction Policy (strict-v1)

Required behavior:
- Redact known secret formats (API keys/tokens/JWT-like material)
- Redact auth header values (`Authorization`, bearer/basic)
- Redact structured fields by key name:
  - `password`, `passwd`, `token`, `secret`, `authorization`, `api_key`, `private_key`, `client_secret`
- Enforce ASCII-only output for persisted fields
- Truncate long values with explicit truncation marker
- If redaction fails, store sentinel value (`[REDACTION_ERROR]`) and continue run

Non-goal:
- Perfect detection for every possible obfuscation pattern in v1

## Retention and Pruning

Pruning should run after successful write:
1. Delete runs older than `max_age_days`
2. If count exceeds `max_runs`, delete oldest runs until limit met
3. If total bytes exceeds `max_bytes`, delete oldest runs until below cap

Deterministic order:
- Sort by run timestamp directory name ascending (oldest first)

## Failure Modes

- Cannot write trace file:
  - Log warning
  - Do not fail main agent run
- Corrupt existing trace file:
  - Skip for parsing-based metrics
  - Include in byte-based retention accounting if file exists
- Missing storage directory:
  - Create recursively

## Compatibility

- Existing Consurg features (`wire`, `guard`, `wrap`, `scaffold-pk-agents`, `apply-proposal`) remain unaffected when telemetry is disabled.
- Future integration should preserve behavior with or without `.pk-agent/runs` present.

## Security Considerations

- Persist only redacted values, never raw payload mirrors
- Keep retention bounded by count, age, and bytes
- Avoid writing secrets in error messages

## Acceptance Criteria

1. Telemetry is disabled by default
2. Enabling telemetry persists trace files at expected location
3. Trace files conform to schema version `1.0`
4. Redaction covers required key patterns and field names
5. ASCII/truncation guarantees hold for persisted strings
6. Retention pruning enforces age/count/byte limits
7. Disk/permission errors never fail primary agent execution
8. Adversarial tests verify no raw secret leakage in stored traces
