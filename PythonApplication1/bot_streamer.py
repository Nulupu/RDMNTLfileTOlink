import os
import re
import asyncio
import logging
from io import BytesIO
from flask import Flask, request, Response
from dotenv import load_dotenv
from datetime import datetime, timedelta

import aiofiles
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import nest_asyncio
from threading import Thread

# --- Init ---
load_dotenv()
nest_asyncio.apply()

# Ensure cache folder exists
CACHE_DIR = "stream_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

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

link_pattern = re.compile(rf'https://t\.me/{from_chat_id}/(\d+)')

# Check for critical env vars
if not BOT_TOKEN or not API_ID or not API_HASH or not WEBHOOK_URL:
    raise RuntimeError("Missing one or more critical .env values")

# Flask app
app = Flask(__name__)


# --- Stream Cache ---
stream_cache = {}  # message_id: {url, expires_at, file_path}

# --- Handle /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Benvenut* al Radio Montello MP3 Streamer Bot! 🎧\n\n"
        f"Inviami un link da Radio Montello (es. https://t.me/{from_chat_id}/NUMERO) e ti darò un link per lo streaming.\n\n"
        "📌 Cosa puoi fare:\n"
        f"1️⃣ copia e incolla un link (non forward) ad un messaggio con file MP3 da {from_chat_id}.\n"
        "2️⃣ Ti restituisco un link streaming compatibile.\n\n"
        f"💡 Solo link da: https://t.me/{from_chat_id}"
    )

# --- Prefetch and Handle Link ---



async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received message: {update.message.text}")
    logger.info(f"Chat type: {update.message.chat.type}")
    ...

    if not update.message or update.message.chat.type != "private":
        return

    msg = update.message.text
    match = link_pattern.match(msg)
    if not match:
        await update.message.reply_text(f"⚠️ Invia solo link validi da https://t.me/{from_chat_id}")
        return

    message_id = int(match.group(1))
    file_path = os.path.join(CACHE_DIR, f"{message_id}.mp3")
    stream_url = f"{WEBHOOK_URL}/stream/{message_id}"
    expires_at = datetime.utcnow() + timedelta(hours=2)

    # Cache entry always updated if not present
    if message_id not in stream_cache:
        stream_cache[message_id] = {
            "url": stream_url,
            "expires_at": expires_at,
            "file_path": file_path
        }

    # If file already exists, just reply
    if os.path.exists(file_path):
        pass
    else:
        try:
            async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
                logger.info("Starting TelegramClient with bot token...")
                await client.start()


                # Retrieve the specific message from the channel
                message = await client.get_messages(from_chat_id, ids=message_id)

                if not isinstance(message.media, MessageMediaDocument):
                    await update.message.reply_text("❌ Il messaggio non contiene un file valido.")
                    return

                doc: Document = message.media.document
                if doc.mime_type != 'audio/mpeg':
                    await update.message.reply_text("❌ Il file non è un MP3.")
                    return

                await client.download_media(message, file=file_path)
                logger.info(f"Downloaded and cached {file_path}")
        except Exception as e:
            logger.error(f"[DOWNLOAD ERROR] {e}", exc_info=True)
            await update.message.reply_text("❌ Errore nel recupero del file.")
            return

    # Respond with stream link
    remaining = expires_at - datetime.utcnow()
    h, m = divmod(remaining.seconds, 3600)
    m, s = divmod(m, 60)
    await update.message.reply_text(
        f"🎧 Ecco il link per lo streaming:\n{stream_url}\n\n"
        f"⏳ Questo link scadrà tra: {h} ore, {m} minuti e {s} secondi."
    )





# --- Streaming endpoint (only cached) ---
@app.route('/stream/<int:message_id>')
def stream_file(message_id):
    if message_id not in stream_cache:
        return Response("⚠️ Link non valido o mai richiesto.", status=404)

    data = stream_cache[message_id]
    if data["expires_at"] < datetime.utcnow():
        return Response("⛔ Link scaduto. Invia di nuovo il link per rigenerarlo.", status=410)

    file_path = data["file_path"]
    if not os.path.exists(file_path):
        return Response("⛔ File non trovato nel cache.", status=404)

    def generate():
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    return Response(generate(), content_type='audio/mpeg')

# --- Cleanup expired files ---
async def cleanup_old_files():
    while True:
        try:
            now = datetime.utcnow()
            for message_id, data in list(stream_cache.items()):
                if data["expires_at"] < now:
                    try:
                        os.remove(data["file_path"])
                        logger.info(f"Removed expired file {data['file_path']}")
                    except:
                        pass
                    del stream_cache[message_id]
        except Exception as e:
            logger.error(f"[CLEANUP ERROR] {e}", exc_info=True)

        await asyncio.sleep(600)

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

# --- Bot Init ---
async def init_bot():
    bot = ApplicationBuilder().token(BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))
    await bot.initialize()
    await bot.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    return bot

# --- Main ---
if __name__ == '__main__':
    def run_flask():
        app.run(host='0.0.0.0', port=10000, use_reloader=False)

    loop = asyncio.get_event_loop()
    bot = loop.run_until_complete(init_bot())

    loop.create_task(cleanup_old_files())
    Thread(target=run_flask).start()
    loop.run_forever()
