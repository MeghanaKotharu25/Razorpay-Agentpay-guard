import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import aiosqlite
from app.config import settings

CONSOLIDATED_VAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_vault_blocks (
    block_index INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_block_hash TEXT NOT NULL,
    current_block_hash TEXT NOT NULL,
    timestamp REAL NOT NULL,
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_prompt TEXT,
    decision TEXT NOT NULL,
    violation_code TEXT,
    reason TEXT,
    payload_json TEXT NOT NULL,
    latency_ms REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS consumed_nonces (
    nonce_hash TEXT PRIMARY KEY,
    consumed_at REAL NOT NULL,
    session_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_escalations (
    escalation_token TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS spend_reservations (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    amount_inr REAL NOT NULL,
    spending_day TEXT NOT NULL,
    reserved_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    fingerprint TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

class CryptographicAuditVault:
    def __init__(self, db_path: str = settings.DATABASE_PATH):
        self.db_path = db_path
        self._genesis_hash = "0" * 64
        self._initialized = False

    async def init_vault(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(CONSOLIDATED_VAULT_SCHEMA)
            await db.commit()
        self._initialized = True

    async def _get_last_block_hash(self, db: aiosqlite.Connection) -> str:
        cursor = await db.execute(
            "SELECT current_block_hash FROM audit_vault_blocks ORDER BY block_index DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else self._genesis_hash

    def _compute_block_hash(self, prev_hash: str, timestamp: float, trace_id: str, payload_json: str, decision: str) -> str:
        block_string = f"{prev_hash}|{timestamp}|{trace_id}|{payload_json}|{decision}".encode("utf-8")
        return hmac.new(settings.AUDIT_HMAC_SECRET.encode(), block_string, hashlib.sha256).hexdigest()

    async def claim_idempotency(self, fingerprint: str, trace_id: str, session_id: str, decision: str = "IN_FLIGHT") -> bool:
        if not self._initialized:
            await self.init_vault()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO idempotency_records (fingerprint, trace_id, session_id, decision, created_at) VALUES (?, ?, ?, ?, ?)",
                (fingerprint, trace_id, session_id, decision, time.time()),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def record_event(
        self,
        trace_id: str,
        session_id: str,
        decision: str,
        payload: Dict[str, Any],
        latency_ms: float,
        user_prompt: Optional[str] = None,
        violation_code: Optional[str] = None,
        reason: Optional[str] = None
    ) -> str:
        if not self._initialized:
            await self.init_vault()

        async with aiosqlite.connect(self.db_path) as db:
            prev_hash = await self._get_last_block_hash(db)
            now = time.time()
            payload_str = json.dumps(payload, sort_keys=True)
            curr_hash = self._compute_block_hash(prev_hash, now, trace_id, payload_str, decision)

            await db.execute(
                """
                INSERT INTO audit_vault_blocks (
                    prev_block_hash, current_block_hash, timestamp,
                    trace_id, session_id, user_prompt, decision, violation_code,
                    reason, payload_json, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (prev_hash, curr_hash, now, trace_id, session_id, user_prompt, decision, violation_code, reason, payload_str, latency_ms)
            )
            await db.commit()
            return curr_hash

    async def is_nonce_consumed(self, nonce_hash: str) -> bool:
        if not self._initialized:
            await self.init_vault()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT 1 FROM consumed_nonces WHERE nonce_hash = ?", (nonce_hash,))
            row = await cursor.fetchone()
            return bool(row)

    async def consume_nonce(self, nonce_hash: str, session_id: str):
        if not self._initialized:
            await self.init_vault()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO consumed_nonces (nonce_hash, consumed_at, session_id) VALUES (?, ?, ?)",
                (nonce_hash, time.time(), session_id)
            )
            await db.commit()

    async def reserve_spend(
        self,
        trace_id: str,
        session_id: str,
        amount_inr: float,
        session_limit_inr: float,
        daily_limit_inr: float,
    ) -> Optional[str]:
        """Atomically reserve authorized spend, returning a violation if capped."""
        if not self._initialized:
            await self.init_vault()
        spending_day = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount_inr), 0) FROM spend_reservations WHERE session_id = ?",
                (session_id,),
            )
            session_total = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount_inr), 0) FROM spend_reservations WHERE spending_day = ?",
                (spending_day,),
            )
            daily_total = (await cursor.fetchone())[0]
            if session_total + amount_inr > session_limit_inr:
                await db.rollback()
                return "CUMULATIVE_SESSION_SPEND_CAP_EXCEEDED"
            if daily_total + amount_inr > daily_limit_inr:
                await db.rollback()
                return "CUMULATIVE_DAILY_SPEND_CAP_EXCEEDED"
            await db.execute(
                "INSERT INTO spend_reservations (trace_id, session_id, amount_inr, spending_day, reserved_at) VALUES (?, ?, ?, ?, ?)",
                (trace_id, session_id, amount_inr, spending_day, time.time()),
            )
            await db.commit()
            return None

    async def fetch_spend_totals(self, session_id: str) -> Dict[str, float]:
        if not self._initialized:
            await self.init_vault()
        spending_day = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount_inr), 0) FROM spend_reservations WHERE session_id = ?",
                (session_id,),
            )
            session_total = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount_inr), 0) FROM spend_reservations WHERE spending_day = ?",
                (spending_day,),
            )
            daily_total = (await cursor.fetchone())[0]
            return {"session_total_inr": session_total, "daily_total_inr": daily_total}

    async def save_pending_escalation(self, escalation_token: str, trace_id: str, session_id: str, user_prompt: str, payload: Dict[str, Any]):
        if not self._initialized:
            await self.init_vault()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO pending_escalations (escalation_token, trace_id, session_id, user_prompt, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (escalation_token, trace_id, session_id, user_prompt, json.dumps(payload), time.time())
            )
            await db.commit()

    async def pop_pending_escalation(self, escalation_token: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            await self.init_vault()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM pending_escalations WHERE escalation_token = ?", (escalation_token,))
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            await db.execute("DELETE FROM pending_escalations WHERE escalation_token = ?", (escalation_token,))
            await db.commit()
            data["payload"] = json.loads(data["payload_json"])
            return data

    async def fetch_recent_blocks(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.init_vault()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM audit_vault_blocks ORDER BY block_index DESC LIMIT ?", (limit,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def verify_chain_integrity(self) -> Dict[str, Any]:
        if not self._initialized:
            await self.init_vault()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM audit_vault_blocks ORDER BY block_index ASC")
            blocks = await cursor.fetchall()
            if not blocks:
                return {"is_valid": True, "total_blocks": 0, "status": "EMPTY_CHAIN"}

            prev_hash = self._genesis_hash
            for block in blocks:
                expected_curr = self._compute_block_hash(
                    block["prev_block_hash"],
                    block["timestamp"],
                    block["trace_id"],
                    block["payload_json"],
                    block["decision"]
                )
                if block["prev_block_hash"] != prev_hash or block["current_block_hash"] != expected_curr:
                    return {
                        "is_valid": False,
                        "tampered_block_index": block["block_index"],
                        "status": "TAMPER_DETECTED"
                    }
                prev_hash = block["current_block_hash"]
            return {"is_valid": True, "total_blocks": len(blocks), "status": "VERIFIED_INTEGRAL"}

crypto_vault = CryptographicAuditVault()