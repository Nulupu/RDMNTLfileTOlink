








        from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetMessagesRequest
from telethon.tl.types import InputPeerChannel
import re

# --- YOUR TELETHON CREDENTIALS ---
api_id = 21646658       # Replace with your API ID
api_hash = "a39a0122616601b09878b8e767c42433"
session_name = "RDMNTLsession"

# --- YOUR BOT TOKEN ---
BOT_TOKEN = "7985637633:AAHkChsT7FfLy5zXe6onY-4oVoyQEMUaqcM"

# Initialize Telethon client
client = TelegramClient(session_name, api_id, api_hash)
client.start()

# Regex to extract message ID from Telegram link
link_pattern = re.compile(r'https://t\.me/RadioMontelloChat/(\d+)')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Inviami un link da Radio Montello (es. https://t.me/RadioMontelloChat/NUMERI) e ti darò un link temporaneo per lo streaming."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    match = link_pattern.match(msg)

    if not match:
        await update.message.reply_text("⚠️ Invia solo link validi da https://t.me/RadioMontelloChat")
        return

    channel_username, msg_id = match.groups()
    msg_id = int(msg_id)

    try:
        entity = await client.get_entity(channel_username)
        messages = await client.get_messages(entity, ids=[msg_id])
        message = messages[0]

        if message.media:
            file = await message.download_media(file=bytes)
            file_path = await client.download_media(message, file=None)
            telegram_cdn_link = await client.get_download_url(message)

            await update.message.reply_text(f"Ecco il link temporaneo per lo streaming:\n\n{telegram_cdn_link}")

        else:
            await update.message.reply_text("Questo messaggio non contiene file multimediali.")

    except Exception as e:
        print("Errore:", e)
        await update.message.reply_text("Errore nel recupero del file. Assicurati che il canale sia pubblico o che il bot utente abbia accesso.")


if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))

    print("Bot is running...")
    app.run_polling()
