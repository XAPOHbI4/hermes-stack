#!/usr/bin/env python3
"""Send a Telegram message as a Bot API 10.1 Rich Message (native markdown:
tables, etc.) — the same sendRichMessage path the gateway uses for replies.

Reads markdown from stdin. Env: TELEGRAM_BOT_TOKEN, CHAT_ID.
Long content is split into <=LIMIT-char parts at line boundaries and sent
sequentially (marked "(k/n)") instead of being hard-truncated mid-sentence.
Falls back to plain sendMessage per part if the rich endpoint is unavailable.
"""
import sys, os, asyncio

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

LIMIT = 3800  # Telegram hard cap is 4096; leave room for the "(k/n)" footer


def split_parts(text):
    text = text.rstrip()
    if len(text) <= LIMIT:
        return [text]
    parts, cur = [], ""
    for line in text.split('\n'):
        while len(line) > LIMIT:                      # pathological single long line
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:LIMIT]); line = line[LIMIT:]
        if cur and len(cur) + 1 + len(line) > LIMIT:
            parts.append(cur); cur = line
        else:
            cur = (cur + '\n' + line) if cur else line
    if cur:
        parts.append(cur)
    return parts


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

    parts = split_parts(md)
    n = len(parts)

    async def go():
        bot = Bot(token)
        ok = True
        for i, part in enumerate(parts, 1):
            body = part if n == 1 else f"{part}\n\n_({i}/{n})_"
            try:
                await bot.do_api_request("sendRichMessage", api_kwargs={
                    "chat_id": int(chat),
                    "rich_message": {"markdown": body},
                    "link_preview_options": {"is_disabled": True},
                })
            except Exception as e:
                try:
                    await bot.send_message(chat_id=int(chat), text=body,
                                           disable_web_page_preview=True)
                    print(f"part {i}/{n} plain_fallback ({type(e).__name__})")
                except Exception as e2:
                    print(f"rich_send: part {i}/{n} failed: {e2}", file=sys.stderr)
                    ok = False
            if i < n:
                await asyncio.sleep(1)   # preserve order, avoid flood limits
        print("rich_sent" if ok else "rich_sent_partial")
        return 0 if ok else 1

    return asyncio.run(go())


raise SystemExit(main())
