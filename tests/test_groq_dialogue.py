"""Tests Groq avec faux transport : aucun appel réseau."""
import json
from datetime import datetime, timezone

import pytest

from bot.conversation import ConversationService, Session
from bot.gemini_dialogue import GeminiLimits, UsageLimit
from bot.groq_dialogue import GroqDialogue, GroqSDKTransport
from bot.lead_store import MemoryLeadStore


class FakeTransport:
    def __init__(self, raw):
        self.raw = raw
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(json.loads(prompt))
        return self.raw.pop(0) if isinstance(self.raw, list) else self.raw


def test_groq_generated_reply_is_natural_and_keeps_python_question(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 12, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "RDW accompagne les études supérieures, l'Ausbildung et l'emploi en Allemagne.",
        "passage_ids": ["filieres"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "Quelles filières accompagne RDW ?").text

    assert answer.startswith("RDW accompagne les études supérieures")
    assert "Réponse Groq" not in answer
    assert "Quel projet envisagez-vous" not in answer
    assert transport.prompts[0]["intent"] == ["filieres"]
    assert transport.prompts[0]["question"] == "Quelles filières accompagne RDW ?"
    assert "telegram" not in json.dumps(transport.prompts[0]).lower()


def test_start_command_stays_reliable_without_spending_a_groq_call(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 12, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "Bonjour. Je suis l'assistant RDW en version de test. Avec plaisir.",
        "passage_ids": [],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage,
                            transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    assert bot.handle(77, 1, "/start").text.startswith("Bonjour et bienvenue chez RDW")
    assert transport.prompts == []


def test_groq_natural_acknowledgement_uses_only_validated_field(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 12, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "Très bien, je note votre formation visée : master.",
        "passage_ids": [],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)
    bot.sessions[77] = Session(tracks=["etudes"], primary="etudes", stage="explore",
                               current_slot="desired_degree", asked=1)

    answer = bot.handle(77, 1, "master").text

    assert answer.startswith("Très bien")
    assert "Dans quel domaine" in answer
    assert transport.prompts[0]["response_mode"] == "acknowledgement"
    assert transport.prompts[0]["latest_fact"] == {
        "field": "desired_degree", "label": "formation visée", "value": "master"
    }
    assert "message" not in transport.prompts[0]


def test_groq_answers_information_request_without_starting_project(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 12, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "RDW accompagne des projets vers l'Allemagne en lien avec Virtulingo.",
        "passage_ids": ["mission"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "Je veux juste me renseigner sur l'agence").text

    assert answer.startswith("RDW accompagne")
    assert "Que souhaitez-vous savoir sur RDW" in answer
    assert transport.prompts[0]["message_kind"] == "question"
    assert bot.sessions[77].primary is None


def test_groq_receives_filtered_darija_question_and_answers_in_french(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 12, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "RDW accompagne des projets vers l'Allemagne en lien avec Virtulingo.",
        "passage_ids": ["mission"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "wach tdirou exactement ?").text

    assert answer.startswith("RDW accompagne")
    assert transport.prompts[0]["message_kind"] == "question"
    assert transport.prompts[0]["intent"] == ["mission"]
    assert transport.prompts[0]["question"] == "wach tdirou exactement ?"


def test_groq_understands_how_can_you_help_and_uses_mission_passage(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "RDW analyse votre profil et vous accompagne dans les démarches adaptées à votre projet vers l'Allemagne.",
        "passage_ids": ["mission"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "comment pouvez vous maider ?").text

    assert answer.startswith("RDW analyse votre profil")
    assert transport.prompts[0]["intent"] == ["mission"]
    assert transport.prompts[0]["question"] == "comment pouvez vous maider ?"


def test_groq_gets_algerian_language_context_for_vague_darija_request(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "Pour votre projet d'études, nous pouvons analyser votre profil et préparer votre dossier pour cibler des établissements adaptés.",
        "passage_ids": ["etudes"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "kifach t9drou t3awnouni bach n9ra f allemagne").text

    assert answer.startswith("Pour votre projet d'études")
    assert "Quelle formation souhaitez-vous suivre" in answer
    prompt = transport.prompts[0]
    assert prompt["message_kind"] == "question"
    assert prompt["intent"] == ["etudes"]
    assert prompt["project_tracks"] == ["etudes"]
    assert prompt["may_ask_one_question"] is False
    assert "contexte algérien" in prompt["language_context"]
    assert "kifach" not in answer.lower() and "t3awn" not in answer.lower()


def test_groq_receives_full_catalogue_for_broad_services_question(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": ("Notre agence examine votre projet, accompagne la préparation du dossier et propose une formation en allemand "
                   "avec Virtulingo. Quel aspect souhaitez-vous approfondir ?"),
        "passage_ids": ["mission", "documents", "langue"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "chno houma les services li 3andkom").text

    assert answer.startswith("Notre agence examine votre projet")
    prompt = transport.prompts[0]
    assert prompt["response_mode"] == "documentary_catalogue"
    assert prompt["max_passage_ids"] == 4
    assert {"mission", "documents", "langue"}.issubset(set(prompt["intent"]))
    assert "language_context" in prompt


def test_groq_catalogue_handles_unseen_reformulation_and_keeps_exact_source(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "Le guide mentionne un suivi à l'arrivée pour certaines offres RDW, selon la prestation choisie.",
        "passage_ids": ["installation"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "Votre soutien continue-t-il après le voyage ?").text

    assert answer.startswith("Le guide mentionne un suivi")
    prompt = transport.prompts[0]
    assert prompt["response_mode"] == "documentary_catalogue"
    assert prompt["question"].startswith("Votre soutien continue")
    assert "installation" in prompt["intent"] and "tarifs" in prompt["intent"]
    assert "p. 32, 42" in bot.sessions[77].last_source


def test_groq_catalogue_accepts_clear_missing_information(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "Cette information n'est pas présente dans le guide RDW.",
        "passage_ids": [],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer)

    answer = bot.handle(77, 1, "Est-ce que vous fournissez un ordinateur portable ?").text

    assert answer.startswith("Cette information n'est pas présente")
    assert transport.prompts[0]["response_mode"] == "documentary_catalogue"


def test_test_headers_distinguish_groq_from_rag_and_dialogue_answers_first(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    transport = FakeTransport([
        json.dumps({
            "answer": "Bonjour ! Nous pouvons vous renseigner sur votre projet vers l'Allemagne.",
            "passage_ids": ["mission"],
        }, ensure_ascii=False),
        json.dumps({
            "answer": "RDW analyse votre profil et vous accompagne dans les démarches adaptées à votre projet.",
            "passage_ids": ["mission"],
        }, ensure_ascii=False),
        json.dumps({
            "answer": "RDW peut vous accompagner dans la préparation, la traduction et la vérification des diplômes lorsque le parcours l'exige.",
            "passage_ids": ["documents"],
        }, ensure_ascii=False),
        json.dumps({
            "answer": "Oui. RDW propose une consultation par appel pour examiner le projet, puis présente les étapes et un devis adapté.",
            "passage_ids": ["consultation"],
        }, ensure_ascii=False),
    ])
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer, debug_source_labels=True)

    assert bot.handle(77, 1, "bonjour").text.startswith("Réponse Groq :")
    assert bot.handle(77, 2, "comment pouvez vous maider ?").text.startswith("Réponse Groq :")
    documents = bot.handle(77, 3, "vous faites les dossiers traduction etc ?").text
    assert documents.startswith("Réponse Groq :") and "traduction" in documents
    consultation = bot.handle(77, 4, "vous faites des consultations ?").text
    assert consultation.startswith("Réponse Groq :") and "consultation" in consultation
    assert "Souhaitez-vous surtout" not in consultation
    repair = bot.handle(77, 5, "tu ne reponds pas a mes questions").text
    assert repair.startswith("Réponse RAG :") and "Reformulez simplement" in repair
    assert [p["intent"] for p in transport.prompts] == [["mission"], ["mission"], ["documents"], ["consultation"]]


def test_invalid_groq_output_is_visibly_tagged_as_rag_in_test_mode(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    transport = FakeTransport("pas du JSON")
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer, debug_source_labels=True)

    answer = bot.handle(77, 1, "Que fait RDW ?").text

    assert answer.startswith("Réponse RAG :")


def test_short_darija_price_request_uses_current_local_policy(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": ("Notre consultation est indiquée à 2 000 DA et sera déduite si une prestation de notre agence est choisie. "
                   "Souhaitez-vous préparer une consultation avec un conseiller commercial ?"),
        "passage_ids": ["tarifs"],
    }, ensure_ascii=False)
    transport = FakeTransport(raw)
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer, debug_source_labels=True)

    answer = bot.handle(77, 1, "prix le3ziz").text

    assert answer.startswith("Réponse RAG :")
    assert "Aucun paiement de consultation" in answer and "1 000 DA" in answer
    assert transport.prompts == []


def test_repeated_practical_questions_trigger_private_channel_goal(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    transport = FakeTransport([
        json.dumps({
            "answer": "Le niveau d'allemand nécessaire dépend du projet et doit être vérifié pour la candidature visée.",
            "passage_ids": ["langue"],
        }, ensure_ascii=False),
        json.dumps({
            "answer": ("Pour un master, le niveau demandé dépend du programme et doit être vérifié. "
                       "Pour approfondir vos démarches, notre canal Telegram privé propose des informations complémentaires "
                       "et des lives, avec un accès à vie pour un paiement unique de 1 000 DA. "
                       "Écrivez /canal pour recevoir les modalités."),
            "passage_ids": ["langue"],
        }, ensure_ascii=False),
    ])
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer, debug_source_labels=True)

    first = bot.handle(77, 1, "esq jai besoin de B2 allemand ?").text
    second = bot.handle(77, 2, "pour master informatique jai besoin de quel niveau en allemand ?").text

    assert first.startswith("Réponse Groq :") and "canal" not in first.lower()
    assert second.startswith("Réponse Groq :")
    assert all(item in second for item in ("1 000 DA", "accès à vie", "lives", "/canal"))
    assert "Quelle formation souhaitez-vous" not in second
    assert "dernier diplôme" in second
    assert transport.prompts[1]["orientation"]["goal"] == "private_channel"
    assert bot.sessions[77].information_turns == 2
    assert bot.sessions[77].private_channel_presented is True


def test_short_follow_up_reuses_only_the_previous_public_topic(tmp_path):
    limits = GeminiLimits()
    usage = UsageLimit(tmp_path / "usage.json", limits,
                       clock=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc))
    raw = json.dumps({
        "answer": "La consultation décrite dure environ trente minutes, par appel vidéo ou classique.",
        "passage_ids": ["consultation"],
    }, ensure_ascii=False)
    transport = FakeTransport([raw, raw])
    composer = GroqDialogue("", "qwen/qwen3.8-27b", limits, usage, transport=transport)
    bot = ConversationService(MemoryLeadStore(), composer=composer, debug_source_labels=True)

    bot.handle(77, 1, "Comment se passe la consultation ?")
    follow_up = bot.handle(77, 2, "et ca dure combien ?").text

    assert follow_up.startswith("Réponse Groq :")
    assert transport.prompts[1]["intent"] == ["consultation"]
    assert transport.prompts[1]["conversation_focus"] == "consultation"
    assert "question" in transport.prompts[1] and "historique" not in transport.prompts[1]


def test_groq_missing_key_and_unapproved_model_are_rejected_before_network():
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqSDKTransport("", "qwen/qwen3.8-27b", GeminiLimits())
    with pytest.raises(ValueError, match="GROQ_MODEL"):
        GroqSDKTransport("synthetic", "modele-payant-ou-inconnu", GeminiLimits())
