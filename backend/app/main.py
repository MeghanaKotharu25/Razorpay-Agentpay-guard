from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
from app.agent.graph import agent_graph
from app.db.crypto_vault import crypto_vault
from app.integrations.mock_merchant import MOCK_CATALOG
from app.gateway.interceptor import security_gateway
from app.config import settings

app = FastAPI(
    title="AgentPay-Guard Enterprise Security Gateway",
    version="2.1.0",
    description="Zero-Trust Invariant Firewall & AP2 Gateway for Autonomous Commerce"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    await crypto_vault.init_vault()

class UserShoppingRequest(BaseModel):
    user_prompt: str
    user_budget: float
    session_id: Optional[str] = None

class EscalationDecisionRequest(BaseModel):
    escalation_token: str
    approved: bool

@app.get("/api/catalog")
async def get_catalog():
    return {"catalog": MOCK_CATALOG}

@app.post("/api/agent/run")
async def run_agent(req: UserShoppingRequest):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    initial_state = {
        "session_id": session_id,
        "user_prompt": req.user_prompt,
        "user_budget": req.user_budget,
        "retrieved_catalog_items": [],
        "raw_catalog_context": "",
        "proposed_payment_payload": {},
        "gateway_decision": {},
        "agent_response_text": ""
    }
    result = await agent_graph.ainvoke(initial_state)
    return result

@app.post("/api/gateway/escalate/resolve")
async def resolve_escalation(req: EscalationDecisionRequest):
    res = await security_gateway.resolve_escalation(req.escalation_token, req.approved)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.get("/api/vault/verify")
async def verify_ledger():
    return await crypto_vault.verify_chain_integrity()

@app.get("/api/vault/spend/{session_id}")
async def get_spend_totals(session_id: str):
    return await crypto_vault.fetch_spend_totals(session_id)

@app.get("/api/audit/logs")
async def get_audit_logs():
    logs = await crypto_vault.fetch_recent_blocks(50)
    return {"logs": logs}