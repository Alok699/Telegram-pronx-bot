"""
telegram_adult_safe_bot.py
Requirements:
  pip install python-telegram-bot==20.3 aiosqlite

Usage:
  1) Put your BOT token into BOT_TOKEN variable below.
  2) Create movies.json with mapping: {"code1": {"file_id": "<telegram_file_id>", "title":"...","license":"..."}}
  3) Run: python telegram_adult_safe_bot.py
Note: This bot is meant to be policy-compliant and does NOT provide ways to evade Telegram moderation.
"""

import json
import logging
import asyncio
from datetime import datetime, timedelta
import aiosqlite
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ---------- CONFIG ----------
BOT_TOKEN = "7853358520:AAFoROdeDDcwL7bcEyGSJ7965cPZXcnGQhU"  # <-- replace with your token
ADMIN_IDS = [7687968365, 6368862755, 6492557901]  # put admin telegram user ids here
MOVIES_FILE = "movies.json"
DB_FILE = "bot_data.db"
DELETE_TIME_MINUTES = 10
RATE_LIMIT_PER_HOUR = 6  # max requests per user per hour
# ----------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# load movies mapping (code -> metadata including Telegram file_id)
def load_movies():
    p = Path(MOVIES_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to load movies.json: %s", e)
        return {}

MOVIES = load_movies()

# ---------- DB helpers ----------
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
                               telegram_id INTEGER PRIMARY KEY,
                               consented INTEGER DEFAULT 0,
                               consent_time TEXT
                             )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS requests (
                               id INTEGER PRIMARY KEY AUTOINCREMENT,
                               telegram_id INTEGER,
                               code TEXT,
                               ts TEXT,
                               delivered INTEGER DEFAULT 0,
                               delivered_chat INTEGER,
                               delivered_message INTEGER
                             )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS deletions (
                               id INTEGER PRIMARY KEY AUTOINCREMENT,
                               request_id INTEGER,
                               ts TEXT
                             )""")
        await db.commit()

async def set_consented(telegram_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (telegram_id, consented, consent_time) VALUES (?, ?, ?)",
            (telegram_id, 1, datetime.utcnow().isoformat()),
        )
        await db.commit()

async def user_consented(telegram_id: int) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT consented FROM users WHERE telegram_id=?", (telegram_id,))
        row = await cur.fetchone()
        return bool(row and row[0] == 1)

async def log_request(telegram_id: int, code: str, delivered=False, chat=None, message=None):
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "INSERT INTO requests (telegram_id, code, ts, delivered, delivered_chat, delivered_message) VALUES (?, ?, ?, ?, ?, ?)",
            (telegram_id, code, datetime.utcnow().isoformat(), int(delivered), chat, message),
        )
        await db.commit()
        return cur.lastrowid

async def mark_deleted(request_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO deletions (request_id, ts) VALUES (?, ?)", (request_id, datetime.utcnow().isoformat()))
        await db.commit()

async def count_requests_last_hour(telegram_id: int) -> int:
    cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE telegram_id=? AND ts>=?", (telegram_id, cutoff)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

# ---------- Utility: simple placeholder NSFW check ----------
# In production integrate a trusted NSFW classifier service and human moderation queue.
async def nsfw_check_allowed(movie_meta: dict) -> bool:
    # placeholder: we assume your MOVIES file contains license info and consent fields.
    # Deny if license missing.
    if not movie_meta.get("license"):
        return False
    # Other checks can be added (e.g., content flagged)
    return True

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚠️ *Adult Content Portal* ⚠️\n\n"
        "Ye channel/ bot 18+ content provide karta hai. Use karne se pehle confirm karein ke aap 18+ hain aur local laws follow karte hain.\n\n"
        "Press *I AM 18+* to continue."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("I AM 18+ ✅", callback_data="consent_yes")]])
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def consent_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if query.data == "consent_yes":
        await set_consented(uid)
        await query.edit_message_text("Thanks. You are marked as consented. Use /help to learn commands.")
        logger.info("User %s consented", uid)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Commands:\n"
        "/start - show consent\n"
        "/help - this message\n"
        "/get <code> - request a video by code (free). Content auto-deletes after 10 minutes.\n\n"
        "Buttons with each file include a *Report* option to notify admins.\n\n"
        "Note: This bot keeps logs of deliveries and deletions for compliance."
    )
    await update.message.reply_text(txt)

async def get_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    args = context.args
    if not await user_consented(uid):
        await update.message.reply_text("Please confirm age first using /start and click *I AM 18+*.", parse_mode="Markdown")
        return
    if not args:
        await update.message.reply_text("Usage: /get <code>")
        return
    code = args[0].lower().strip()
    if code not in MOVIES:
        await update.message.reply_text("Invalid code. Check and try again.")
        return

    # rate limit
    cnt = await count_requests_last_hour(uid)
    if cnt >= RATE_LIMIT_PER_HOUR:
        await update.message.reply_text("Rate limit exceeded. Try again later.")
        return

    movie = MOVIES[code]
    allowed = await nsfw_check_allowed(movie)
    if not allowed:
        await update.message.reply_text("This item is not available (missing license or blocked). Contact admins.")
        return

    # Send deletion warning
    warn = f"⚠️ File expires in *{DELETE_TIME_MINUTES} minutes* — save if needed."
    await update.message.reply_text(warn, parse_mode="Markdown")

    # send video (file_id from MOVIES)
    try:
        sent = await context.bot.send_video(
            chat_id=update.effective_chat.id,
            video=movie["file_id"],
            caption=f"📁 {movie.get('title','File')}\nExpires in {DELETE_TIME_MINUTES} minutes.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⚠️ Report", callback_data=f"report|{code}")]]
            ),
        )
    except Exception as e:
        logger.error("Failed to send video: %s", e)
        await update.message.reply_text("Failed to deliver file. Contact admins.")
        return

    # schedule deletion
    async def delete_job(ctx: ContextTypes.DEFAULT_TYPE):
        try:
            await ctx.bot.delete_message(chat_id=sent.chat_id, message_id=sent.message_id)
            logger.info("Auto-deleted message %s:%s", sent.chat_id, sent.message_id)
            # mark deletion in DB
            await mark_deleted(request_id)
            # notify admins optionally
            for admin in ADMIN_IDS:
                try:
                    await ctx.bot.send_message(admin, f"Auto-deleted message {sent.message_id} in chat {sent.chat_id} (code {code})")
                except Exception:
                    pass
        except Exception as e:
            logger.error("Error auto-deleting: %s", e)

    # log request
    request_id = await log_request(uid, code, delivered=True, chat=sent.chat_id, message=sent.message_id)

    # schedule via job queue
    context.job_queue.run_once(delete_job, DELETE_TIME_MINUTES * 60)

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user = query.from_user
    if data.startswith("report|"):
        code = data.split("|", 1)[1]
        # notify admins with report details
        text = f"🚨 Report from @{user.username or user.id}\nUser id: {user.id}\nReported item code: {code}\nTime: {datetime.utcnow().isoformat()}"
        for admin in ADMIN_IDS:
            try:
                await context.bot.send_message(admin, text)
            except Exception:
                logger.exception("Failed to notify admin")
        await query.edit_message_text("Thank you. Report sent to moderators.")
    else:
        await query.edit_message_text("Unknown action.")

# Admin commands
async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("Unauthorized.")
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /revoke <chat_id> <message_id>")
        return
    try:
        chat_id = int(args[0])
        msg_id = int(args[1])
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        await update.message.reply_text("Deleted.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("Unauthorized.")
        return
    # simple stats: total requests and deletions
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT COUNT(*) FROM requests")
        total_reqs = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM deletions")
        total_dels = (await cur.fetchone())[0]
    await update.message.reply_text(f"Total requests: {total_reqs}\nTotal deletions: {total_dels}")

# Fallback for unknown text
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Use /help.")

# ---------- main ----------
async def main():
    await init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(consent_cb, pattern="^consent_yes$"))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("get", get_cmd))
    app.add_handler(CallbackQueryHandler(callback_router, pattern="^(report\|)"))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), unknown))

    logger.info("Bot starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()  # keeps webhook off; polling used
    await app.idle()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
