import asyncio

from telegram.ext import Application

from bot.webhook import TelegramWebhookBridge


def test_webhook_bridge_enqueues_a_telegram_update():
    async def scenario():
        application = Application.builder().token("123456:TEST_TOKEN").build()
        bridge = TelegramWebhookBridge(application, asyncio.get_running_loop())
        accepted = await asyncio.to_thread(bridge.submit, {
            "update_id": 456,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": 99, "type": "private"},
                "from": {"id": 99, "is_bot": False, "first_name": "Test"},
                "text": "bonjour",
            },
        })
        update = await asyncio.wait_for(application.update_queue.get(), timeout=1)
        assert accepted is True
        assert update.update_id == 456
        assert update.message.text == "bonjour"

    asyncio.run(scenario())


def test_webhook_bridge_rejects_payload_without_update_id():
    async def scenario():
        application = Application.builder().token("123456:TEST_TOKEN").build()
        bridge = TelegramWebhookBridge(application, asyncio.get_running_loop())
        assert await asyncio.to_thread(bridge.submit, {"message": {}}) is False
        assert application.update_queue.empty()

    asyncio.run(scenario())
