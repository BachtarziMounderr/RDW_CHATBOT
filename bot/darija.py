"""Reconnaissance locale et prudente de formulations courantes en daridja algérienne.

Le texte libre reste local. Ce module déduit seulement une intention documentaire ou
une voie de projet ; la langue de réponse est choisie séparément par la personne.
"""
from __future__ import annotations

import re

from .rag import normalize


_INFO_LATIN = re.compile(
    r"\b(?:nheb|n7eb|hab|rani\s+hab|bghit)\s+(?:ghir\s+)?"
    r"(?:nestafser|nestaqsi|nefhem|na3ref|n3ref|ma3loumat|maloumat)\b|"
    r"\b(?:ma3loumat|maloumat)\s+(?:3la|ala)\b"
)
_INFO_ARABIC = re.compile(
    r"(?:حاب|نحب|بغيت).{0,18}(?:نستفسر|نسقسي|نفهم|نعرف|معلومات)|"
    r"معلومات.{0,12}(?:على|عن)"
)
_QUESTION_LATIN = re.compile(
    r"\b(?:wach|weche|wech|chkon|chkoun|chno|chnou|chniya|chya|kifach|kifech|"
    r"chhal|ch7al|9adech|win|3lach|ida|est-ce-que)\b"
)
_QUESTION_ARABIC = re.compile(r"(?:واش|وش|شكون|كيفاش|شحال|قداش|وين|علاش|ماذا|هل|كيف|كم|متى|أين|اين|لماذا|ما هي|ما هو|أي|اي)")

_STUDIES_LATIN = re.compile(r"\b(?:nqra|ne9ra|na9ra|n9ra|n9ari|9raya|qraya|universite|faculte|master|licence)\b")
_STUDIES_ARABIC = re.compile(r"(?:نقرا|قراية|دراسة|دراسات|جامعة|ماستر|ليسانس)")
_WORK_LATIN = re.compile(r"\b(?:nkhdem|nekhdem|khedma|khadma)\b")
_WORK_ARABIC = re.compile(r"(?:نخدم|خدمة|عمل)")
_AUSBILDUNG = re.compile(r"\b(?:ausbildung|azubi|apprentissage|alternance)\b|(?:أوسبيلدونغ|اوسبيلدونغ)")

_PRICE_LATIN = re.compile(r"\b(?:chhal|ch7al|9adech|souma|prix|tarif)\b")
_PRICE_ARABIC = re.compile(r"(?:شحال|قداش|السعر|سومة)")
_MISSION_LATIN = re.compile(
    r"\b(?:chkon|chkoun)\b|\bwach\s+(?:tdirou|dirou|takhdmou)\b|"
    r"\b(?:agence|rdw)\s+(?:wach|chkon|chkoun)\b|"
    r"\b(?:kifach|kifech)\s+(?:t9drou|te9drou|tqadrou|t3awnou|t3awnouni)\b|"
    r"\b(?:chno|chnou|chniya|wach)\b.{0,25}\b(?:services?|t9drou|te9drou|t3awnou|3andkom)\b|"
    r"\b(?:services?|khadamat)\b.{0,20}\b(?:3andkom|ta3kom|proposez|tdirou)\b"
)
_MISSION_ARABIC = re.compile(r"(?:شكون\s+(?:نتوما|انتم)|واش\s+تديرو|وش\s+تديرو|ماذا\s+تقدمون|ما هي\s+خدمات|الخدمات|خدماتكم|تساعدون|تساعدني|الوكالة)")
_PROCESS_LATIN = re.compile(
    r"\b(?:kifach|kifech)\b.{0,45}\b(?:rdw|accompagnement|dossier|processus|procedure|demarches?)\b|"
    r"\b(?:kifach|kifech)\s+(?:temchi|timchi|tsra)\b|"
    r"\b(?:procedure|processus|demarches?)\b.{0,25}\b(?:temchi|timchi|dirou|tdirou)\b"
)
_PROCESS_ARABIC = re.compile(r"كيفاش.{0,30}(?:المرافقة|الملف|الإجراءات|اجراءات)")
_DOCUMENTS_LATIN = re.compile(
    r"\b(?:wra9|wara9|papiers?|documents?|dossier|cv|traduction|traduire|tarjama|terjem[a-z]*)\b"
)
_DOCUMENTS_ARABIC = re.compile(r"(?:وراق|أوراق|وثائق|الوثائق|ترجمة|الترجمة|الملف|سيرة ذاتية)")
_LANGUAGE_LATIN = re.compile(r"\b(?:lugha|lougha|allemand|deutsch|niveau)\b")
_LANGUAGE_ARABIC = re.compile(r"(?:لغة|ألمانية|الالمانية|المستوى)")
_DARIJA_SIGNAL = re.compile(
    r"\b(?:nheb|n7eb|hab|bghit|nestafser|nestaqsi|na3ref|n3ref|ma3loumat|maloumat|"
    r"wach|weche|wech|chkon|chkoun|chno|chnou|chniya|chya|kifach|kifech|chhal|ch7al|9adech|win|3lach|ida|"
    r"nqra|ne9ra|na9ra|n9ra|n9ari|9raya|qraya|nkhdem|nekhdem|khedma|khadma|wra9|wara9|lugha|lougha|"
    r"tdirou|dirou|takhdmou|t9drou|te9drou|tqadrou|t3awnou|t3awnouni|3andkom|ta3kom|"
    r"temchi|timchi|tsra|khadamat|tarjama|souma|ta3)\b|[\u0600-\u06ff]"
)


def is_information_request(text: str) -> bool:
    q = normalize(text)
    return bool(_INFO_LATIN.search(q) or _INFO_ARABIC.search(q))


def is_question(text: str) -> bool:
    q = normalize(text)
    return bool(_QUESTION_LATIN.search(q) or _QUESTION_ARABIC.search(q) or is_information_request(text))


def has_darija_signal(text: str) -> bool:
    """Indique une formulation algérienne probable sans traduire ni conserver le message."""
    return bool(_DARIJA_SIGNAL.search(normalize(text)))


def project_tracks(text: str) -> list[str]:
    q = normalize(text)
    tracks: list[str] = []
    if _STUDIES_LATIN.search(q) or _STUDIES_ARABIC.search(q):
        tracks.append("etudes")
    if _AUSBILDUNG.search(q):
        tracks.append("ausbildung")
    if _WORK_LATIN.search(q) or _WORK_ARABIC.search(q):
        tracks.append("emploi")
    return tracks


def topic(text: str) -> str | None:
    """Retourne uniquement un sujet déjà présent dans le corpus public RDW."""
    q = normalize(text)
    if not _DARIJA_SIGNAL.search(q):
        return None
    if _PRICE_LATIN.search(q) or _PRICE_ARABIC.search(q):
        return "tarifs_langue" if (_LANGUAGE_LATIN.search(q) or _LANGUAGE_ARABIC.search(q)) else "tarifs"
    if _DOCUMENTS_LATIN.search(q) or _DOCUMENTS_ARABIC.search(q):
        return "cv" if re.search(r"\bcv\b|سيرة ذاتية", q) else "documents"
    if _PROCESS_LATIN.search(q) or _PROCESS_ARABIC.search(q):
        return "processus"
    if _LANGUAGE_LATIN.search(q) or _LANGUAGE_ARABIC.search(q):
        return "langue"
    tracks = project_tracks(text)
    if len(tracks) == 1:
        return tracks[0]
    if _MISSION_LATIN.search(q) or _MISSION_ARABIC.search(q) or is_information_request(text):
        return "mission"
    return None
