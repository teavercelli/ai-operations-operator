# DELIVERY_DELAY — essential evaluation

Date: 2026-09-29

## Result

- Deterministic test methods: **10/10 passed**
- Deterministic scenario checks: **14/14 passed** (the delay-band and invalid-decision tests contain subcases)
- Full project suite: **19/19 passed**
- Gemini calls made during this evaluation: **0**
- External actions executed: **0**

## Deterministic coverage

The suite uses real Olist orders for:

- low delay: `eb314576a333adeb296496f38c4c7852` (`0.1` days);
- medium delay: `cfa4fa27b417971e86d8127cb688712f` (`7.1` days);
- high delay: `95ec4886946c5ae0d453e95648834ac6` (`30.1` days);
- not late: `0607f0efea4b566f1eb8f7d3c2397320`;
- canceled: `1b9ecfe83cdc259250e1a8aca174f0ad`;
- missing delivery date: `2d1e2d5bf4dc7227b3bfebb81328c15f`.

It also verifies rejection of:

- incomplete verified facts and missing decision evidence;
- invalid severity;
- unauthorized recommended action;
- confidence outside `[0, 1]`;
- invalid state transition;
- LLM timeout, with case state `FAILED` and no simulated external action;
- approval/action attempts before `PENDING_HUMAN_APPROVAL`.

## Problems found and corrected

The deterministic evaluation exposed that malformed facts could reach decision
validation if the facts block itself was incomplete. Validation now requires
the order identity, delivered status, positive delay, and both delivery dates.

The preview command for the future LLM suite also had a serialization issue
with set-valued expectations; it is fixed. No Gemini call is made unless the
explicit `--run-live` flag is supplied.

## Prepared LLM evaluation

`evaluation/llm_evaluation.py` contains three real delayed orders and measures:

- severity and recommended-action agreement with the evaluation rubric;
- decision schema compliance;
- evidence presence and grounding anchors;
- confidence range;
- per-case latency;
- pass count and failure rate.

Preview without quota consumption:

```bash
python3 evaluation/llm_evaluation.py
```

Opt-in execution for a future run:

```bash
python3 evaluation/llm_evaluation.py --run-live --limit 3
```

Successful cases remain pending human approval. The suite never approves or
executes them automatically.

## Still requiring Gemini live

Only the following remain unverified without live Gemini quota:

- actual LLM severity and action agreement;
- actual evidence wording/coherence;
- live JSON output compliance;
- live failure rate across multiple cases;
- live Gemini latency distribution.
