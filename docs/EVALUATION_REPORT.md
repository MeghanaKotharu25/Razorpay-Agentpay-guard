# Evaluation Report

## Benchmark design

`backend/tests/benchmark_dataset.json` contains 64 cases spanning legitimate purchases, prompt injection, poisoned catalog/SKU context, category substitutions, currency and budget abuse, AP2 mandate forgery, replay, quantity manipulation, and regex evasion. Cases requiring the live semantic guard are skipped when the repository is run with the offline mock key.

## Reported metrics

The benchmark prints a case table and calculates:

| Metric | Meaning |
| --- | --- |
| Attack prevention rate | Threats hard-blocked or held for human approval |
| Clean-block rate | Threats hard-blocked without escalation |
| False allows | Threats autonomously dispatched, expected to be zero |
| Security decision precision | Hard blocks divided by hard blocks plus legitimate false blocks |
| False-positive GMV loss | Legitimate value hard-blocked |
| Step-up preserved capital | Value held for explicit approval |
| Average latency | End-to-end gateway decision time |

Run it with:

```bash
cd backend
PYTHONPATH=. ./venv/bin/pytest tests/test_adversarial_suite.py -v -s
```

## What broke and how it was handled

The semantic guard can be unavailable because the remote free-tier model is rate-limited or unreachable. Returning a fake-safe result would create a fail-open payment path. The gateway instead raises `GuardServiceUnavailableError`, stores a one-use escalation, records the event, and requires human approval. Razorpay authentication/network failures similarly fall back to an explicit simulated test-sandbox order.

The original drift implementation also contained an unused cosine-distance helper while executing only keyword/category matching. It is now named `LexicalCategoryDriftEngine`, making the measured behavior match the claim. Spend is reserved transactionally only after approval gates, preventing repeated individually-valid calls from exceeding session or daily limits.

## Residual risk

The benchmark is defense-focused and not a substitute for production abuse testing. The demo has no API authentication, uses SQLite, and defaults to a free remote model. These are disclosed deployment constraints, not hidden assumptions.
