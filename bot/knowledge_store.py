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

    def payment_counts(self) -> dict[str, int]:
        return {}


class PostgresKnowledgeStore(PostgresStore):
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

    def payment_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT status,count(*) FROM telegram.payment_events GROUP BY status").fetchall()
        return dict(rows)
