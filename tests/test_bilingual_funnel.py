from pathlib import Path
from datetime import datetime, timezone
import json

from bot.conversation import ConversationService
from bot.lead_store import MemoryLeadStore
from bot.knowledge_store import MemoryKnowledgeStore
from bot.gemini_dialogue import GeminiLimits, UsageLimit
from bot.groq_dialogue import GroqDialogue


class Dialog:
    def __init__(self, **kwargs):
        self.bot = ConversationService(MemoryLeadStore(), **kwargs)
        self.update_id = 0

    def send(self, value: str, *, callback: bool = False):
        self.update_id += 1
        return self.bot.handle(42, self.update_id, value, callback)


def test_start_language_choice_then_sends_original_ebook():
    d = Dialog()
    welcome = d.send("/start")
    assert welcome.buttons == [("🇫🇷 Français", "lang:fr"), ("🇩🇿 العربية", "lang:ar")]

    ebook = d.send("lang:fr", callback=True)
    assert ebook.buttons[0][1] == "ebook:continue"
    assert Path(ebook.document_path).is_file()
    assert Path(ebook.document_path).stat().st_size > 2_000_000


def test_strict_funnel_reaches_premium_and_vip_payment_paths():
    premium = Dialog()
    premium.send("/start")
    premium.send("lang:fr", callback=True)
    pitch = premium.send("ebook:continue", callback=True)
    assert {value for _, value in pitch.buttons} == {"funnel:premium", "funnel:self"}
    project = premium.send("funnel:premium", callback=True)
    assert "2 000 DA" in project.text
    assert {value for _, value in project.buttons} == {"project:etudes", "project:ausbildung", "project:emploi"}

    vip = Dialog(payment_proof_telegram="0541501832")
    vip.send("/start")
    vip.send("lang:fr", callback=True)
    vip.send("ebook:continue", callback=True)
    offer = vip.send("funnel:self", callback=True)
    assert "500 DA" in offer.text and "accès à vie" in offer.text
    payment = vip.send("vip:join", callback=True)
    assert "BaridiMob" in payment.text and "CCP" in payment.text
    assert "0541501832" in payment.text
    assert "vérifiera le paiement manuellement" in payment.text


def test_question_during_tunnel_is_answered_then_same_step_resumes():
    d = Dialog()
    d.send("/start")
    d.send("lang:fr", callback=True)
    d.send("ebook:continue", callback=True)
    reply = d.send("Est-ce que vous aidez pour traduire les documents ?")
    assert "traduction" in reply.text
    assert "Préférez-vous" in reply.text
    assert {value for _, value in reply.buttons} == {"funnel:premium", "funnel:self"}


def test_arabic_choice_changes_tunnel_and_documentary_answer_language():
    d = Dialog()
    d.send("/start")
    ebook = d.send("lang:ar", callback=True)
    assert "دليل" in ebook.text
    pitch = d.send("ebook:continue", callback=True)
    assert "مرافقتنا" in pitch.text
    answer = d.send("هل تساعدون في ترجمة الوثائق؟")
    assert any("\u0600" <= char <= "\u06ff" for char in answer.text)
    assert "الترجمة" in answer.text
    assert {value for _, value in answer.buttons} == {"funnel:premium", "funnel:self"}


def test_payment_details_are_configurable_and_never_invented():
    d = Dialog(baridimob_payment_details="00799999000123456789",
               ccp_payment_details="12345678 clé 90")
    d.send("/start")
    d.send("lang:fr", callback=True)
    d.send("ebook:continue", callback=True)
    d.send("funnel:self", callback=True)
    payment = d.send("vip:join", callback=True)
    assert "00799999000123456789" in payment.text
    assert "12345678 clé 90" in payment.text


def test_non_personal_funnel_stage_survives_a_service_restart():
    state_store = MemoryKnowledgeStore()
    first = ConversationService(MemoryLeadStore(), review_store=state_store)
    first.handle(42, 1, "/start")
    first.handle(42, 2, "lang:ar", True)

    restarted = ConversationService(MemoryLeadStore(), review_store=state_store)
    pitch = restarted.handle(42, 3, "ebook:continue", True)
    assert "مرافقتنا" in pitch.text
    assert restarted.sessions[42].language == "ar"


def test_groq_receives_selected_arabic_language_and_returns_grounded_arabic(tmp_path):
    class Transport:
        def __init__(self):
            self.payload = None

        def generate(self, prompt: str) -> str:
            self.payload = json.loads(prompt)
            return json.dumps({
                "answer": "يمكن لوكالتنا مساعدتكم في إعداد الملف وترجمة الوثائق عندما يتطلب المسار ذلك.",
                "passage_ids": ["documents"],
            }, ensure_ascii=False)

    transport = Transport()
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    d = Dialog(composer=composer)
    d.send("/start")
    d.send("lang:ar", callback=True)
    d.send("ebook:continue", callback=True)
    answer = d.send("هل تساعدون في ترجمة الوثائق؟")

    assert transport.payload["output_language"] == "ar"
    assert answer.text.startswith("يمكن لوكالتنا")
    assert "مرافقتنا المميزة" in answer.text
