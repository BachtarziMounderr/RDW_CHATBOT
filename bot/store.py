"""Stockage transactionnel PostgreSQL; la mémoire est réservée aux tests."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


EMPTY = {
    "stage": "idle", "data_consent": False, "contact_consent": False,
    "last_update_id": None, "rate_window": None, "rate_count": 0,
    "track": None, "first_name": None, "contact_detail": None,
    "project_summary": None, "handoff_requested": False,
}


class MemoryStore:
    """Faux magasin déterministe pour les tests; jamais utilisé au démarrage réel."""

    def __init__(self):
        self.rows = {}
        self.events = set()
        self.consents = []

    @contextmanager
    def user(self, user_id: int, update_id: int):
        if update_id in self.events:
            yield None
            return
        row = deepcopy(self.rows.get(user_id, EMPTY))
        row["_consents"] = []
        row["_event_kind"] = "message"
        row["_delete"] = False
        yield row
        if row["_delete"]:
            self.rows.pop(user_id, None)
            self.consents = [c for c in self.consents if c[0] != user_id]
            self.events.discard(update_id)
            return
        self.consents += [(user_id, p, v) for p, v in row.pop("_consents")]
        row.pop("_event_kind")
        row.pop("_delete")
        row["last_update_id"] = update_id
        self.rows[user_id] = row
        self.events.add(update_id)


class PostgresStore:
    def __init__(self, dsn: str):
        if not dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL doit être une URL PostgreSQL psycopg (postgresql://).")
        self.dsn = dsn

    def connect(self):
        import psycopg
        return psycopg.connect(self.dsn, connect_timeout=5)

    def check_schema(self):
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('telegram.conversation_state')")
                if cur.fetchone()[0] is None:
                    raise RuntimeError("Schéma Telegram absent. Lancez : python -m bot.main init-db")

    def init_schema(self):
        sql = (Path(__file__).parent / "sql" / "001_telegram.sql").read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.execute(sql)

    @contextmanager
    def user(self, user_id: int, update_id: int):
        with self.connect() as conn:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
                seen = conn.execute("SELECT 1 FROM telegram.bot_events WHERE update_id=%s", (update_id,)).fetchone()
                if seen:
                    yield None
                    return
                state = conn.execute(
                    "SELECT stage,data_consent,contact_consent,last_update_id,rate_window,rate_count "
                    "FROM telegram.conversation_state WHERE telegram_user_id=%s", (user_id,)
                ).fetchone()
                prospect = conn.execute(
                    "SELECT track,first_name,contact_detail,project_summary,handoff_requested "
                    "FROM telegram.prospects WHERE telegram_user_id=%s", (user_id,)
                ).fetchone()
                row = dict(EMPTY)
                if state:
                    row.update(zip(("stage", "data_consent", "contact_consent", "last_update_id", "rate_window", "rate_count"), state))
                if prospect:
                    row.update(zip(("track", "first_name", "contact_detail", "project_summary", "handoff_requested"), prospect))
                if row["rate_window"] is None:
                    row["rate_window"] = datetime.now(timezone.utc)
                row["_consents"] = []
                row["_event_kind"] = "message"
                row["_delete"] = False
                yield row
                if row["_delete"]:
                    for table in ("prospects", "conversation_state", "consent_events", "bot_events"):
                        conn.execute(f"DELETE FROM telegram.{table} WHERE telegram_user_id=%s", (user_id,))
                    return
                conn.execute(
                    "INSERT INTO telegram.conversation_state "
                    "(telegram_user_id,stage,data_consent,contact_consent,last_update_id,rate_window,rate_count) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (telegram_user_id) DO UPDATE SET "
                    "stage=EXCLUDED.stage,data_consent=EXCLUDED.data_consent,contact_consent=EXCLUDED.contact_consent,"
                    "last_update_id=EXCLUDED.last_update_id,rate_window=EXCLUDED.rate_window,rate_count=EXCLUDED.rate_count,updated_at=now()",
                    (user_id, row["stage"], row["data_consent"], row["contact_consent"], update_id,
                     row["rate_window"], row["rate_count"]),
                )
                if row["data_consent"]:
                    conn.execute(
                        "INSERT INTO telegram.prospects "
                        "(telegram_user_id,track,first_name,contact_detail,project_summary,handoff_requested) "
                        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (telegram_user_id) DO UPDATE SET "
                        "track=EXCLUDED.track,first_name=EXCLUDED.first_name,contact_detail=EXCLUDED.contact_detail,"
                        "project_summary=EXCLUDED.project_summary,handoff_requested=EXCLUDED.handoff_requested,updated_at=now()",
                        (user_id, row["track"], row["first_name"], row["contact_detail"],
                         row["project_summary"], row["handoff_requested"]),
                    )
                for purpose, granted in row["_consents"]:
                    conn.execute("INSERT INTO telegram.consent_events (telegram_user_id,purpose,granted) VALUES (%s,%s,%s)",
                                 (user_id, purpose, granted))
                conn.execute("INSERT INTO telegram.bot_events (update_id,telegram_user_id,kind) VALUES (%s,%s,%s)",
                             (update_id, user_id, row["_event_kind"]))

    def export_handoffs(self):
        with self.connect() as conn:
            return conn.execute(
                "SELECT telegram_user_id,track,first_name,contact_detail,project_summary,updated_at "
                "FROM telegram.prospects WHERE handoff_requested AND contact_detail IS NOT NULL "
                "ORDER BY updated_at"
            ).fetchall()
