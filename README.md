# AI Operations Operator

AI Operations Automation control center built on the Olist Brazilian
E-Commerce dataset. The product is intentionally narrow: it detects and
operates one workflow, `DELIVERY_DELAY`, with deterministic facts, bounded AI
investigation, Python guardrails, conservative automation policy, human review,
safe simulated actions and an append-only audit trail.

## Business problem

An operations team should not need to search thousands of historical orders by
hand, reconstruct delivery facts, decide how serious a delay is, and remember
what happened afterwards. The Operator turns that repeatable work into a
reviewable case workflow while keeping the final authority outside the LLM.

## Final architecture

```text
Olist SQLite data
      │
      ▼
Python/SQL detection ──► idempotent Operations Case (OPEN)
      │
      ▼
Bounded runner ──► authorized Python facts tools
      │
      ▼
Gemini decision: severity, action, rationale, confidence, evidence, message
      │
      ▼
Python validation / guardrails
      │
      ▼
Deterministic Automation Policy
      ├── safe + allowlisted ──► simulated action ──► CLOSED
      └── otherwise ───────────► human approval
                                      ├── approve ─► simulated action ─► CLOSED
                                      └── reject ──► CLOSED, no action
      │
      ▼
operations.db: cases, transitions, tool calls, decisions, policy and audit
```

Gemini never executes SQL, chooses its own authority, or sends email. The
`contact_customer` action always requires human approval. The public UI always
uses simulation mode; SMTP is only a prepared, separately configured adapter.

## Automatic workflow

The scheduler-ready runner is a stateless one-shot process. It can be called by
cron later without adding scheduler infrastructure:

```bash
python3 src/runner_cli.py --scan-only
python3 src/runner_cli.py --max-orders-scanned 5 --max-cases-created 3 \
  --max-cases-processed 2 --max-gemini-calls 4
```

Every run has independent caps for scanned orders, created cases, processed
cases and Gemini interaction attempts. Detection is deterministic and
idempotent. Existing cases for the same order and issue type are skipped.
`--scan-only` creates cases without calling Gemini and is the safe public-demo
mode.

The older focused commands remain available:

```bash
python3 src/detection_cli.py --limit 5
python3 src/orchestrator_cli.py --limit 1
```

## Control Center

Start the local app:

```bash
python3 -m streamlit run src/dashboard.py
```

The first tab is **AI Operations Control Center**, not a BI dashboard. It
contains:

- operational KPIs for scanned orders, detected issues, OPEN cases, AI-processed
  cases, auto-resolved cases, human approvals and failures;
- an Operations Queue with case, order, issue type, severity, confidence,
  recommended action and status;
- case detail with order context, Python facts, AI evidence, rationale,
  customer message, policy decision and full audit trail;
- APPROVE / REJECT controls and message editing for pending cases;
- an Activity Feed showing detected → created → investigated → decided →
  approved/action/closed or failed;
- secondary BI tabs for overview, delivery risk, order lookup and the copilot.

The UI is demo-safe: external actions are forced to simulation and Gemini is
opt-in for each bounded run. Missing credentials, quota errors or invalid AI
output are shown as failure states and never silently converted into success.
For a simulated `contact_customer`, the UI uses a non-deliverable
`example.invalid` recipient unless one is explicitly provided; this is only an
audit/demo value, never a live destination.

## Setup and configuration

Use Python 3.11+ and install the pinned project dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 src/create_database.py
```

Gemini is optional for deterministic detection, the dashboard and tests. If it
is available, configure the key in the shell or deployment secret store only:

```bash
export GEMINI_API_KEY="your-key"
```

Never commit `.env`, API keys, SMTP passwords or `data/operations.db`.

The conservative demo automation policy defaults to human approval:

```bash
export AI_OPERATOR_AUTO_EXECUTION_ENABLED=false
export AI_OPERATOR_AUTO_EXECUTION_CONFIDENCE_THRESHOLD=0.95
export AI_OPERATOR_AUTO_EXECUTION_ALLOWLIST=monitor_only
```

The email adapter supports simulation/dry-run and a provider-neutral SMTP live
mode. Live mode is deliberately not configured in the demo:

```bash
export AI_OPERATOR_EMAIL_MODE=simulation
export AI_OPERATOR_EXTERNAL_ACTIONS_ENABLED=false
```

An eventual authorized SMTP test additionally needs `AI_OPERATOR_EMAIL_MODE=live`,
`AI_OPERATOR_EXTERNAL_ACTIONS_ENABLED=true`, `AI_OPERATOR_EMAIL_RECIPIENT`,
`AI_OPERATOR_EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
`SMTP_PASSWORD` and `SMTP_STARTTLS`. Olist has no customer email field, so a
trusted recipient mapping is a separate prerequisite. No live send is part of
the public demo.

## Evaluation and verification

Run the full deterministic suite:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover database import, delivery-delay rules, duplicate prevention,
workflow failures, Gemini call limits, automation policy, fake email success
and failure, kill switches, human approval and audit integrity. Controlled
clients are used only for infrastructure tests; they are never presented as
live Gemini decisions. Live LLM evaluation remains optional and quota-bound:

```bash
python3 evaluation/llm_evaluation.py
python3 evaluation/llm_evaluation.py --run-live --limit 3
```

## Dataset limitations

Olist is a real historical e-commerce dataset, not a live production system.
It contains orders, customers, products, payments, reviews and sellers, but no
customer email addresses. Delivery-delay detection is therefore a valid
historical operational demonstration, while customer contact requires a
separate trusted identity/email source. External actions are simulated by
default and no production SLA, recipient identity, business threshold or live
Gemini quota should be inferred from this demo.
