"""Entrée CLI du bot RDW. Le démarrage n'utilise que telegram-bot/.env."""
from __future__ import annotations

import argparse
import asyncio
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Conflict
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from .config import load_config
from .admin import AdminService, ADMIN_COMMANDS
from .conversation import ConversationService
from .knowledge_store import PostgresKnowledgeStore
from .lead_store import PostgresLeadStore
from .gemini_dialogue import GeminiDialogue, UsageLimit
from .groq_dialogue import GroqDialogue
from .qa import PrivateQAService
from .rag import Corpus
from .service import Service
from .store import PostgresStore
from .dashboard import start_dashboard
from .webhook import run_webhook_application


logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "telegram", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.CRITICAL)
LOG = logging.getLogger("rdw_bot")
RUNTIME = Path(__file__).resolve().parents[1] / ".runtime"


@contextmanager
def single_instance():
    RUNTIME.mkdir(exist_ok=True)
    path = RUNTIME / "bot.lock"
    if not path.exists():
        path.write_bytes(b"0")
    try:
        lock_file = path.open("r+b")
    except OSError:
        raise SystemExit("Une instance du bot est déjà lancée sur ce PC.") from None
    with lock_file as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("Une instance du bot est déjà lancée sur ce PC.") from None
        (RUNTIME / "bot.pid").write_text(str(os.getpid()), encoding="ascii")
        try:
            yield
        finally:
            (RUNTIME / "bot.pid").unlink(missing_ok=True)
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def record_ready(authorized_count: int, mode: str, ai_enabled: bool = False,
                 provider: str | None = None, model: str | None = None,
                 access_mode: str = "private", dashboard_url: str | None = None):
    (RUNTIME / "ready.json").write_text(json.dumps({
        "connected_at": datetime.now(timezone.utc).isoformat(),
        "bot_username": "RDW_assistant_bot",
        "authorized_count": authorized_count,
        "mode": mode,
        "access_mode": access_mode,
        "ai_enabled": ai_enabled,
        "ai_provider": provider if ai_enabled else None,
        "ai_model": model if ai_enabled else None,
        "dashboard_url": dashboard_url,
    }), encoding="utf-8")


def record_exchange(kind: str):
    """Compteurs de contrôle sans identifiant, contenu de message ni coordonnées."""
    path = RUNTIME / "exchanges.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data[kind] = int(data.get(kind, 0)) + 1
        data["last_reply_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        LOG.error("Compteur de réponse indisponible")


def watch_stop_request(application: Application):
    loop = asyncio.get_running_loop()

    def watcher():
        request = RUNTIME / "stop.request"
        while not request.exists():
            time.sleep(1)
        request.unlink(missing_ok=True)
        loop.call_soon_threadsafe(application.stop_running)

    threading.Thread(target=watcher, name="rdw-stop-watcher", daemon=True).start()


def keyboard(buttons):
    if not buttons:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=value)] for label, value in buttons])


def normalize_telegram_command(value: str) -> str:
    """Retire le suffixe @nom_du_bot ajouté par Telegram aux commandes."""
    stripped = value.strip()
    if not stripped:
        return value
    parts = stripped.split(maxsplit=1)
    first = parts[0]
    if first.startswith("/") and "@" in first:
        first = first.split("@", 1)[0]
    return first + (" " + parts[1] if len(parts) == 2 else "")


def private_access_allowed(user_id: int, value: str, allowed_user_ids: frozenset[int]) -> bool:
    normalized = normalize_telegram_command(value)
    first = normalized.split(maxsplit=1)[0].lower() if normalized else ""
    return user_id in allowed_user_ids or first == "/id"


async def flush_review_notifications(application: Application):
    store = application.bot_data.get("review_store")
    admins = application.bot_data.get("admin_user_ids", frozenset())
    if not store or not admins:
        return
    try:
        pending = await asyncio.to_thread(store.pending_notifications, 5)
    except Exception:
        LOG.error("File de revue indisponible")
        return
    for item in pending:
        context = dict(item.get("context") or {})
        # Une question posée par l'administrateur pendant ses essais reste dans /attente,
        # mais ne doit pas réapparaître comme alerte dans sa conversation client.
        if context.pop("origine_admin", False):
            await asyncio.to_thread(store.mark_notified, item["id"])
            continue
        message = (f"Question RDW #{item['id']} à traiter :\n{item['question']}\n"
                   f"Contexte sans identité : {json.dumps(context, ensure_ascii=False)}\n"
                   f"Répondez avec /repondre {item['id']} votre réponse validée.")
        try:
            for admin_id in admins:
                await application.bot.send_message(admin_id, message[:3900])
            await asyncio.to_thread(store.mark_notified, item["id"])
        except Exception:
            LOG.error("Notification RDW non remise ; elle reste en attente")
            return


async def flush_lead_notifications(application: Application):
    store = application.bot_data.get("lead_store")
    admins = application.bot_data.get("admin_user_ids", frozenset())
    if not store or not admins or not hasattr(store, "pending_admin_notifications"):
        return
    try:
        pending = await asyncio.to_thread(store.pending_admin_notifications, 5)
        for item in pending:
            profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
            facts = profile.get("facts") if isinstance(profile.get("facts"), dict) else {}
            details = ", ".join(
                f"{key}={value.get('value')}" for key, value in facts.items()
                if isinstance(value, dict) and value.get("status") == "declared"
            )
            message = (
                "Nouvelle demande Premium confirmée\n"
                f"Nom : {item.get('last_name') or '-'}\nPrénom : {item.get('first_name') or '-'}\n"
                f"Téléphone : {item.get('phone') or '-'}\nProjet : {item.get('summary') or '-'}\n"
                f"Profil : {details or '-'}"
            )
            for admin_id in admins:
                await application.bot.send_message(admin_id, message[:3900])
            await asyncio.to_thread(store.mark_admin_notified, item["user_id"])
    except Exception:
        LOG.error("Notification de demande Premium non remise")


async def flush_payment_notifications(application: Application):
    store = application.bot_data.get("review_store")
    admins = application.bot_data.get("admin_user_ids", frozenset())
    if not store or not admins or not hasattr(store, "pending_payment_receipts"):
        return
    try:
        pending = await asyncio.to_thread(store.pending_payment_receipts, 5)
        for item in pending:
            buttons = keyboard([
                ("✅ Valider le paiement", f"payment:approve:{item['id']}"),
                ("❌ Refuser", f"payment:reject:{item['id']}"),
            ])
            caption = (f"Reçu VIP #{item['id']} — {item['amount_dzd']} DA\n"
                       f"Client Telegram : {item['user_id']}\n"
                       "Vérifiez visuellement le montant et le bénéficiaire avant de valider.")
            for admin_id in admins:
                await application.bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=item["source_chat_id"],
                    message_id=item["source_message_id"],
                    caption=caption,
                    reply_markup=buttons,
                )
            await asyncio.to_thread(store.mark_payment_notified, item["id"])
    except Exception:
        LOG.error("Notification de reçu non remise")


def _payment_media(message):
    if message.photo:
        photo = message.photo[-1]
        return "photo", photo.file_id, photo.file_unique_id
    document = message.document
    if document and (document.mime_type == "application/pdf" or (document.mime_type or "").startswith("image/")):
        return "pdf" if document.mime_type == "application/pdf" else "photo", document.file_id, document.file_unique_id
    return None


async def review_payment(application: Application, admin_id: int, payment_id: int, approve: bool) -> str:
    store = application.bot_data.get("review_store")
    if not store or not hasattr(store, "get_payment"):
        return "Gestion des paiements indisponible."
    payment = await asyncio.to_thread(store.get_payment, payment_id)
    if not payment:
        return f"Reçu #{payment_id} introuvable."
    if payment["status"] != "unverified":
        return f"Reçu #{payment_id} déjà traité : {payment['status']}."
    if not approve:
        reviewed = await asyncio.to_thread(store.review_payment, payment_id, admin_id, "rejected")
        if not reviewed:
            return f"Reçu #{payment_id} déjà traité."
        await application.bot.send_message(
            payment["user_id"],
            f"Le reçu #{payment_id} n'a pas été validé. Vérifiez le montant et le bénéficiaire, puis envoyez une nouvelle preuve lisible dans cette conversation.",
        )
        return f"Reçu #{payment_id} refusé. Le client a été informé."
    channel_id = str(application.bot_data.get("vip_channel_id") or "").strip()
    if not channel_id:
        return "VIP_CHANNEL_ID n'est pas configuré sur Render. Le reçu reste en attente."
    try:
        telegram_channel = int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id
        invite = await application.bot.create_chat_invite_link(
            chat_id=telegram_channel,
            member_limit=1,
            name=f"RDW VIP reçu {payment_id}",
        )
    except Exception:
        LOG.error("Création du lien VIP impossible")
        return ("Impossible de créer le lien VIP. Vérifiez VIP_CHANNEL_ID et que le bot est administrateur "
                "du canal avec le droit d'inviter. Le reçu reste en attente.")
    reviewed = await asyncio.to_thread(
        store.review_payment, payment_id, admin_id, "verified", invite.invite_link,
    )
    if not reviewed:
        return f"Reçu #{payment_id} déjà traité."
    try:
        await application.bot.send_message(
            payment["user_id"],
            "Votre paiement VIP a été validé. Voici votre lien personnel, utilisable une seule fois :\n"
            + invite.invite_link,
        )
    except Exception:
        return (f"Reçu #{payment_id} validé et lien créé, mais Telegram n'a pas pu le remettre au client. "
                "Le lien reste enregistré dans la base.")
    return f"Reçu #{payment_id} validé. Le lien unique a été envoyé au client."


async def dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_chat or update.effective_chat.type != "private":
        return
    callback = update.callback_query
    media = None
    if callback:
        await callback.answer()
        value = callback.data if isinstance(callback.data, str) else ""
    elif update.message and update.message.text:
        value = normalize_telegram_command(update.message.text)
    elif update.message and (media := _payment_media(update.message)):
        value = ""
    else:
        if update.message:
            await update.message.reply_text("Ce type de fichier n'est pas accepté. Pour un reçu VIP, envoyez une photo ou un PDF après avoir choisi /canal.")
        return
    access_restricted = context.application.bot_data.get("access_restricted", False)
    if access_restricted:
        allowed = context.application.bot_data["allowed_user_ids"]
        if not private_access_allowed(update.effective_user.id, value, allowed):
            await context.bot.send_message(update.effective_chat.id,
                "Ce test est privé. Envoyez /id pour obtenir votre identifiant numérique, puis demandez à l'administrateur de l'ajouter à la liste autorisée.")
            record_exchange("denied")
            return
    service = context.application.bot_data["service"]
    command = value.strip().split(maxsplit=1)[0].lower() if value.strip() else ""
    if callback and value.startswith("payment:"):
        admins = context.application.bot_data.get("admin_user_ids", frozenset())
        if update.effective_user.id not in admins:
            await context.bot.send_message(update.effective_chat.id, "Action réservée à l'administrateur RDW.")
            return
        match = re.fullmatch(r"payment:(approve|reject):(\d+)", value)
        if not match:
            await context.bot.send_message(update.effective_chat.id, "Action de paiement invalide.")
            return
        answer = await review_payment(context.application, update.effective_user.id,
                                      int(match.group(2)), match.group(1) == "approve")
        await context.bot.send_message(update.effective_chat.id, answer)
        return
    if media:
        try:
            reply = await asyncio.to_thread(
                service.receive_payment_receipt,
                update.effective_user.id,
                update.update_id,
                media_type=media[0], file_id=media[1], file_unique_id=media[2],
                source_chat_id=update.effective_chat.id,
                source_message_id=update.message.message_id,
            )
        except Exception:
            LOG.error("Réception du reçu indisponible")
            await context.bot.send_message(update.effective_chat.id, "Le reçu n'a pas pu être enregistré. Réessayez plus tard.")
            return
        await context.bot.send_message(update.effective_chat.id, reply.text)
        await flush_payment_notifications(context.application)
        return
    if command in ADMIN_COMMANDS:
        admins = context.application.bot_data.get("admin_user_ids", frozenset())
        if update.effective_user.id not in admins:
            await context.bot.send_message(update.effective_chat.id, "Commande réservée à l'administrateur RDW.")
            return
        try:
            payment_command = re.fullmatch(r"/(valider_paiement|refuser_paiement)\s+(\d+)", value, re.I)
            if payment_command:
                answer = await review_payment(
                    context.application, update.effective_user.id, int(payment_command.group(2)),
                    payment_command.group(1).lower() == "valider_paiement",
                )
            else:
                answer = await asyncio.to_thread(context.application.bot_data["admin_service"].handle,
                                                 update.effective_user.id, value)
        except Exception:
            LOG.error("Gestion RDW indisponible")
            answer = "Gestion indisponible. Réessayez plus tard."
        await context.bot.send_message(update.effective_chat.id, answer)
        return
    try:
        reply = await asyncio.to_thread(service.handle, update.effective_user.id, update.update_id, value, bool(callback))
    except Exception:
        LOG.error("Traitement indisponible (sans contenu de message)")
        await context.bot.send_message(update.effective_chat.id, "Service momentanément indisponible. Réessayez plus tard.")
        return
    if reply:
        review_store = context.application.bot_data.get("review_store")
        if review_store and not callback and command != "/supprimer":
            try:
                await asyncio.to_thread(review_store.append_turn, update.effective_user.id,
                                        update.update_id, value, reply.text)
            except Exception:
                LOG.error("Historique volontaire indisponible")
                reply.text += "\n\nL'historique n'a pas pu être enregistré pour ce message."
        if reply.document_path:
            document_path = Path(reply.document_path)
            if not document_path.is_file():
                LOG.error("Document RDW indisponible")
                await context.bot.send_message(
                    update.effective_chat.id,
                    "L'Ebook RDW est momentanément indisponible. Réessayez avec /start.",
                    reply_markup=keyboard(reply.buttons),
                )
            else:
                with document_path.open("rb") as document:
                    await context.bot.send_document(
                        update.effective_chat.id,
                        document=document,
                        filename=document_path.name,
                        caption=reply.text,
                        reply_markup=keyboard(reply.buttons),
                    )
        else:
            await context.bot.send_message(update.effective_chat.id, reply.text, reply_markup=keyboard(reply.buttons))
        if access_restricted:
            record_exchange("id" if command == "/id" else "authorized")
        await flush_review_notifications(context.application)
        await flush_lead_notifications(context.application)
        await flush_payment_notifications(context.application)


async def on_error(_update: object, context: ContextTypes.DEFAULT_TYPE):
    LOG.error("Erreur réseau ou Telegram : %s", type(context.error).__name__)
    if isinstance(context.error, Conflict):
        context.application.stop_running()


def validate_bot_username(username: str | None):
    if (username or "").casefold() != "rdw_assistant_bot":
        raise RuntimeError("Le token Telegram ne correspond pas à @RDW_assistant_bot. Démarrage annulé.")


def build_application(token: str, service, *, private_mode: bool = False, assistant_mode: bool = False,
                      allowed_user_ids: frozenset[int] = frozenset(),
                      ai_enabled: bool = False, ai_provider: str | None = None, ai_model: str | None = None,
                      review_store=None, admin_user_ids: frozenset[int] = frozenset(),
                      restrict_access: bool | None = None, dashboard_url: str | None = None,
                      lead_store=None, vip_channel_id: str = "") -> Application:
    access_restricted = private_mode if restrict_access is None else restrict_access

    async def verify_bot(application: Application):
        identity = await application.bot.get_me()
        validate_bot_username(identity.username)
        commands = [("start", "Accueil"), ("aide", "Aide"), ("id", "Voir mon identifiant Telegram")]
        if not private_mode:
            commands += [("fiche", "Commencer ou reprendre ma fiche"),
                         ("humain", "Demander un conseiller"), ("annuler", "Interrompre la fiche"),
                         ("mes_donnees", "Voir mes données"), ("supprimer", "Effacer mes données")]
        if assistant_mode:
            commands += [("reprendre", "Reprendre mon projet"), ("source", "Voir la source de la dernière réponse")]
            commands += [("guide", "Sujets du guide RDW"), ("faq", "Questions fréquentes"), ("videos", "Vidéos RDW"),
                         ("historique", "Gestion de votre historique")]
        await application.bot.set_my_commands(commands)
        if (private_mode or assistant_mode) and not application.bot_data.get("defer_ready"):
            record_ready(len(allowed_user_ids), "assistant" if assistant_mode else "private_qa",
                         ai_enabled, ai_provider, ai_model,
                         "private" if access_restricted else "public", dashboard_url)
            watch_stop_request(application)
        if assistant_mode:
            await flush_review_notifications(application)
            await flush_lead_notifications(application)
            await flush_payment_notifications(application)

    app = Application.builder().token(token).post_init(verify_bot).concurrent_updates(False).build()
    app.bot_data["service"] = service
    app.bot_data["access_restricted"] = access_restricted
    app.bot_data["allowed_user_ids"] = allowed_user_ids
    app.bot_data["review_store"] = review_store
    app.bot_data["lead_store"] = lead_store
    app.bot_data["admin_user_ids"] = admin_user_ids
    app.bot_data["vip_channel_id"] = vip_channel_id
    if review_store:
        app.bot_data["admin_service"] = AdminService(review_store)
    names = ("start", "aide", "id", "fiche", "humain", "annuler", "reprendre", "source", "guide",
             "mes_donnees", "supprimer", "faq", "videos", "historique", "historique_on", "historique_off",
             "admin", "attente", "faq_candidats", "repondre", "contenu", "faq_ajouter", "video", "paiements")
    names += ("valider_paiement", "refuser_paiement")
    for name in names:
        app.add_handler(CommandHandler(name, dispatch))
    app.add_handler(CallbackQueryHandler(dispatch))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dispatch))
    app.add_handler(MessageHandler(filters.ALL, dispatch))
    app.add_error_handler(on_error)
    return app


def export_handoffs(store: PostgresStore, path: Path):
    # Destination choisie par l'opérateur local ; pas d'API publique ni envoi automatique.
    path = path.resolve()
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        if isinstance(store, PostgresLeadStore):
            writer.writerow(("telegram_user_id", "filiere", "nom", "prenom", "contact", "projet", "mise_a_jour",
                             "contact_method", "profile_json", "open_questions", "consent_at", "consent_version",
                             "source", "orientation", "statut_offre"))
        else:
            writer.writerow(("telegram_user_id", "filiere", "prenom", "contact", "projet", "mise_a_jour"))
        for row in store.export_handoffs():
            safe = []
            for value in row:
                cell = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
                if cell.startswith(("=", "+", "-", "@")):
                    cell = "'" + cell
                safe.append(cell)
            writer.writerow(safe)
    print(f"Export créé : {path}")


def build_ai_composer(config):
    """Construit uniquement le fournisseur explicitement sélectionné."""
    if config.ai_provider == "groq":
        if not config.groq_key:
            raise ValueError("GROQ_API_KEY absente dans .env.")
        usage = UsageLimit(RUNTIME / "ai_usage_groq.json", config.gemini_limits)
        return GroqDialogue(config.groq_key, config.groq_model, config.gemini_limits, usage)
    if config.ai_provider == "gemini":
        if not config.gemini_key:
            raise ValueError("GEMINI_API_KEY absente dans .env.")
        usage = UsageLimit(RUNTIME / "ai_usage_gemini.json", config.gemini_limits)
        return GeminiDialogue(config.gemini_key, config.gemini_model, config.gemini_limits, usage)
    raise ValueError("AI_PROVIDER doit valoir groq ou gemini lorsque AI_ENABLED=true.")


def selected_ai_model(config) -> str | None:
    if not config.ai_enabled:
        return None
    return config.groq_model if config.ai_provider == "groq" else config.gemini_model


def main():
    parser = argparse.ArgumentParser(description="Assistant Telegram RDW")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("init-db")
    sub.add_parser("check-ai", help="Une question synthétique pour vérifier le fournisseur IA, sans Telegram ni données personnelles")
    export = sub.add_parser("export-handoffs")
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_config()
    if args.command == "check-ai":
        if not config.ai_enabled:
            parser.error("check-ai exige AI_ENABLED=true et une clé dédiée au fournisseur choisi dans .env.")
        from .conversation import Session
        corpus = Corpus()
        try:
            composer = build_ai_composer(config)
        except ValueError as exc:
            parser.error(str(exc))
        passage = next(p for p in corpus.passages if p["id"] == "filieres")
        answer = composer.compose(user_id=0, message="Quels parcours RDW accompagne-t-elle ?",
                                  session=Session(), passages=[passage])
        if not answer:
            raise SystemExit(f"Échec du contrôle {composer.provider_label} : connexion, quota ou réponse non conforme. Aucun appel Telegram lancé.")
        print(f"{composer.provider_label} a répondu avec {composer.model} à la question synthétique : {answer}")
        return
    if args.command == "run" and not config.token:
        parser.error("TELEGRAM_BOT_TOKEN absent dans telegram-bot/.env. Aucun transport Telegram lancé.")
    if config.bot_mode not in {"private_qa", "assistant", "full"}:
        parser.error("BOT_MODE doit valoir private_qa, assistant ou full.")
    if config.telegram_transport == "webhook" and config.bot_mode != "assistant":
        parser.error("TELEGRAM_TRANSPORT=webhook exige BOT_MODE=assistant.")
    if config.bot_mode != "assistant" and config.ai_enabled:
        parser.error("L'IA est autorisée uniquement avec BOT_MODE=assistant dans ce test privé.")
    if args.command in {"init-db", "export-handoffs"} or config.bot_mode in {"assistant", "full"}:
        if not config.database_url:
            parser.error("DATABASE_URL absent dans telegram-bot/.env (PostgreSQL requis pour ce mode).")
        store = PostgresLeadStore(config.database_url) if config.bot_mode == "assistant" or args.command in {"init-db", "export-handoffs"} else PostgresStore(config.database_url)
    else:
        store = None
    if args.command == "init-db":
        store.init_schema()
        print("Schéma telegram prêt.")
        return
    if args.command == "export-handoffs":
        store.check_schema()
        export_handoffs(store, args.output)
        return
    if config.bot_mode == "private_qa":
        service = PrivateQAService()
        app = build_application(config.token, service, private_mode=True,
                                allowed_user_ids=config.allowed_user_ids)
        print("Mode privé documentaire en démarrage. Arrêt : Ctrl+C.")
        with single_instance():
            (RUNTIME / "ready.json").unlink(missing_ok=True)
            (RUNTIME / "stop.request").unlink(missing_ok=True)
            try:
                app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=False)
            except Exception:
                raise SystemExit("Démarrage impossible : vérifiez le token Telegram et le réseau.") from None
        return
    if config.bot_mode == "assistant":
        store.check_schema()
        review_store = PostgresKnowledgeStore(config.database_url)
        dashboard_server = None
        dashboard_url = (config.webhook_public_url if config.telegram_transport == "webhook" else
                         f"http://{config.dashboard_host}:{config.dashboard_port}")
        composer = None
        if config.ai_enabled:
            try:
                composer = build_ai_composer(config)
            except ValueError as exc:
                parser.error(str(exc))
        service = ConversationService(store, composer=composer, review_store=review_store,
                                      admin_user_ids=config.admin_user_ids,
                                      private_channel_price_dzd=config.private_channel_price_dzd,
                                      payment_proof_telegram=config.payment_proof_telegram,
                                      baridimob_payment_details=config.baridimob_payment_details,
                                      ccp_payment_details=config.ccp_payment_details,
                                      ccp_account_holder_name=config.ccp_account_holder_name,
                                      debug_source_labels=config.debug_source_labels)
        app = build_application(config.token, service, assistant_mode=True,
                                allowed_user_ids=config.allowed_user_ids,
                                ai_enabled=config.ai_enabled, ai_provider=config.ai_provider,
                                ai_model=selected_ai_model(config),
                                review_store=review_store, admin_user_ids=config.admin_user_ids,
                                restrict_access=config.telegram_access_mode == "private",
                                dashboard_url=dashboard_url, lead_store=store,
                                vip_channel_id=config.vip_channel_id)
        if config.telegram_transport == "webhook":
            if not config.dashboard_enabled:
                parser.error("DASHBOARD_ENABLED=true est requis : le serveur HTTP reçoit aussi le webhook Telegram.")
            app.bot_data["defer_ready"] = True

            def start_web_server(webhook_callback, health_ready):
                return start_dashboard(
                    config.database_url,
                    config.dashboard_host,
                    config.dashboard_port,
                    config.dashboard_username,
                    config.dashboard_password,
                    health_ready=health_ready,
                    webhook_path=config.telegram_webhook_path,
                    webhook_secret=config.telegram_webhook_secret,
                    webhook_callback=webhook_callback,
                )

            def mark_webhook_ready():
                record_ready(len(config.allowed_user_ids), "assistant", config.ai_enabled,
                             config.ai_provider, selected_ai_model(config), config.telegram_access_mode,
                             dashboard_url)

            print("Assistant RDW en démarrage avec webhook Telegram.")
            with single_instance():
                (RUNTIME / "ready.json").unlink(missing_ok=True)
                try:
                    asyncio.run(run_webhook_application(
                        app,
                        public_url=config.webhook_public_url,
                        webhook_path=config.telegram_webhook_path,
                        webhook_secret=config.telegram_webhook_secret,
                        start_server=start_web_server,
                        on_ready=mark_webhook_ready,
                    ))
                except Exception:
                    raise SystemExit(
                        "Démarrage webhook impossible : vérifiez Neon, Telegram, l'URL HTTPS et les variables cloud."
                    ) from None
            return

        if config.dashboard_enabled:
            try:
                dashboard_server = start_dashboard(config.database_url, config.dashboard_host,
                                                   config.dashboard_port,
                                                   config.dashboard_username,
                                                   config.dashboard_password,
                                                   health_ready=lambda: (RUNTIME / "ready.json").exists())
            except (OSError, ValueError) as exc:
                parser.error(f"Dashboard local indisponible : {exc}")
        print("Assistant RDW en démarrage avec polling. Arrêt : stop-private.ps1.")
        try:
            with single_instance():
                (RUNTIME / "ready.json").unlink(missing_ok=True)
                (RUNTIME / "stop.request").unlink(missing_ok=True)
                try:
                    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=False)
                except Exception:
                    raise SystemExit("Démarrage impossible : vérifiez PostgreSQL, le token Telegram et le réseau.") from None
        finally:
            if dashboard_server:
                dashboard_server.shutdown()
                dashboard_server.server_close()
        return
    store.check_schema()
    service = Service(store)
    app = build_application(config.token, service)
    print("Bot RDW en démarrage. Arrêt : Ctrl+C.")
    try:
        with single_instance():
            app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=False)
    except Exception:
        raise SystemExit("Démarrage impossible : vérifiez le token Telegram, le réseau et PostgreSQL.") from None


if __name__ == "__main__":
    main()
