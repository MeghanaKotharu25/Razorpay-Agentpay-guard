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

The original drift implementation also contained an unused cosine-distance helper while executing only keyword/category matching. It is now named `LexicalCategoryDriftEngine`, making the measured behavior match the claim. Its bounded delta checks the final amount and quantity against the initial prompt; there is no lenient embedding fallback. Spend is reserved transactionally only after approval gates, preventing repeated individually-valid calls from exceeding session or daily limits. Bounded actions use the live Razorpay Payment Link API when configured and expose the local fallback mode explicitly when credentials are absent.

## Verified offline run

Run on 2026-09-04 with the CI environment (`OPENROUTER_API_KEY=mock-offline-key`):

```text
5 passed in under 1s
Total Test Cases: 64 (skipped offline: 3)
Attack Prevention Rate (BLOCK+escalate): 100.0%
false allow: 0
false block: 0
Security Decision Precision: 100.0%
The offline run also exercises one clean autonomous `ALLOW`; higher-value benign catalog purchases are correctly reported as human-gated because they exceed the ₹2,000 autonomous transaction bound.
```

## Residual risk

The benchmark is defense-focused and not a substitute for production abuse testing. The demo API uses a shared API key rather than user identity or per-user authorization, uses SQLite, and defaults to a free remote model. These are disclosed deployment constraints, not hidden assumptions.

Benign coverage includes the low-value keyboard purchase used to prove a clean autonomous `ALLOW`, along with the legitimate catalog purchase cases. Gift wrapping and discount-code language should remain non-mutating context; they must not be interpreted as authorization to change amount, merchant, quantity, or currency.
