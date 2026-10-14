"""Logique conversationnelle indépendante de Telegram et du stockage."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from .rag import Corpus, normalize, validate_generated


TRACKS = {"etudes": "Études", "ausbildung": "Ausbildung", "emploi": "Emploi", "volontariat": "Volontariat"}
SENSITIVE_INPUT = re.compile(r"\b(?:passeport|passport|matricule|carte d.identite|numero de securite sociale)\b", re.I)
PRICE_INTENT = re.compile(r"\b(?:prix|tarif|cout|frais|combien|rembours\w*|adresse|telephone|visa|delai|legal|loi)\b")


@dataclass
class Reply:
    text: str
    buttons: list[tuple[str, str]] | None = None


MENU = [("🎓 Études", "track:etudes"), ("🛠 Ausbildung", "track:ausbildung"),
        ("💼 Emploi", "track:emploi"), ("🤝 Volontariat", "track:volontariat"),
        ("👤 Parler à un conseiller", "human")]
YES_NO = [("Oui", "consent:yes"), ("Non", "consent:no")]
CONTACT_YES_NO = [("Oui, être recontacté", "contact:yes"), ("Non", "contact:no")]
HUMAN_INTENT = re.compile(r"\b(?:parler|contacter|joindre)\b.*\b(?:humain|conseiller|commercial|personne)\b", re.I)


class Service:
    def __init__(self, store, corpus: Corpus | None = None, provider=None, clock=None):
        self.store = store
        self.corpus = corpus or Corpus()
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def handle(self, user_id: int, update_id: int, value: str, callback: bool = False) -> Reply | None:
        if not isinstance(value, str) or len(value) > 1000:
            return Reply("Message trop long. Limitez votre question à 500 caractères.")
        with self.store.user(user_id, update_id) as row:
            if row is None:
                return None
            now = self.clock()
            if row["rate_window"] is None or now - row["rate_window"] >= timedelta(minutes=1):
                row["rate_window"], row["rate_count"] = now, 0
            row["rate_count"] += 1
            urgent_command = not callback and value.strip().split(maxsplit=1)[0].lower() in {"/supprimer", "/mes_donnees", "/annuler"} if value.strip() else False
            if row["rate_count"] > 20 and not urgent_command:
                row["_event_kind"] = "rate_limit"
                return Reply("Trop de messages pour le moment. Réessayez dans une minute.")
            if callback:
                return self._callback(row, value)
            return self._message(row, value.strip())

    def _callback(self, row: dict, value: str) -> Reply:
        if value == "human":
            return self._message(row, "/humain")
        if value.startswith("track:"):
            track = value.partition(":")[2]
            if track not in TRACKS:
                return Reply("Choix invalide. Utilisez les boutons proposés.", MENU)
            if not row["data_consent"]:
                row["stage"] = "data_consent"
                return Reply("Pour préparer une fiche prospect, acceptez-vous que RDW conserve vos réponses et votre identifiant Telegram afin d'étudier votre demande ? Vous pouvez refuser et continuer à poser des questions. /supprimer efface vos données.", YES_NO)
            row["track"] = track
            row["stage"] = "first_name"
            return Reply(f"Voie choisie : {TRACKS[track]}. Quel prénom souhaitez-vous indiquer ? (120 caractères maximum, sans document sensible)")
        if value.startswith("consent:"):
            if row["stage"] not in {"data_consent", "data_consent_human"} or value not in {"consent:yes", "consent:no"}:
                return Reply("Ce bouton n'est plus valable. Utilisez /fiche pour reprendre.")
            yes = value == "consent:yes"
            human = row["stage"] == "data_consent_human"
            row["data_consent"] = yes
            row["_consents"].append(("data", yes))
            row["stage"] = ("contact_detail" if human else "choose_track") if yes else "idle"
            if yes and human:
                return Reply("Merci. Indiquez un email ou un numéro de téléphone pour que l'équipe puisse vous répondre.")
            return Reply("Merci. Choisissez votre voie pour commencer la fiche.", MENU) if yes else Reply("C'est noté. Aucune réponse personnelle n'a été enregistrée. Vous pouvez toujours poser une question sur RDW.")
        if value.startswith("contact:"):
            if row["stage"] != "contact_consent" or value not in {"contact:yes", "contact:no"}:
                return Reply("Ce bouton n'est plus valable. Utilisez /humain pour reprendre.")
            yes = value == "contact:yes"
            row["contact_consent"] = yes
            row["handoff_requested"] = yes and bool(row["contact_detail"])
            row["_consents"].append(("contact", yes))
            row["stage"] = "done" if yes else "idle"
            if yes:
                return Reply("Votre demande de contact est enregistrée pour l'équipe RDW. Aucun délai de réponse n'est garanti. /mes_donnees permet de revoir votre fiche et /supprimer de l'effacer.")
            return Reply("C'est noté. Votre fiche reste enregistrée, sans demande de rappel. Vous pouvez la supprimer avec /supprimer.")
        return Reply("Bouton inconnu. Utilisez /start pour afficher le menu.")

    def _message(self, row: dict, text: str) -> Reply:
        command = text.split(maxsplit=1)[0].lower() if text else ""
        if HUMAN_INTENT.search(text) and row["stage"] not in {"first_name", "project", "contact_detail"}:
            command = "/humain"
        if command in {"/start", "/aide"}:
            return Reply("Bonjour, je suis l'assistant RDW. Je peux répondre à des questions générales sur les études, l'Ausbildung, l'emploi et le volontariat en Allemagne, ou préparer une fiche pour un conseiller. Je ne garantis ni admission, ni emploi, ni visa. /fiche : commencer ou reprendre ; /humain : demander un contact ; /annuler : interrompre ; /mes_donnees : consulter ; /supprimer : effacer. Ne m'envoyez pas de documents sensibles.", MENU)
        if command == "/annuler":
            row["stage"] = "idle"
            return Reply("Questionnaire interrompu. Les réponses déjà consenties restent enregistrées. /fiche permet de reprendre, /supprimer les efface.")
        if command == "/supprimer":
            row["_delete"] = True
            return Reply("Vos réponses, consentements et événements associés ont été supprimés de la base du bot.")
        if command == "/mes_donnees":
            if not row["data_consent"]:
                return Reply("Aucune fiche prospect enregistrée.")
            return Reply(f"Fiche : voie {TRACKS.get(row['track'], 'non choisie')}; prénom {row['first_name'] or 'non indiqué'}; projet {row['project_summary'] or 'non indiqué'}; contact {row['contact_detail'] or 'non indiqué'}; accord de rappel : {'oui' if row['contact_consent'] else 'non'}. /supprimer pour effacer.")
        if command == "/fiche":
            if not row["data_consent"]:
                row["stage"] = "data_consent"
                return Reply("Acceptez-vous que RDW conserve vos réponses et votre identifiant Telegram pour étudier votre projet ? Vous pouvez refuser. /supprimer efface ensuite vos données.", YES_NO)
            if not row["track"]:
                row["stage"] = "choose_track"
                return Reply("Choisissez votre voie.", MENU)
            for field, stage, prompt in (("first_name", "first_name", "Quel prénom souhaitez-vous indiquer ?"),
                                          ("project_summary", "project", "Décrivez brièvement votre projet (120 caractères maximum)."),
                                          ("contact_detail", "contact_detail", "Indiquez un email ou un numéro de téléphone pour un éventuel rappel. Ne transmettez aucun document.")):
                if not row[field]:
                    row["stage"] = stage
                    return Reply(prompt)
            row["stage"] = "contact_consent"
            return Reply("Acceptez-vous séparément que l'équipe RDW vous recontacte avec les coordonnées fournies ?", CONTACT_YES_NO)
        if command == "/humain":
            if not row["data_consent"]:
                row["stage"] = "data_consent_human"
                return Reply("Pour transmettre une demande de contact à l'équipe, acceptez-vous d'abord l'enregistrement de votre fiche et de votre identifiant Telegram ?", YES_NO)
            if not row["contact_detail"]:
                row["stage"] = "contact_detail"
                return Reply("Indiquez un email ou un numéro de téléphone pour que l'équipe puisse vous répondre.")
            row["stage"] = "contact_consent"
            return Reply("Acceptez-vous que l'équipe RDW vous recontacte avec ces coordonnées ?", CONTACT_YES_NO)
        if command.startswith("/"):
            return Reply("Commande inconnue. Tapez /aide pour voir les commandes.")
        if row["stage"] in {"first_name", "project", "contact_detail"}:
            return self._field(row, text)
        if not text or len(text) > 500:
            return Reply("Écrivez une question de 500 caractères maximum.")
        if SENSITIVE_INPUT.search(text):
            return Reply("Ne partagez pas de passeport, matricule ou document sensible dans ce bot. Posez une question générale ou utilisez /humain.")
        query = normalize(text)
        if PRICE_INTENT.search(query):
            p = next(p for p in self.corpus.passages if p["id"] == "limites")
            return Reply(f"{p['text']}\n\nSource : {p['citation']}")
        answer, passages = self.corpus.documentary_answer(text)
        if self.provider and passages:
            try:
                generated = self.provider.answer(text, passages)
                if generated and validate_generated(generated[0], generated[1], passages):
                    body, refs = generated
                    return Reply(body + "\n\nSource : " + ", ".join(refs))
            except Exception:
                # Aucun contenu personnel ou secret dans les journaux.
                pass
        return Reply(answer)

    def _field(self, row: dict, text: str) -> Reply:
        if not row["data_consent"]:
            row["stage"] = "idle"
            return Reply("Consentement requis. Tapez /fiche pour commencer.")
        if not text or len(text) > 120 or SENSITIVE_INPUT.search(text) or re.search(r"\d{6,}", text):
            return Reply("Réponse non acceptée. Limitez-vous à 120 caractères et n'envoyez aucun numéro de document ni donnée sensible.")
        if row["stage"] == "first_name":
            if not re.fullmatch(r"[\wÀ-ÿ' -]{2,80}", text) or any(c.isdigit() for c in text):
                return Reply("Indiquez seulement un prénom (2 à 80 caractères).")
            row["first_name"] = text
            row["stage"] = "project"
            return Reply("Merci. Décrivez brièvement votre projet (120 caractères maximum).")
        if row["stage"] == "project":
            row["project_summary"] = text
            row["stage"] = "contact_detail"
            return Reply("Merci. Indiquez un email ou un numéro de téléphone pour un éventuel rappel. C'est facultatif : /annuler interrompt le questionnaire.")
        if not (re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text) or re.fullmatch(r"\+?[0-9 ()-]{8,25}", text)):
            return Reply("Indiquez une adresse email ou un numéro de téléphone valide, ou /annuler.")
        row["contact_detail"] = text
        row["stage"] = "contact_consent"
        return Reply("Acceptez-vous séparément que l'équipe RDW vous recontacte avec cette coordonnée ?", CONTACT_YES_NO)
