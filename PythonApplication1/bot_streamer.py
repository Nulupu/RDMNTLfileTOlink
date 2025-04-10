import os
import re
import asyncio
import requests
from flask import Flask, request, Response, jsonify
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaDocument, Document

# Load .env file
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "RDMNTL_session"  # saved locally by Telethon

app = Flask(__name__)

# Route to stream a Telegram MP3 file
@app.route('/stream/<int:message_id>')
def stream_file(message_id):
    async def get_stream():
        async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
            message = await client.get_messages('NLPTST', ids=message_id)

            if not isinstance(message.media, MessageMediaDocument):
                return "Message does not contain a valid document", 404

            doc: Document = message.media.document
            if doc.mime_type != 'audio/mpeg':
                return "File is not an MP3", 415

            # Get the file reference needed for authenticated download
            url = await client._download_cdn_file(doc, file_ref=doc.file_reference, request_cdn=True)

            def generate():
                with requests.get(url, stream=True) as r:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            yield chunk

            return Response(generate(), content_type='audio/mpeg')

    return asyncio.run(get_stream())

# Route for Telegram bot webhook (optional)
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.json
    message = data.get('message', {}).get('text', '')

    match = re.match(r'https://t.me/NLPTST/(\d+)', message)
    if not match:
        return jsonify({"ok": False, "error": "Invalid or unsupported link"}), 400

    message_id = int(match.group(1))
    stream_url = f"{request.url_root}stream/{message_id}"
    return jsonify({"stream_url": stream_url}), 200

if __name__ == '__main__':
    app.run(debug=True, port=8000)
