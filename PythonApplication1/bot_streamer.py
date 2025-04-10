import os
import re
from flask import Flask, request, Response
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# --- Load environment variables ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "RDMNTL_session"  # Saved locally by Telethon
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Webhook URL


   
# --- Chat username and link pattern ---
from_chat_id = 'NLPTST'
link_pattern = re.compile(rf'https://t\.me/{from_chat_id}/(\d+)')

# Flask app for handling webhook and file streaming
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint for Telegram bot"""
    data = request.get_json(silent=True)  # Use get_json with silent=True to avoid exceptions
    if not data:
        print("No JSON data received or malformed request")  # Debugging
        return "Bad Request: No JSON data received", 400

    print(f"Incoming update: {data}")  # Debugging
    try:
        update = Update.de_json(data, bot)
        bot.process_update(update)  # Process the update
    except Exception as e:
        print(f"Error processing update: {e}")  # Log any errors
        return "Internal Server Error", 500

    return "OK", 200
     




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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Inviami un link da Radio Montello (es. https://t.me/{from_chat_id}/NUMERI) e ti darò un link per lo streaming.\n\n"
        "🎉 Welcome to the Telegram MP3 Streamer Bot! 🎧\n\n"
        "📌 Here's what you can do:\n"
        "1️⃣ Send me a link to a Telegram message containing an MP3 file.\n"
        "2️⃣ I'll generate a streamable link for you to listen to the file online.\n\n"
        f"💡 Tip: Make sure the link is from the {from_chat_id} chat and points to a valid MP3 file.\n\n"
        "🚀 Let's get started! Send me a link now!"
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

@app.route('/')
def home():
    return "Welcome to the Telegram MP3 Streamer!"

if __name__ == '__main__':
    # Start Flask app
    from threading import Thread
    def run_flask():
        app.run(host='0.0.0.0', port=10000)  # Use a different port for Flask
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # Start Telegram bot using webhook
    bot = ApplicationBuilder().token(BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))
    bot.run_webhook(
        listen="0.0.0.0",
        port=11000,  # Use a different port for the bot
        webhook_url=f"{WEBHOOK_URL}/webhook"
    )

