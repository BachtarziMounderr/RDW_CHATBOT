"""Réponses courtes exclusivement issues du corpus public actif."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from difflib import get_close_matches
import hashlib
import re

from .rag import Corpus, normalize
from .service import Reply, SENSITIVE_INPUT
from .darija import project_tracks as darija_tracks, topic as darija_topic


UNKNOWN = "Je ne trouve pas de réponse vérifiée à cette question dans le guide RDW. Vous pouvez la joindre à une demande de contact."
DISABLED = "Cette version de test répond uniquement aux questions sur RDW. Le questionnaire et les demandes de rappel sont désactivés."

ALIASES = {
    "ausbildng": "ausbildung", "ausbildin": "ausbildung", "ausbildung": "ausbildung",
    "apprentissage": "ausbildung", "alternance": "ausbildung", "azubi": "ausbildung",
    "benevolat": "volontariat", "volontaire": "volontariat", "volontaria": "volontariat",
    "universite": "etudes", "universitaire": "etudes", "etudier": "etudes", "etude": "etudes", "etudes": "etudes",
    "travail": "emploi", "travailler": "emploi", "job": "emploi", "boulot": "emploi",
    "lebenslauf": "cv", "curriculum": "cv", "vitae": "cv",
    "papier": "documents", "papiers": "documents", "diplome": "documents", "diplomes": "documents",
    "traduction": "documents", "traduire": "documents", "traduit": "documents",
    "services": "agence", "service": "agence",
    "accompagnez": "accompagnement", "accompagner": "accompagnement", "accompagne": "accompagnement",
    "aide": "accompagnement", "aider": "accompagnement", "aidez": "accompagnement",
    "maider": "accompagnement", "aideriez": "accompagnement",
    "fonctionne": "fonctionnement", "marche": "fonctionnement", "deroule": "fonctionnement",
    "etape": "etapes", "etappes": "etapes", "filiere": "filieres", "parcour": "parcours",
    "documants": "documents", "dossie": "dossier", "motivaton": "motivation",
    "allemand": "langue", "german": "langue", "sprachkurs": "langue",
    "cout": "tarifs", "coute": "tarifs", "prix": "tarifs", "tarif": "tarifs", "tarifs": "tarifs",
    "rdv": "consultation", "rendezvous": "consultation", "rappel": "consultation",
    "ebook": "guide", "livre": "guide", "sommaire": "guide",
}
KNOWN = set(ALIASES) | set(ALIASES.values()) | {
    "rdw", "agence", "filieres", "parcours", "programmes", "voies", "fonctionnement",
    "accompagnement", "etapes", "processus", "cv", "documents", "dossier", "pieces",
    "certificats", "justificatifs", "lettre", "motivation", "candidature",
    "etudes", "ausbildung", "emploi", "volontariat", "fsj", "bfd", "esc",
    "langue", "consultation", "installation", "garantie", "garanties", "remboursement",
    "guide",
}


def canonical_words(question: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", normalize(question)))
    result = set()
    for word in words:
        if word in ALIASES:
            result.add(ALIASES[word])
        elif word in KNOWN:
            result.add(word)
        elif len(word) >= 5:
            match = get_close_matches(word, KNOWN, n=1, cutoff=0.84)
            if match:
                result.add(ALIASES.get(match[0], match[0]))
    result.update(darija_tracks(question))
    return result


class PrivateQAService:
    """Ne garde en mémoire que des IDs de déduplication et compteurs de fréquence."""

    def __init__(self, corpus: Corpus | None = None, clock=None):
        self.corpus = corpus or Corpus()
        self.by_id = {p["id"]: p for p in self.corpus.passages}
        for passage in self.by_id.values():
            if hashlib.sha256(passage["test_answer"].encode()).hexdigest() != passage.get("answer_sha256"):
                raise ValueError("Empreinte de réponse documentaire invalide.")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.recent_updates = deque(maxlen=512)
        self.recent_set = set()
        self.rate = {}

    def handle(self, user_id: int, update_id: int, value: str, callback: bool = False) -> Reply | None:
        if update_id in self.recent_set:
            return None
        if len(self.recent_updates) == self.recent_updates.maxlen:
            self.recent_set.discard(self.recent_updates.popleft())
        self.recent_updates.append(update_id)
        self.recent_set.add(update_id)
        now = self.clock()
        start, count = self.rate.get(user_id, (now, 0))
        if now - start >= timedelta(minutes=1):
            start, count = now, 0
        self.rate[user_id] = (start, count + 1)
        if count >= 20:
            return Reply("Trop de messages pour le moment. Réessayez dans une minute.")
        if callback:
            return Reply(DISABLED)
        text = value.strip()
        command = text.split(maxsplit=1)[0].lower() if text else ""
        if command == "/start":
            return Reply("Bonjour ! Je suis l'assistant RDW en version de test privée. Posez-moi une question en français sur les études, l'Ausbildung, l'emploi, le CV ou le dossier. Je réponds uniquement avec le guide RDW 2026. /aide affiche les sujets possibles. N'envoyez pas de données personnelles ni de documents.")
        if command == "/aide":
            return Reply("Vous pouvez demander : « Que fait RDW ? », « Quelles filières accompagnez-vous ? », « Comment se passe l'accompagnement ? », « Que mettre dans un CV ou un dossier ? ». Les prix du guide 2026 sont à confirmer ; ce mode ne collecte pas de fiche et ne donne pas de décision de visa. /id affiche votre identifiant Telegram.")
        if command == "/id":
            return Reply(f"Votre identifiant Telegram numérique : {user_id}. Transmettez uniquement ce numéro à la personne qui configure le test.")
        if command in {"/fiche", "/humain", "/annuler", "/mes_donnees", "/supprimer"}:
            return Reply(DISABLED)
        if command.startswith("/"):
            return Reply("Commande inconnue. Utilisez /aide.")
        if not text or len(text) > 500:
            return Reply("Écrivez une question de 500 caractères maximum.")
        if SENSITIVE_INPUT.search(text) or re.search(r"\b\d{7,}\b", text):
            return Reply("Ne partagez pas de numéro de document ni de donnée sensible dans ce bot. Posez une question générale.")
        topic = self._topic(text)
        if topic is None:
            return Reply(UNKNOWN)
        if topic == "guide_overview":
            return Reply(self.guide_overview())
        if topic == "cv_documents":
            cv = self.by_id["cv"]
            docs = self.by_id["documents"]
            return Reply("Le CV présente votre formation, vos expériences vérifiables et vos langues. Le dossier peut aussi comprendre une lettre ciblée et des justificatifs ; la liste exacte dépend du parcours. N'envoyez aucun document personnel ici."
                         f"\n\nSources : {cv['citation']}, {docs['citation']}")
        p = self.by_id[topic]
        return Reply(f"{p['test_answer']}\n\nSource : {p['citation']}")

    def _topic(self, question: str) -> str | None:
        q = normalize(question)
        words = canonical_words(question)
        # Les questions hors périmètre ne sont pas rattachées artificiellement à RDW.
        if re.search(r"\b(?:meteo|impot|billet|transport)\b|quel temps fait|quelle temperature", q):
            return None
        if "guide" in words and re.search(r"\b(?:contient|sommaire|sujets?|points?|parle|explique)\b", q):
            return "guide_overview"
        if (re.search(r"\b(?:quels?|quelles?|liste|ensemble|tous?|toutes?|chno|chnou|chniya|wach)\b.{0,35}\bservices?\b", q)
                or re.search(r"\bservices?\b.{0,30}\b(?:proposez|offrez|faites|3andkom|ta3kom)\b", q)
                or re.search(r"\b(?:vous|rdw|agence)\b.{0,20}\b(?:proposez quoi|faites quoi|offrez quoi)\b", q)):
            return "guide_overview"
        if hinted := darija_topic(question):
            return hinted
        if words & {"filieres", "parcours", "voies"} or re.search(r"\b(?:quels? programmes|types? de programmes)\b", q):
            return "filieres"
        if re.search(r"\b(?:visas?|titre de sejour|admissions?|admis)\b", q):
            return "limites"
        if re.search(r"\b(?:garanti\w*|rembours\w*|satisfait ou rembourse)\b", q):
            return "garanties"
        if re.search(r"\b(?:prix|tarifs?|cout\w*|frais|payer|paiement|combien coute)\b", q):
            return "tarifs_langue" if re.search(r"\b(?:langue|allemand|virtulingo|a1|a2|b1|b2)\b", q) else "tarifs"
        if re.search(r"\b(?:visas?|titre de sejour|admissions?|admis|compte bloque|financement|equivalence|delai garanti|legal|juridique|loi)\b", q):
            return "limites"
        if "volontariat" in words or words & {"fsj", "bfd", "esc"}:
            return None
        if "consultation" in words or re.search(r"\b(?:conseiller|commercial|rendez.vous|rappel)\b", q):
            return "consultation"
        if "installation" in words or re.search(r"\b(?:arrivee|logement|sur place)\b", q):
            return "installation"
        if "lettre" in words or "motivation" in words or re.search(r"\b(?:personnaliser|personnalisee)\b", q):
            return "lettres"
        if "cv" in words and words & {"documents", "dossier", "pieces", "certificats", "justificatifs"}:
            return "cv_documents"
        if "cv" in words:
            return "cv"
        if words & {"documents", "dossier", "pieces", "certificats", "justificatifs"}:
            return "documents"
        if re.search(r"\bcomment\b.{0,30}\b(?:m\s+)?(?:aider|aidez|maider)\b", q):
            return "mission"
        if (words & {"fonctionnement", "etapes", "processus"}
                or re.search(r"\b(?:demarches?|procedure)\b", q)
                or ("accompagnement" in words and re.search(r"\b(?:comment|deroule|passe)\b", q))):
            return "processus"
        if "langue" in words or re.search(r"\b(?:cours d.allemand|niveau d.allemand|virtulingo)\b", q):
            return "langue"
        if words & {"ausbildung"}:
            return "ausbildung"
        if words & {"etudes"}:
            return "etudes"
        if words & {"emploi"}:
            return "emploi"
        if "rdw" in words or "agence" in words or "accompagnement" in words:
            return "mission"
        if re.search(r"\b(?:renseignements?|informations?|me renseigner|en savoir plus|connaitre|connaître)\b", q):
            return "mission"
        matches = self.corpus.search(question, limit=1)
        return matches[0]["id"] if matches else None

    def guide_overview(self) -> str:
        return ("Le guide RDW présente les projets d'études, d'Ausbildung et d'emploi, le fonctionnement de l'accompagnement, "
                "la formation en allemand, le CV, la lettre de motivation, les documents, la consultation, les tarifs indiqués, "
                "l'installation et les limites concernant les garanties, l'admission, le financement et le visa. "
                "Vous pouvez me demander d'expliquer l'un de ces points.")
