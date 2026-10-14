import asyncio
import os
from types import SimpleNamespace

import pytest

from bot.admin import AdminService
from bot.conversation import ConversationService
from bot.knowledge_store import MemoryKnowledgeStore, PostgresKnowledgeStore, question_key, valid_video_url
from bot.lead_store import MemoryLeadStore
from bot.main import flush_review_notifications


def test_unknown_question_notifies_once_and_owner_answer_is_reused():
    knowledge = MemoryKnowledgeStore()
    bot = ConversationService(MemoryLeadStore(), review_store=knowledge)
    first = bot.handle(7, 1, "Pouvez-vous organiser une garde d'animaux ?").text
    assert "réponse vérifiée" in first
    pending = knowledge.pending_notifications()
    assert len(pending) == 1 and pending[0]["question"].endswith("animaux ?")
    knowledge.mark_notified(pending[0]["id"])
    assert knowledge.pending_notifications() == []
    admin = AdminService(knowledge)
    assert "Réponse validée" in admin.handle(7, "/repondre 1 RDW ne documente pas cet accompagnement dans sa base actuelle.")
    second = bot.handle(8, 2, "Pouvez-vous organiser une garde d'animaux ?").text
    assert "ne documente pas cet accompagnement" in second
    assert bot.sessions[8].last_source.startswith("RDW:réponse-validée:")
    reformulated = bot.handle(9, 3, "Est-ce que vous organisez la garde des animaux ?").text
    assert "ne documente pas cet accompagnement" in reformulated


def test_absurd_or_repeated_unknown_goes_to_faq_without_notification():
    knowledge = MemoryKnowledgeStore()
    bot = ConversationService(MemoryLeadStore(), review_store=knowledge)
    bot.handle(7, 1, "Quelle météo fait-il demain ?")
    assert knowledge.pending_notifications() == []
    assert knowledge.list_questions("faq_candidate")[0]["question"].startswith("Quelle météo")

    bot.handle(8, 2, "Pouvez-vous réserver une fusée pour Mars ?")
    assert len(knowledge.pending_notifications()) == 1
    bot.handle(8, 3, "Pouvez-vous réserver une fusée pour Mars ?")
    faq = knowledge.list_questions("faq_candidate")
    assert any(item["question"].endswith("Mars ?") and item["occurrences"] == 2 for item in faq)


def test_admin_own_unknown_question_is_kept_without_chat_notification():
    knowledge = MemoryKnowledgeStore()
    bot = ConversationService(MemoryLeadStore(), review_store=knowledge,
                              admin_user_ids=frozenset({7}))
    bot.handle(7, 1, "Pouvez-vous organiser une garde d'animaux ?")
    pending = knowledge.pending_notifications()
    assert pending[0]["context"]["origine_admin"] is True

    sent = []

    class FakeBot:
        async def send_message(self, chat_id, message):
            sent.append((chat_id, message))

    application = SimpleNamespace(
        bot_data={"review_store": knowledge, "admin_user_ids": frozenset({7})},
        bot=FakeBot(),
    )
    asyncio.run(flush_review_notifications(application))

    assert sent == []
    assert knowledge.pending_notifications() == []
    assert knowledge.list_questions("needs_answer")[0]["status"] == "open"


def test_faq_is_not_repeated_on_an_unrelated_greeting():
    knowledge = MemoryKnowledgeStore()
    bot = ConversationService(MemoryLeadStore(), review_store=knowledge)
    bot.handle(7, 1, "Question inconnue alpha zéphyr ?")
    bot.handle(7, 2, "Question inconnue alpha zéphyr ?")
    answer = bot.handle(7, 3, "bonjour").text
    assert "/faq" not in answer


def test_faq_video_and_history_are_explicit_and_deletable():
    knowledge = MemoryKnowledgeStore()
    admin = AdminService(knowledge)
    assert "Contenu validé" in admin.handle(7, "/faq_ajouter Que fait RDW ? | RDW accompagne des projets vers l'Allemagne.")
    assert "Vidéo" in admin.handle(7, "/video Présentation RDW | https://youtu.be/example")
    assert valid_video_url("https://youtu.be/example")
    assert not valid_video_url("http://example.com/video")

    bot = ConversationService(MemoryLeadStore(), review_store=knowledge)
    assert "Que fait RDW" in bot.handle(7, 1, "/faq").text
    assert "youtu.be" in bot.handle(7, 2, "/videos").text
    assert "activé" in bot.handle(7, 3, "/historique_on").text
    knowledge.append_turn(7, 4, "Bonjour", "Bonjour")
    assert len(knowledge.messages) == 2
    bot.handle(7, 5, "/supprimer")
    assert knowledge.messages == [] and not knowledge.history_enabled(7)


def test_payment_status_never_accepts_a_screenshot_as_verification():
    admin = AdminService(MemoryKnowledgeStore())
    assert "Aucun paiement" in admin.handle(7, "/paiements")


@pytest.mark.skipif(not os.getenv("TEST_TELEGRAM_DATABASE_URL"), reason="PostgreSQL de test non configuré")
def test_postgres_review_answer_history_and_cleanup():
    store = PostgresKnowledgeStore(os.environ["TEST_TELEGRAM_DATABASE_URL"])
    user_id, update_id = -99002702026, -99002702026
    question = "Question synthétique unique zéphyr boréal ?"
    key = question_key(question)
    ticket_id = entry_id = None
    try:
        ticket_id, notify = store.record_question(question, {"parcours": []}, "needs_answer")
        assert notify and any(item["id"] == ticket_id for item in store.pending_notifications())
        store.mark_notified(ticket_id)
        entry_id = store.answer_ticket(ticket_id, "Réponse synthétique réservée au test.", user_id)
        assert store.find_answer(question)["id"] == entry_id
        store.set_history(user_id, True)
        store.append_turn(user_id, update_id, question, "Réponse de test")
        assert store.history_enabled(user_id)
        store.delete_history(user_id)
        assert not store.history_enabled(user_id)
    finally:
        with store.connect() as conn:
            conn.execute("DELETE FROM telegram.review_questions WHERE question_key=%s", (key,))
            conn.execute("DELETE FROM telegram.knowledge_entries WHERE question_key=%s", (key,))
            conn.execute("DELETE FROM telegram.conversation_messages WHERE telegram_user_id=%s", (user_id,))
            conn.execute("DELETE FROM telegram.history_preferences WHERE telegram_user_id=%s", (user_id,))
