import aiosqlite
import json
import time
from typing import Optional, Dict, Any, List
from app.config import settings

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    user_prompt TEXT NOT NULL,
    proposed_payload TEXT NOT NULL,
    decision TEXT NOT NULL,
    violation_code TEXT,
    reason TEXT,
    semantic_drift_score REAL,
    injection_detected INTEGER,
    total_latency_ms REAL NOT NULL
);
"""

class AuditLogger:
    def __init__(self, db_path: str = settings.DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(DB_SCHEMA)
            await db.commit()

    async def log_event(
        self,
        trace_id: str,
        session_id: str,
        user_prompt: str,
        proposed_payload: Dict[str, Any],
        decision: str,
        total_latency_ms: float,
        violation_code: Optional[str] = None,
        reason: Optional[str] = None,
        semantic_drift_score: Optional[float] = None,
        injection_detected: bool = False
    ):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO audit_events (
                    trace_id, session_id, timestamp, user_prompt,
                    proposed_payload, decision, violation_code, reason,
                    semantic_drift_score, injection_detected, total_latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    session_id,
                    time.time(),
                    user_prompt,
                    json.dumps(proposed_payload),
                    decision,
                    violation_code,
                    reason,
                    semantic_drift_score,
                    1 if injection_detected else 0,
                    total_latency_ms
                )
            )
            await db.commit()

    async def fetch_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

audit_logger = AuditLogger()