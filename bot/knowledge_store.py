"""Revue documentaire et historique volontaire, sans exposer les secrets du bot."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlparse

from .gemini_dialogue import PRIVATE, safe_message
from .rag import normalize, tokens
from .store import PostgresStore


def question_key(question: str) -> str:
    canonical = re.sub(r"[^a-z0-9]+", " ", normalize(question)).strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def closest_entry(question: str, entries: list[dict]) -> dict | None:
    wanted = tokens(question)
    if len(wanted) < 2:
        return None
    ranked = []
    for entry in entries:
        known = tokens(entry["question"])
        shared = len(wanted & known)
        if shared < 2:
            continue
        containment = shared / min(len(wanted), len(known))
        jaccard = shared / len(wanted | known)
        if containment >= 0.65 and jaccard >= 0.4:
            ranked.append((containment, jaccard, entry["id"], entry))
    return dict(max(ranked)[-1]) if ranked else None


def reviewable_question(question: str) -> str | None:
    clean = question.strip()
    return clean if safe_message(clean, 500) and len(clean) >= 5 else None


def valid_answer(text: str) -> bool:
    return bool(text and 8 <= len(text) <= 900 and not PRIVATE.search(text)
                and not re.search(r"https?://|\b\d{9,}\b", text, re.I))


def valid_video_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").casefold()
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and host in {"youtube.com", "www.youtube.com", "youtu.be", "vimeo.com", "www.vimeo.com"})
    except ValueError:
        return False


class MemoryKnowledgeStore:
    """Équivalent minimal pour les tests, sans réseau ni données réelles."""

    def __init__(self):
        self.entries: list[dict] = []
        self.questions: list[dict] = []
        self.preferences: dict[int, bool] = {}
        self.messages: list[dict] = []
        self.funnel_sessions: dict[int, dict] = {}
        self.payments: list[dict] = []

    def load_funnel_state(self, user_id: int) -> dict | None:
        state = self.funnel_sessions.get(user_id)
        return dict(state) if state else None

    def save_funnel_state(self, user_id: int, state: dict):
        self.funnel_sessions[user_id] = dict(state)

    def delete_funnel_state(self, user_id: int):
        self.funnel_sessions.pop(user_id, None)

    def record_question(self, question: str, context: dict, category: str) -> tuple[int, bool] | None:
        clean = reviewable_question(question)
        if not clean:
            return None
        key = question_key(clean)
        for item in self.questions:
            if item["key"] == key:
                item["occurrences"] += 1
                if category == "faq_candidate" and item["notified_at"] is None:
                    item["category"] = category
                return item["id"], False
        item = {"id": len(self.questions) + 1, "key": key, "question": clean,
                "context": dict(context), "category": category, "status": "open",
                "occurrences": 1, "notified_at": None}
        self.questions.append(item)
        return item["id"], category == "needs_answer"

    def pending_notifications(self, limit: int = 5) -> list[dict]:
        return [dict(item) for item in self.questions if item["category"] == "needs_answer"
                and item["status"] == "open" and item["notified_at"] is None][:limit]

    def mark_notified(self, ticket_id: int):
        self.questions[ticket_id - 1]["notified_at"] = datetime.now(timezone.utc)

    def add_entry(self, kind: str, question: str, answer: str, admin_id: int) -> int:
        entry_id = len(self.entries) + 1
        self.entries.append({"id": entry_id, "kind": kind, "question": question.strip(),
                             "key": question_key(question), "answer": answer.strip(),
                             "created_by": admin_id})
        return entry_id

    def answer_ticket(self, ticket_id: int, answer: str, admin_id: int) -> int | None:
        if not 1 <= ticket_id <= len(self.questions):
            return None
        ticket = self.questions[ticket_id - 1]
        if ticket["status"] != "open":
            return None
        entry_id = self.add_entry("answer", ticket["question"], answer, admin_id)
        ticket["status"] = "answered"
        ticket["answer_entry_id"] = entry_id
        return entry_id

    def find_answer(self, question: str) -> dict | None:
        key = question_key(question)
        eligible = [item for item in self.entries if item["kind"] in {"answer", "faq"}]
        exact = next((dict(item) for item in reversed(eligible) if item["key"] == key), None)
        return exact or closest_entry(question, eligible)

    def list_entries(self, kind: str, limit: int = 10) -> list[dict]:
        return [dict(item) for item in reversed(self.entries) if item["kind"] == kind][:limit]

    def list_questions(self, category: str, limit: int = 10) -> list[dict]:
        return [dict(item) for item in self.questions if item["category"] == category
                and item["status"] == "open"][:limit]

    def history_enabled(self, user_id: int) -> bool:
        return self.preferences.get(user_id, False)

    def set_history(self, user_id: int, enabled: bool):
        self.preferences[user_id] = enabled

    def append_turn(self, user_id: int, update_id: int, user_text: str, bot_text: str):
        if not self.history_enabled(user_id):
            return
        if any(item["update_id"] == update_id for item in self.messages):
            return
        self.messages.extend([{"user_id": user_id, "update_id": update_id, "role": "user", "body": user_text},
                              {"user_id": user_id, "update_id": update_id, "role": "bot", "body": bot_text}])

    def delete_history(self, user_id: int):
        self.messages = [item for item in self.messages if item["user_id"] != user_id]
        self.preferences.pop(user_id, None)
        self.delete_funnel_state(user_id)

    def payment_counts(self) -> dict[str, int]:
        return dict(Counter(item["status"] for item in self.payments))

    def create_payment_receipt(self, user_id: int, *, update_id: int, media_type: str,
                               file_id: str, file_unique_id: str,
                               source_chat_id: int, source_message_id: int,
                               amount_dzd: int, language: str = "fr") -> dict:
        existing = next((item for item in self.payments
                         if item["file_unique_id"] == file_unique_id), None)
        if existing:
            return dict(existing)
        item = {
            "id": len(self.payments) + 1, "user_id": user_id, "update_id": update_id,
            "media_type": media_type, "file_id": file_id, "file_unique_id": file_unique_id,
            "source_chat_id": source_chat_id, "source_message_id": source_message_id,
            "amount_dzd": amount_dzd, "language": language, "status": "unverified",
            "notified_at": None, "reviewed_by": None, "invite_link": None,
        }
        self.payments.append(item)
        return dict(item)

    def pending_payment_receipts(self, limit: int = 5) -> list[dict]:
        return [dict(item) for item in self.payments
                if item["status"] == "unverified" and item["notified_at"] is None][:limit]

    def mark_payment_notified(self, payment_id: int):
        item = next((item for item in self.payments if item["id"] == payment_id), None)
        if item:
            item["notified_at"] = datetime.now(timezone.utc)

    def get_payment(self, payment_id: int) -> dict | None:
        item = next((item for item in self.payments if item["id"] == payment_id), None)
        return dict(item) if item else None

    def review_payment(self, payment_id: int, admin_id: int, status: str,
                       invite_link: str | None = None) -> dict | None:
        item = next((item for item in self.payments if item["id"] == payment_id), None)
        if not item or item["status"] != "unverified" or status not in {"verified", "rejected"}:
            return None
        item.update(status=status, reviewed_by=admin_id, invite_link=invite_link)
        return dict(item)


class PostgresKnowledgeStore(PostgresStore):
    def load_funnel_state(self, user_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT language,stage,lead_source,funnel_route,offer_status,private_channel_presented "
                "FROM telegram.funnel_sessions WHERE telegram_user_id=%s", (user_id,),
            ).fetchone()
        if not row:
            return None
        return {"language": row[0], "stage": row[1], "lead_source": row[2],
                "funnel_route": row[3], "offer_status": row[4],
                "private_channel_presented": row[5]}

    def save_funnel_state(self, user_id: int, state: dict):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO telegram.funnel_sessions "
                "(telegram_user_id,language,stage,lead_source,funnel_route,offer_status,private_channel_presented) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (telegram_user_id) DO UPDATE SET "
                "language=EXCLUDED.language,stage=EXCLUDED.stage,lead_source=EXCLUDED.lead_source,"
                "funnel_route=EXCLUDED.funnel_route,offer_status=EXCLUDED.offer_status,"
                "private_channel_presented=EXCLUDED.private_channel_presented,updated_at=now()",
                (user_id, state.get("language"), state.get("stage", "idle"),
                 state.get("lead_source", "direct"), state.get("funnel_route", "undetermined"),
                 state.get("offer_status", "exploring"), bool(state.get("private_channel_presented"))),
            )

    def delete_funnel_state(self, user_id: int):
        with self.connect() as conn:
            conn.execute("DELETE FROM telegram.funnel_sessions WHERE telegram_user_id=%s", (user_id,))

    def record_question(self, question: str, context: dict, category: str) -> tuple[int, bool] | None:
        from psycopg.types.json import Jsonb

        clean = reviewable_question(question)
        if not clean:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "INSERT INTO telegram.review_questions (question_key,question,context_json,category) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (question_key) DO UPDATE SET "
                "occurrences=telegram.review_questions.occurrences+1,last_seen_at=now(), "
                "category=CASE WHEN telegram.review_questions.notified_at IS NULL "
                "AND EXCLUDED.category='faq_candidate' THEN 'faq_candidate' "
                "ELSE telegram.review_questions.category END "
                "RETURNING id,occurrences,category,status",
                (question_key(clean), clean, Jsonb(context), category),
            ).fetchone()
        return row[0], row[1] == 1 and row[2] == "needs_answer" and row[3] == "open"

    def pending_notifications(self, limit: int = 5) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,question,context_json,occurrences FROM telegram.review_questions "
                "WHERE category='needs_answer' AND status='open' AND notified_at IS NULL "
                "ORDER BY id LIMIT %s", (limit,),
            ).fetchall()
        return [{"id": row[0], "question": row[1], "context": row[2], "occurrences": row[3]} for row in rows]

    def mark_notified(self, ticket_id: int):
        with self.connect() as conn:
            conn.execute("UPDATE telegram.review_questions SET notified_at=now() WHERE id=%s AND notified_at IS NULL",
                         (ticket_id,))

    def add_entry(self, kind: str, question: str, answer: str, admin_id: int) -> int:
        with self.connect() as conn:
            return conn.execute(
                "INSERT INTO telegram.knowledge_entries (kind,question,question_key,answer,created_by) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (kind, question.strip(), question_key(question), answer.strip(), admin_id),
            ).fetchone()[0]

    def answer_ticket(self, ticket_id: int, answer: str, admin_id: int) -> int | None:
        with self.connect() as conn:
            with conn.transaction():
                row = conn.execute("SELECT question FROM telegram.review_questions WHERE id=%s AND status='open' FOR UPDATE",
                                   (ticket_id,)).fetchone()
                if not row:
                    return None
                entry_id = conn.execute(
                    "INSERT INTO telegram.knowledge_entries (kind,question,question_key,answer,created_by) "
                    "VALUES ('answer',%s,%s,%s,%s) RETURNING id",
                    (row[0], question_key(row[0]), answer.strip(), admin_id),
                ).fetchone()[0]
                conn.execute("UPDATE telegram.review_questions SET status='answered',answer_entry_id=%s WHERE id=%s",
                             (entry_id, ticket_id))
                return entry_id

    def find_answer(self, question: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id,question,answer,kind FROM telegram.knowledge_entries "
                "WHERE kind IN ('answer','faq') AND question_key=%s AND active "
                "ORDER BY id DESC LIMIT 1", (question_key(question),),
            ).fetchone()
            if row:
                return {"id": row[0], "question": row[1], "answer": row[2], "kind": row[3]}
            rows = conn.execute(
                "SELECT id,question,answer,kind FROM telegram.knowledge_entries "
                "WHERE kind IN ('answer','faq') AND active ORDER BY id DESC LIMIT 200"
            ).fetchall()
        candidates = [{"id": item[0], "question": item[1], "answer": item[2], "kind": item[3]}
                      for item in rows]
        return closest_entry(question, candidates)

    def list_entries(self, kind: str, limit: int = 10) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,question,answer FROM telegram.knowledge_entries "
                "WHERE kind=%s AND active ORDER BY id DESC LIMIT %s", (kind, limit),
            ).fetchall()
        return [{"id": row[0], "question": row[1], "answer": row[2]} for row in rows]

    def list_questions(self, category: str, limit: int = 10) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,question,occurrences FROM telegram.review_questions "
                "WHERE category=%s AND status='open' ORDER BY id LIMIT %s", (category, limit),
            ).fetchall()
        return [{"id": row[0], "question": row[1], "occurrences": row[2]} for row in rows]

    def history_enabled(self, user_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT enabled FROM telegram.history_preferences WHERE telegram_user_id=%s",
                               (user_id,)).fetchone()
        return bool(row and row[0])

    def set_history(self, user_id: int, enabled: bool):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO telegram.history_preferences (telegram_user_id,enabled) VALUES (%s,%s) "
                "ON CONFLICT (telegram_user_id) DO UPDATE SET enabled=EXCLUDED.enabled,updated_at=now()",
                (user_id, enabled),
            )

    def append_turn(self, user_id: int, update_id: int, user_text: str, bot_text: str):
        with self.connect() as conn:
            with conn.transaction():
                enabled = conn.execute(
                    "SELECT enabled FROM telegram.history_preferences WHERE telegram_user_id=%s FOR UPDATE",
                    (user_id,),
                ).fetchone()
                if not enabled or not enabled[0]:
                    return
                for role, body in (("user", user_text), ("bot", bot_text)):
                    conn.execute(
                        "INSERT INTO telegram.conversation_messages (telegram_user_id,update_id,role,body) "
                        "VALUES (%s,%s,%s,%s) ON CONFLICT (update_id,role) DO NOTHING",
                        (user_id, update_id, role, body[:2000]),
                    )

    def delete_history(self, user_id: int):
        with self.connect() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM telegram.conversation_messages WHERE telegram_user_id=%s", (user_id,))
                conn.execute("DELETE FROM telegram.history_preferences WHERE telegram_user_id=%s", (user_id,))
                conn.execute("DELETE FROM telegram.funnel_sessions WHERE telegram_user_id=%s", (user_id,))

    def payment_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT status,count(*) FROM telegram.payment_events GROUP BY status").fetchall()
        return dict(rows)

    def create_payment_receipt(self, user_id: int, *, update_id: int, media_type: str,
                               file_id: str, file_unique_id: str,
                               source_chat_id: int, source_message_id: int,
                               amount_dzd: int, language: str = "fr") -> dict:
        from psycopg.types.json import Jsonb

        payload = Jsonb({"update_id": update_id, "language": language})
        with self.connect() as conn:
            row = conn.execute(
                "INSERT INTO telegram.payment_events "
                "(telegram_user_id,provider,external_reference,amount_minor,currency,status,event_payload,"
                "media_type,telegram_file_id,telegram_file_unique_id,source_chat_id,source_message_id) "
                "VALUES (%s,'telegram_receipt',%s,%s,'DZD','unverified',%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (provider,external_reference) DO UPDATE SET external_reference=EXCLUDED.external_reference "
                "RETURNING id,telegram_user_id,amount_minor,status,media_type,telegram_file_id,"
                "telegram_file_unique_id,source_chat_id,source_message_id,notified_at,reviewed_by,invite_link,event_payload",
                (user_id, file_unique_id, amount_dzd * 100, payload, media_type, file_id,
                 file_unique_id, source_chat_id, source_message_id),
            ).fetchone()
        return self._payment_dict(row)

    @staticmethod
    def _payment_dict(row) -> dict:
        payload = row[12] or {}
        return {
            "id": row[0], "user_id": row[1], "amount_dzd": int(row[2] or 0) // 100,
            "status": row[3], "media_type": row[4], "file_id": row[5],
            "file_unique_id": row[6], "source_chat_id": row[7], "source_message_id": row[8],
            "notified_at": row[9], "reviewed_by": row[10], "invite_link": row[11],
            "language": payload.get("language", "fr"),
        }

    def pending_payment_receipts(self, limit: int = 5) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,telegram_user_id,amount_minor,status,media_type,telegram_file_id,"
                "telegram_file_unique_id,source_chat_id,source_message_id,notified_at,reviewed_by,invite_link,event_payload "
                "FROM telegram.payment_events WHERE provider='telegram_receipt' "
                "AND status='unverified' AND notified_at IS NULL ORDER BY id LIMIT %s", (limit,),
            ).fetchall()
        return [self._payment_dict(row) for row in rows]

    def mark_payment_notified(self, payment_id: int):
        with self.connect() as conn:
            conn.execute(
                "UPDATE telegram.payment_events SET notified_at=now() "
                "WHERE id=%s AND notified_at IS NULL", (payment_id,),
            )

    def get_payment(self, payment_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id,telegram_user_id,amount_minor,status,media_type,telegram_file_id,"
                "telegram_file_unique_id,source_chat_id,source_message_id,notified_at,reviewed_by,invite_link,event_payload "
                "FROM telegram.payment_events WHERE id=%s", (payment_id,),
            ).fetchone()
        return self._payment_dict(row) if row else None

    def review_payment(self, payment_id: int, admin_id: int, status: str,
                       invite_link: str | None = None) -> dict | None:
        if status not in {"verified", "rejected"}:
            raise ValueError("Statut de paiement invalide")
        with self.connect() as conn:
            row = conn.execute(
                "UPDATE telegram.payment_events SET status=%s,reviewed_by=%s,reviewed_at=now(),invite_link=%s "
                "WHERE id=%s AND status='unverified' "
                "RETURNING id,telegram_user_id,amount_minor,status,media_type,telegram_file_id,"
                "telegram_file_unique_id,source_chat_id,source_message_id,notified_at,reviewed_by,invite_link,event_payload",
                (status, admin_id, invite_link, payment_id),
            ).fetchone()
        return self._payment_dict(row) if row else None
