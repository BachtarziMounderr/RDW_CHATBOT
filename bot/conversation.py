"""Accueil et qualification progressive. Les faits personnels restent temporaires avant accord."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from .qa import PrivateQAService, canonical_words
from .rag import Corpus, normalize
from .service import Reply, SENSITIVE_INPUT, TRACKS
from .llm import validate_interpretation
from .gemini_dialogue import safe_facts
from .knowledge_store import question_key
from .darija import (is_information_request as is_darija_information,
                     is_question as is_darija_question, project_tracks as darija_project_tracks)
from .sales_funnel import AGENCY_INFO, CONSULTATION, PROCEDURE_INFO, SELF_GUIDED, detect_sales_intent


CONSENT_VERSION = "rdw_contact_v5_2026-10-16"
CONSENT_TEXT = (Path(__file__).parent / "data" / f"consent_{CONSENT_VERSION}.txt").read_text(encoding="utf-8").strip()
YES = {"oui", "ouais", "d'accord", "ok", "exact", "c'est correct", "je confirme", "نعم", "صحيح", "أوافق", "اوافق"}
NO = {"non", "pas maintenant", "je refuse", "non merci", "لا", "ليس الآن", "ارفض", "أرفض"}
SKIP = {"je ne sais pas", "je sais pas", "aucune idee", "pas encore", "passer", "je passe", "a definir", "لا أعرف", "لا اعرف"}
GREETING = re.compile(r"^(bonjour|bonsoir|salut|hello|coucou|slm|salam|slt|bjr|alo|allô)[! .]*$", re.I)
THANKS = re.compile(r"^(merci|merci beaucoup|super merci|parfait merci)[! .]*$", re.I)
FRUSTRATION = re.compile(
    r"\b(?:tu|vous)\s+ne\s+r[eé]ponds?\s+pas|\b(?:ca|cela)\s+ne\s+r[eé]pond\s+pas|"
    r"\bje\s+n['’ ]?ai\s+pas\s+(?:eu|recu|reçu)\s+(?:de\s+)?r[eé]ponse\b", re.I)
QUESTION_PERMISSION = re.compile(
    r"\b(?:j['’ ]?ai|jai|j'aurais|jaurais)\s+(?:des?|quelques?)\s+questions?\b|"
    r"\b(?:je\s+peux|puis.je|est.ce\s+que\s+je\s+peux|possible\s+de|je\s+voudrais|je\s+veux)\b"
    r".{0,35}\b(?:poser|demander|faire)\b.{0,15}\b(?:questions?|demande)\b|"
    r"\b(?:n9der|nqder|nakder|ne9der)\b.{0,20}\b(?:nse9si|nsaqsi|nsaksi|nesqsi)\b|"
    r"\b(?:3andi|andi)\b.{0,12}\b(?:soual|so2al|as2ila)\b",
    re.I,
)
QUESTION_PERMISSION_AR = re.compile(
    r"(?:عندي\s+(?:سؤال|اسئلة|أسئلة)|هل\s+يمكنني\s+(?:أن\s+)?(?:أسأل|اسأل)|"
    r"(?:نقدر|اقدر|أقدر)\s+(?:نسقسي|نسأل|نسال))"
)
PERSONAL_PROJECT = re.compile(r"\b(?:je veux|je souhaite|j'aimerais|je voudrais|mon projet|je cherche|j'envisage|je pense a|je suis interesse|j'ai un|j'ai une)\b")
READY_ACTION = re.compile(
    r"\b(?:je suis pret|je suis prete|pret a payer|prete a payer|je veux (?:prendre|commencer)|"
    r"je souhaite (?:prendre|commencer)|avancer avec (?:rdw|vous|l.agence))\b", re.I)
HUMAN = re.compile(r"\b(?:parler|echanger|contacter|joindre)\b.*\b(?:humain|conseiller|commercial|personne)\b")
CORRECTION = re.compile(r"\b(?:je corrige|correction|en fait|plutot|je me suis trompe|non c'est)\b")
QUESTION_START = re.compile(r"^(?:est.ce que|comment|quels?|quelles?|que|quoi|qui|ou|quand|combien|pourquoi|pouvez.vous|faut.il|c.est quoi|avez.vous)\b")
QUESTION_INVERSION = re.compile(r"\b(?:peut|peuvent|fait|aide|accompagne|propose|offre|avez|etes|est|sont|dois|faut)[ -](?:il|elle|on|vous|ils|elles)\b")
INFORMATION_INTENT = re.compile(
    r"\b(?:renseignements?|informations?|me renseigner|en savoir plus|connaitre|connaître)\b|"
    r"\b(?:renseignez|presentez|présentez|parlez)[ -]?(?:moi|nous)\b|"
    r"\b(?:comprendre|savoir)\s+ce\s+que\b", re.I)
INFORMATION_FRAGMENT = re.compile(
    r"\b(?:prix|tarifs?|cout|souma|ch7al|chhal|services?|consultations?|tradu\w*|"
    r"documents?|dossiers?|cv|visa|admission|garanties?|rembours\w*|virtulingo|"
    r"accompagnement|demarches?|procedure|aide[rz]?|maider|t3awn\w*|"
    r"lettre de motivation|cours d.allemand)\b", re.I)
FOLLOW_UP = re.compile(
    r"^(?:et\b|donc\b|sinon\b|aussi\b|pour\b|concernant\b|a propos\b|"
    r"qu.en est.il\b|ca\b|cela\b|combien\b|comment\b|pourquoi\b)", re.I)
FOLLOW_UP_PIVOT = re.compile(
    r"\b(?:prix|tarif|cout|visa|admission|cv|dossier|documents?|langue|allemand|"
    r"ausbildung|emploi|etudes?|consultations?|traduction|lettre|installation)\b", re.I)
TRACK_LABELS = {"etudes": "études", "ausbildung": "Ausbildung", "emploi": "emploi", "volontariat": "volontariat"}
SUPPORTED_TRACKS = {"etudes", "ausbildung", "emploi"}
PREMIUM_FORM_STAGES = {
    "premium_last_name", "premium_first_name", "premium_age", "premium_degree",
    "premium_field", "premium_german", "premium_english", "premium_experience",
}


def is_question_permission(text: str) -> bool:
    return bool(QUESTION_PERMISSION.search(normalize(text)) or QUESTION_PERMISSION_AR.search(text))

PROMPTS = {
    "etudes": [
        ("desired_degree", "Quelle formation souhaitez-vous suivre en Allemagne ?"),
        ("desired_field", "Dans quel domaine souhaitez-vous étudier ?"),
        ("current_degree", "Quel est votre dernier diplôme obtenu ?"),
        ("german_level", "Quel est votre niveau actuel en allemand ? Vous pouvez dire « je ne sais pas »."),
        ("timeline", "À quelle rentrée pensez-vous ?"),
        ("current_field", "Dans quel domaine avez-vous étudié ?"),
        ("country", "Dans quel pays résidez-vous actuellement ?"),
    ],
    "ausbildung": [
        ("school_level", "Quel est votre niveau scolaire actuel ?"),
        ("desired_field", "Quel métier ou domaine d'Ausbildung vous intéresse ?"),
        ("german_level", "Quel est votre niveau actuel en allemand ?"),
        ("timeline", "Quand souhaiteriez-vous commencer ?"),
        ("country", "Dans quel pays résidez-vous actuellement ?"),
    ],
    "emploi": [
        ("current_degree", "Quelle qualification ou formation avez-vous ?"),
        ("desired_field", "Quel métier recherchez-vous ?"),
        ("experience", "Quelle expérience pertinente avez-vous dans ce métier ?"),
        ("german_level", "Quel est votre niveau actuel en allemand ?"),
        ("timeline", "À partir de quand seriez-vous disponible ?"),
        ("country", "Dans quel pays résidez-vous actuellement ?"),
    ],
    "volontariat": [
        ("desired_field", "Quel domaine de volontariat vous intéresse ?"),
        ("german_level", "Quel est votre niveau actuel en allemand ?"),
        ("timeline", "À quelle période souhaiteriez-vous partir ?"),
        ("country", "Dans quel pays résidez-vous actuellement ?"),
    ],
}

PROMPTS_AR = {
    "etudes": [
        ("desired_degree", "ما هو التكوين أو الشهادة التي تريد دراستها في ألمانيا؟"),
        ("desired_field", "في أي تخصص تريد الدراسة؟"),
        ("current_degree", "ما هي آخر شهادة تحصلت عليها؟"),
        ("german_level", "ما هو مستواك الحالي في اللغة الألمانية؟ يمكنك أن تقول: لا أعرف."),
        ("timeline", "متى تريد بدء الدراسة؟"),
        ("current_field", "في أي تخصص درست؟"),
        ("country", "في أي بلد تقيم حاليا؟"),
    ],
    "ausbildung": [
        ("school_level", "ما هو مستواك الدراسي الحالي؟"),
        ("desired_field", "ما هي مهنة أو تخصص Ausbildung الذي يهمك؟"),
        ("german_level", "ما هو مستواك الحالي في اللغة الألمانية؟"),
        ("timeline", "متى تريد أن تبدأ؟"),
        ("country", "في أي بلد تقيم حاليا؟"),
    ],
    "emploi": [
        ("current_degree", "ما هو مؤهلك أو تكوينك؟"),
        ("desired_field", "ما هي المهنة التي تبحث عنها؟"),
        ("experience", "ما هي خبرتك في هذه المهنة؟"),
        ("german_level", "ما هو مستواك الحالي في اللغة الألمانية؟"),
        ("timeline", "ابتداء من متى يمكنك العمل؟"),
        ("country", "في أي بلد تقيم حاليا؟"),
    ],
}

EBOOK_PATH = Path(__file__).parent / "assets" / "Ta-route-vers-l-Allemagne-RDW.pdf"

ARABIC_DOCUMENTARY_ANSWERS = {
    "mission": "ترافق RDW المشاريع نحو ألمانيا بالتعاون مع Virtulingo، وهي مدرسة ألمانية عبر الإنترنت. يدرس الفريق الملف والإجراءات المناسبة للمشروع.",
    "filieres": "يركز دليل RDW على ثلاثة مسارات: الدراسة الجامعية، Ausbildung والعمل. ولا يصف عرضا خاصا بالتطوع.",
    "etudes": "بالنسبة للدراسة، يمكن لوكالتنا تحليل ملفكم، إعداد الوثائق واستهداف المؤسسات. يجب التحقق من شروط القبول حسب حالتكم.",
    "ausbildung": "بالنسبة إلى Ausbildung، يمكن لوكالتنا المساعدة في تحليل الملف، السيرة الذاتية، الترشحات والتحضير للمقابلات. وتبقى النتيجة مرتبطة بالمشغل والسلطات.",
    "emploi": "بالنسبة للعمل، يمكن لوكالتنا دراسة ملفكم، إعداد ترشحات مخصصة والتحضير للمقابلات. لا يمكن ضمان التوظيف.",
    "processus": "نبدأ بدراسة ملفكم ومشروعكم. حسب الخدمة المختارة، يمكننا المساعدة في الوثائق والترشحات والمقابلات وبعض الإجراءات. يتم تأكيد التفاصيل في عرض السعر.",
    "langue": "تقترح Virtulingo دروسا في الألمانية عبر الإنترنت من A1 إلى B2 حسب الدليل. المستوى المطلوب يتغير حسب المشروع ويجب التحقق منه لكل ترشح.",
    "cv": "يجب أن تعرض السيرة الذاتية بوضوح تكوينكم وخبراتكم القابلة للتحقق واللغات. ويمكن لوكالتنا تكييفها مع الترشح.",
    "lettres": "يجب أن تشرح رسالة التحفيز المنصب المستهدف وعلاقته بمهاراتكم وتوفركم. ويوصي الدليل بتكييفها مع كل ترشح.",
    "documents": "يمكننا مرافقة إعداد الملف، مثل إثباتات التكوين واللغة والترجمة والتصديق والتحقق من الشهادات عند الحاجة. تختلف القائمة الدقيقة حسب المسار والجهة المختصة.",
    "consultation": "يصف الدليل استشارة عبر مكالمة فيديو أو مكالمة عادية لدراسة المشروع، ثم عرض سعر حسب الخدمات المطلوبة. لا يمكنني تأكيد موعد أو مدة اتصال.",
    "tarifs": "يشير دليل 2026 إلى 2 000 دج للاستشارة، وتُخصم من خدمة RDW مختارة، ثم يقدم عرض سعر حسب الخدمات. يجب تأكيد الأسعار والشروط الحالية مع RDW.",
    "tarifs_langue": "يعرض دليل 2026 سعرا فرديا قدره 105 000 دج وباقة مجتمع Virtulingo بسعر 89 000 دج لقراء الدليل. يجب تأكيد الأسعار والشروط قبل التسجيل.",
    "garanties": "يذكر الدليل ضمانات بصيغ مختلفة بين الصفحات، لذلك لا يمكنني تأكيد شروطها. اطلبوا عقد RDW وعرض السعر.",
    "installation": "يذكر الدليل متابعة عند الوصول في بعض عروض RDW. وتتحدد الإجراءات المشمولة حسب الخدمة وعرض السعر.",
    "limites": "يحتوي الدليل على أرقام مختلفة حول التمويل ولا يكفي لتأكيد شرط تأشيرة أو قبول. تحققوا من المؤسسة أو الجهة المختصة.",
}


@dataclass
class Session:
    language: str | None = None
    tracks: list[str] = field(default_factory=list)
    primary: str | None = None
    facts: dict[str, dict] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    open_questions: list[str] = field(default_factory=list)
    stage: str = "idle"
    current_slot: str | None = None
    last_message_key: str | None = None
    repeat_count: int = 0
    stalled_count: int = 0
    asked: int = 0
    last_name: str | None = None
    first_name: str | None = None
    contact_method: str | None = None
    contact_detail: str | None = None
    contact_confirmed: bool = False
    last_source: str | None = None
    last_topic: str | None = None
    lead_source: str = "direct"
    funnel_route: str = "undetermined"
    offer_status: str = "exploring"
    information_turns: int = 0
    private_channel_presented: bool = False
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def put(self, key: str, value: str, status: str = "declared"):
        self.facts[key] = {"value": value.strip(), "status": status}
        self.skipped.discard(key)

    def value(self, key: str) -> str | None:
        item = self.facts.get(key)
        return item["value"] if item and item["status"] == "declared" else None


def _clean(value: str) -> str:
    return re.split(r"\s+(?:et|mais|pour|afin|en allemagne|puis|j['’ ]?ai|jai)\b|[,;.!?]", value, maxsplit=1, flags=re.I)[0].strip(" .,:;!")[:80]


def normalize_contact_phone(text: str) -> str | None:
    """Convertit un mobile algérien local en E.164 et accepte les formats internationaux."""
    phone = re.sub(r"[\s().-]", "", text.strip())
    if re.fullmatch(r"0[567][0-9]{8}", phone):
        return "+213" + phone[1:]
    if re.fullmatch(r"[567][0-9]{8}", phone):
        return "+213" + phone
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    elif re.fullmatch(r"213[567][0-9]{8}", phone):
        phone = "+" + phone
    return phone if re.fullmatch(r"\+[1-9][0-9]{7,14}", phone) else None


def extract_declared(text: str) -> tuple[list[str], dict[str, str], list[str]]:
    """Extraction conservatrice de déclarations explicites, sans compléter les inconnues."""
    q = normalize(text)
    words = canonical_words(text)
    tracks = [track for track in ("etudes", "ausbildung", "emploi", "volontariat") if track in words]
    tracks = list(dict.fromkeys(tracks + darija_project_tracks(text)))
    if (re.search(r"\b(?:universite|faculte|etudier)\b", q) or
        re.search(r"\b(?:veux|souhaite|voudrais|aimerais|poursuivre|faire)\b[^.!?]{0,40}\b(?:master|licence|bachelor|doctorat)\b", q)) and "etudes" not in tracks:
        tracks.insert(0, "etudes")
    if re.search(r"\b(?:fsj|bfd|esc)\b", q) and "volontariat" not in tracks:
        tracks.append("volontariat")
    facts = {}
    hypotheses = []
    degree = re.search(r"\b(?:j['’ ]?ai|titulaire d['’ ]?|dipl[oô]m[eé] d['’ ]?)\s*(?:d[eé]j[aà]\s*)?(?:un[e]?\s+)?(master|licence|bac|doctorat|bachelor)\b(?:\s+en\s+([\wÀ-ÿ-]+))?", text, re.I)
    if degree:
        facts["current_degree"] = degree.group(1).lower()
        if degree.group(2):
            facts["current_field"] = _clean(degree.group(2))
    no_degree = re.search(
        r"\b(?:je\s+n(?:['’ ]?ai)|j['’ ]?ai)\s+(?:encore\s+)?"
        r"(?:aucun\s+diplome|pas\s+de\s+diplome)\b|"
        r"\b(?:ma3andich|maandich)\s+(?:hata\s+)?diplome\b",
        q,
    )
    if no_degree:
        facts["current_degree"] = "aucun diplôme obtenu"
    desired = re.search(r"\b(?:veux|souhaite|voudrais|aimerais|envisage|poursuivre|faire|suivre|integrer|intégrer)\b[^.!?]{0,45}?\b(master|licence|bachelor|doctorat)\b(?:\s+en\s+([\wÀ-ÿ-]+))?", text, re.I)
    if desired:
        facts["desired_degree"] = desired.group(1).lower()
        if desired.group(2):
            value = _clean(desired.group(2))
            facts["study_language" if normalize(value) in {"anglais", "allemand"} else "desired_field"] = value
        if "etudes" not in tracks:
            tracks.insert(0, "etudes")
    if (not facts.get("desired_degree")
            and re.search(r"\b(?:j['’ ]?ai besoin|jai besoin|je vise|mon projet)\b", q)):
        contextual_degree = re.search(
            r"\b(master|licence|bachelor|doctorat)\b(?:\s+(?:en\s+)?([\wÀ-ÿ-]+(?:\s+[\wÀ-ÿ-]+)?))?", text, re.I)
        if contextual_degree:
            facts["desired_degree"] = contextual_degree.group(1).lower()
            if contextual_degree.group(2):
                field_value = _clean(contextual_degree.group(2))
                if field_value:
                    facts["desired_field"] = field_value
            if "etudes" not in tracks:
                tracks.insert(0, "etudes")
    if not facts.get("desired_degree"):
        darija_degree = re.search(
            r"\b(?:nheb|n7eb|hab|bghit|nqra|ne9ra|na9ra)\b[^.!?]{0,35}?"
            r"\b(master|licence|bachelor|doctorat)\b", q)
        if darija_degree:
            facts["desired_degree"] = darija_degree.group(1).lower()
            if "etudes" not in tracks:
                tracks.insert(0, "etudes")
        elif re.search(r"(?:حاب|نحب|بغيت|نقرا).{0,30}ماستر", text):
            facts["desired_degree"] = "master"
            if "etudes" not in tracks:
                tracks.insert(0, "etudes")
    field = re.search(r"\b(?:ausbildung|formation|emploi|poste|travail|volontariat)\s+(?:en|dans|comme|de)\s+([\wÀ-ÿ-]+(?:\s+[\wÀ-ÿ-]+)?)", text, re.I)
    if field and not facts.get("desired_field"):
        facts["desired_field"] = _clean(field.group(1))
    goal = re.search(r"\b(?:veux|souhaite|voudrais|aimerais)\s+(?:devenir|travailler comme|exercer comme)\s+([\wÀ-ÿ-]+(?:\s+[\wÀ-ÿ-]+){0,2})", text, re.I)
    if goal and not facts.get("desired_field"):
        facts["desired_field"] = _clean(goal.group(1))
    study_language = re.search(r"\b(?:etudes?|programme|formation)\s+(?:en|enseignes?\s+en)\s+(anglais|allemand)\b", q)
    if study_language:
        facts["study_language"] = normalize(study_language.group(1))
    german = re.search(r"\b(?:allemand\s*(?:niveau\s*)?|niveau\s+(?:en\s+)?allemand\s*)(A1|A2|B1|B2|C1|C2)\b|\b(A1|A2|B1|B2|C1|C2)\s+en\s+allemand\b", text, re.I)
    if german:
        facts["german_level"] = (german.group(1) or german.group(2)).upper()
    elif re.search(r"\b(?:ne parle pas|aucun niveau en)\s+(?:l['’])?allemand\b", q):
        facts["german_level"] = "aucun niveau déclaré"
    english = re.search(r"\b(?:anglais\s*(?:niveau\s*)?|niveau\s+(?:en\s+)?anglais\s*)(A1|A2|B1|B2|C1|C2)\b|\b(A1|A2|B1|B2|C1|C2)\s+en\s+anglais\b", text, re.I)
    if english:
        facts["english_level"] = (english.group(1) or english.group(2)).upper()
    country = re.search(r"\b(?:j['’ ]?habite|je vis|je r[eé]side)\s+(?:en|au|aux)\s+([\wÀ-ÿ-]+)", text, re.I)
    if country:
        facts["country"] = _clean(country.group(1))
    timeline = re.search(r"\b(?:rentr[eé]e|janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre|d[eè]s|[aà] partir de)\s+([\wÀ-ÿ-]+(?:\s+\d{4})?)", text, re.I)
    if timeline:
        facts["timeline"] = _clean(timeline.group(0))
    experience = re.search(r"\b(\d{1,2}\s+ans?\s+d['’ ]?exp[eé]rience)\b", text, re.I)
    if experience:
        facts["experience"] = experience.group(1)
    if re.search(r"\b(?:peut.et\w*|je pense|j'hesite|j’h[eé]site|pas sur)\b", q):
        hypotheses = tracks[:]
        tracks = []
    return tracks, facts, hypotheses


class ConversationService:
    def __init__(self, store, corpus: Corpus | None = None, interpreter=None, clock=None,
                 composer=None, review_store=None, admin_user_ids: frozenset[int] = frozenset(),
                 private_channel_price_dzd: int = 1000,
                 payment_proof_telegram: str = "0541501832",
                 baridimob_payment_details: str = "", ccp_payment_details: str = "",
                 ccp_account_holder_name: str = "",
                 debug_source_labels: bool = False):
        self.store = store
        self.corpus = corpus or Corpus()
        self.knowledge = PrivateQAService(self.corpus)
        self.interpreter = interpreter
        self.composer = composer
        self.review_store = review_store
        self.admin_user_ids = frozenset(admin_user_ids)
        self.private_channel_price_dzd = private_channel_price_dzd
        self.payment_proof_telegram = payment_proof_telegram
        self.baridimob_payment_details = baridimob_payment_details
        self.ccp_payment_details = ccp_payment_details
        self.ccp_account_holder_name = ccp_account_holder_name
        self.debug_source_labels = debug_source_labels
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sessions: dict[int, Session] = {}
        self.recent = deque(maxlen=1024)
        self.seen = set()
        self.rate: dict[int, tuple[datetime, int]] = {}

    def handle(self, user_id: int, update_id: int, value: str, callback: bool = False) -> Reply | None:
        if user_id not in self.sessions and self.review_store and hasattr(self.review_store, "load_funnel_state"):
            try:
                restored = self.review_store.load_funnel_state(user_id)
                if restored:
                    allowed_stages = {"idle", "paused", "language_choice", "ebook_wait", "premium_choice",
                                      "premium_project", "private_channel_offer", "vip_payment"}
                    if restored.get("stage") in allowed_stages:
                        self.sessions[user_id] = Session(**restored)
            except Exception:
                pass
        before = self.sessions.get(user_id)
        previous_stage = before.stage if before else "idle"
        previous_slot = before.current_slot if before else None
        previous_slot_value = before.value(previous_slot) if before and previous_slot else None
        previous_topic = before.last_topic if before else None
        key = question_key(value) if value and not callback else None
        repeated = bool(before and key and key == before.last_message_key)
        reply = self._handle_local(user_id, update_id, value, callback)
        session = self.sessions.get(user_id)
        if session and self.review_store and hasattr(self.review_store, "save_funnel_state"):
            try:
                persistable_stages = {"idle", "paused", "language_choice", "ebook_wait", "premium_choice",
                                      "premium_project", "private_channel_offer", "vip_payment"}
                self.review_store.save_funnel_state(user_id, {
                    "language": session.language,
                    "stage": session.stage if session.stage in persistable_stages else "idle",
                    "lead_source": session.lead_source,
                    "funnel_route": session.funnel_route,
                    "offer_status": session.offer_status,
                    "private_channel_presented": session.private_channel_presented,
                })
            except Exception:
                pass
        if session and key and not value.strip().startswith("/"):
            session.repeat_count = session.repeat_count + 1 if repeated else 1
            session.last_message_key = key
        if self.review_store and reply and session and not callback and not value.strip().startswith("/"):
            stalled_this_turn = False
            topic = self.knowledge._topic(value)
            unknown = "Je n'ai pas de réponse vérifiée" in reply.text
            if unknown and self.review_store.find_answer(value) is None:
                normalized = normalize(value)
                off_topic = bool(re.search(r"\b(?:meteo|impot|billet|transport)\b|quel temps fait|quelle temperature", normalized))
                looping = session.repeat_count >= 2
                category = "faq_candidate" if off_topic or looping else "needs_answer"
                context = {"parcours": session.tracks[:2], "étape": session.current_slot or session.stage,
                           "faits_déclarés": safe_facts(session),
                           "origine_admin": user_id in self.admin_user_ids}
                try:
                    self.review_store.record_question(value, context, category)
                except Exception:
                    reply = Reply(reply.text + "\n\nLa question n'a pas pu être enregistrée pour RDW.", reply.buttons)
                session.stalled_count += 1
                stalled_this_turn = True
            elif repeated and not session.primary:
                session.stalled_count += 1
                stalled_this_turn = True
            elif session.primary:
                session.stalled_count = 0
            if stalled_this_turn and session.stalled_count >= 2 and not reply.buttons and " /faq" not in reply.text:
                reply = Reply(reply.text + "\n\nPour explorer les questions fréquentes, utilisez /faq.", reply.buttons)
        buttons_without_question = bool(reply and reply.buttons and not self._looks_like_question(value))
        if (not self.composer or not reply or callback or value.strip().startswith("/") or buttons_without_question
                or is_question_permission(value)
                or THANKS.match(value.strip()) or FRUSTRATION.search(value)):
            return self._with_source_label(reply, "RAG")
        private_stages = {"last_name", "first_name", "contact_detail", "contact_confirm", "consent"} | PREMIUM_FORM_STAGES
        if (not session or ((previous_stage in private_stages or session.stage in private_stages)
                            and not self._looks_like_question(value))):
            return self._with_source_label(reply, "RAG")
        if (session.last_source and session.last_source.startswith("RDW:réponse-validée:")
                and self.review_store and (approved := self.review_store.find_answer(value))
                and approved["answer"] in reply.text):
            return self._with_source_label(reply, "RAG")
        last_paragraph = reply.text.split("\n\n")[-1]
        match = re.search(r"([^\n.!?]*\?)(?:[ \t]*[^?\n]*)?$", last_paragraph)
        next_question = match.group(0).strip() if match else ""
        topic = self.knowledge._topic(value)
        private_offer_due = self._should_suggest_private_channel(session, topic, value, repeated)
        local_topic = topic
        if (previous_topic in self.knowledge.by_id
                and self._looks_like_question(value)
                and (FOLLOW_UP.search(normalize(value)) or len(normalize(value).split()) <= 6)
                and not FOLLOW_UP_PIVOT.search(normalize(value))):
            topic = previous_topic
        if topic != local_topic and topic in self.knowledge.by_id:
            corrected = self._answer_question(session, value, topic)
            reply = Reply(corrected + ("\n\n" + next_question if next_question else ""), reply.buttons)
        # La politique commerciale actuelle remplace l'ancienne consultation payante du guide.
        # Elle est rendue localement afin qu'aucun modèle ne puisse réintroduire l'ancien tarif.
        if topic == "tarifs":
            return self._with_source_label(reply, "RAG")
        if topic == "cv_documents":
            passages = [self.knowledge.by_id[key] for key in ("cv", "documents")]
        elif topic in self.knowledge.by_id:
            passages = [self.knowledge.by_id[topic]]
        elif not self._looks_like_question(value) and session.primary in self.knowledge.by_id:
            passages = [self.knowledge.by_id[session.primary]]
        elif not self._looks_like_question(value) and not session.primary:
            passages = [self.knowledge.by_id["mission"]]
        else:
            # Pour une reformulation inconnue, Groq reçoit un catalogue compact de tout le corpus public.
            passages = list(self.corpus.passages)
        catalogue_mode = topic in {None, "guide_overview"} and self._looks_like_question(value)
        if topic in self.knowledge.by_id:
            session.last_topic = topic
        acknowledgement_field = None
        if (previous_slot and not self._looks_like_question(value)
                and session.current_slot != previous_slot
                and session.value(previous_slot)
                and session.value(previous_slot) != previous_slot_value):
            acknowledgement_field = previous_slot
        try:
            orientation = self._orientation_context(session, topic, suggest_private_channel=private_offer_due)
            generated = self.composer.compose(user_id=user_id, message=value, session=session,
                                               passages=passages,
                                               acknowledgement_field=acknowledgement_field,
                                               catalogue_mode=catalogue_mode,
                                               orientation=orientation,
                                               may_ask_question=not bool(next_question))
        except Exception:
            if private_offer_due:
                session.private_channel_presented = True
                reply = Reply(reply.text + "\n\n" + self._private_channel_teaser(session), reply.buttons)
            return self._with_source_label(reply, "RAG")
        if not generated:
            # Les détails fournisseur restent dans le statut local. Le client reçoit
            # directement la réponse documentaire validée, sans diagnostic technique.
            if private_offer_due:
                session.private_channel_presented = True
                reply = Reply(reply.text + "\n\n" + self._private_channel_teaser(session), reply.buttons)
            return self._with_source_label(reply, "RAG")
        if hasattr(self.composer, "last_passage_ids"):
            used_ids = set(self.composer.last_passage_ids or ())
            source = " ".join(p["citation"] for p in passages if p["id"] in used_ids)
        else:
            source = " ".join(p["citation"] for p in passages)
        session.last_source = source or session.last_source
        if getattr(self.composer, "last_passage_ids", None):
            session.last_topic = self.composer.last_passage_ids[0]
        if private_offer_due:
            session.private_channel_presented = True
            normalized_generated = normalize(generated)
            required_offer_details = ("canal", "live", "1000", "vie", "unique", "/canal")
            if not all(item in normalized_generated for item in required_offer_details):
                generated += "\n\n" + self._private_channel_teaser(session)
        if session.stage == "premium_choice":
            body = generated + "\n\n" + self._premium_pitch(session).text
        elif session.stage == "premium_project":
            body = generated + "\n\n" + self._premium_start(session).text
        elif session.stage == "private_channel_offer":
            body = generated + "\n\n" + self._private_channel_offer(session)
        elif session.stage == "vip_payment":
            body = generated + "\n\n" + self._payment_instructions(session)
        else:
            body = generated + ("\n\n" + next_question if next_question else "")
        return self._with_source_label(Reply(body, reply.buttons), getattr(self.composer, "provider_label", "IA"))

    def receive_payment_receipt(self, user_id: int, update_id: int, *, media_type: str,
                                file_id: str, file_unique_id: str,
                                source_chat_id: int, source_message_id: int) -> Reply:
        """Redirige les nouveaux reçus vers le contact RDW chargé du contrôle manuel."""
        if user_id not in self.sessions and self.review_store and hasattr(self.review_store, "load_funnel_state"):
            restored = self.review_store.load_funnel_state(user_id)
            if restored:
                self.sessions[user_id] = Session(**restored)
        session = self.sessions.get(user_id)
        contact = self.payment_proof_telegram or "le contact RDW indiqué dans /canal"
        if not session:
            return Reply(
                f"Le bot ne collecte pas les preuves de paiement. Envoyez la photo ou le PDF du reçu "
                f"au compte Telegram associé au numéro {contact}. Après vérification, un administrateur "
                "vous ajoutera manuellement au canal VIP."
            )
        return Reply(self._t(
            session,
            f"Le bot ne collecte pas les preuves de paiement. Envoyez la photo ou le PDF du reçu "
            f"au compte Telegram associé au numéro {contact}. Après vérification, un administrateur "
            "vous ajoutera manuellement au canal VIP.",
            f"لا يجمع البوت وصولات الدفع. أرسلوا صورة الوصل أو ملف PDF إلى حساب Telegram المرتبط بالرقم "
            f"{contact}. بعد التحقق، سيضيفكم المسؤول يدويا إلى قناة VIP.",
        ))

    def _with_source_label(self, reply: Reply | None, source: str) -> Reply | None:
        if not reply or not self.debug_source_labels:
            return reply
        return Reply(f"Réponse {source} :\n{reply.text}", reply.buttons, reply.document_path, reply.payment_id)

    def _should_suggest_private_channel(self, session: Session, topic: str | None,
                                        text: str, repeated: bool) -> bool:
        informative_topics = {"etudes", "ausbildung", "emploi", "processus", "langue", "cv",
                              "lettres", "documents", "installation", "limites", "garanties"}
        if (session.private_channel_presented or session.funnel_route == "consultation"
                or session.stage in {"private_channel_offer", "offer_contact", "last_name", "first_name",
                                     "contact_detail", "contact_confirm", "consent"}
                or not self._looks_like_question(text)):
            return False
        if topic in informative_topics and not repeated:
            session.information_turns += 1
        return session.information_turns >= 2

    def _orientation_context(self, session: Session, topic: str | None,
                             suggest_private_channel: bool = False) -> dict[str, str]:
        if session.funnel_route == "private_channel" or suggest_private_channel:
            price = f"{self.private_channel_price_dzd:,}".replace(",", " ")
            return {
                "goal": "private_channel",
                "when": ("La personne cherche plusieurs informations pratiques sur les démarches, ou dit explicitement "
                         "vouloir avancer seule ou sans accompagnement d'agence."),
                "approved_facts": (f"Notre canal Telegram privé propose des informations complémentaires sur les démarches et des lives. "
                                   f"Son accès coûte {price} DA en paiement unique et reste valable à vie. "
                                   "Pendant ce test, l'équipe confirme manuellement les modalités de paiement et l'accès ; "
                                   "le bot ne valide aucun paiement."),
                "next_action": ("Après avoir répondu, présenter calmement le canal privé. Inviter la personne à écrire /canal "
                                "pour recevoir les modalités, sans exercer de pression."),
            }
        if session.funnel_route == "consultation" or topic in {"consultation", "tarifs", "tarifs_langue"}:
            return {
                "goal": "agency_consultation",
                "when": "La personne montre un intérêt pour les prix, la consultation ou un accompagnement par notre agence.",
                "approved_facts": ("L'évaluation Premium sert à comparer le profil avec les possibilités disponibles. "
                                   "Le bot ne demande aucun paiement de consultation ; les prestations Premium font ensuite l'objet d'un contrat et d'un devis."),
                "next_action": "Après avoir répondu, proposer le formulaire Premium seulement si la personne confirme vouloir démarrer cette voie.",
            }
        return {
            "goal": "ebook_information",
            "when": "La personne cherche d'abord à comprendre RDW, nos services ou les démarches du guide.",
            "approved_facts": "Nous répondons à partir des passages du guide RDW et aidons la personne à clarifier son projet.",
            "next_action": "Répondre d'abord à la demande, puis poser au besoin une seule question utile pour comprendre ce qu'elle veut approfondir.",
        }

    def _handle_local(self, user_id: int, update_id: int, value: str, callback: bool = False) -> Reply | None:
        if update_id in self.seen:
            return None
        if len(self.recent) == self.recent.maxlen:
            self.seen.discard(self.recent.popleft())
        self.recent.append(update_id)
        self.seen.add(update_id)
        now = self.clock()
        self.sessions = {uid: s for uid, s in self.sessions.items() if now - s.updated_at < timedelta(hours=2)}
        s = self.sessions.setdefault(user_id, Session(updated_at=now))
        s.updated_at = now
        start, count = self.rate.get(user_id, (now, 0))
        if now - start >= timedelta(minutes=1):
            start, count = now, 0
        self.rate[user_id] = (start, count + 1)
        if count >= 20 and value.strip().lower() not in {"/supprimer", "/mes_donnees"}:
            return Reply("Vous avez envoyé beaucoup de messages. Réessayez dans une minute.")
        if callback:
            if value in {"lang:fr", "lang:ar"}:
                s.language = value.partition(":")[2]
                s.stage = "ebook_wait"
                return self._ebook_delivery(s)
            if value == "ebook:continue":
                s.stage = "premium_choice"
                return self._premium_pitch(s)
            if value == "funnel:premium":
                s.funnel_route = "consultation"
                s.offer_status = "premium_interested"
                s.stage = "premium_project"
                return self._premium_start(s)
            if value == "funnel:self":
                s.funnel_route = "private_channel"
                s.offer_status = "private_channel_presented"
                s.private_channel_presented = True
                s.stage = "private_channel_offer"
                return Reply(self._private_channel_offer(s), self._private_channel_buttons(s))
            if value == "vip:join":
                s.funnel_route = "private_channel"
                s.offer_status = "payment_instructions_shown"
                s.stage = "vip_payment"
                return Reply(self._payment_instructions(s), self._vip_payment_buttons(s))
            if value == "vip:consultant":
                s.funnel_route = "consultation"
                s.offer_status = "premium_interested"
                s.stage = "premium_project"
                return self._premium_start(s)
            if value.startswith("project:"):
                track = value.partition(":")[2]
                if track not in SUPPORTED_TRACKS:
                    return Reply(self._t(s, "Ce choix n'est plus valable.", "هذا الاختيار لم يعد صالحا."))
                s.tracks = [track]
                s.primary = track
                if s.funnel_route == "consultation" and s.offer_status == "premium_interested":
                    s.stage = "premium_last_name"
                    return Reply(self._premium_stage_prompt(s))
                s.stage = "explore"
                return self._next(s)
            value = {"summary:yes": "oui", "summary:no": "non", "offer:yes": "oui",
                     "offer:no": "non", "coord:yes": "oui", "coord:no": "non",
                     "consent:accept": "j'accepte", "consent:decline": "je refuse"}.get(value, "")
            if not value:
                return Reply("Ce bouton n'est plus valable. Vous pouvez répondre par écrit.")
        text = value.strip()
        command = text.split(maxsplit=1)[0].lower() if text else ""
        if command == "/start":
            source = "canal_gratuit" if len(text.split()) > 1 and normalize(text.split(maxsplit=1)[1]) == "canal_gratuit" else "direct"
            self.sessions[user_id] = Session(updated_at=now, lead_source=source, stage="language_choice")
            return Reply(self._language_welcome(), [("🇫🇷 Français", "lang:fr"), ("🇩🇿 العربية", "lang:ar")])
        if command == "/aide":
            return Reply("Décrivez naturellement votre projet ou posez une question sur RDW. /guide présente les sujets du guide ; /faq affiche les réponses fréquentes ; /canal présente le canal VIP à 1 000 DA à vie. /reprendre reprend un échange ; /annuler le met en pause ; /humain prépare une demande Premium ; /mes_donnees montre la fiche enregistrée ; /supprimer l'efface ; /source indique le passage utilisé. La preuve de paiement doit être envoyée au contact indiqué dans /canal.")
        if command == "/guide":
            return Reply(self.knowledge.guide_overview())
        if command == "/faq":
            entries = self.review_store.list_entries("faq", 5) if self.review_store else []
            if entries:
                return Reply("FAQ RDW :\n" + "\n".join(f"• {item['question']} — {item['answer']}" for item in entries))
            return Reply("Questions fréquentes à essayer : Quelles filières RDW accompagne ? Comment se passe l'accompagnement ? Que mettre dans mon CV ?")
        if command == "/videos":
            entries = self.review_store.list_entries("video", 5) if self.review_store else []
            return Reply("Vidéos RDW :\n" + "\n".join(f"• {item['question']} : {item['answer']}" for item in entries)) if entries else Reply("Aucune vidéo validée n'est encore publiée.")
        if command == "/historique":
            active = bool(self.review_store and self.review_store.history_enabled(user_id))
            return Reply(("Historique activé." if active else "Historique désactivé.") + " /historique_on l'active pour les prochains messages ; /historique_off l'arrête. /supprimer efface votre historique local. Les anciens messages ne sont pas récupérables.")
        if command in {"/historique_on", "/historique_off"}:
            if not self.review_store:
                return Reply("Historique indisponible dans ce mode.")
            self.review_store.set_history(user_id, command == "/historique_on")
            return Reply("Historique local activé pour vos prochains messages. /supprimer efface cet historique." if command == "/historique_on" else "Historique local arrêté ; les messages déjà enregistrés restent jusqu'à /supprimer.")
        if command == "/id":
            return Reply(f"Votre identifiant Telegram numérique : {user_id}.")
        if command == "/canal":
            s.funnel_route = "private_channel"
            s.offer_status = "private_channel_presented"
            s.private_channel_presented = True
            s.stage = "private_channel_offer"
            return Reply(self._private_channel_offer(s), self._private_channel_buttons(s))
        if command == "/annuler":
            if s.stage in {"last_name", "first_name", "contact_detail", "contact_confirm", "consent"} | PREMIUM_FORM_STAGES:
                s.last_name = s.first_name = s.contact_method = s.contact_detail = None
                s.contact_confirmed = False
            s.stage = "paused"
            return Reply("D'accord, je mets l'échange en pause. Vous pourrez le reprendre avec /reprendre ou poser une autre question.")
        if command in {"/reprendre", "/fiche"}:
            if s.stage == "paused":
                s.stage = "explore"
            elif not s.tracks:
                saved = self.store.get(user_id)
                if saved:
                    return Reply("Votre demande de rappel est enregistrée. Vous pouvez poser une question ou utiliser /supprimer.")
            if s.current_slot:
                return Reply(self._stage_prompt(s))
            return self._next(s)
        if command == "/mes_donnees":
            saved = self.store.get(user_id)
            if saved:
                identity = " ".join(part for part in (saved.get("first_name"), saved.get("last_name")) if part)
                return Reply(f"Fiche enregistrée pour {identity} : {saved['summary']} Téléphone confirmé : {saved['contact_detail']}. Accord : {saved['consent_version']} du {saved['consent_at'].date()}. /supprimer pour effacer.")
            return Reply("Aucune fiche durable enregistrée. " + (self._summary(s) if s.tracks else "Votre échange temporaire n'est pas conservé après l'arrêt du bot."))
        if command == "/supprimer":
            try:
                self.store.delete(user_id)
                if self.review_store:
                    self.review_store.delete_history(user_id)
            except Exception:
                return Reply("La suppression n'a pas pu être confirmée. Réessayez plus tard ; je ne prétends pas que les données ont été effacées.")
            self.sessions.pop(user_id, None)
            return Reply("Votre fiche RDW et le contexte temporaire de cet échange ont été supprimés du bot.")
        if command == "/source":
            return Reply(s.last_source or "Aucune réponse documentaire récente à citer.")
        if command == "/humain" or HUMAN.search(normalize(text)):
            if s.stage in {"last_name", "first_name", "contact_detail", "contact_confirm", "consent"} | PREMIUM_FORM_STAGES:
                return Reply("Je peux enregistrer une demande de rappel après votre accord, mais je ne peux pas joindre directement un conseiller. " + self._stage_prompt(s))
            s.funnel_route = "consultation"
            s.offer_status = "premium_interested"
            s.stage = "premium_project"
            return self._premium_start(s)
        if command.startswith("/"):
            return Reply("Commande inconnue. Utilisez /aide.")
        if not text or len(text) > 500:
            return Reply("Écrivez un message de 500 caractères maximum.")
        contact_number_expected = s.stage == "contact_detail"
        if SENSITIVE_INPUT.search(text) or (not contact_number_expected and re.search(r"\b\d{9,}\b", text)):
            return Reply("Ne transmettez pas de passeport, de matricule ni de document sensible dans cette conversation.")
        if is_question_permission(text):
            return Reply(self._t(
                s,
                "Oui, bien sûr. Vous pouvez me poser toutes vos questions concernant l'Ebook, notre agence ou vos démarches vers l'Allemagne. Je vous répondrai d'abord, puis nous reprendrons le parcours là où vous l'avez laissé.",
                "نعم، بالطبع. يمكنكم طرح كل أسئلتكم حول الدليل أو وكالتنا أو إجراءاتكم نحو ألمانيا. سأجيب أولا، ثم نعود إلى المرحلة التي توقفنا عندها.",
            ))
        if GREETING.match(text):
            if s.stage == "language_choice":
                return Reply(self._language_welcome(), [("🇫🇷 Français", "lang:fr"), ("🇩🇿 العربية", "lang:ar")])
            if s.stage == "paused":
                return Reply("Bonjour ! Votre projet est en pause. Utilisez /reprendre pour le poursuivre ou /start pour commencer un nouveau projet.")
            return Reply(self._welcome(s) if s.stage == "idle" else self._t(s, "Bonjour ! ", "مرحبا! ") + self._stage_prompt(s))
        if THANKS.match(text):
            if s.stage == "paused":
                return Reply("Avec plaisir. Utilisez /reprendre si vous souhaitez continuer votre projet.")
            return Reply("Avec plaisir. " + (self._stage_prompt(s) if s.stage != "idle" else "Dites-moi simplement ce que vous souhaitez comprendre ou préparer."))
        if FRUSTRATION.search(text):
            if s.stage == "route_clarify":
                s.stage = "idle"
            return Reply("Vous avez raison, je n'ai pas traité votre demande correctement. Reformulez simplement la question à laquelle vous voulez une réponse ; je la traiterai avant de poursuivre l'orientation.")
        if s.stage == "language_choice":
            normalized_language = normalize(text)
            if normalized_language in {"francais", "français", "fr"}:
                s.language, s.stage = "fr", "ebook_wait"
                return self._ebook_delivery(s)
            if normalized_language in {"arabe", "arabic", "العربية", "عربي"}:
                s.language, s.stage = "ar", "ebook_wait"
                return self._ebook_delivery(s)
            # Compatibilité avec une personne qui écrit directement au lieu d'utiliser le bouton.
            s.language = "ar" if re.search(r"[\u0600-\u06ff]", text) else "fr"
            s.stage = "idle"
        if s.stage == "ebook_wait":
            if self._looks_like_question(text):
                return Reply(self._answer_question(s, text) + "\n\n" + self._t(
                    s, "Quand vous êtes prêt, continuez le parcours.", "عندما تكونون مستعدين، واصلوا المسار."
                ), [(self._t(s, "📖 J'ai lu l'Ebook / Continuer", "📖 قرأت الدليل / متابعة"), "ebook:continue")])
            return Reply(self._t(s, "Consultez l'Ebook puis continuez.", "اطلعوا على الدليل ثم واصلوا."),
                         [(self._t(s, "📖 J'ai lu l'Ebook / Continuer", "📖 قرأت الدليل / متابعة"), "ebook:continue")])
        if s.stage == "premium_choice":
            if self._looks_like_question(text):
                answered = self._answer_question(s, text)
                pitch = self._premium_pitch(s)
                return Reply(answered + "\n\n" + pitch.text, pitch.buttons)
            return self._premium_pitch(s)
        if s.stage == "premium_project" and self._looks_like_question(text):
            answered = self._answer_question(s, text)
            prompt = self._premium_start(s)
            return Reply(answered + "\n\n" + prompt.text, prompt.buttons)
        if s.stage in PREMIUM_FORM_STAGES:
            if self._looks_like_question(text):
                return Reply(self._answer_question(s, text) + "\n\n" + self._premium_stage_prompt(s))
            return self._premium_stage_reply(s, text)
        if s.stage == "vip_payment":
            if self._looks_like_question(text):
                return Reply(self._answer_question(s, text) + "\n\n" + self._payment_instructions(s),
                             self._vip_payment_buttons(s))
            return Reply(self._payment_instructions(s), self._vip_payment_buttons(s))
        if s.stage == "paused":
            return Reply(self._answer_question(s, text) if self._looks_like_question(text) else "L'échange est en pause. Utilisez /reprendre pour continuer, ou posez une question sur RDW.")
        if s.stage == "clarify_track":
            guessed = s.facts.get("hypothesis_track", {}).get("value")
            if normalize(text) in YES and guessed:
                s.tracks = [guessed]
                s.primary = guessed
                s.facts.pop("hypothesis_track", None)
                s.stage = "explore"
                return self._next(s)
            if normalize(text) in NO:
                s.stage = "idle"
                s.facts.pop("hypothesis_track", None)
                return Reply("D'accord. Quelle autre piste souhaitez-vous explorer ?")
        if s.stage == "route_clarify":
            intent = detect_sales_intent(text)
            if self._looks_like_question(text) and normalize(text) not in YES | NO:
                answer = self._answer_question(s, text)
                s.stage = "idle"
                return Reply(answer)
            if intent == SELF_GUIDED:
                s.funnel_route = "private_channel"
                s.stage = "private_channel_offer"
                return Reply(self._private_channel_offer(s), self._private_channel_buttons(s))
            if intent == CONSULTATION or re.search(r"\b(?:avec rdw|avec vous|agence)\b", normalize(text)):
                s.funnel_route = "consultation"
                s.stage = "idle"
                return Reply("Très bien. Pour préparer une consultation adaptée, quel projet envisagez-vous en Allemagne : études, Ausbildung ou emploi ?")
            return Reply("Souhaitez-vous surtout comprendre les démarches pour avancer par vous-même, ou faire examiner votre projet par RDW ?")
        if s.stage == "private_channel_offer":
            if normalize(text) in YES:
                s.offer_status = "private_channel_interested"
                s.stage = "offer_contact"
                s.offer_status = "payment_instructions_shown"
                s.stage = "vip_payment"
                return Reply(self._payment_instructions(s), self._vip_payment_buttons(s))
            if normalize(text) in NO:
                s.offer_status = "private_channel_declined"
                s.stage = "idle"
                return Reply("D'accord. Vous pouvez continuer à me poser vos questions sur RDW ou sur les démarches présentées dans le guide.")
            if self._looks_like_question(text):
                return Reply(self._answer_question(s, text) + "\n\n" + self._private_channel_offer(s), self._private_channel_buttons(s))
            return Reply("Souhaitez-vous recevoir les informations d'accès à ce canal privé lorsqu'elles seront disponibles ?")
        if s.stage in {"summary_confirm", "offer_contact", "last_name", "first_name", "contact_detail", "contact_confirm", "consent"}:
            if self._looks_like_question(text) and normalize(text) not in YES | NO:
                return Reply(self._answer_question(s, text) + "\n\n" + self._stage_prompt(s))
            return self._stage_reply(s, user_id, update_id, text)
        if normalize(text) in SKIP and s.current_slot:
            s.skipped.add(s.current_slot)
            s.current_slot = None
            return self._next(s)
        if s.stage == "choose_primary":
            if self._looks_like_question(text):
                return Reply(self._answer_question(s, text) + "\n\n" + self._stage_prompt(s))
            if normalize(text) in SKIP:
                s.stage = "idle"
                return Reply("Aucun problème : gardons ces deux pistes ouvertes. Vous pouvez poser une question ou préciser votre préférence plus tard.")
            chosen = self._choose_track(text, s.tracks)
            if chosen:
                s.primary = chosen
                s.stage = "explore"
                return self._next(s)
            return Reply("Vous pouvez choisir une piste à explorer en premier, ou dire « je ne sais pas »." )
        sales_intent = detect_sales_intent(text)
        if sales_intent == AGENCY_INFO:
            s.funnel_route = "ebook_info"
        if sales_intent == CONSULTATION:
            s.funnel_route = "ebook_info" if self._looks_like_question(text) else "consultation"
        if sales_intent == SELF_GUIDED:
            s.funnel_route = "private_channel"
            s.stage = "private_channel_offer"
            answer = self._answer_question(s, text) if self._looks_like_question(text) else None
            return Reply((answer + "\n\n" if answer else "") + self._private_channel_offer(s), self._private_channel_buttons(s))
        if sales_intent == PROCEDURE_INFO and not s.tracks:
            s.funnel_route = "procedure_info"

        tracks, facts, hypotheses = extract_declared(text)
        unsupported = "volontariat" in tracks or "volontariat" in hypotheses
        tracks = [track for track in tracks if track in SUPPORTED_TRACKS]
        hypotheses = [track for track in hypotheses if track in SUPPORTED_TRACKS]
        if unsupported and not tracks and not self._looks_like_question(text) and (not s.current_slot or CORRECTION.search(normalize(text))):
            if CORRECTION.search(normalize(text)):
                s.tracks, s.primary, s.current_slot, s.asked = [], None, None, 0
            if text not in s.open_questions and len(s.open_questions) < 3:
                s.open_questions.append(text[:160])
            return Reply("Le guide RDW ne décrit pas de prestation pour le volontariat. Quel autre projet souhaitez-vous explorer : études, Ausbildung ou emploi ?")
        if s.current_slot and self._looks_like_question(text):
            answer = self._answer_question(s, text)
            for key, item in facts.items():
                s.put(key, item)
            if s.current_slot in facts:
                s.current_slot = None
                return Reply(answer + "\n\n" + self._next(s).text)
            return Reply(answer + "\n\n" + self._stage_prompt(s))
        if s.current_slot and not self._looks_like_question(text):
            if CORRECTION.search(normalize(text)) and tracks:
                s.tracks = tracks
                s.primary = tracks[0] if len(tracks) == 1 else None
                s.current_slot = None
                s.asked = 0
                return self._next(s)
            if s.current_slot not in {"german_level", "english_level"}:
                bare_level = re.fullmatch(r"\s*(A1|A2|B1|B2|C1|C2)\s*", text, re.I)
                if bare_level:
                    facts["german_level"] = bare_level.group(1).upper()
            for key, item in facts.items():
                s.put(key, item)
            if s.current_slot in facts or self._capture_slot(s, s.current_slot, text):
                completed_slot = s.current_slot
                s.current_slot = None
                following = self._next(s)
                acknowledgement = self._slot_acknowledgement(completed_slot, s.value(completed_slot))
                return Reply(acknowledgement + "\n\n" + following.text, following.buttons)
            if facts:
                return Reply("J'ai noté cette précision. " + self._stage_prompt(s))
            return Reply("Je n'ai pas bien saisi cette réponse. Vous pouvez préciser ou dire « je ne sais pas ».")
        llm_topic = None
        if self.interpreter:
            try:
                public_context = self._public_context(text)
                proposed = self.interpreter.interpret(text, self._safe_context(s), public_context)
                extra = validate_interpretation(
                    {"tracks": proposed.tracks, "facts": proposed.facts,
                     "question_topic": proposed.question_topic}, text, public_context)
                tracks = list(dict.fromkeys(tracks + extra.tracks))
                tracks = [track for track in tracks if track in SUPPORTED_TRACKS]
                facts.update({k: v for k, v in extra.facts.items() if k not in facts})
                llm_topic = extra.question_topic
            except Exception:
                pass
        correction = bool(CORRECTION.search(normalize(text)))
        had_project = bool(s.tracks)
        for key, item in facts.items():
            s.put(key, item)
        if tracks:
            if correction:
                s.tracks = tracks
                s.primary = tracks[0] if len(tracks) == 1 else None
                s.asked = 0
                s.skipped.clear()
            else:
                s.tracks = list(dict.fromkeys(s.tracks + tracks))
                if len(s.tracks) == 1:
                    s.primary = s.tracks[0]
        if hypotheses:
            s.stage = "clarify_track"
            s.facts["hypothesis_track"] = {"value": hypotheses[0], "status": "hypothesis"}
            return Reply(f"Vous envisagez peut-être {TRACK_LABELS[hypotheses[0]]}. Est-ce bien une piste que vous souhaitez explorer ?")
        answer = self._answer_question(s, text, llm_topic) if self._looks_like_question(text) else None
        if unsupported and tracks:
            note = "Le guide RDW ne décrit pas de prestation pour le volontariat."
            answer = (answer + " " if answer else "") + note
        information_request = bool(INFORMATION_INTENT.search(text) or is_darija_information(text))
        if not s.tracks and information_request and not tracks:
            return Reply((answer + "\n\n" if answer else "")
                         + "Que souhaitez-vous savoir sur RDW ou son accompagnement ?")
        if not s.tracks and not (tracks or PERSONAL_PROJECT.search(normalize(text))):
            if answer and self._looks_like_question(text):
                return Reply(answer)
            next_question = ("Que souhaitez-vous savoir sur RDW ou son accompagnement ?"
                             if information_request
                             else "Quel projet envisagez-vous en Allemagne : études, Ausbildung ou emploi ?")
            return Reply((answer + "\n\n" if answer else "") + next_question)
        if not s.tracks:
            return Reply((answer + "\n\n" if answer else "") + "Quel type de projet envisagez-vous : études, Ausbildung ou emploi ?")
        if len(s.tracks) > 1 and not s.primary:
            s.stage = "choose_primary"
            names = " et ".join(TRACK_LABELS[t] for t in s.tracks)
            return Reply((answer + "\n\n" if answer else "") + f"Vous envisagez {names}. Quelle piste souhaitez-vous explorer d'abord ?")
        s.stage = "explore"
        next_reply = self._next(s)
        if not had_project and facts and s.primary and not answer:
            public = self.knowledge.by_id[s.primary]
            s.last_source = public["citation"]
            intro = self._summary(s) + " " + public["test_answer"]
            return Reply(intro + "\n\n" + next_reply.text, next_reply.buttons)
        return Reply((answer + "\n\n" if answer else "") + next_reply.text, next_reply.buttons)

    def _safe_context(self, s: Session) -> dict:
        return {"tracks": s.tracks[:4], "facts": {k: v["value"] for k, v in s.facts.items() if v["status"] == "declared"}}

    def _t(self, s: Session, french: str, arabic: str) -> str:
        return arabic if s.language == "ar" else french

    def _language_welcome(self) -> str:
        return ("Bonjour et bienvenue chez RDW ! Je suis l'assistant virtuel de notre agence. "
                "Avec Virtulingo, nous accompagnons les projets vers l'Allemagne : études, Ausbildung ou emploi. "
                "Je vais vous envoyer notre guide Ebook gratuit, répondre à vos questions et préparer votre demande si vous souhaitez avancer avec nous. "
                "Que souhaitez-vous savoir ou préparer ? Vous pourrez me le dire après avoir choisi votre langue.\n\n"
                "مرحبا بكم في RDW! سأرسل لكم دليلنا المجاني وأساعدكم في اختيار الحل المناسب لمشروعكم نحو ألمانيا.\n\n"
                "Choisissez votre langue / اختر لغتك :")

    def _ebook_delivery(self, s: Session) -> Reply:
        text = self._t(
            s,
            "Voici votre Ebook gratuit RDW. Il présente les principales voies vers l'Allemagne, les démarches et les services de notre agence. Prenez le temps de le consulter, puis continuez quand vous êtes prêt.",
            "إليكم دليل RDW المجاني. يشرح أهم المسارات نحو ألمانيا والإجراءات وخدمات وكالتنا. اطلعوا عليه ثم واصلوا عندما تكونون مستعدين.",
        )
        button = self._t(s, "📖 J'ai lu l'Ebook / Continuer", "📖 قرأت الدليل / متابعة")
        return Reply(text, [(button, "ebook:continue")], str(EBOOK_PATH))

    def _premium_pitch(self, s: Session) -> Reply:
        text = self._t(
            s,
            ("Deux voies sont possibles.\n\n"
             "💎 Premium : notre agence prend en charge les étapes prévues au contrat, notamment la langue, la traduction et l'authentification du dossier, le CV et les lettres adaptés, les candidatures et la préparation aux entretiens. Nos équipes en Allemagne démarchent les recruteurs pour rechercher des entretiens. Après l'évaluation, les profils acceptés peuvent recevoir un contrat écrit « Satisfait ou Remboursé » ; ses conditions et les engagements exacts sont ceux du contrat signé.\n\n"
             "🛠️ Solo : vous avancez à votre rythme avec l'Ebook et pouvez rejoindre notre canal communautaire pour recevoir davantage de ressources et d'aide.\n\n"
             "Quelle voie souhaitez-vous choisir ?"),
            ("لديكم مساران.\n\n"
             "💎 المرافقة المميزة: تتولى وكالتنا المراحل المحددة في العقد، ومنها اللغة، ترجمة وتصديق الملف، السيرة الذاتية ورسائل التحفيز، الترشحات والتحضير للمقابلات. تتواصل فرقنا في ألمانيا مع جهات التوظيف للبحث عن مقابلات. بعد دراسة الملف، يمكن للملفات المقبولة الحصول على عقد مكتوب «راض أو مسترجع لأموالك»، وتبقى الشروط والالتزامات الدقيقة هي المكتوبة في العقد الموقع.\n\n"
             "🛠️ المسار الفردي: تتقدمون بطريقتكم باستعمال الدليل ويمكنكم الانضمام إلى قناتنا للحصول على موارد ومساعدة إضافية.\n\n"
             "أي مسار تختارون؟"),
        )
        return Reply(text, [
            (self._t(s, "💎 Démarrer la procédure Premium", "💎 بدء المرافقة المميزة"), "funnel:premium"),
            (self._t(s, "🛠️ Faire ma procédure tout seul", "🛠️ أقوم بالإجراءات بنفسي"), "funnel:self"),
        ])

    def _premium_start(self, s: Session) -> Reply:
        text = self._t(
            s,
            ("Très bien. Pour vérifier si votre profil peut entrer dans notre procédure Premium et quelles offres peuvent lui correspondre, je vais vous poser quelques questions courtes : identité, âge, diplôme et domaine, langues et expérience. Une fois le formulaire confirmé, notre équipe commerciale l'examinera et vous contactera pour planifier l'évaluation.\n\nQuel projet préparez-vous ?"),
            ("جيد. للتحقق من ملاءمة ملفكم للمرافقة المميزة والعروض الممكنة، سأطرح أسئلة قصيرة عن الهوية والعمر والشهادة والتخصص واللغات والخبرة. بعد تأكيد الاستمارة، يدرسها الفريق التجاري ويتصل بكم لتحديد موعد التقييم.\n\nما هو مشروعكم؟"),
        )
        return Reply(text, [
            (self._t(s, "🎓 Études", "🎓 دراسة"), "project:etudes"),
            ("🛠 Ausbildung", "project:ausbildung"),
            (self._t(s, "💼 Emploi", "💼 عمل"), "project:emploi"),
        ])

    def _premium_stage_prompt(self, s: Session) -> str:
        prompts = {
            "premium_last_name": self._t(s, "Quel est votre nom de famille ?", "ما هو لقبكم؟"),
            "premium_first_name": self._t(s, "Quel est votre prénom ?", "ما هو اسمكم؟"),
            "premium_age": self._t(s, "Quel âge avez-vous ?", "كم عمركم؟"),
            "premium_degree": self._t(s, "Quel est votre dernier diplôme ou niveau d'études ?", "ما هي آخر شهادة أو مستوى دراسي لديكم؟"),
            "premium_field": self._t(s, "Quel est votre domaine de formation ou le domaine visé en Allemagne ?", "ما هو تخصصكم أو المجال الذي تستهدفونه في ألمانيا؟"),
            "premium_german": self._t(s, "Quel est votre niveau d'allemand ? Vous pouvez répondre « aucun » ou « je ne sais pas ».", "ما هو مستواكم في الألمانية؟ يمكنكم الإجابة: لا يوجد أو لا أعرف."),
            "premium_english": self._t(s, "Quel est votre niveau d'anglais ? Vous pouvez répondre « aucun » ou « je ne sais pas ».", "ما هو مستواكم في الإنجليزية؟ يمكنكم الإجابة: لا يوجد أو لا أعرف."),
            "premium_experience": self._t(s, "Quelle expérience professionnelle avez-vous ? Vous pouvez répondre « aucune ».", "ما هي خبرتكم المهنية؟ يمكنكم الإجابة: لا توجد."),
        }
        return prompts.get(s.stage, self._t(s, "Quelle précision souhaitez-vous ajouter ?", "ما هي المعلومة التي تريدون إضافتها؟"))

    def _premium_stage_reply(self, s: Session, text: str) -> Reply:
        answer = normalize(text)
        name_pattern = r"[A-Za-zÀ-ÿ\u0600-\u06ff][A-Za-zÀ-ÿ\u0600-\u06ff' -]{1,79}"
        if s.stage == "premium_last_name":
            if any(char.isdigit() for char in text) or not re.fullmatch(name_pattern, text):
                return Reply(self._t(s, "Indiquez seulement votre nom de famille.", "اكتبوا اللقب فقط."))
            s.last_name = text.strip()
            s.stage = "premium_first_name"
            return Reply(self._premium_stage_prompt(s))
        if s.stage == "premium_first_name":
            if any(char.isdigit() for char in text) or not re.fullmatch(name_pattern, text):
                return Reply(self._t(s, "Indiquez seulement votre prénom.", "اكتبوا الاسم فقط."))
            s.first_name = text.strip()
            s.stage = "premium_age"
            return Reply(self._premium_stage_prompt(s))
        if s.stage == "premium_age":
            age = re.fullmatch(r"\s*(\d{1,2})(?:\s*ans?)?\s*", text, re.I)
            if not age or not 14 <= int(age.group(1)) <= 99:
                return Reply(self._t(s, "Indiquez votre âge en nombre, entre 14 et 99 ans.", "اكتبوا العمر رقما بين 14 و99 سنة."))
            s.put("age", age.group(1))
            s.stage = "premium_degree"
            return Reply(self._premium_stage_prompt(s))
        if s.stage == "premium_degree":
            if not 1 < len(text) <= 120:
                return Reply(self._premium_stage_prompt(s))
            s.put("current_degree", text[:120])
            s.stage = "premium_field"
            return Reply(self._premium_stage_prompt(s))
        if s.stage == "premium_field":
            if not 1 < len(text) <= 120:
                return Reply(self._premium_stage_prompt(s))
            s.put("desired_field", text[:120])
            s.stage = "premium_german"
            return Reply(self._premium_stage_prompt(s))
        if s.stage in {"premium_german", "premium_english"}:
            slot = "german_level" if s.stage == "premium_german" else "english_level"
            level = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", text, re.I)
            no_level = answer in SKIP | {"aucun", "aucune", "debutant", "débutant", "لا يوجد", "لا أعرف"}
            if not level and not no_level:
                return Reply(self._t(s, "Répondez par A1, A2, B1, B2, C1, C2, « aucun » ou « je ne sais pas ».",
                                     "أجيبوا بـ A1 أو A2 أو B1 أو B2 أو C1 أو C2 أو لا يوجد أو لا أعرف."))
            s.put(slot, level.group(1).upper() if level else "aucun niveau déclaré")
            s.stage = "premium_english" if s.stage == "premium_german" else "premium_experience"
            return Reply(self._premium_stage_prompt(s))
        if s.stage == "premium_experience":
            if not 1 < len(text) <= 160:
                return Reply(self._premium_stage_prompt(s))
            s.put("experience", text[:160])
            s.contact_method = "telephone"
            s.stage = "contact_detail"
            return Reply(self._stage_prompt(s))
        return Reply(self._premium_stage_prompt(s))

    def _private_channel_buttons(self, s: Session) -> list[tuple[str, str]]:
        return [
            (self._t(s, "🚀 Rejoindre le canal VIP", "🚀 الانضمام إلى قناة VIP"), "vip:join"),
            (self._t(s, "📞 Parler à un conseiller", "📞 التحدث مع مستشار"), "vip:consultant"),
        ]

    def _private_channel_offer(self, s: Session) -> str:
        price = f"{self.private_channel_price_dzd:,}".replace(",", " ")
        return self._t(
            s,
            ("Vous pouvez avancer seul avec l'Ebook gratuit. Notre canal Telegram VIP vous aide à aller plus loin :\n\n"
             "🎥 lives hebdomadaires avec questions/réponses ;\n"
             "💼 contacts, sites d'offres et méthodes de candidature partagés par l'équipe ;\n"
             "🗣️ séances de communication en allemand ;\n"
             "🤝 entraide avec d'autres candidats ;\n"
             "🔄 possibilité de passer ensuite au Premium si vous souhaitez nous confier la suite.\n\n"
             f"L'accès coûte {price} DA une seule fois et reste valable à vie."),
            ("يمكنكم التقدم بمفردكم باستعمال الدليل المجاني. تساعدكم قناة Telegram VIP بمحتوى إضافي:\n\n"
             "🎥 لقاءات أسبوعية وأسئلة وأجوبة؛\n"
             "💼 جهات اتصال ومواقع عروض وطرق الترشح؛\n"
             "🗣️ حصص تواصل بالألمانية؛\n"
             "🤝 تعاون مع مترشحين آخرين؛\n"
             "🔄 إمكانية الانتقال لاحقا إلى المرافقة المميزة.\n\n"
             f"سعر الدخول {price} دج مرة واحدة، والدخول صالح مدى الحياة."),
        )

    def _private_channel_teaser(self, s: Session) -> str:
        price = f"{self.private_channel_price_dzd:,}".replace(",", " ")
        return self._t(
            s,
            f"Pour aller plus loin à votre rythme, notre canal Telegram privé propose plus de détails et des lives, avec un accès à vie pour un paiement unique de {price} DA. Écrivez /canal pour recevoir les modalités.",
            f"للحصول على تفاصيل أكثر وبثوث مباشرة، توفر قناتنا الخاصة دخولا مدى الحياة بدفع واحد قدره {price} دج. اكتب /canal لمعرفة طريقة الدخول.",
        )

    def _vip_payment_buttons(self, s: Session) -> list[tuple[str, str]]:
        return [(self._t(s, "💎 Voir l'accompagnement Premium", "💎 عرض المرافقة المميزة"), "vip:consultant")]

    def _payment_instructions(self, s: Session) -> str:
        price = f"{self.private_channel_price_dzd:,}".replace(",", " ")
        if self.baridimob_payment_details or self.ccp_payment_details:
            methods_fr = []
            methods_ar = []
            if self.baridimob_payment_details:
                methods_fr.append(f"BaridiMob : {self.baridimob_payment_details}")
                methods_ar.append(f"BaridiMob : {self.baridimob_payment_details}")
            if self.ccp_payment_details:
                methods_fr.append(f"CCP : {self.ccp_payment_details}")
                methods_ar.append(f"CCP : {self.ccp_payment_details}")
                if self.ccp_account_holder_name:
                    methods_fr.append(f"Titulaire du compte CCP : {self.ccp_account_holder_name}")
                    methods_ar.append(f"اسم صاحب حساب CCP : {self.ccp_account_holder_name}")
            details_fr = "\n".join(methods_fr)
            details_ar = "\n".join(methods_ar)
        else:
            details_fr = ("Les coordonnées BaridiMob/CCP ne sont pas encore configurées dans le bot. "
                          f"Demandez-les au support RDW : {self.payment_proof_telegram}.")
            details_ar = ("لم يتم إعداد معلومات BaridiMob/CCP في البوت بعد. "
                          f"اطلبوها من دعم RDW: {self.payment_proof_telegram}.")
        return self._t(
            s,
            (f"L'accès VIP coûte {price} DA, en paiement unique pour un accès à vie.\n\n{details_fr}\n\n"
             f"Après le versement de {price} DA, envoyez la photo ou le PDF du reçu au compte Telegram associé au numéro {self.payment_proof_telegram}. Après vérification du paiement, un administrateur RDW vous ajoutera manuellement au canal VIP."),
            (f"سعر الدخول إلى قناة VIP هو {price} دج، بدفع واحد ودخول مدى الحياة.\n\n{details_ar}\n\n"
             f"بعد دفع {price} دج، أرسلوا صورة الوصل أو ملف PDF إلى حساب Telegram المرتبط بالرقم {self.payment_proof_telegram}. بعد التحقق من الدفع، سيضيفكم مسؤول RDW يدويا إلى قناة VIP."),
        )

    def _consent_text(self, s: Session) -> str:
        if s.language != "ar":
            return CONSENT_TEXT
        return ("بموافقتكم، تسجل RDW معلومات الاستمارة ورقم الهاتف المؤكد لكي يدرس الفريق التجاري طلب المرافقة المميزة ويتصل بكم. "
                "يمكنكم مشاهدة البيانات عبر /mes_donnees وطلب حذفها عبر /supprimer. هل توافقون؟")

    def _welcome(self, s: Session) -> str:
        return self._t(
            s,
            "Bienvenue chez RDW. Je peux répondre à vos questions à partir de l'Ebook et vous aider à avancer avec notre agence ou par vous-même. Que souhaitez-vous savoir ou préparer ?",
            "مرحبا بكم في RDW. يمكنني الإجابة عن أسئلتكم اعتمادا على الدليل ومساعدتكم على التقدم مع وكالتنا أو بأنفسكم.",
        )

    def _public_context(self, text: str) -> list[dict]:
        return [{"id": p["id"], "citation": p["citation"], "text": p["text"]}
                for p in self.corpus.search(text, limit=2)]

    def _looks_like_question(self, text: str) -> bool:
        normalized = normalize(text)
        if READY_ACTION.search(normalized):
            return False
        return ("?" in text or bool(QUESTION_START.search(normalized)
                                    or QUESTION_INVERSION.search(normalized)
                                    or INFORMATION_INTENT.search(normalized)
                                    or INFORMATION_FRAGMENT.search(normalized)
                                    or is_darija_question(text)))

    def _slot_acknowledgement(self, slot: str, value: str | None) -> str:
        """Transitions locales naturelles utilisées aussi comme repli si l'IA échoue."""
        if slot == "desired_degree":
            return f"Très bien, je note la formation visée{f' : {value}' if value else ''}."
        if slot == "desired_field":
            return "D'accord, je note le domaine qui vous intéresse."
        if slot in {"current_degree", "school_level"}:
            return "Merci pour cette précision sur votre parcours actuel."
        if slot == "german_level":
            return f"Très bien, votre niveau d'allemand déclaré est {value}." if value else "Très bien, je note votre niveau d'allemand."
        if slot == "english_level":
            return f"Très bien, votre niveau d'anglais déclaré est {value}." if value else "Très bien, je note votre niveau d'anglais."
        if slot == "experience":
            return "Merci, je note cette expérience."
        if slot == "timeline":
            return "D'accord, je note la période envisagée."
        if slot == "country":
            return "Très bien, je note votre pays de résidence."
        return "Merci pour cette précision."

    def _answer_question(self, s: Session, text: str, topic_override: str | None = None) -> str:
        s.last_source = None
        if self.review_store:
            approved = self.review_store.find_answer(text)
            if approved:
                s.last_source = f"RDW:réponse-validée:{approved['id']}"
                return approved["answer"]
        words = canonical_words(text)
        if words & {"volontariat", "fsj", "bfd", "esc"}:
            if text not in s.open_questions and len(s.open_questions) < 3:
                s.open_questions.append(text[:160])
            return self._t(s,
                           "Le guide RDW ne décrit pas de prestation pour le volontariat. Je peux joindre cette question à une demande de contact si vous le souhaitez.",
                           "لا يصف دليل RDW خدمة خاصة بالتطوع. يمكنني إرفاق هذا السؤال بطلب تواصل إذا أردتم.")
        topic = topic_override or self.knowledge._topic(text)
        if topic is None:
            if text not in s.open_questions and len(s.open_questions) < 3:
                s.open_questions.append(text[:160])
            return self._t(s,
                           "Je n'ai pas de réponse vérifiée à cette question dans la base RDW. Si vous souhaitez un rappel, je pourrai joindre cette question à votre demande.",
                           "لا أجد جوابا موثقا عن هذا السؤال في قاعدة RDW. يمكنني إرفاقه بطلب تواصل إذا أردتم.")
        if topic == "cv_documents":
            cv = self.knowledge.by_id["cv"]
            docs = self.knowledge.by_id["documents"]
            s.last_source = cv["citation"] + " " + docs["citation"]
            s.last_topic = "documents"
            return self._t(s,
                           "Le CV présente votre formation, vos expériences vérifiables et vos langues. Le dossier peut aussi comprendre une lettre ciblée et des justificatifs ; les pièces exactes dépendent du parcours.",
                           "تعرض السيرة الذاتية تكوينكم وخبراتكم القابلة للتحقق واللغات. ويمكن أن يضم الملف رسالة مخصصة ووثائق إثبات، وتختلف القطع الدقيقة حسب المسار.")
        if topic == "guide_overview":
            s.last_topic = "guide_overview"
            return self._t(s, self.knowledge.guide_overview(),
                           "يشرح دليل RDW الدراسة وAusbildung والعمل، وطريقة المرافقة، واللغة الألمانية، والسيرة الذاتية، ورسائل التحفيز، والوثائق، والاستشارة، والأسعار المذكورة، والاستقرار وحدود الضمانات والقبول والتأشيرة.")
        if topic == "tarifs":
            s.last_topic = "tarifs"
            return self._t(
                s,
                "Aucun paiement de consultation n'est demandé dans le bot. Si vous choisissez la voie Premium, notre équipe étudie d'abord le formulaire puis vous présente le contrat et le devis correspondant. Le canal VIP pour les démarches en autonomie coûte 1 000 DA, en paiement unique avec accès à vie.",
                "لا يطلب البوت دفعا مقابل استشارة التقييم. عند اختيار المسار المميز، يدرس الفريق الاستمارة أولا ثم يقدم العقد وعرض السعر المناسب. سعر قناة VIP للمسار الفردي هو 1000 دج بدفع واحد ودخول مدى الحياة.",
            )
        p = self.knowledge.by_id[topic]
        s.last_source = p["citation"]
        s.last_topic = topic
        if topic == "limites":
            if text not in s.open_questions and len(s.open_questions) < 3:
                s.open_questions.append(text[:160])
            answer = ARABIC_DOCUMENTARY_ANSWERS[topic] if s.language == "ar" else p["test_answer"]
            return answer + self._t(s, " Si vous souhaitez un rappel, je peux joindre votre question à la demande.",
                                    " ويمكنني إرفاق سؤالكم بطلب تواصل إذا أردتم.")
        return ARABIC_DOCUMENTARY_ANSWERS.get(topic, p["test_answer"]) if s.language == "ar" else p["test_answer"]

    def _choose_track(self, text: str, choices: list[str]) -> str | None:
        words = canonical_words(text)
        matches = [track for track in choices if track in words]
        return matches[0] if len(matches) == 1 else None

    def _capture_slot(self, s: Session, slot: str, text: str) -> bool:
        if len(text) > 120 or SENSITIVE_INPUT.search(text):
            return False
        if slot not in {"german_level", "english_level"} and re.fullmatch(r"\s*(A1|A2|B1|B2|C1|C2)\s*", text, re.I):
            return False
        if slot not in {"experience", "timeline"} and re.search(r"\b\d{1,2}\s+ans?\s+d['’ ]?exp[eé]rience\b|\b\d{4}\b", text, re.I):
            return False
        if slot in {"german_level", "english_level"}:
            level = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", text, re.I)
            if not level:
                if normalize(text) in {"debutant", "aucun", "je ne parle pas allemand"}:
                    s.put(slot, "débutant ou aucun niveau déclaré")
                    return True
                return False
            s.put(slot, level.group(1).upper())
            return True
        if slot in {"current_degree", "desired_degree", "school_level"}:
            s.put(slot, text[:80])
            return True
        if slot in {"current_field", "desired_field", "experience", "timeline", "country"}:
            if len(text) < 2:
                return False
            s.put(slot, text[:80])
            return True
        return False

    def _prompts(self, s: Session) -> list[tuple[str, str]]:
        prompts = PROMPTS_AR[s.primary] if s.language == "ar" and s.primary in PROMPTS_AR else PROMPTS[s.primary]
        if s.primary == "etudes" and s.value("study_language") == "anglais":
            return [("english_level", "Quel est votre niveau actuel en anglais ? Vous pouvez dire « je ne sais pas ».")
                    if slot == "german_level" else (slot, prompt) for slot, prompt in prompts]
        return prompts

    def _stage_prompt(self, s: Session) -> str:
        if s.stage in PREMIUM_FORM_STAGES:
            return self._premium_stage_prompt(s)
        if s.current_slot and s.primary and s.stage not in {"last_name", "first_name", "contact_detail", "contact_confirm", "consent"}:
            return next((prompt for slot, prompt in self._prompts(s) if slot == s.current_slot), "Quelle précision souhaitez-vous ajouter ?")
        if s.language == "ar":
            return {
                "summary_confirm": "هل فهمت مشروعكم بشكل صحيح؟",
                "offer_contact": "هل تريدون أن يتصل بكم مستشار من RDW؟",
                "route_clarify": "هل تريدون القيام بالإجراءات بأنفسكم أم دراسة مشروعكم مع RDW؟",
                "private_channel_offer": "هل تريدون معرفة طريقة الدخول إلى القناة الخاصة؟",
                "last_name": "ما هو لقبكم؟",
                "first_name": "ما هو اسمكم؟",
                "contact_detail": "ما هو رقم الهاتف الذي تريدون استعماله؟ يمكنكم كتابة رقم جزائري مثل 0550123456.",
                "contact_confirm": "هل هذا الرقم صحيح؟",
                "consent": "هل توافقون على التسجيل الموضح أعلاه؟",
                "choose_primary": "أي مسار تريدون دراسته أولا؟",
            }.get(s.stage, "ما هو المشروع الذي تريدون دراسته؟")
        return {
            "summary_confirm": "Est-ce que mon résumé est correct ?",
            "offer_contact": "Souhaitez-vous qu'un conseiller RDW vous contacte ?",
            "route_clarify": "Souhaitez-vous avancer par vous-même ou faire examiner votre projet par RDW ?",
            "private_channel_offer": "Souhaitez-vous recevoir les informations d'accès au canal privé ?",
            "last_name": "Quel est votre nom de famille ?",
            "first_name": "Quel est votre prénom ?",
            "contact_detail": "Quel numéro de téléphone souhaitez-vous utiliser ? Vous pouvez écrire directement un mobile algérien comme 0550123456.",
            "contact_confirm": "Ce numéro est-il correct ?",
            "consent": "Acceptez-vous l'enregistrement expliqué ci-dessus ?",
            "choose_primary": "Quelle piste souhaitez-vous explorer d'abord ?",
        }.get(s.stage, "Quel projet souhaitez-vous explorer ?")

    def _next(self, s: Session) -> Reply:
        if not s.primary:
            return Reply(self._t(s, "Quelle voie vous intéresse : études, Ausbildung ou emploi ?",
                                 "أي مسار يهمكم: الدراسة، Ausbildung أم العمل؟"))
        # Limite par parcours ; les informations spontanées suppriment les questions correspondantes.
        max_questions = 4 if s.primary == "ausbildung" else 5
        if s.asked >= max_questions:
            s.stage = "summary_confirm"
            return Reply(self._summary(s) + self._t(s, " Est-ce que j'ai bien compris ?", " هل فهمتكم بشكل صحيح؟"),
                         [(self._t(s, "Oui", "نعم"), "summary:yes"),
                          (self._t(s, "Corriger", "تصحيح"), "summary:no")])
        for slot, prompt in self._prompts(s):
            if slot not in s.facts and slot not in s.skipped:
                s.current_slot = slot
                s.asked += 1
                return Reply(prompt)
        s.stage = "summary_confirm"
        return Reply(self._summary(s) + self._t(s, " Est-ce que j'ai bien compris ?", " هل فهمتكم بشكل صحيح؟"),
                     [(self._t(s, "Oui", "نعم"), "summary:yes"),
                      (self._t(s, "Corriger", "تصحيح"), "summary:no")])

    def _summary(self, s: Session) -> str:
        if s.language == "ar":
            labels = {"etudes": "الدراسة", "ausbildung": "Ausbildung", "emploi": "العمل"}
            project = labels.get(s.primary, "مشروع نحو ألمانيا")
            details = []
            for key, label in (("desired_degree", "التكوين المطلوب"), ("desired_field", "التخصص"),
                               ("current_degree", "آخر شهادة"), ("german_level", "الألمانية"),
                               ("experience", "الخبرة"), ("timeline", "الفترة"), ("country", "الإقامة")):
                if s.value(key):
                    details.append(f"{label}: {s.value(key)}")
            return f"أنتم تفكرون في {project} في ألمانيا" + (" (" + "؛ ".join(details) + ")" if details else "") + "."
        if not s.tracks:
            return "Vous souhaitez être recontacté par RDW au sujet de votre projet en Allemagne."
        tracks = " et ".join(TRACK_LABELS[t] for t in s.tracks) if s.tracks else "un projet en Allemagne"
        if s.primary == "etudes":
            def degree_phrase(value: str | None) -> str | None:
                if not value:
                    return None
                if re.match(r"^(?:un|une|mon|ma|le|la)\b", normalize(value)):
                    return value
                article = "une" if normalize(value).startswith("licence") else "un"
                return f"{article} {value}"

            desired = " ".join(x for x in (degree_phrase(s.value("desired_degree")), "en " + s.value("desired_field") if s.value("desired_field") else None) if x)
            current = " ".join(x for x in (degree_phrase(s.value("current_degree")), "en " + s.value("current_field") if s.value("current_field") else None) if x)
            base = f"Vous envisagez des études en Allemagne" + (f", notamment {desired}" if desired else "")
            if s.value("study_language"):
                base += f" avec un enseignement en {s.value('study_language')}"
            if current:
                base += f", après {current}"
            others = [TRACK_LABELS[track] for track in s.tracks if track != "etudes"]
            if others:
                base += "; vous avez aussi évoqué " + " et ".join(others)
        else:
            project = ({"ausbildung": "une Ausbildung", "emploi": "un emploi", "volontariat": "un volontariat"}.get(s.primary, tracks)
                       if len(s.tracks) == 1 else f"plusieurs pistes ({tracks})")
            base = f"Vous envisagez {project} en Allemagne"
            if s.value("desired_field"):
                base += f" dans le domaine {s.value('desired_field')}"
            if s.primary == "ausbildung" and s.value("school_level"):
                base += f", avec un niveau scolaire déclaré : {s.value('school_level')}"
            if s.primary == "emploi" and s.value("current_degree"):
                base += f", avec une qualification déclarée : {s.value('current_degree')}"
        details = []
        for key, label in (("age", "âge"), ("german_level", "allemand"), ("english_level", "anglais"), ("experience", "expérience"),
                           ("timeline", "période"), ("country", "résidence")):
            if s.value(key):
                value = s.value(key)
                if key == "experience":
                    value = re.sub(r"\s+d['’ ]?expérience$", "", value, flags=re.I)
                details.append(f"{label} : {value}")
        return base + (" (" + "; ".join(details) + ")" if details else "") + "."

    def _stage_reply(self, s: Session, user_id: int, update_id: int, text: str) -> Reply:
        answer = normalize(text)
        if s.stage == "summary_confirm":
            if answer in YES:
                s.stage = "offer_contact"
                s.funnel_route = "consultation"
                return Reply(self._t(s,
                                     "Souhaitez-vous passer à la voie Premium et enregistrer ce profil afin que notre équipe commerciale l'examine ? Aucun paiement de consultation n'est demandé dans le bot.",
                                     "هل تريدون الانتقال إلى المسار المميز وتسجيل هذا الملف لكي يدرسه الفريق التجاري؟ لا يطلب البوت دفعا مقابل الاستشارة."),
                             [(self._t(s, "Oui", "نعم"), "offer:yes"),
                              (self._t(s, "Non merci", "لا شكرا"), "offer:no")])
            tracks, facts, _ = extract_declared(text)
            tracks = [track for track in tracks if track in SUPPORTED_TRACKS]
            if tracks or facts:
                if tracks:
                    s.tracks = tracks
                    s.primary = tracks[0] if len(tracks) == 1 else None
                for key, value in facts.items():
                    s.put(key, value)
                s.stage = "explore"
                s.asked = 0
                return self._next(s)
            s.stage = "explore"
            s.asked = 0
            s.current_slot = None
            return Reply("Bien sûr. Quel élément souhaitez-vous corriger ?")
        if s.stage == "offer_contact":
            return self._contact_flow(s, user_id, update_id, text)
        if s.stage == "last_name":
            if answer in NO:
                s.stage = "paused" if s.primary else "idle"
                return Reply("D'accord. Aucune nouvelle demande n'est enregistrée ; vous pouvez continuer à poser des questions.")
            if any(char.isdigit() for char in text) or not re.fullmatch(r"[A-Za-zÀ-ÿ\u0600-\u06ff][A-Za-zÀ-ÿ\u0600-\u06ff' -]{1,79}", text):
                return Reply("Quel nom de famille souhaitez-vous indiquer ? Évitez les chiffres et les noms de documents.")
            s.last_name = text.strip()
            s.stage = "first_name"
            return Reply(self._t(s, "Quel est votre prénom ?", "ما هو اسمكم؟"))
        if s.stage == "first_name":
            if answer in NO:
                s.stage = "paused" if s.primary else "idle"
                return Reply("D'accord. Aucune nouvelle demande n'est enregistrée ; vous pouvez continuer à poser des questions.")
            if any(char.isdigit() for char in text) or not re.fullmatch(r"[A-Za-zÀ-ÿ\u0600-\u06ff][A-Za-zÀ-ÿ\u0600-\u06ff' -]{1,79}", text):
                return Reply("Quel prénom souhaitez-vous indiquer ? Évitez les chiffres et les noms de documents.")
            s.first_name = text.strip()
            s.contact_method = "telephone"
            s.stage = "contact_detail"
            return Reply(self._t(s,
                                 "Quel numéro de téléphone souhaitez-vous utiliser ? Vous pouvez écrire directement un mobile algérien, par exemple 0550123456, ou utiliser un indicatif international comme +213…",
                                 "ما هو رقم الهاتف الذي تريدون استعماله؟ يمكنكم كتابة رقم جزائري مباشرة مثل 0550123456 أو رقما دوليا يبدأ بمفتاح البلد."))
        if s.stage == "contact_detail":
            phone = normalize_contact_phone(text)
            if not phone:
                return Reply(self._t(s,
                                     "Ce numéro ne semble pas complet. Écrivez un mobile algérien de 10 chiffres, par exemple 0550123456, ou un numéro international avec son indicatif. Vous pouvez aussi utiliser /annuler.",
                                     "يبدو أن الرقم غير كامل. اكتبوا رقم هاتف جزائري من 10 أرقام مثل 0550123456 أو رقما دوليا مع مفتاح البلد. يمكنكم أيضا استعمال /annuler."))
            s.contact_detail = phone
            s.stage = "contact_confirm"
            return Reply(self._t(s, f"J'ai noté {phone} au format international. Est-ce correct ?",
                                 f"سجلت الرقم {phone} بالصيغة الدولية. هل هو صحيح؟"),
                         [(self._t(s, "Confirmer", "تأكيد"), "coord:yes"),
                          (self._t(s, "Corriger", "تصحيح"), "coord:no")])
        if s.stage == "contact_confirm":
            if answer in YES:
                s.contact_confirmed = True
                s.stage = "consent"
                return Reply(self._consent_text(s),
                             [(self._t(s, "J'accepte", "أوافق"), "consent:accept"),
                              (self._t(s, "Je refuse", "أرفض"), "consent:decline")])
            s.contact_detail = None
            s.contact_confirmed = False
            s.stage = "contact_detail"
            return Reply("D'accord. Quel numéro souhaitez-vous utiliser ? Vous pouvez écrire directement un mobile algérien comme 0550123456.")
        if s.stage == "consent":
            if answer not in {"j'accepte", "je refuse"}:
                return Reply("Pour enregistrer et transmettre la demande, choisissez « J'accepte » ou « Je refuse ». Vous pouvez continuer à poser des questions sans accepter.")
            if answer == "je refuse":
                s.stage = "paused" if s.primary else "idle"
                s.last_name = s.first_name = s.contact_detail = s.contact_method = None
                return Reply("Je respecte votre choix. Aucune nouvelle fiche ni coordonnée n'a été enregistrée ; vous pouvez continuer à poser des questions.")
            requested_offer = ("private_channel_access_requested"
                               if s.funnel_route == "private_channel" else "consultation_requested")
            data = {"primary_track": s.primary, "last_name": s.last_name, "first_name": s.first_name,
                    "contact_method": s.contact_method, "contact_detail": s.contact_detail,
                    "summary": self._summary(s), "open_questions": s.open_questions[:],
                    "profile": {"tracks": s.tracks[:], "facts": s.facts.copy(), "skipped": sorted(s.skipped),
                                "funnel_route": s.funnel_route, "lead_source": s.lead_source,
                                "offer_status": requested_offer}}
            if not s.contact_confirmed or not s.last_name or not s.first_name or not s.contact_detail:
                return Reply("Il manque un nom ou un numéro confirmé. Utilisez /humain pour reprendre.")
            try:
                saved = self.store.save(user_id, update_id, data, CONSENT_VERSION)
            except Exception:
                return Reply("Je n'ai pas pu enregistrer votre demande. Aucun rappel n'est confirmé. Réessayez plus tard ou continuez à poser des questions.")
            if not saved:
                return None
            s.stage = "idle"
            s.offer_status = requested_offer
            if s.funnel_route == "private_channel":
                return Reply("Votre demande d'accès au canal privé est enregistrée pour l'équipe RDW. Aucun paiement n'est validé par le bot ; l'équipe doit encore vous transmettre et confirmer les modalités. /mes_donnees permet de voir la fiche ; /supprimer permet de l'effacer.")
            return Reply(self._t(s,
                                 "Votre formulaire Premium est enregistré. Notre équipe commerciale va l'examiner avant de vous contacter pour planifier l'évaluation. Aucun créneau ni résultat n'est encore confirmé. /mes_donnees permet de voir la fiche ; /supprimer permet de l'effacer.",
                                 "تم تسجيل استمارة المرافقة المميزة. سيدرسها الفريق التجاري قبل الاتصال بكم لتحديد موعد التقييم. لم يتم بعد تأكيد موعد أو نتيجة. يمكنكم عرض البيانات عبر /mes_donnees وحذفها عبر /supprimer."))
        return Reply("Je n'ai pas compris. Vous pouvez utiliser /aide.")

    def _contact_flow(self, s: Session, user_id: int, update_id: int, text: str) -> Reply:
        if normalize(text) in NO:
            s.stage = "paused" if s.primary else "idle"
            return Reply("Bien entendu. Vous pouvez continuer à poser des questions ; aucune nouvelle demande n'est enregistrée.")
        if s.current_slot:
            s.current_slot = None
            s.asked = max(0, s.asked - 1)
        s.stage = "last_name"
        if s.funnel_route == "private_channel":
            return Reply(self._t(s,
                                 "Je vais préparer votre demande afin que l'équipe vous transmette les modalités du canal privé. Quel est votre nom de famille ?",
                                 "سأجهز طلبكم حتى يرسل لكم الفريق طريقة الدخول إلى القناة الخاصة. ما هو لقبكم؟"))
        s.funnel_route = "consultation"
        return Reply(self._t(s,
                             "Je vais préparer votre demande de consultation pour l'équipe RDW. Quel est votre nom de famille ?",
                             "سأجهز طلب الاستشارة لفريق RDW. ما هو لقبكم؟"))
