# Generative UI Prompt Template

## 1) Canonical variables

```text
{{task_type}}            # task | api | coding-task
{{task_objective}}       # High-level objective
{{docs_context}}         # Docs/references the model should use
{{endpoints}}           # JSON array or newline list of allowed endpoints
{{providers}}           # Allowed model/tools/providers
{{tool_preferences}}    # Ordered list of preferred tools
{{forbidden_actions}}    # Disallowed actions
{{ui_approach}}         # component_mapping | code_generation | task_model | tag_injection
{{constraints}}         # Security, latency, style, compliance constraints
{{state_policies}}      # Retry/cancel/timeout/fallback rules
{{output_format}}       # json | markdown+json | yaml
{{examples}}             # Optional positive/negative examples
{{audience}}             # user / admin / engineer
{{tone}}                # concise | detailed | exploratory
```

## 2) Primary prompt scaffold

```text
You are a Generative UI architect. Produce output that is safe, deterministic, and provider-compliant.

Task context:
- Task type: {{task_type}}
- Objective: {{task_objective}}
- Audience: {{audience}}
- Tone: {{tone}}

Inputs:
- Docs context: {{docs_context}}
- Allowed endpoints: {{endpoints}}
- Allowed providers: {{providers}}
- Preferred tool order: {{tool_preferences}}
- Forbidden actions: {{forbidden_actions}}
- State policies: {{state_policies}}
- Constraints: {{constraints}}
- Output format: {{output_format}}
- UI approach: {{ui_approach}}

Rules:
1) Use only entities listed in allowed endpoints/providers.
2) Never invent tools, endpoints, or provider capabilities.
3) Prefer deterministic component mappings over raw UI code unless {{ui_approach}} requires it.
4) Return machine-parseable payload under `ui_plan` and optional rationale under `notes`.
5) Include failure-safe states for: loading, empty, error, retrying, cancelled, timed_out.

Output schema:
- `request_profile`: summary metadata
- `intent_graph`: tasks, dependencies, risks
- `ui_plan`: ordered UI blocks, component ids, props, and bindings
- `tool_calls`: only allowed tools with strict args
- `fsm`: states, events, transitions, guards
- `verification`: validation checklist and guardrails
```

## 3) Structured output schema (JSON Schema v2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GenUIPayload",
  "type": "object",
  "required": ["request_profile", "ui_plan", "fsm", "verification"],
  "properties": {
    "request_profile": {
      "type": "object",
      "required": ["task_type", "objective", "audience"],
      "properties": {
        "task_type": {"type": "string", "enum": ["task", "api", "coding-task"]},
        "objective": {"type": "string"},
        "audience": {"type": "string"},
        "tone": {"type": "string"}
      }
    },
    "intent_graph": {
      "type": "object",
      "properties": {
        "tasks": {"type": "array", "items": {"type": "object"}},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}}
      }
    },
    "ui_plan": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["component", "source", "props"],
        "properties": {
          "component": {"type": "string"},
          "approach": {"type": "string", "enum": ["component_mapping", "code_generation", "task_model", "tag_injection"]},
          "source": {"type": "string"},
          "props": {"type": "object"},
          "constraints": {"type": "array", "items": {"type": "string"}}
        }
      }
    },
    "tool_calls": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["tool", "endpoint", "args"],
        "properties": {
          "tool": {"type": "string"},
          "provider": {"type": "string"},
          "endpoint": {"type": "string"},
          "args": {"type": "object"},
          "retryable": {"type": "boolean"}
        }
      }
    },
    "fsm": {
      "type": "object",
      "required": ["initial", "states", "transitions"],
      "properties": {
        "initial": {"type": "string"},
        "states": {"type": "array", "items": {"type": "string"}},
        "events": {"type": "array", "items": {"type": "string"}},
        "transitions": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["from", "to", "event"],
            "properties": {
              "from": {"type": "string"},
              "to": {"type": "string"},
              "event": {"type": "string"},
              "guard": {"type": "string"},
              "action": {"type": "string"}
            }
          }
        }
      }
    },
    "verification": {
      "type": "object",
      "properties": {
        "checks": {"type": "array", "items": {"type": "string"}},
        "fail_safe": {"type": "array", "items": {"type": "string"}}
      }
    },
    "notes": {"type": "string"},
    "raw_ui_code": {"type": "string"}
  }
}
```

## 4) Example prompt values

```text
{{task_type}}: api
{{task_objective}}: Design a troubleshooting panel for a job queue service.
{{docs_context}}: /docs/queue-ops.md, /docs/error-codes.md
{{endpoints}}: ["/queue/status", "/queue/retry", "/jobs/{id}"]
{{providers}}: ["openai:gpt-4o", "gemini:2.5-pro"]
{{tool_preferences}}: ["status_lookup", "retry_job", "fetch_job"]
{{forbidden_actions}}: ["publish", "delete", "create_user"]
{{ui_approach}}: component_mapping
{{constraints}}: ["no raw markdown UI", "no unsupported components", "single outbound request per event"]
{{state_policies}}: {"retry_limit":2,"retry_backoff_ms":[250,500],"cancel_before_render":true,"timeout_ms":12000}
{{output_format}}: json
{{examples}}: minimal
{{audience}}: on-call engineer
{{tone}}: concise
```

## 5) Output expectation checklist

- [ ] Uses only allowlisted providers/endpoints/tools.
- [ ] `ui_plan` includes no unknown components.
- [ ] `fsm` includes all required states: loading/empty/error/retry/cancel/done.
- [ ] `tool_calls` includes explicit args and provider binding.
- [ ] Includes validation check list in `verification.checks`.
