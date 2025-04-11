import os
import re
import asyncio
import logging
from io import BytesIO
from flask import Flask, request, Response
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import nest_asyncio
import telegram
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
SESSION_NAME = "RDMNTL_session"
from_chat_id = 'NLPTST'
link_pattern = re.compile(rf'https://t\.me/{from_chat_id}/(\d+)')

# Check for critical env vars
if not BOT_TOKEN or not API_ID or not API_HASH or not WEBHOOK_URL:
    raise RuntimeError("Missing one or more critical .env values")

# Flask app
app = Flask(__name__)

# Simple memory cache
stream_cache = {}

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Benvenut* al Radio Monell MP3 Streamer Bot! 🎧\n\n"
        f"Inviami un link da Radio Montello (es. https://t.me/{from_chat_id}/NUMERO) e ti darò un link per lo streaming.\n\n"
        "📌 Cosa puoi fare:\n"
        "1️⃣ Mandami un link ad un messaggio con file MP3 da NLPTST.\n"
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

    if message_id in stream_cache:
        stream_url = stream_cache[message_id]
    else:
        stream_url = f"{WEBHOOK_URL}/stream/{message_id}"
        stream_cache[message_id] = stream_url

    await update.message.reply_text(f"🎧 Ecco il link per lo streaming:\n{stream_url}")

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
async def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot.bot)
        await bot.process_update(update)
    except Exception as e:
        logger.error(f"[WEBHOOK ERROR] {e}", exc_info=True)
        return "Internal error", 500
    return "OK", 200

# --- MP3 streaming endpoint ---
@app.route('/stream/<int:message_id>')
async def stream_file(message_id):
    async def get_stream():
        try:
            async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
                await client.start(bot_token=BOT_TOKEN)
                message = await client.get_messages(from_chat_id, ids=message_id)

                if not isinstance(message.media, MessageMediaDocument):
                    return Response("Not a valid document", status=404)

                doc: Document = message.media.document
                if doc.mime_type != 'audio/mpeg':
                    return Response("File is not an MP3", status=415)

                stream = BytesIO()
                await client.download_media(message, file=stream)
                stream.seek(0)

                return Response(stream, content_type='audio/mpeg')
        except Exception as e:
            logger.error(f"[STREAM ERROR] {e}", exc_info=True)
            return Response("Errore durante lo streaming.", status=500)

    return await get_stream()

# --- Root page ---
@app.route('/')
def home():
    return "🎧 Welcome to the Telegram MP3 Streamer!"

# --- Async keep-alive loop ---
async def keep_alive():
    while True:
        await asyncio.sleep(10)

# --- Main ---
if __name__ == '__main__':
    def run_flask():
        app.run(host='0.0.0.0', port=10000, use_reloader=False)

    loop = asyncio.get_event_loop()
    bot = loop.run_until_complete(init_bot())

    # Run Flask and async keep-alive in parallel
    Thread(target=run_flask).start()
    loop.create_task(keep_alive())
    loop.run_forever()
