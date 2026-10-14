"""Commandes Telegram de revue, réservées aux comptes explicitement administrateurs."""
from __future__ import annotations

import re

from .knowledge_store import valid_answer, valid_video_url


ADMIN_COMMANDS = {"/admin", "/attente", "/faq_candidats", "/repondre", "/contenu",
                  "/faq_ajouter", "/video", "/paiements"}


class AdminService:
    def __init__(self, knowledge_store):
        self.store = knowledge_store

    def handle(self, admin_id: int, value: str) -> str:
        command, _, argument = value.strip().partition(" ")
        command = command.lower()
        if command == "/admin":
            return ("Gestion RDW : /attente, /repondre N réponse, /faq_candidats, "
                    "/faq_ajouter Question | Réponse, /contenu Question | Réponse, "
                    "/video Titre | https://..., /paiements. Les réponses publiées sont des faits validés par vous.")
        if command in {"/attente", "/faq_candidats"}:
            category = "needs_answer" if command == "/attente" else "faq_candidate"
            rows = self.store.list_questions(category, 10)
            if not rows:
                return "Aucune question dans cette liste."
            return "\n".join(f"#{item['id']} ({item['occurrences']} fois) {item['question']}" for item in rows)
        if command == "/repondre":
            match = re.fullmatch(r"(\d+)\s+(.+)", argument, re.S)
            if not match or not valid_answer(match.group(2)):
                return "Format : /repondre N réponse validée (8 à 900 caractères, sans coordonnées ni lien)."
            entry_id = self.store.answer_ticket(int(match.group(1)), match.group(2).strip(), admin_id)
            return (f"Réponse validée #{entry_id}, disponible pour cette question."
                    if entry_id else "Question introuvable ou déjà traitée.")
        if command in {"/contenu", "/faq_ajouter"}:
            question, separator, answer = argument.partition("|")
            question, answer = question.strip(), answer.strip()
            if not separator or not 8 <= len(question) <= 300 or not valid_answer(answer):
                return "Format : /contenu Question | Réponse, ou /faq_ajouter Question | Réponse. Sans coordonnées ni lien."
            kind = "faq" if command == "/faq_ajouter" else "answer"
            entry_id = self.store.add_entry(kind, question, answer, admin_id)
            return f"Contenu validé #{entry_id}." + (" Il apparaît dans /faq." if kind == "faq" else "")
        if command == "/video":
            title, separator, url = argument.partition("|")
            title, url = title.strip(), url.strip()
            if not separator or not 4 <= len(title) <= 100 or not valid_video_url(url):
                return "Format : /video Titre | lien HTTPS YouTube ou Vimeo. Une vidéo n'est pas une source RAG sans transcription validée."
            entry_id = self.store.add_entry("video", title, url, admin_id)
            return f"Vidéo #{entry_id} publiée dans /videos."
        if command == "/paiements":
            counts = self.store.payment_counts()
            return ("Paiements enregistrés : " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
                    if counts else "Aucun paiement enregistré. Aucune capture d'écran ne vaut vérification.")
        return "Commande administrateur inconnue. /admin affiche l'aide."
