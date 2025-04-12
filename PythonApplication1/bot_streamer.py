import os
import re
import asyncio
import logging
from io import BytesIO
from flask import Flask, request, Response
from dotenv import load_dotenv
from datetime import datetime, timedelta

from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import nest_asyncio
from threading import Thread

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
from_chat_id =  os.getenv("from_chat_id", "")


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
        # Generate a new streaming link and set TTL
        stream_url = f"{WEBHOOK_URL}/stream/{message_id}"
        expires_at = datetime.utcnow() + timedelta(hours=2)  # Set TTL to 2 hours
        stream_cache[message_id] = {"url": stream_url, "expires_at": expires_at}

    # Calculate remaining time for the countdown
    remaining_time = expires_at - datetime.utcnow()
    hours, remainder = divmod(remaining_time.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Send the response with the streaming link and countdown
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
        asyncio.run(bot.process_update(update))  # Use asyncio.run to process the update
    except Exception as e:
        logger.error(f"[WEBHOOK ERROR] {e}", exc_info=True)
        return "Internal error", 500
    return "OK", 200

# --- MP3 streaming endpoint ---
@app.route('/stream/<int:message_id>')
async def stream_file(message_id):
    async def get_stream():
        try:
            # Check if the link has expired
            if message_id not in stream_cache or stream_cache[message_id]["expires_at"] < datetime.utcnow():
                return Response("Link scaduto. Richiedi un nuovo link.", status=410)

            client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
            await client.start(bot_token=BOT_TOKEN)

            message = await client.get_messages(from_chat_id, ids=message_id)
            logger.info(f"Message found: {getattr(message, 'text', 'No text')}")

            if not isinstance(message.media, MessageMediaDocument):
                logger.error("Not a valid document")
                await client.disconnect()
                return Response("Not a valid document", status=404)

            doc: Document = message.media.document
            if doc.mime_type != 'audio/mpeg':
                logger.error(f"Invalid MIME type: {doc.mime_type}")
                await client.disconnect()
                return Response("File is not an MP3", status=415)

            stream = BytesIO()
            await client.download_media(message, file=stream)
            stream.seek(0)

            logger.info("Streaming the audio file...")
            await client.disconnect()
            return Response(stream, content_type='audio/mpeg')

        except Exception as e:
            logger.error(f"[STREAM ERROR] {e}", exc_info=True)
            return Response("Errore durante lo streaming.", status=500)

    return await get_stream()

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

    # Run Flask in a separate thread
    Thread(target=run_flask).start()
    loop.run_forever()



