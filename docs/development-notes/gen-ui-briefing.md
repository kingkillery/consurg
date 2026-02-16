# Generative UI Briefing

## Goal
Build a variable-driven prompt template for **task / api / coding-task** flows that incorporates:
- Docs context
- Endpoints
- Providers
- Tool preferences
- Endpoint + provider enforcement
- Safe UI generation strategy

## Approach Analysis

### 1) Tool Calling (Component Mapping)
- LLM emits structured intents or tool-call payloads.
- Runtime renders from a controlled component registry.
- Best fit for safety, traceability, and policy compliance.
- Recommended for v1 because it aligns with explicit endpoint/provider constraints.

### 2) Direct Code Generation (Autonomous Web Developer)
- LLM emits JSX/HTML/CSS directly.
- High flexibility and speed for prototypes.
- High risk: policy drift, injection issues, and unpredictable rendering/state behavior.
- Requires heavy post-processing and security hardening.

### 3) Task-Driven Data Model (Malleable UI)
- LLM emits structured task/state models, not raw UI.
- Strong fit for iterative systems and long-lived task workflows.
- Higher initial modeling cost and more complex render orchestration.

### 4) Tag-Based Streaming Injection
- LLM emits custom tags in stream; frontend hydrates components at tagged points.
- Good as latency/UX enhancement, not a standalone architecture.
- Works best when combined with tool-calling model output handling.

### 5) Paradigm Shift: Co-creation + Representation Fluidity
- Treat UI generation as collaborative planning across text, schema, and render layers.
- Useful lens for product direction, but still needs concrete implementation architecture.

## Recommendation
1. Start with **Tool Calling + strict schema validation** for v1.
2. Add **tag-streaming bridge** only for non-blocking UX while keeping schema validation as source of truth.
3. Include FSM-based orchestration for lifecycle reliability.
4. Defer full Task-Driven Data Model to a v2 phase once component registry and payload schema are stable.

## Proposed Design Baseline
- Prompt template is schema-first with explicit variables:
  - `{{task_type}}` (task | api | coding-task)
  - `{{docs_context}}`
  - `{{endpoints}}`
  - `{{providers}}`
  - `{{tool_preferences}}`
  - `{{constraints}}`
  - `{{forbidden_actions}}`
  - `{{ui_approach}}`
  - `{{state_model}}` (streaming/cancel/retry/retry policy)
- Allowed components and endpoints are allowlisted.
- Output contract enforces machine-readable payload and optional narrative sections.

## Key Risks
- Prompt injection and prompt leakage from open tool generation.
- Invalid endpoint/tool calls.
- FSM state explosions in streaming/retry/cancel conditions.
- Component mismatch between providers and selected rendering strategy.

## State Orchestration Requirement
Use a finite state machine (XState or equivalent) for transitions such as:
- idle -> composing -> tool_selected -> executing -> rendering
- rendering -> streaming -> done
- executing/rendering -> error/retry -> executing
- any state -> cancel -> cancelled
- timeout -> retry or aborted

## Migration Path
- v1: tool-calling schema + hard allowlists.
- v2: introduce task-model synthesis for malleable UI.
- v3: evolve policy-aware planner prompt and richer registry of renderer components.
