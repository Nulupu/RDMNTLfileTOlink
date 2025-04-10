import os
import re
import asyncio
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from aiohttp import web

# Load .env file
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "RDMNTL_session"  # saved locally by Telethon

app = Flask(__name__)

# Flask route to stream a Telegram MP3 file
@app.route('/stream/<int:message_id>')
async def stream_file(message_id):
    async def get_stream():
        async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
            message = await client.get_messages('NLPTST', ids=message_id)

            if not isinstance(message.media, MessageMediaDocument):
                return "Message does not contain a valid document", 404

            doc: Document = message.media.document
            if doc.mime_type != 'audio/mpeg':
                return "File is not an MP3", 415

            # Stream the file directly
            def generate():
                with open(doc.file_path, "rb") as f:
                    while chunk := f.read(1024):
                        yield chunk

            return Response(generate(), content_type='audio/mpeg')

    return await get_stream()

# Route for Telegram bot webhook (optional)
@app.route('/webhook', methods=['POST'])
async def telegram_webhook():
    data = await request.json()
    message = data.get('message', {}).get('text', '')

    match = re.match(r'https://t.me/NLPTST/(\d+)', message)
    if not match:
        return jsonify({"ok": False, "error": "Invalid or unsupported link"}), 400

    message_id = int(match.group(1))
    stream_url = f"{request.url_root}stream/{message_id}"
    return jsonify({"stream_url": stream_url}), 200

# Define the start command function for Telegram bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Received /start command!")
    welcome_message = (
        "🎉 Welcome to the Telegram MP3 Streamer Bot! 🎧\n\n"
        "📌 Here's what you can do:\n"
        "1️⃣ Send me a link to a Telegram message containing an MP3 file.\n"
        "2️⃣ I'll generate a streamable link for you to listen to the file online.\n\n"
        "💡 Tip: Make sure the link is from the @NLPTST chat and points to a valid MP3 file.\n\n"
        "🚀 Let's get started! Send me a link now!"
    )
    await update.message.reply_text(welcome_message)

# Telegram bot setup
async def bot_main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    # Initialize the application
    await application.initialize()  # Explicitly initialize the application
    
    # Start the application
    await application.start()  # Start the bot without blocking the event loop
    print("Telegram bot is running...")
    
    # Keep the application running
    await application.updater.start_polling()  # Start polling for updates

# Create the aiohttp web application and integrate Flask
async def main():
    # Start Flask app with aiohttp
    app_instance = web.Application()
    app_instance.add_routes([web.get('/', lambda request: web.Response(text="Welcome to the Telegram MP3 Streamer!"))])

    runner = web.AppRunner(app_instance)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()

    # Start Telegram bot
    await bot_main()  # Run bot in the same event loop

# Run both the Flask app and Telegram bot in the same event loop
if __name__ == '__main__':
    asyncio.run(main())
