import os
import re
import asyncio
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from dotenv import load_dotenv
from datetime import datetime, timedelta
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import aiofiles
import nest_asyncio

# --- Init ---
load_dotenv()
nest_asyncio.apply()

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
SESSION_NAME = os.getenv("SESSION_NAME", "")
from_chat_id = os.getenv("from_chat_id", "")
CACHE_FOLDER = "cached_mp3s"
CACHE_TTL_HOURS = 2

link_pattern = re.compile(rf'https://t\.me/{from_chat_id}/(\d+)')

# FastAPI app
app = FastAPI()
os.makedirs(CACHE_FOLDER, exist_ok=True)

# --- Stream Cache ---
stream_cache = {}  # {message_id: {"url": str, "expires_at": datetime, "file_path": str}}

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Benvenut* al Radio Montello MP3 Streamer Bot! 🎧\n\n"
        f"Inviami un link da Radio Montello (es. https://t.me/{from_chat_id}/NUMERO) e ti darò un link per lo streaming.\n\n"
        "📌 Cosa puoi fare:\n"
        f"1️⃣ copia e incolla un link (non forward) ad un messaggio con file MP3 da {from_chat_id}.\n"
        "2️⃣ Ti restituisco un link streaming compatibile.\n\n"
        f"💡 Solo link da: https://t.me/{from_chat_id}"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    msg = update.message.text
    match = link_pattern.match(msg)
    if not match:
        await update.message.reply_text(f"⚠️ Invia solo link validi da https://t.me/{from_chat_id}")
        return

    message_id = int(match.group(1))
    stream_url = f"{WEBHOOK_URL}/stream/{message_id}"

    expires_at = datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)
    stream_cache[message_id] = {"url": stream_url, "expires_at": expires_at}

    remaining = expires_at - datetime.utcnow()
    hours, minutes = divmod(remaining.seconds // 60, 60)

    await update.message.reply_text(
        f"🎧 Ecco il link per lo streaming:\n{stream_url}\n\n"
        f"⏳ Questo link scadrà tra: {hours} ore, {minutes} minuti."
    )

# --- Bot Initialization ---
async def init_bot():
    bot = ApplicationBuilder().token(BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))
    await bot.initialize()
    await bot.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    return bot

# --- Webhook endpoint ---
@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, bot.bot)
        asyncio.create_task(bot.process_update(update))
    except Exception as e:
        logger.error(f"[WEBHOOK ERROR] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")
    return PlainTextResponse("OK")

# --- MP3 streaming endpoint ---
@app.get("/stream/{message_id}")
async def stream_file(message_id: int):
    cache_info = stream_cache.get(message_id)
    expires_at = cache_info["expires_at"] if cache_info else datetime.utcnow()
    if datetime.utcnow() > expires_at:
        raise HTTPException(status_code=410, detail="⛔ Link scaduto. Richiedi un nuovo link.")

    file_path = os.path.join(CACHE_FOLDER, f"{message_id}.mp3")

    if not os.path.exists(file_path):
        try:
            client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
            await client.start(bot_token=BOT_TOKEN)
            message = await client.get_messages(from_chat_id, ids=message_id)

            if not isinstance(message.media, MessageMediaDocument):
                await client.disconnect()
                raise HTTPException(status_code=404, detail="❌ Non è un file valido.")

            doc: Document = message.media.document
            if doc.mime_type != "audio/mpeg":
                await client.disconnect()
                raise HTTPException(status_code=415, detail="❌ Il file non è un MP3 valido.")

            async with aiofiles.open(file_path, 'wb') as f:
                await client.download_media(message, file=f)
            await client.disconnect()

            logger.info(f"📥 File scaricato e salvato: {file_path}")
        except Exception as e:
            logger.error(f"[DOWNLOAD ERROR] {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="❌ Errore durante il download.")

    # Streaming in chunks asynchronously
    async def generate():
        async with aiofiles.open(file_path, 'rb') as f:
            while True:
                chunk = await f.read(64 * 1024)  # Read 64 KB chunks
                if not chunk:
                    break
                yield chunk

    logger.info(f"🎧 Streaming file: {file_path}")
    return StreamingResponse(generate(), media_type="audio/mpeg")

# --- Root page ---
@app.get("/")
async def home():
    return PlainTextResponse("🎉 Benvenut* al Radio Montello MP3 Streamer Bot! 🎧")

# --- Cleanup Task ---
async def cleanup_cache():
    while True:
        now = datetime.utcnow()
        for msg_id, data in list(stream_cache.items()):
            if now > data["expires_at"]:
                path = os.path.join(CACHE_FOLDER, f"{msg_id}.mp3")
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info(f"🗑️ File rimosso: {path}")
                    except Exception as e:
                        logger.warning(f"⚠️ Impossibile rimuovere {path}: {e}")
                stream_cache.pop(msg_id)
        await asyncio.sleep(300)  # Check every 5 minutes

# --- Main ---
if __name__ == '__main__':
    import uvicorn

    loop = asyncio.get_event_loop()
    bot = loop.run_until_complete(init_bot())

    # Start the cleanup task
    loop.create_task(cleanup_cache())

    # Run the FastAPI app with uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
