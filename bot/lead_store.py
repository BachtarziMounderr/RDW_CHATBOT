"""Persistance des prospects consentis seulement; aucune conversation brute."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .store import PostgresStore


class MemoryLeadStore:
    """Faux stockage pour évaluations hors ligne uniquement."""

    def __init__(self):
        self.rows = {}
        self.updates = set()
        self.consents = []

    def save(self, user_id: int, update_id: int, data: dict, version: str) -> bool:
        if update_id in self.updates:
            return False
        row = deepcopy(data)
        row["consent_at"] = datetime.now(timezone.utc)
        row["consent_version"] = version
        self.rows[user_id] = row
        self.updates.add(update_id)
        self.consents.append((user_id, version, row["consent_at"]))
        return True

    def get(self, user_id: int) -> dict | None:
        return deepcopy(self.rows.get(user_id))

    def delete(self, user_id: int):
        self.rows.pop(user_id, None)
        self.consents = [entry for entry in self.consents if entry[0] != user_id]
        self.updates.clear()


class PostgresLeadStore(PostgresStore):
    def init_schema(self):
        super().init_schema()
        with self.connect() as conn:
            for migration in ("002_conversation.sql", "003_contact_name.sql", "004_knowledge_review.sql",
                              "005_sales_funnel.sql", "006_funnel_sessions.sql",
                              "007_premium_payments.sql"):
                sql = (Path(__file__).parent / "sql" / migration).read_text(encoding="utf-8")
                conn.execute(sql)

    def check_schema(self):
        super().check_schema()
        with self.connect() as conn:
            found = conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema='telegram' "
                "AND table_name='prospects' AND column_name IN "
                "('profile_json','last_name','lead_source','funnel_route','offer_status')"
            ).fetchall()
            if len(found) != 5:
                raise RuntimeError("Schéma conversation absent. Lancez : python -m bot.main init-db")
            if conn.execute("SELECT to_regclass('telegram.review_questions')").fetchone()[0] is None:
                raise RuntimeError("Schéma de revue absent. Lancez : python -m bot.main init-db")
            if conn.execute("SELECT to_regclass('telegram.funnel_sessions')").fetchone()[0] is None:
                raise RuntimeError("Schéma du tunnel absent. Lancez : python -m bot.main init-db")
            if conn.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema='telegram' "
                    "AND table_name='payment_events' AND column_name='source_message_id'"
            ).fetchone() is None:
                raise RuntimeError("Schéma de paiement absent. Lancez : python -m bot.main init-db")

    def save(self, user_id: int, update_id: int, data: dict, version: str) -> bool:
        from psycopg.types.json import Jsonb

        with self.connect() as conn:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
                inserted = conn.execute(
                    "INSERT INTO telegram.bot_events (update_id,telegram_user_id,kind) "
                    "VALUES (%s,%s,'lead_saved') ON CONFLICT DO NOTHING RETURNING update_id",
                    (update_id, user_id),
                ).fetchone()
                if not inserted:
                    return False
                conn.execute(
                    "INSERT INTO telegram.prospects "
                    "(telegram_user_id,track,last_name,first_name,contact_detail,project_summary,handoff_requested,"
                    "profile_json,contact_method,contact_confirmed,consent_at,consent_version,open_questions,"
                    "lead_source,funnel_route,offer_status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,true,%s,%s,true,now(),%s,%s,%s,%s,%s) "
                    "ON CONFLICT (telegram_user_id) DO UPDATE SET "
                    "track=EXCLUDED.track,last_name=EXCLUDED.last_name,first_name=EXCLUDED.first_name,contact_detail=EXCLUDED.contact_detail,"
                    "project_summary=EXCLUDED.project_summary,handoff_requested=true,profile_json=EXCLUDED.profile_json,"
                    "contact_method=EXCLUDED.contact_method,contact_confirmed=true,consent_at=now(),"
                    "consent_version=EXCLUDED.consent_version,open_questions=EXCLUDED.open_questions,"
                    "lead_source=EXCLUDED.lead_source,funnel_route=EXCLUDED.funnel_route,"
                    "offer_status=EXCLUDED.offer_status,updated_at=now()",
                    (user_id, data.get("primary_track"), data["last_name"], data["first_name"], data["contact_detail"],
                     data["summary"], Jsonb(data["profile"]), data["contact_method"], version,
                     Jsonb(data.get("open_questions", [])), data["profile"].get("lead_source", "direct"),
                     data["profile"].get("funnel_route", "consultation"),
                     data["profile"].get("offer_status", "consultation_requested")),
                )
                conn.execute(
                    "INSERT INTO telegram.consent_events (telegram_user_id,purpose,granted,text_version) "
                    "VALUES (%s,'contact',true,%s)", (user_id, version),
                )
                conn.execute(
                    "UPDATE telegram.prospects SET admin_notified_at=NULL "
                    "WHERE telegram_user_id=%s", (user_id,),
                )
                return True

    def get(self, user_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT track,last_name,first_name,contact_detail,project_summary,profile_json,contact_method,"
                "open_questions,consent_at,consent_version,lead_source,funnel_route,offer_status FROM telegram.prospects "
                "WHERE telegram_user_id=%s AND handoff_requested=true", (user_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "primary_track": row[0], "last_name": row[1], "first_name": row[2], "contact_detail": row[3],
                "summary": row[4], "profile": row[5], "contact_method": row[6],
                "open_questions": row[7] or [], "consent_at": row[8], "consent_version": row[9],
                "lead_source": row[10], "funnel_route": row[11], "offer_status": row[12],
            }

    def delete(self, user_id: int):
        with self.connect() as conn:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
                for table in ("prospects", "conversation_state", "consent_events", "bot_events"):
                    conn.execute(f"DELETE FROM telegram.{table} WHERE telegram_user_id=%s", (user_id,))

    def pending_admin_notifications(self, limit: int = 5) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT telegram_user_id,track,last_name,first_name,contact_detail,project_summary,profile_json "
                "FROM telegram.prospects WHERE handoff_requested=true AND contact_confirmed=true "
                "AND consent_at IS NOT NULL AND admin_notified_at IS NULL "
                "ORDER BY updated_at LIMIT %s", (limit,),
            ).fetchall()
        return [{
            "user_id": row[0], "track": row[1], "last_name": row[2], "first_name": row[3],
            "phone": row[4], "summary": row[5], "profile": row[6] or {},
        } for row in rows]

    def mark_admin_notified(self, user_id: int):
        with self.connect() as conn:
            conn.execute(
                "UPDATE telegram.prospects SET admin_notified_at=now() "
                "WHERE telegram_user_id=%s AND admin_notified_at IS NULL", (user_id,),
            )

    def export_handoffs(self):
        with self.connect() as conn:
            return conn.execute(
                "SELECT telegram_user_id,track,last_name,first_name,contact_detail,project_summary,updated_at,"
                "contact_method,profile_json,open_questions,consent_at,consent_version,"
                "lead_source,funnel_route,offer_status "
                "FROM telegram.prospects WHERE handoff_requested=true AND contact_confirmed=true "
                "AND consent_at IS NOT NULL ORDER BY updated_at"
            ).fetchall()
