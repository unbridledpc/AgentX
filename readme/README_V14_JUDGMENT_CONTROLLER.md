# AgentX V14 — Pre-Inference Judgment Controller

V14 adds a lightweight rule-based controller that classifies a request before calling a model.

## Routes

The controller returns one of:

- `FAST` — short/simple work that should use the fast route.
- `HOLD` — missing context or incomplete input; wait or clarify before inference.
- `BLOCK` — destructive/high-risk action; do not auto-route.
- `DEEP` — coding, architecture, patches, repo work, or long context.
- `RECOVER` — logs, tracebacks, validation failures, or repair loops.

## Endpoints

```text
GET  /v1/judgment/policy
POST /v1/judgment/classify
```

Example:

```bash
curl -s http://127.0.0.1:8000/v1/judgment/classify   -H 'Content-Type: application/json'   -d '{"text":"fix this TypeScript error and make a patch","context_turns":4}' | python3 -m json.tool
```

## Why This Comes Before the Coding Playground

The coding playground will produce many kinds of requests:

- quick questions
- file inspection
- patch generation
- failed validation recovery
- destructive shell commands
- long-context workspace analysis

The judgment controller gives AgentX a cheap local gate before it spends tokens or routes work to the heavy model.

## V14 Scope

This release adds the backend classifier and API surface first. It does **not** automatically override chat routing yet.

Future V14/V15 work can wire this into:

- visible UI route badges
- automatic fast/heavy endpoint choice
- validation failure recovery
- coding playground patch workflows

## Validation

```bash
python3 -m compileall AgentX/agentx apps/api/agentx_api apps/api/tests
./scripts/smoke-test-v10.sh

curl -s http://127.0.0.1:8000/v1/judgment/policy | python3 -m json.tool
curl -s http://127.0.0.1:8000/v1/judgment/classify   -H 'Content-Type: application/json'   -d '{"text":"hello"}' | python3 -m json.tool
```

## Frontend Preview

The chat composer can call `/v1/judgment/classify` while the user types and show a non-blocking preview:

```text
Judgment: FAST -> fast
Judgment: DEEP -> heavy
Judgment: RECOVER -> heavy
Judgment: BLOCK -> none
```

This preview does not automatically change routing yet. It is visibility-only for V14.
