import os
import re
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from dotenv import load_dotenv

from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

import aiofiles
import httpx  # For self-ping

# --- Init ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment ---
BOT_TOKEN     = os.getenv("BOT_TOKEN", "")
API_ID        = int(os.getenv("API_ID", "0"))
API_HASH      = os.getenv("API_HASH", "")
WEBHOOK_URL   = os.getenv("WEBHOOK_URL", "")
SESSION_NAME  = os.getenv("SESSION_NAME", "bot_session")
from_chat_id  = os.getenv("from_chat_id", "")
CACHE_FOLDER  = "cached_mp3s"
CACHE_TTL_HOURS = 3

link_pattern = re.compile(rf'https://t\.me/{from_chat_id}/(\d+)')

# --- FastAPI app ---
app = FastAPI()
os.makedirs(CACHE_FOLDER, exist_ok=True)

# --- In-memory cache ---
stream_cache: dict[int, dict] = {}

# --- Init Telethon client & Telegram Bot application ---
tele_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
bot_app = None  # will be set in startup

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Benvenut* al Radio Montello MP3 Streamer Bot! 🎧\n\n"
        f"Inviami un link da Radio Montello (es. https://t.me/{from_chat_id}/NUMERO) e ti darò un link per lo streaming.\n\n"
        "📌 Cosa puoi fare:\n"
        f"1️⃣ copia e incolla un link (non forward) ad un messaggio con file MP3 da Chat - RadioMontello.\n"
        "2️⃣ Ti restituisco un link streaming compatibile.\n\n"
        f"💡 Solo link da: https://t.me/{from_chat_id}"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    msg = update.message.text
    m = link_pattern.match(msg)
    if not m:
        await update.message.reply_text(
            f"⚠️ Invia solo link validi da https://t.me/{from_chat_id}"
        )
        return

    message_id = int(m.group(1))
    stream_url = f"{WEBHOOK_URL}/stream/{message_id}"

    expires_at = datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)
    file_path = os.path.join(CACHE_FOLDER, f"{message_id}.mp3")

    stream_cache[message_id] = {
        "url": stream_url,
        "expires_at": expires_at,
        "file_path": file_path
    }

    remaining = expires_at - datetime.utcnow()
    hours, minutes = divmod(remaining.seconds // 60, 60)

    await update.message.reply_text(
        f"🎧 Ecco il link per lo streaming:\n{stream_url}\n\n"
        f"⏳ Questo link scadrà tra: {hours} ore, {minutes} minuti."
    )

# --- FastAPI startup: connect both clients and schedule cleanup ---
@app.on_event("startup")
async def on_startup():
    global bot_app
    # 1) Start Telethon
    await tele_client.start(bot_token=BOT_TOKEN)
    logger.info("✅ Telethon client started")

    # 2) Start Telegram bot
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link)
    )
    await bot_app.initialize()
    await bot_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    logger.info("✅ Telegram Bot webhook set to %s/webhook", WEBHOOK_URL)

    # 3) Schedule cleanup task
    asyncio.create_task(cleanup_cache())
    logger.info("✅ Scheduled cleanup task")

    # 4) Schedule self-ping task
    asyncio.create_task(self_ping_task())
    logger.info("✅ Scheduled self-ping task")

# --- Webhook endpoint ---
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    asyncio.create_task(bot_app.process_update(update))
    return PlainTextResponse("OK")

# --- MP3 streaming endpoint ---
@app.get("/stream/{message_id}")
async def stream_file(message_id: int):
    info = stream_cache.get(message_id)
    if not info:
        raise HTTPException(404, "⚠️ Link non valido o mai richiesto.")
    if datetime.utcnow() > info["expires_at"]:
        raise HTTPException(410, "⛔ Link scaduto. Richiedi un nuovo link.")

    fp = info["file_path"]

    # Download if missing
    if not os.path.exists(fp):
        try:
            msg = await tele_client.get_messages(from_chat_id, ids=message_id)
            if not isinstance(msg.media, MessageMediaDocument):
                raise HTTPException(404, "❌ Non è un file valido.")
            doc: Document = msg.media.document
            if doc.mime_type != "audio/mpeg":
                raise HTTPException(415, "❌ Il file non è un MP3 valido.")

            await tele_client.download_media(msg, file=fp)
            logger.info("📥 File scaricato e salvato: %s", fp)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("[DOWNLOAD ERROR] %s", e, exc_info=True)
            raise HTTPException(500, "❌ Errore durante il download.")

    # Async generator to stream in 64KB chunks
    async def generate():
        async with aiofiles.open(fp, "rb") as f:
            while True:
                chunk = await f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    logger.info("🎧 Streaming file: %s", fp)
    return StreamingResponse(generate(), media_type="audio/mpeg")

# --- Root page ---
@app.get("/")
async def home():
    return PlainTextResponse("🎉 Benvenut* al Radio Montello MP3 Streamer Bot! 🎧")

# --- Cleanup Task ---
async def cleanup_cache():
    while True:
        now = datetime.utcnow()
        for mid, info in list(stream_cache.items()):
            if now > info["expires_at"]:
                try:
                    os.remove(info["file_path"])
                    logger.info("🗑️ File rimosso: %s", info["file_path"])
                except FileNotFoundError:
                    pass
                stream_cache.pop(mid, None)
        await asyncio.sleep(300)

# --- Self Ping Task (every 14 minutes) ---
async def self_ping_task():
    while True:
        try:
            url = f"{WEBHOOK_URL}/"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                logger.info("🔁 Self-ping response: %s", resp.status_code)
        except Exception as e:
            logger.error("❌ Self-ping failed: %s", e)
        await asyncio.sleep(840)  # 14 minutes

# --- Run via Uvicorn ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
