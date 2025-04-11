import os
import re
import asyncio
from io import BytesIO
from flask import Flask, request, Response
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from threading import Thread
import nest_asyncio

# --- Init ---
load_dotenv()
nest_asyncio.apply()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "RDMNTL_session"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
from_chat_id = 'NLPTST'
link_pattern = re.compile(rf'https://t\.me/{from_chat_id}/(\d+)')

import telegram

telegram.Bot(BOT_TOKEN).set_webhook(f"{WEBHOOK_URL}/webhook")

# Flask app
app = Flask(__name__)




@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot.bot)

    async def handle_update():
        try:
            await bot.initialize()
        except RuntimeError:
            pass  # Already initialized
        await bot.process_update(update)

    asyncio.run(handle_update())
    return "OK", 200















@app.route('/stream/<int:message_id>')
def stream_file(message_id):
    async def get_stream():
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

    return asyncio.run(get_stream())

@app.route('/')
def home():
    return "Welcome to the Telegram MP3 Streamer!"

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Inviami un link da Radio Montello (es. https://t.me/{from_chat_id}/NUMERO) e ti darò un link per lo streaming.\n\n"
        "🎉 Welcome to the Telegram MP3 Streamer Bot! 🎧\n\n"
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
    try:
        stream_url = f"{WEBHOOK_URL}/stream/{message_id}"
        await update.message.reply_text(f"🎧 Ecco il link per lo streaming:\n{stream_url}")
    except Exception as e:
        print("Error:", e)
        await update.message.reply_text("Errore nel generare il link di streaming.")

# --- Main ---
if __name__ == '__main__':
    # Start Flask in a separate thread
    def run_flask():
        app.run(host='0.0.0.0', port=10000)
    Thread(target=run_flask).start()

    # Setup Telegram bot
    bot = ApplicationBuilder().token(BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))

    # Set webhook (run this once or protect with flag)
    bot.bot.set_webhook(f"{WEBHOOK_URL}/webhook")

    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))
