"""Détection locale et conservatrice des intentions du tunnel RDW."""
from __future__ import annotations

import re

from .rag import normalize


CONSULTATION = "consultation"
AGENCY_INFO = "agency_info"
SELF_GUIDED = "self_guided"
PROCEDURE_INFO = "procedure_info"

_CONSULTATION = re.compile(
    r"\b(?:consultation|rendez[ -]?vous|rdv|conseiller)\b|"
    r"\b(?:pret|prête|prete)\b.{0,24}\b(?:payer|commencer|consultation)\b|"
    r"\b(?:commencer|avancer|faire les demarches)\b.{0,30}\b(?:avec rdw|avec vous|agence)\b|"
    r"\b(?:accompagnement complet|prendre en charge mon dossier|2000\s*(?:da|dinar))\b"
)
_AGENCY_INFO = re.compile(
    r"\b(?:votre agence|rdw|vos services|ce que vous (?:faites|proposez)|virtulingo)\b"
)
_SELF_GUIDED = re.compile(
    r"\b(?:seul|seule|moi[ -]?meme|par moi[ -]?meme|sans agence|sans accompagnement)\b|"
    r"\b(?:pas interesse|pas intéressé|je ne veux pas|je veux pas)\b.{0,25}\b(?:agence|accompagnement|consultation)\b|"
    r"\b(?:juste|seulement)\b.{0,25}\b(?:les demarches|les démarches|comprendre comment faire)\b|"
    r"\b(?:wa7di|wahdi|bo7di|bouhdi)\b"
)
_PROCEDURE = re.compile(
    r"\b(?:demarches?|démarches?|procedure|procédure|etapes?|étapes?|comment faire|dossier|visa|"
    r"compte bloque|compte bloqué|traduction|candidature)\b"
)


def detect_sales_intent(text: str) -> str | None:
    q = normalize(text)
    if _SELF_GUIDED.search(q):
        return SELF_GUIDED
    if _CONSULTATION.search(q):
        return CONSULTATION
    if _AGENCY_INFO.search(q):
        return AGENCY_INFO
    if _PROCEDURE.search(q):
        return PROCEDURE_INFO
    return None
