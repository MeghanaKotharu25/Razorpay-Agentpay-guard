```mermaid
flowchart TD
	subgraph Agentic Layer
		U[AI Buyer / Autonomous Agent] -->|Agentic Commerce Action| AP2[AP2 Protocol Request]
	end

	subgraph AgentPay-Guard Gateway
		AP2 --> INT[Gateway Interceptor]
		INT --> VAL[Schema & Pydantic Validator]
		VAL --> RE[Deterministic Rules Engine]
		RE -->|Budget & Velocity Check| SG[Semantic Drift & Injection Guard]
		SG -->|Pass| RZP[Razorpay Test API Client]
		SG -->|Drift > Threshold| CB[Circuit Breaker / Human Gate]
		RE -->|Budget Exceeded| CB
	end

	subgraph Settlement & Integrity
		RZP -->|order.created / payment.authorized| AUDIT[(HMAC Hash Chain Vault)]
		CB -->|Graceful Fallback| LINK[Emit Hosted Payment Link to User]
		LINK --> AUDIT
	end
```

# AgentPay-Guard

AgentPay-Guard is a zero-trust gateway for agentic commerce. A shopping agent proposes an order, then the gateway validates deterministic payment invariants, verifies an AP2 mandate, checks semantic intent and lexical category drift, and either blocks, escalates to a human, or dispatches to Razorpay test mode. Every decision is hash-chained in SQLite.

## Demo flow

1. Start the backend with `cd backend && uvicorn app.main:app --reload` and the frontend with `cd frontend && npm run dev`.
2. Run a clean purchase such as `Buy Dell Inspiron laptop within 45000`.
3. Run `SKU-LAPTOP-POISONED-01` or a prompt-injection case and inspect the block reason.
4. Run a borderline product substitution, approve it in the dashboard, then open `/api/vault/verify`.

The dashboard keeps a browser session ID, so repeated approved orders share the cumulative session cap. The gateway also enforces a UTC daily cap. Blocked and pending orders do not consume spend; only dispatched orders reserve it atomically. Bounded actions create an expiring Razorpay Payment Link when test credentials are configured, or a clearly marked local demo fallback otherwise.

## Architecture

The request path is: schema and currency/budget/merchant/replay checks -> AP2 signature verification -> semantic guard -> deterministic lexical category drift -> block, human approval, or Razorpay order -> audit event. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Evaluation

The 64-case adversarial suite covers prompt injection, currency arbitrage, mandate forgery, quantity manipulation, replay, and category/regex evasion. It reports clean blocks, escalations, false allows, false blocks, latency, and economic impact rather than treating every escalation as a failure. See [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md) and run `cd backend && PYTHONPATH=. pytest tests/test_adversarial_suite.py -v -s`.

## Deployment

The repository includes [render.yaml](render.yaml) for the backend and [frontend/vercel.json](frontend/vercel.json) for the dashboard. Set `OPENROUTER_API_KEY`, Razorpay test keys, `ALLOWED_ORIGINS`, `VITE_API_BASE_URL`, and production spend limits in the platform secret/environment settings. SQLite is suitable for this demo; use a managed database and a real authentication layer for production.

## Known limitations

- The demo API has no authentication on `/api/agent/run` or escalation resolution. Add identity, authorization, and per-user session ownership before production use.
- The semantic guard and agent default to a free, rate-limited OpenRouter model. Guard outages fail closed to human approval, but a recorded demo should use a pinned, provisioned model or offline fixtures.
- CORS is restricted to `ALLOWED_ORIGINS`; the local default is `http://localhost:5173`.
- `vector_drift.py` is intentionally a deterministic lexical category guard. It does not claim to calculate embedding/vector distance.
