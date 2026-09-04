import uuid
import time
import json
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from openai import AsyncOpenAI
from app.config import settings
from app.agent.tools import search_catalog_tool
from app.gateway.ap2_schema import ap2_verifier, AP2PaymentMandate
from app.gateway.interceptor import security_gateway, GatewayDecision

class AgentWorkflowState(TypedDict):
    session_id: str
    user_prompt: str
    user_budget: float
    retrieved_catalog_items: List[Dict[str, Any]]
    raw_catalog_context: str
    proposed_payment_payload: Dict[str, Any]
    gateway_decision: Dict[str, Any]
    agent_response_text: str

client = AsyncOpenAI(
    base_url=settings.OPENROUTER_BASE_URL,
    api_key=settings.OPENROUTER_API_KEY
)

# Step A: Search catalog via agent tool
async def search_node(state: AgentWorkflowState) -> Dict[str, Any]:
    prompt = state["user_prompt"]
    items = search_catalog_tool(prompt)
    context_str = json.dumps(items, indent=2)
    return {
        "retrieved_catalog_items": items,
        "raw_catalog_context": context_str
    }

# Step B: Agent reasoning & AP2 payment proposal
async def reason_and_propose_node(state: AgentWorkflowState) -> Dict[str, Any]:
    system_instruction = """
    You are an autonomous AI shopping agent.
    Your goal is to select the most suitable product matching the user prompt and generate an exact purchase proposal.
    Output ONLY a JSON object with this format:
    {
      "explanation": "why you chose this item",
      "tool_call": {
        "merchant_id": "merchant_name",
        "amount_inr": float,
        "currency": "INR",
        "product_sku": "SKU-ID",
        "quantity": int
      }
    }
    """
    
    user_input = {
        "user_request": state["user_prompt"],
        "max_budget": state["user_budget"],
        "catalog_results": state["retrieved_catalog_items"]
    }

    try:
        response = await client.chat.completions.create(
            model=settings.PRIMARY_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": json.dumps(user_input)}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
    except Exception as e:
        return {
            "proposed_payment_payload": {},
            "agent_response_text": f"Agent proposal unavailable; gateway failed closed ({str(e)[:120]})."
        }
    tool_call = parsed.get("tool_call", {})
    
    # Generate the simplified HMAC-based AP2 mandate simulation token.
    valid_until = time.time() + 600.0  # 10 minute TTL
    user_id = f"usr_{state['session_id'][:8]}"
    mandate_sig = ap2_verifier.generate_mandate_signature(
        user_id=user_id,
        max_amount_inr=state["user_budget"],
        valid_until=valid_until
    )
    
    tool_call["session_id"] = state["session_id"]
    tool_call["intent_id"] = f"intent_{uuid.uuid4().hex[:8]}"
    tool_call["nonce"] = uuid.uuid4().hex
    tool_call["user_max_budget"] = state["user_budget"]
    tool_call["ap2_mandate"] = {
        "mandate_id": f"mandate_{uuid.uuid4().hex[:8]}",
        "user_id": user_id,
        "max_amount_inr": state["user_budget"],
        "currency": "INR",
        "valid_until": valid_until,
        "signature": mandate_sig
    }

    return {
        "proposed_payment_payload": tool_call,
        "agent_response_text": parsed.get("explanation", "Proposing payment execution.")
    }

# Step C: Gateway Intercept Node
async def gateway_interceptor_node(state: AgentWorkflowState) -> Dict[str, Any]:
    decision: GatewayDecision = await security_gateway.process_payment_request(
        session_id=state["session_id"],
        user_prompt=state["user_prompt"],
        retrieved_context=state["raw_catalog_context"],
        tool_payload=state["proposed_payment_payload"]
    )
    return {"gateway_decision": decision.model_dump()}

# Build the Graph
builder = StateGraph(AgentWorkflowState)
builder.add_node("search_catalog", search_node)
builder.add_node("agent_reason", reason_and_propose_node)
builder.add_node("gateway_inspect", gateway_interceptor_node)

builder.set_entry_point("search_catalog")
builder.add_edge("search_catalog", "agent_reason")
builder.add_edge("agent_reason", "gateway_inspect")
builder.add_edge("gateway_inspect", END)

agent_graph = builder.compile()

if __name__ == "__main__":
    import asyncio

    async def simulate_agentic_catalog_loop():
        query = "compact mechanical keyboard"
        items = search_catalog_tool(query)
        print(json.dumps({
            "user_request": "Buy a compact mechanical keyboard under INR 2,000",
            "catalog_query": query,
            "discovered_items": items,
            "next_step": "Submit the selected item to POST /api/agent/run for gateway inspection.",
        }, indent=2))

    asyncio.run(simulate_agentic_catalog_loop())