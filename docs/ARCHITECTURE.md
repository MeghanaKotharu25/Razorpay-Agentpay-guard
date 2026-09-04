# AgentPay-Guard Architecture

## Request lifecycle

```text
Shopping agent
	 -> POST /api/agent/run
	 -> PaymentToolPayload schema
	 -> deterministic rules
		 currency, per-order budget, AP2 signature, system ceiling,
		 merchant allowlist, persistent nonce replay protection
	 -> semantic guard (LLM, fail-closed on outage)
	 -> lexical category drift and amount/quantity delta
		 < .35 allow candidate, .35-.70 human approval, >= .70 block
	 -> atomic authorized-spend reservation
		 cumulative session cap + UTC daily cap
	 -> Razorpay test order
	 -> hash-chained audit vault
```

Human approval stores a one-use escalation token. Approval performs the same atomic spend reservation before dispatch; rejection records a block. The SQLite vault stores nonces, pending escalations, spend reservations, idempotency claims, and audit blocks. Each audit block uses HMAC-SHA256 over the previous hash and event data, and the chain is verified by `/api/vault/verify` or `/api/v1/audit/verify`. Bounded actions use Razorpay Payment Links when credentials are configured.

## Trust boundaries

The proposed tool payload and retrieved catalog context are untrusted. The semantic model is advisory and cannot bypass deterministic rules. Razorpay is an external side effect and is called only after all checks and spend reservation succeed. The demo API itself is not authenticated and must sit behind identity-aware access control in production.

## Configuration

`MAX_SESSION_SPEND_INR` is cumulative per session, while `MAX_DAILY_SPEND_INR` is cumulative across all sessions for the UTC day. `ALLOWED_ORIGINS` controls browser access. Defaults are intentionally local/demo-oriented.
