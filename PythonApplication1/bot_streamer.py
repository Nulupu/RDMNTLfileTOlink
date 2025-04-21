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
stream_cache = {}  # Stores {message_id: {"url": str, "expires_at": datetime}}

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
    if not update.message or update.message.chat.type != "private":
        return  # only respond to private DMs

    msg = update.message.text
    match = link_pattern.match(msg)
    if not match:
        await update.message.reply_text(f"⚠️ Invia solo link validi da https://t.me/{from_chat_id}")
        return

    message_id = int(match.group(1))

    # Check if the link is already cached
    if message_id in stream_cache:
        stream_data = stream_cache[message_id]
        stream_url = stream_data["url"]
        expires_at = stream_data["expires_at"]
    else:
        stream_url = f"{WEBHOOK_URL}/stream/{message_id}"
        expires_at = datetime.utcnow() + timedelta(hours=2)
        stream_cache[message_id] = {"url": stream_url, "expires_at": expires_at}

    # Calculate remaining time
    remaining_time = expires_at - datetime.utcnow()
    hours, remainder = divmod(remaining_time.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    await update.message.reply_text(
        f"🎧 Ecco il link per lo streaming:\n{stream_url}\n\n"
        f"⏳ Questo link scadrà tra: {hours} ore, {minutes} minuti e {seconds} secondi."
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

# --- Stream helper ---
def stream_local_file(file_path):
    def generate():
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
    return Response(generate(), content_type='audio/mpeg')

# --- MP3 streaming endpoint ---
@app.route('/stream/<int:message_id>')
async def stream_file(message_id):
    async def get_stream():
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            file_path = os.path.join(CACHE_DIR, f"{message_id}.mp3")

            # ✅ If cached: stream directly
            if os.path.exists(file_path):
                logger.info(f"Streaming cached file {file_path}")
                return stream_local_file(file_path)

            # ❌ If TTL expired and not cached: deny
            if message_id not in stream_cache or stream_cache[message_id]["expires_at"] < datetime.utcnow():
                logger.warning(f"Stream link for message {message_id} expired and not cached.")
                return Response("Link scaduto. Richiedi un nuovo link.", status=410)

            # 🌀 Otherwise: fetch and stream
            client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

            # Start the client in a new thread to avoid locking errors
            def fetch_file():
                try:
                    client.start(bot_token=BOT_TOKEN)
                    message = client.get_messages(from_chat_id, ids=message_id)
                    
                    if not isinstance(message.media, MessageMediaDocument):
                        client.disconnect()
                        return "Not a valid document"
                    
                    doc: Document = message.media.document
                    if doc.mime_type != 'audio/mpeg':
                        client.disconnect()
                        return "File is not an MP3"

                    with open(file_path, 'wb') as f:
                        for chunk in client.iter_download(message, chunk_size=64 * 1024):
                            f.write(chunk)

                    client.disconnect()
                    logger.info(f"Downloaded and cached file {file_path}")
                except Exception as e:
                    logger.error(f"[STREAM ERROR] {e}", exc_info=True)
                    return "Error during file download"
            
            # Run the fetch_file function in a separate thread to avoid blocking
            thread = Thread(target=fetch_file)
            thread.start()
            return Response("Streaming started...", status=200)  # Respond immediately

        except Exception as e:
            logger.error(f"[STREAM ERROR] {e}", exc_info=True)
            return Response("Errore durante lo streaming.", status=500)

    return await get_stream()

# --- Cleanup expired files ---
async def cleanup_old_files():
    while True:
        try:
            now = datetime.utcnow()
            for filename in os.listdir(CACHE_DIR):
                if filename.endswith(".mp3"):
                    message_id = int(filename.replace(".mp3", ""))
                    if (message_id in stream_cache and
                            stream_cache[message_id]["expires_at"] < now):
                        file_path = os.path.join(CACHE_DIR, filename)
                        os.remove(file_path)
                        logger.info(f"Deleted expired file: {file_path}")
                        del stream_cache[message_id]
        except Exception as e:
            logger.error(f"[CLEANUP ERROR] {e}", exc_info=True)

        await asyncio.sleep(600)  # Run every 10 minutes

# --- Root page ---
@app.route('/')
def home():
    return "🎉 Benvenut* al Radio Montello MP3 Streamer Bot! 🎧"

# --- Main ---
if __name__ == '__main__':
    def run_flask():
        app.run(host='0.0.0.0', port=10000, use_reloader=False)

    loop = asyncio.get_event_loop()
    bot = loop.run_until_complete(init_bot())

    # Start cleanup task
    loop.create_task(cleanup_old_files())

    # Run Flask in a separate thread
    Thread(target=run_flask).start()
    loop.run_forever()
