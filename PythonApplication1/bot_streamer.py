import os
import re
import asyncio
import logging
from flask import Flask, request, Response
from dotenv import load_dotenv
from datetime import datetime, timedelta
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import nest_asyncio
from threading import Thread
import aiofiles

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

# Flask app
app = Flask(__name__)
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
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot.bot)
        asyncio.run(bot.process_update(update))
    except Exception as e:
        logger.error(f"[WEBHOOK ERROR] {e}", exc_info=True)
        return "Internal error", 500
    return "OK", 200

# --- MP3 streaming endpoint ---
@app.route('/stream/<int:message_id>')
async def stream_file(message_id):
    cache_info = stream_cache.get(message_id)
    expires_at = cache_info["expires_at"] if cache_info else datetime.utcnow()
    if datetime.utcnow() > expires_at:
        return Response("⛔ Link scaduto. Richiedi un nuovo link.", status=410)

    file_path = os.path.join(CACHE_FOLDER, f"{message_id}.mp3")

    if not os.path.exists(file_path):
        try:
            client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
            await client.start(bot_token=BOT_TOKEN)
            message = await client.get_messages(from_chat_id, ids=message_id)

            if not isinstance(message.media, MessageMediaDocument):
                await client.disconnect()
                return Response("❌ Non è un file valido.", status=404)

            doc: Document = message.media.document
            if doc.mime_type != "audio/mpeg":
                await client.disconnect()
                return Response("❌ Il file non è un MP3 valido.", status=415)

            async with aiofiles.open(file_path, 'wb') as f:
                await client.download_media(message, file=f)
            await client.disconnect()

            logger.info(f"📥 File scaricato e salvato: {file_path}")
        except Exception as e:
            logger.error(f"[DOWNLOAD ERROR] {e}", exc_info=True)
            return Response("❌ Errore durante il download.", status=500)

    # Streaming in chunks asynchronously
    async def generate():
        async with aiofiles.open(file_path, 'rb') as f:
            while True:
                chunk = await f.read(64 * 1024)  # Read 64 KB chunks
                if not chunk:
                    break
                yield chunk

    logger.info(f"🎧 Streaming file: {file_path}")
    return Response(generate(), content_type="audio/mpeg")

# --- Root page ---
@app.route('/')
def home():
    return "🎉 Benvenut* al Radio Montello MP3 Streamer Bot! 🎧"

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
    def run_flask():
        app.run(host='0.0.0.0', port=10000, use_reloader=False)

    loop = asyncio.get_event_loop()
    bot = loop.run_until_complete(init_bot())

    Thread(target=run_flask).start()
    loop.create_task(cleanup_cache())
    loop.run_forever()
