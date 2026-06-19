import sqlite3
import json
import datetime
from typing import Optional, List, Tuple
from .models import Anchor, ConfidenceHistoryEntry, HealEvent

class AnchorStore:
    def __init__(self, db_path="anchorheal.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS anchors (
                    caller_id TEXT PRIMARY KEY,
                    primary_selector TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    tag TEXT NOT NULL,
                    classes TEXT NOT NULL,
                    id_attr TEXT,
                    text_pattern TEXT NOT NULL,
                    parent_chain TEXT NOT NULL,
                    sibling_text TEXT NOT NULL,
                    xpath TEXT NOT NULL,
                    rel_position TEXT,
                    bbox TEXT,
                    viewport TEXT,
                    crop_32 BLOB,
                    crop_64 BLOB
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS confidence_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    caller_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    confidence REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS heal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    caller_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    old_selector TEXT NOT NULL,
                    new_selector TEXT NOT NULL,
                    healed_features TEXT NOT NULL,
                    confidence_before REAL NOT NULL,
                    confidence_after REAL NOT NULL,
                    primary_winning_signal TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_confidence_history_caller ON confidence_history(caller_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_heal_events_caller ON heal_events(caller_id)")
            conn.commit()

    def save_anchor(self, anchor: Anchor):
        data = anchor.model_dump()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO anchors (
                    caller_id, primary_selector, confidence, tag, classes, id_attr, text_pattern,
                    parent_chain, sibling_text, xpath, rel_position, bbox, viewport, crop_32, crop_64
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(caller_id) DO UPDATE SET
                    confidence=excluded.confidence,
                    tag=excluded.tag,
                    classes=excluded.classes,
                    id_attr=excluded.id_attr,
                    text_pattern=excluded.text_pattern,
                    parent_chain=excluded.parent_chain,
                    sibling_text=excluded.sibling_text,
                    xpath=excluded.xpath,
                    rel_position=excluded.rel_position,
                    bbox=excluded.bbox,
                    viewport=excluded.viewport,
                    crop_32=excluded.crop_32,
                    crop_64=excluded.crop_64
            """, (
                data["caller_id"],
                data["primary_selector"],
                data["confidence"],
                data["tag"],
                json.dumps(data["classes"]),
                data["id_attr"],
                data["text_pattern"],
                json.dumps(data["parent_chain"]),
                json.dumps(data["sibling_text"]),
                data["xpath"],
                json.dumps(data["rel_position"]) if data["rel_position"] else None,
                json.dumps(data["bbox"]) if data["bbox"] else None,
                json.dumps(data["viewport"]) if data["viewport"] else None,
                data["crop_32"],
                data["crop_64"]
            ))
            conn.commit()

    def get_anchor(self, caller_id: str) -> Optional[Anchor]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM anchors WHERE caller_id = ?", (caller_id,)).fetchone()
            if not row:
                return None
            
            return Anchor(
                caller_id=row["caller_id"],
                primary_selector=row["primary_selector"],
                confidence=row["confidence"],
                tag=row["tag"],
                classes=json.loads(row["classes"]),
                id_attr=row["id_attr"],
                text_pattern=row["text_pattern"],
                parent_chain=json.loads(row["parent_chain"]),
                sibling_text=json.loads(row["sibling_text"]),
                xpath=row["xpath"],
                rel_position=json.loads(row["rel_position"]) if row["rel_position"] else None,
                bbox=json.loads(row["bbox"]) if row["bbox"] else None,
                viewport=json.loads(row["viewport"]) if row["viewport"] else None,
                crop_32=row["crop_32"],
                crop_64=row["crop_64"]
            )

    def log_confidence(self, caller_id: str, confidence: float, timestamp: Optional[datetime.datetime] = None):
        if timestamp is not None:
            ts = timestamp.replace(tzinfo=None)
        else:
            ts = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        ts_str = ts.isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO confidence_history (caller_id, timestamp, confidence) VALUES (?, ?, ?)",
                (caller_id, ts_str, confidence)
            )
            # Also update the main anchor's confidence
            conn.execute("UPDATE anchors SET confidence = ? WHERE caller_id = ?", (confidence, caller_id))
            conn.commit()

    def log_heal_event(self, event: HealEvent):
        ts = event.timestamp.replace(tzinfo=None)
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO heal_events (
                    caller_id, timestamp, old_selector, new_selector, healed_features,
                    confidence_before, confidence_after, primary_winning_signal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.caller_id,
                ts.isoformat(),
                event.old_selector,
                event.new_selector,
                json.dumps(event.healed_features),
                event.confidence_before,
                event.confidence_after,
                event.primary_winning_signal
            ))
            conn.commit()

    def get_confidence_history(self, caller_id: str) -> List[Tuple[datetime.datetime, float]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT timestamp, confidence FROM confidence_history WHERE caller_id = ? ORDER BY timestamp ASC",
                (caller_id,)
            ).fetchall()
            return [(datetime.datetime.fromisoformat(r["timestamp"]).replace(tzinfo=None), r["confidence"]) for r in rows]

    def get_heal_events(self, caller_id: str) -> List[HealEvent]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM heal_events WHERE caller_id = ? ORDER BY timestamp DESC",
                (caller_id,)
            ).fetchall()
            return [
                HealEvent(
                    caller_id=r["caller_id"],
                    timestamp=datetime.datetime.fromisoformat(r["timestamp"]).replace(tzinfo=None),
                    old_selector=r["old_selector"],
                    new_selector=r["new_selector"],
                    healed_features=json.loads(r["healed_features"]),
                    confidence_before=r["confidence_before"],
                    confidence_after=r["confidence_after"],
                    primary_winning_signal=r["primary_winning_signal"]
                ) for r in rows
            ]
