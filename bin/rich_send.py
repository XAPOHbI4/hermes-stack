#!/usr/bin/env python3
"""Send a Telegram message as a Bot API 10.1 Rich Message (native markdown:
tables, etc.) — the same sendRichMessage path the gateway uses for replies.

Reads markdown from stdin. Env: TELEGRAM_BOT_TOKEN, CHAT_ID.
Falls back to a plain sendMessage if the rich endpoint is unavailable.
"""
import sys, os, asyncio

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("CHAT_ID", "").strip()
    md = sys.stdin.read()
    if not token or not chat or not md.strip():
        print("rich_send: missing token/chat/body", file=sys.stderr)
        return 2
    try:
        from telegram import Bot
    except Exception as e:
        print(f"rich_send: ptb import failed: {e}", file=sys.stderr)
        return 2

    async def go():
        bot = Bot(token)
        try:
            await bot.do_api_request("sendRichMessage", api_kwargs={
                "chat_id": int(chat),
                "rich_message": {"markdown": md},
                "link_preview_options": {"is_disabled": True},
            })
            print("rich_sent")
            return 0
        except Exception as e:
            # capability / parser issue → fall back to plain text so the
            # digest still arrives (just without the native table).
            try:
                await bot.send_message(chat_id=int(chat), text=md,
                                       disable_web_page_preview=True)
                print(f"plain_fallback ({type(e).__name__}: {str(e)[:80]})")
                return 0
            except Exception as e2:
                print(f"rich_send: both failed: {e2}", file=sys.stderr)
                return 1

    return asyncio.run(go())


raise SystemExit(main())
