"""Transport webhook Telegram adapté aux services qui peuvent se mettre en veille."""
from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable

from telegram import Update
from telegram.ext import Application


ALLOWED_UPDATES = ["message", "callback_query"]


class TelegramWebhookBridge:
    """Transfère un POST reçu par le serveur HTTP vers la boucle asyncio de PTB."""

    def __init__(self, application: Application, loop: asyncio.AbstractEventLoop):
        self.application = application
        self.loop = loop

    def submit(self, payload: dict) -> bool:
        if not isinstance(payload.get("update_id"), int):
            return False
        update = Update.de_json(payload, self.application.bot)
        if update is None:
            return False
        future = asyncio.run_coroutine_threadsafe(self.application.update_queue.put(update), self.loop)
        future.result(timeout=2)
        return True


async def run_webhook_application(
    application: Application,
    *,
    public_url: str,
    webhook_path: str,
    webhook_secret: str,
    start_server: Callable[[Callable[[dict], bool], Callable[[], bool]], object],
    on_ready: Callable[[], None],
) -> None:
    """Démarre PTB et HTTP sans supprimer le webhook lors d'une mise en veille."""
    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()
    ready = threading.Event()
    bridge = TelegramWebhookBridge(application, loop)
    server = start_server(bridge.submit, ready.is_set)
    initialized = False
    started = False

    def request_stop(*_args) -> None:
        loop.call_soon_threadsafe(stopping.set)

    installed_signals = []
    for name in ("SIGTERM", "SIGINT"):
        current_signal = getattr(signal, name, None)
        if current_signal is None:
            continue
        try:
            loop.add_signal_handler(current_signal, request_stop)
            installed_signals.append(current_signal)
        except (NotImplementedError, RuntimeError):
            signal.signal(current_signal, request_stop)

    try:
        await application.initialize()
        initialized = True
        if application.post_init:
            await application.post_init(application)
        await application.start()
        started = True
        expected_url = f"{public_url}{webhook_path}"
        registered = await application.bot.set_webhook(
            url=expected_url,
            secret_token=webhook_secret,
            allowed_updates=ALLOWED_UPDATES,
            max_connections=10,
            drop_pending_updates=False,
        )
        if not registered:
            raise RuntimeError("Telegram a refusé l'enregistrement du webhook.")
        webhook_info = await application.bot.get_webhook_info()
        if webhook_info.url != expected_url:
            raise RuntimeError("Telegram ne confirme pas l'URL du webhook.")
        ready.set()
        on_ready()
        await stopping.wait()
    finally:
        ready.clear()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        if started:
            await application.stop()
            if application.post_stop:
                await application.post_stop(application)
        if initialized:
            await application.shutdown()
            if application.post_shutdown:
                await application.post_shutdown(application)
        for current_signal in installed_signals:
            loop.remove_signal_handler(current_signal)
