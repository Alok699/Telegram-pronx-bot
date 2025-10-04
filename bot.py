import json
import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = "8118283984:AAEFh5VCmAd5WLn_lKAfYU38T6wzo0Hynr8"
ADMIN_IDS = [7687968365, 6368862755, 6492557901]
CHANNEL_USERNAME = "@xvideos_op"
MOVIES_FILE = "movies.json"
BATCHES_FILE = "batches.json"
DELETE_TIME_MINUTES = 30

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def load_json(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

MOVIES = load_json(MOVIES_FILE)
BATCHES = load_json(BATCHES_FILE)

async def auto_delete(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(job.chat_id, job.data['message_id'])
        logger.info(f"Deleted message {job.data['message_id']} from chat {job.chat_id}")
    except Exception as e:
        logger.error(f"Delete error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    chat_id = update.effective_chat.id
    DELETION_WARNING = ("⚠️ <b>Important Notice</b>\n\n"
        "⏰ Files expire in <b>30 minutes</b>\n"
        "💾 Save immediately\n\n"
        "🔒 Automated delivery system")
    
    if args:
        code = args[0].lower()
        if code in BATCHES:
            batch = BATCHES[code]
            await update.message.reply_text(DELETION_WARNING, parse_mode="HTML")
            for idx, video_code in enumerate(batch['videos'], 1):
                if video_code in MOVIES:
                    movie = MOVIES[video_code]
                    caption = (f"📁 <b>File {idx}/{len(batch['videos'])}</b>\n"
                        "━━━━━━━━━━━━━━━\n"
                        f"⏰ Expires: {DELETE_TIME_MINUTES} min")
                    buttons = [
                        [InlineKeyboardButton("💾 Save", url="https://t.me/+42777")], 
                        [InlineKeyboardButton("📢 Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
                    ]
                    sent = await context.bot.send_video(
                        chat_id=chat_id, 
                        video=movie['file_id'], 
                        caption=caption, 
                        parse_mode="HTML", 
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                    context.job_queue.run_once(
                        auto_delete, 
                        DELETE_TIME_MINUTES * 60, 
                        chat_id=chat_id, 
                        data={'message_id': sent.message_id}
                    )
                    import asyncio
                    await asyncio.sleep(3)
            return
        elif code in MOVIES:
            movie = MOVIES[code]
            await update.message.reply_text(DELETION_WARNING, parse_mode="HTML")
            caption = ("📁 <b>File Delivery</b>\n"
                "━━━━━━━━━━━━━━━\n"
                f"⏰ Expires: {DELETE_TIME_MINUTES} min")
            buttons = [
                [InlineKeyboardButton("💾 Save", url="https://t.me/+42777")], 
                [InlineKeyboardButton("📢 Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
            ]
            sent = await context.bot.send_video(
                chat_id=chat_id, 
                video=movie['file_id'], 
                caption=caption, 
                parse_mode="HTML", 
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            context.job_queue.run_once(
                auto_delete, 
                DELETE_TIME_MINUTES * 60, 
                chat_id=chat_id, 
                data={'message_id': sent.message_id}
            )
            return
    
    welcome_text = ("👋 <b>Welcome to File Delivery Bot</b>\n\n"
        "📤 <b>How to use:</b>\n"
        "• Click on file links to get videos\n"
        "• Files auto-delete after 30 minutes\n"
        "• Save immediately after receiving\n\n"
        "👨‍💼 <b>Admin Commands:</b>\n"
        "/add - Upload new file\n"
        "/addbatch - Create collection\n"
        "/list - View all files\n"
        "/listbatch - View collections\n"
        "/delete - Remove file\n"
        "/deletebatch - Remove collection\n"
        "/stats - Bot statistics\n\n"
        "🔒 Secure • ⚡ Fast • 🤖 Automated")
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    await update.message.reply_text("📁 <b>Upload File</b>\n\n📤 Send video now...", parse_mode="HTML")
    context.user_data['adding_movie'] = True

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    if context.user_data.get('adding_movie'):
        video = update.message.video
        context.user_data['temp_file_id'] = video.file_id
        context.user_data['adding_movie'] = False
        context.user_data['awaiting_code'] = True
        await update.message.reply_text("✅ Received\n\n🔑 Enter code:", parse_mode="HTML")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    text = update.message.text.strip()
    
    if context.user_data.get('awaiting_code'):
        if text.lower() in MOVIES:
            await update.message.reply_text("❌ Code exists")
            return
        context.user_data['movie_code'] = text.lower()
        context.user_data['awaiting_code'] = False
        context.user_data['awaiting_title'] = True
        await update.message.reply_text("✅ Code saved\n\n📝 Enter label:")

    elif context.user_data.get('awaiting_title'):
        context.user_data['movie_title'] = text
        context.user_data['awaiting_title'] = False
        context.user_data['awaiting_description'] = True
        await update.message.reply_text("✅ Label saved\n\n📄 Note (or skip):")
    
    elif context.user_data.get('awaiting_description'):
        description = "" if text.lower() == 'skip' else text
        movie_code = context.user_data['movie_code']
        MOVIES[movie_code] = {
            'file_id': context.user_data['temp_file_id'], 
            'title': context.user_data['movie_title'], 
            'description': description, 
            'added_time': int(time.time())
        }
        save_json(MOVIES_FILE, MOVIES)
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={movie_code}"
        await update.message.reply_text(
            f"✅ Uploaded\n\n📝 {context.user_data['movie_title']}\n🔑 {movie_code}\n🔗 {link}\n\n📊 Total: {len(MOVIES)}"
        )
        context.user_data.clear()
    
    elif context.user_data.get('batch_awaiting_codes'):
        codes = [c.strip().lower() for c in text.split(',')]
        valid_codes = [c for c in codes if c in MOVIES]
        if len(codes) != len(valid_codes):
            await update.message.reply_text("❌ Invalid codes")
            return
        context.user_data['batch_codes'] = valid_codes
        context.user_data['batch_awaiting_codes'] = False
        context.user_data['batch_awaiting_title'] = True
        await update.message.reply_text(f"✅ {len(valid_codes)} verified\n\n📝 Name:")
    
    elif context.user_data.get('batch_awaiting_title'):
        context.user_data['batch_title'] = text
        context.user_data['batch_awaiting_title'] = False
        context.user_data['batch_awaiting_code'] = True
        await update.message.reply_text("✅ Saved\n\n🔑 Batch code:")
    
    elif context.user_data.get('batch_awaiting_code'):
        batch_code = text.lower().replace(' ', '_')
        if batch_code in BATCHES:
            await update.message.reply_text("❌ Exists")
            return
        BATCHES[batch_code] = {
            'title': context.user_data['batch_title'], 
            'videos': context.user_data['batch_codes'], 
            'created_time': int(time.time())
        }
        save_json(BATCHES_FILE, BATCHES)
        bot_username = (await context.bot.get_me()).username
        batch_link = f"https://t.me/{bot_username}?start={batch_code}"
        await update.message.reply_text(
            f"✅ Created\n\n📦 {context.user_data['batch_title']}\n🔑 {batch_code}\n📁 {len(context.user_data['batch_codes'])} files\n🔗 {batch_link}"
        )
        context.user_data.clear()

async def addbatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    if not MOVIES:
        await update.message.reply_text("❌ No files")
        return
    await update.message.reply_text("📦 Create Collection\n\n📝 Codes (comma-separated):")
    context.user_data['batch_awaiting_codes'] = True

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    if MOVIES:
        message = "📁 Files\n━━━━━━━━━━━━━━━\n\n" + "\n".join([
            f"{i}. {code} - {data['title']}" for i, (code, data) in enumerate(MOVIES.items(), 1)
        ]) + f"\n\n📊 Total: {len(MOVIES)}"
    else:
        message = "❌ No files"
    await update.message.reply_text(message)

async def listbatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    if BATCHES:
        message = "📦 Collections\n━━━━━━━━━━━━━━━\n\n" + "\n".join([
            f"{i}. {code} - {data['title']} ({len(data['videos'])} files)" 
            for i, (code, data) in enumerate(BATCHES.items(), 1)
        ]) + f"\n\n📊 Total: {len(BATCHES)}"
    else:
        message = "❌ No collections"
    await update.message.reply_text(message)

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /delete code")
        return
    code = context.args[0].lower()
    if code in MOVIES:
        del MOVIES[code]
        save_json(MOVIES_FILE, MOVIES)
        await update.message.reply_text("✅ Deleted")
    else:
        await update.message.reply_text("❌ Not found")

async def deletebatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /deletebatch code")
        return
    code = context.args[0].lower()
    if code in BATCHES:
        del BATCHES[code]
        save_json(BATCHES_FILE, BATCHES)
        await update.message.reply_text("✅ Deleted")
    else:
        await update.message.reply_text("❌ Not found")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: 
        return
    await update.message.reply_text(
        f"📊 Status\n━━━━━━━━━━━━━━━\n\n📁 Files: {len(MOVIES)}\n📦 Collections: {len(BATCHES)}\n👥 Admins: {len(ADMIN_IDS)}\n⏰ Expire: {DELETE_TIME_MINUTES} min\n✅ Active"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("addbatch", addbatch_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("listbatch", listbatch_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("deletebatch", deletebatch_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.VIDEO & filters.User(ADMIN_IDS), handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_IDS), handle_text))
    logger.info("🚀 Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
