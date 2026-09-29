# AI Operations Operator

An AI-powered operations automation system that automatically detects delivery exceptions, investigates them using business data and AI, applies deterministic safety policies, and routes operational actions based on risk.

### 🚀 Live Demo

👉 **[Open the AI Operations Operator](https://ai-operations-operator-j7eld28lxectwdkktmfu6a.streamlit.app/)**

---

## Overview

Many operational processes still require employees to manually identify problems, investigate data, decide what to do, take action, and document the result.

The **AI Operations Operator** explores how this workflow can be automated safely with AI.

The system automatically detects delivery-delay exceptions from real e-commerce data, creates operational cases, collects the relevant business facts, uses Gemini to investigate the case, validates the AI output through deterministic Python guardrails, and determines whether the proposed action can be automated or requires human approval.

Every decision, tool call, state transition and action is recorded in an audit trail.

### Core workflow

```text
Detect → Investigate → Decide → Validate → Act → Audit
```

The goal is not to build another AI chatbot.

The goal is to build an AI system capable of participating safely in a real operational process.

---

## What it does

Instead of requiring an operations analyst to manually inspect thousands of orders, the Operator can:

1. 🔎 Automatically detect delivery exceptions
2. 📂 Create an Operations Case
3. 🛠️ Collect facts through authorized Python and SQL tools
4. 🤖 Use Gemini to investigate the case
5. 🧠 Produce severity, evidence, confidence and a recommended action
6. 🛡️ Validate the AI decision through deterministic Python guardrails
7. ⚙️ Apply an Automation Policy
8. 👤 Route higher-risk cases to human approval
9. ⚡ Execute safe allowlisted actions automatically
10. 📋 Record the complete process in an audit trail

---

## Project at a glance

| Metric | Value |
|---|---:|
| Orders | 99,441 |
| Order items | 112,650 |
| Products | 32,951 |
| Sellers | 3,095 |
| Customers | 96,096 |
| Historical delayed deliveries detected | 7,826 |
| Historical delivery delay rate | 8.1% |
| Automated tests | 43 |
| Operational workflow | `DELIVERY_DELAY` |

The project uses the **Olist Brazilian E-Commerce Public Dataset**, containing real historical and anonymized e-commerce transactions.

---

## Business Problem

A traditional operations workflow may look like this:

```text
Operations employee
        ↓
Search orders
        ↓
Identify delivery problem
        ↓
Collect information
        ↓
Investigate the case
        ↓
Assess severity
        ↓
Decide what to do
        ↓
Take action
        ↓
Document the outcome
```

The AI Operations Operator transforms this into:

```text
Automatic Detection
        ↓
Operations Case
        ↓
AI Investigation
        ↓
Validated Decision
        ↓
Automation Policy
      ↙          ↘
Auto Action    Human Approval
      ↘          ↙
          Action
            ↓
           Audit
```

This allows humans to focus on exceptions that actually require judgment rather than manually processing every case.

---

## How the Operator Works

### 1. Automatic Detection

Python and SQL automatically scan the operational database for delivery exceptions.

Detection is deterministic and does not require an LLM.

```text
Orders
   ↓
Python / SQL rules
   ↓
Delivery delay detected
   ↓
Operations Case created
```

The detection process is idempotent: running it multiple times does not create duplicate cases for the same operational issue.

### 2. AI Investigation

Once a case exists, the AI Operator investigates it.

Gemini does not receive unrestricted database access.

Instead, it can use authorized Python tools that retrieve specific business facts.

```text
Gemini
   ↓
Authorized Tool
   ↓
Python
   ↓
SQL
   ↓
Operational Facts
```

The AI can produce:

- severity
- recommended action
- rationale
- confidence
- supporting evidence
- proposed customer message

### 3. Python Guardrails

The LLM does not control the workflow.

Python validates the AI output before any action can occur.

Guardrails verify:

- valid severity
- valid recommended action
- confidence range
- required evidence
- case state
- allowed state transitions
- completeness and consistency of operational facts

Invalid AI output cannot bypass these controls.

### 4. Automation Policy

A separate deterministic policy determines how much authority the AI receives.

```text
                 AI Decision
                      ↓
              Python Guardrails
                      ↓
             Automation Policy
                 ↙         ↘
          Safe Case       Review Required
              ↓                ↓
        AUTO_APPROVED      HUMAN APPROVAL
              ↓
            Action
```

The LLM cannot decide its own level of autonomy.

The policy considers:

- severity
- confidence
- action allowlist
- evidence validity
- global kill switch

Automation thresholds are configurable and represent demo policies rather than validated production business rules.

### 5. Human-in-the-loop

Higher-risk actions stop before execution.

An operator can inspect:

- order information
- business facts
- AI evidence
- severity
- confidence
- rationale
- recommended action
- proposed customer message
- automation-policy decision
- complete audit history

The operator can then **APPROVE** or **REJECT** the proposed action.

### 6. External Actions

The architecture includes a provider-neutral email adapter for the `contact_customer` action.

This action always requires human approval.

The system supports:

```text
Simulation / Dry Run
Live SMTP
```

The public demo always uses simulation mode.

No real customer email is sent from the deployed application.

### 7. Audit Trail

Every important operation is persisted.

Example:

```text
case_created
      ↓
automatic_ai_processing_started
      ↓
tool_call_completed
      ↓
decision_recorded
      ↓
automation_policy_decision
      ↓
human_approval_requested
      ↓
action_executed
      ↓
case_closed
```

This makes the AI system observable and auditable rather than treating the LLM as a black box.

---

## Beyond a Chatbot

This project deliberately separates **AI reasoning from system authority**.

Gemini cannot:

- execute arbitrary SQL
- approve its own actions
- bypass workflow states
- determine its own automation permissions
- directly send customer emails
- bypass deterministic guardrails

Instead:

```text
LLM
 ↓
Proposes a decision

Python
 ↓
Validates the decision

Automation Policy
 ↓
Determines permitted autonomy

Human
 ↓
Handles higher-risk exceptions
```

---

## Architecture

```text
                     OLIST DATA
                         │
                         ▼
                    SQLite DB
                         │
                         ▼
               Python / SQL Detection
                         │
                         ▼
                 Operations Case
                         │
                         ▼
                   AI Operator
                         │
             ┌───────────┴───────────┐
             │                       │
      Authorized Tools             Gemini
             │                       │
             └───────────┬───────────┘
                         ▼
                    AI Decision
                         │
                         ▼
                 Python Guardrails
                         │
                         ▼
                Automation Policy
                   ↙           ↘
           AUTO_APPROVED     HUMAN REVIEW
                   │             │
                   └──────┬──────┘
                          ▼
                        Action
                          │
                          ▼
                      Audit Log
                          │
                          ▼
                        CLOSED
```

---

## AI Operations Control Center

The Streamlit web application acts as the control layer for the AI Operator.

### 🌐 Live Application

👉 **[Launch the AI Operations Control Center](https://ai-operations-operator-j7eld28lxectwdkktmfu6a.streamlit.app/)**

The Control Center includes:

- operational KPIs
- Operations Queue
- case status
- AI severity and confidence
- recommended actions
- evidence and rationale
- customer-message review
- APPROVE / REJECT controls
- automation-policy decisions
- complete audit trail
- Operator Activity Feed
- secondary business intelligence views

The web application is not the automation itself.

It is the interface used to **observe and control the AI automation running behind it**.

---

## Evaluation & Testing

The project includes automated testing for:

- database creation
- SQL joins
- operational tools
- delivery-delay detection
- duplicate prevention
- idempotency
- case-state transitions
- AI schema validation
- missing evidence
- invalid confidence
- invalid actions
- LLM failures and timeouts
- Gemini call limits
- automation policy
- kill switches
- human approval
- simulated email success and failure
- audit integrity

Run the deterministic test suite with:

```bash
python3 -m unittest discover -s tests -v
```

Current result:

```text
43 tests
43 passed
```

A separate LLM evaluation suite is available for controlled live testing.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Programming | Python |
| Database | SQLite |
| Data querying | SQL |
| AI | Google Gemini |
| AI integration | Function Calling |
| Web application | Streamlit |
| Workflow orchestration | Python |
| Safety | Deterministic Guardrails + Automation Policy |
| Testing | Python unittest |
| External actions | Email Adapter / SMTP |
| Deployment | Streamlit Community Cloud |

---

## Project Structure

```text
ai-operations-operator/
│
├── data/
├── evaluation/
├── reports/
│
├── src/
│   ├── create_database.py
│   ├── queries.py
│   ├── ai_operator.py
│   ├── delivery_delay_detection.py
│   ├── delivery_delay_workflow.py
│   ├── operations_case_store.py
│   ├── automation_policy.py
│   ├── automation_runner.py
│   ├── email_adapter.py
│   ├── dashboard.py
│   └── runner_cli.py
│
├── tests/
├── requirements.txt
└── README.md
```

---

## Run Locally

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Build the SQLite database:

```bash
python3 src/create_database.py
```

Start the web application:

```bash
python3 -m streamlit run src/dashboard.py
```

---

## Dataset

This project uses the **Olist Brazilian E-Commerce Public Dataset**, containing real historical and anonymized Brazilian e-commerce transactions.

The dataset includes:

- orders
- customers
- products
- sellers
- payments
- order items
- reviews
- delivery timestamps
- geographical information

---

## Limitations

This is a portfolio-grade operational automation prototype, not a production deployment.

Important limitations:

- Olist contains historical rather than live operational data
- customer email addresses are not included in the dataset
- the public application uses simulated external actions
- automation thresholds are demonstration policies rather than business-validated production rules
- live Gemini behavior depends on API availability, quota and latency
- production deployment would require authentication, monitoring, access controls, live system integrations and organization-specific policies

The architecture was intentionally designed so these components can be replaced or extended without giving the LLM unrestricted control over operational systems.

---

## Future Extensions

The current implementation deliberately focuses on one workflow: `DELIVERY_DELAY`.

The same architecture could later support:

- payment failures
- order cancellations
- negative customer reviews
- seller-performance issues
- inventory exceptions
- fulfillment failures

The objective of the current version is not workflow breadth, but demonstrating a complete and controlled AI operations loop end-to-end.
