from telegram import Update, Message, error
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import re


# --- Your Bot Token ---

import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


# --- The file stream bot username ---
FILESTREAM_BOT_USERNAME = "FileStreamBot"

# --- Link pattern for only RadioMontelloChat ---
link_pattern = re.compile(r'https://t\.me/NLPTST/(\d+)')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Inviami un link da Radio Montello (es. https://t.me/RadioMontelloChat/NUMERI) e ti darò un link per lo streaming."
    )
  
    
    

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    match = link_pattern.match(msg)

    if not match:
        await update.message.reply_text("⚠️ Invia solo link validi da https://t.me/RadioMontelloChat")
        return

    message_id = int(match.group(1))
    from_chat_id = '@NLPTST'  # Update this if necessary

    try:
        # Debug: Check chat access
        chat = await context.bot.get_chat(from_chat_id)
        print(f"Bot has access to chat: {chat.title}")
        print(f"Extracted message_id: {message_id}")
     

        # Forward message to FileStreamBot
        forwarded = await context.bot.forward_message(
            chat_id=FILESTREAM_BOT_USERNAME,
            from_chat_id=from_chat_id,
            message_id=message_id
        )

        await update.message.reply_text("✅ File inviato al bot di conversione, attendi il link...")

        # Wait for FileStreamBot to respond (max 15 sec)
        for _ in range(15):
            await asyncio.sleep(1)
            updates = await context.bot.get_updates()
            for u in updates:
                if u.message and u.message.chat.username == FILESTREAM_BOT_USERNAME:
                    if u.message.text and "http" in u.message.text:
                        await update.message.reply_text(f"🎧 Ecco il link per lo streaming:\n{u.message.text}")
                        return

        await update.message.reply_text("⏳ Non ho ricevuto una risposta. Riprova tra poco o verifica manualmente.")

    except error.BadRequest as e:  # Updated to use the correct import
        if "Chat not found" in str(e):
            await update.message.reply_text("❌ Chat non trovata. Assicurati che il bot sia stato aggiunto alla chat e che il nome utente sia corretto.")
        else:
            print("Errore:", e)
            await update.message.reply_text("Errore durante l'elaborazione del link.")
    except Exception as e:
        print("Errore:", e)
        await update.message.reply_text("Errore durante l'elaborazione del link. Assicurati che il file sia accessibile.")




if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_link))

    print("✅ Bot is running...")
    app.run_polling()