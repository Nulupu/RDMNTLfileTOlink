import os
import re
import asyncio
from flask import Flask, request, Response
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, MessageHandler,
    ContextTypes, filters
)
from threading import Thread

# --- Load environment variables ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "RDMNTL_session"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Still needed for stream links

# --- Telegram chat source ---
from_chat_id = 'NLPTST'
link_pattern = re.compile(rf'https://t\.me/{from_chat_id}/(\d+)')

# --- Flask App for Streaming ---
app = Flask(__name__)

@app.route('/stream/<int:message_id>')
def stream_file(message_id):
    """Route to stream MP3 files"""
    async def get_stream():
        async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
            await client.start(bot_token=BOT_TOKEN)
            message = await client.get_messages(from_chat_id, ids=message_id)
            if not isinstance(message.media, MessageMediaDocument):
                return "Message does not contain a valid document", 404
            doc: Document = message.media.document
            if doc.mime_type != 'audio/mpeg':
                return "File is not an MP3", 415
            temp_file_path = f"/tmp/{doc.id}.mp3"
            await client.download_media(message, file=temp_file_path)

            def generate():
                with open(temp_file_path, "rb") as f:
                    while chunk := f.read(1024):
                        yield chunk
            return Response(generate(), content_type='audio/mpeg')

    return asyncio.run(get_stream())

@app.route('/')
def home():
    return "Welcome to the Telegram MP3 Streamer!"

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
         "🎉 Benvenuto nel bot di streaming MP3 di Radio Montello! 🎧\n\n"
         f"Inviami un link da Radio Montello (es. https://t.me/{from_chat_id}/NUMERO) "
         "e ti darò un link per lo streaming.\n\n"
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
        await update.message.reply_text("Errore durante l'elaborazione del link. Assicurati che il file sia accessibile.")

# --- Run Everything ---
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))
    print("🚀 Bot is polling...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

if __name__ == '__main__':
    # Start Flask streaming server in background
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=10000))
    flask_thread.start()

    # Run bot with polling
    asyncio.run(main())
