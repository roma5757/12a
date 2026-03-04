import os
import sqlite3
import time
import random
import asyncio
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

ANTI_SPAM_SECONDS = 10

# ================= БАЗА ДАННЫХ =================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

# Угадай слово
cursor.execute("""
CREATE TABLE IF NOT EXISTS contest (
    word TEXT,
    is_active INTEGER,
    winner_id INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS attempts (
    user_id INTEGER PRIMARY KEY,
    last_attempt INTEGER
)
""")

# Giveaway
cursor.execute("""
CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    winners_count INTEGER,
    end_time INTEGER,
    is_active INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS giveaway_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id INTEGER,
    user_id INTEGER,
    username TEXT
)
""")

conn.commit()

# ================= ПРОВЕРКА ПОДПИСКИ =================

async def is_subscribed(user_id, context):
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# =====================================================
# ================= УГАДАЙ СЛОВО =====================
# =====================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("Введите слово для конкурса:")
    return 1

async def set_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = update.message.text.lower()
    cursor.execute("DELETE FROM contest")
    cursor.execute("INSERT INTO contest VALUES (?, 1, NULL)", (word,))
    conn.commit()
    await update.message.reply_text("Слово установлено.")
    return ConversationHandler.END

async def check_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.lower().strip()

    if not await is_subscribed(user.id, context):
        return

    # антиспам
    now = int(time.time())
    cursor.execute("SELECT last_attempt FROM attempts WHERE user_id=?", (user.id,))
    data = cursor.fetchone()
    if data and now - data[0] < ANTI_SPAM_SECONDS:
        return

    cursor.execute("INSERT OR REPLACE INTO attempts VALUES (?,?)", (user.id, now))
    conn.commit()

    cursor.execute("SELECT word, is_active FROM contest")
    contest = cursor.fetchone()
    if not contest:
        return

    word, is_active = contest
    if is_active and text == word:
        cursor.execute("UPDATE contest SET is_active=0, winner_id=?", (user.id,))
        conn.commit()

        await update.message.reply_text(f"🎉 Победитель: @{user.username}")
        await context.bot.send_message(
            ADMIN_ID,
            f"Угадал слово: @{user.username}"
        )

# =====================================================
# ================= GIVEAWAY ==========================
# =====================================================

PHOTO, DESC, WINNERS, TIME = range(4)

async def giveaway_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("Отправьте фото или /skip")
    return PHOTO

async def giveaway_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["photo"] = update.message.photo[-1].file_id
    await update.message.reply_text("Введите описание:")
    return DESC

async def giveaway_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["photo"] = None
    await update.message.reply_text("Введите описание:")
    return DESC

async def giveaway_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["desc"] = update.message.text
    await update.message.reply_text("Сколько победителей?")
    return WINNERS

async def giveaway_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["winners"] = int(update.message.text)
    await update.message.reply_text("Через сколько минут завершить?")
    return TIME

async def giveaway_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    minutes = int(update.message.text)
    end_time = int(time.time()) + minutes * 60

    text = f"""
🎁 <b>РОЗЫГРЫШ</b>

{context.user_data["desc"]}

🏆 Победителей: {context.user_data["winners"]}
⏳ Итоги через {minutes} мин.
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎉 Участвовать (0)", callback_data="join")]
    ])

    if context.user_data["photo"]:
        msg = await context.bot.send_photo(
            CHANNEL_USERNAME,
            context.user_data["photo"],
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        msg = await context.bot.send_message(
            CHANNEL_USERNAME,
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    cursor.execute("""
    INSERT INTO giveaways (message_id, winners_count, end_time, is_active)
    VALUES (?, ?, ?, 1)
    """, (msg.message_id, context.user_data["winners"], end_time))
    conn.commit()

    asyncio.create_task(finish_giveaway(context, msg.message_id))

    await update.message.reply_text("Розыгрыш запущен.")
    return ConversationHandler.END

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    if not await is_subscribed(user.id, context):
        return

    cursor.execute("SELECT id FROM giveaways WHERE is_active=1")
    g = cursor.fetchone()
    if not g:
        return

    giveaway_id = g[0]

    cursor.execute("""
    SELECT * FROM giveaway_participants
    WHERE giveaway_id=? AND user_id=?
    """, (giveaway_id, user.id))
    if cursor.fetchone():
        return

    cursor.execute("""
    INSERT INTO giveaway_participants (giveaway_id,user_id,username)
    VALUES (?,?,?)
    """, (giveaway_id, user.id, user.username))
    conn.commit()

    cursor.execute("""
    SELECT COUNT(*) FROM giveaway_participants WHERE giveaway_id=?
    """, (giveaway_id,))
    count = cursor.fetchone()[0]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎉 Участвовать ({count})", callback_data="join")]
    ])

    await query.edit_message_reply_markup(reply_markup=keyboard)

async def finish_giveaway(context, message_id):
    while True:
        cursor.execute("""
        SELECT id, winners_count, end_time
        FROM giveaways
        WHERE message_id=? AND is_active=1
        """, (message_id,))
        data = cursor.fetchone()

        if not data:
            return

        giveaway_id, winners_count, end_time = data

        if int(time.time()) >= end_time:
            cursor.execute("""
            SELECT username FROM giveaway_participants
            WHERE giveaway_id=?
            """, (giveaway_id,))
            participants = cursor.fetchall()

            if not participants:
                return

            random.shuffle(participants)
            winners = participants[:winners_count]

            winners_text = "\n".join([f"@{w[0]}" for w in winners])

            await context.bot.send_message(
                CHANNEL_USERNAME,
                f"🏆 <b>Победители:</b>\n{winners_text}",
                parse_mode="HTML",
                reply_to_message_id=message_id
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Перевыбрать", callback_data="reroll")]
            ])

            await context.bot.send_message(
                CHANNEL_USERNAME,
                "Перевыбрать победителей:",
                reply_markup=keyboard
            )

            cursor.execute("UPDATE giveaways SET is_active=0 WHERE id=?", (giveaway_id,))
            conn.commit()
            return

        await asyncio.sleep(10)

async def reroll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    cursor.execute("""
    SELECT id, winners_count FROM giveaways
    ORDER BY id DESC LIMIT 1
    """)
    g = cursor.fetchone()

    if not g:
        return

    giveaway_id, winners_count = g

    cursor.execute("""
    SELECT username FROM giveaway_participants
    WHERE giveaway_id=?
    """, (giveaway_id,))
    participants = cursor.fetchall()

    random.shuffle(participants)
    winners = participants[:winners_count]

    winners_text = "\n".join([f"@{w[0]}" for w in winners])

    await query.message.reply_text(
        f"🔄 <b>Новые победители:</b>\n{winners_text}",
        parse_mode="HTML"
    )

# ================= ЗАПУСК =================

app = ApplicationBuilder().token(TOKEN).build()

# угадай слово
conv_word = ConversationHandler(
    entry_points=[CommandHandler("admin", admin)],
    states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_word)]},
    fallbacks=[]
)

# giveaway
conv_give = ConversationHandler(
    entry_points=[CommandHandler("giveaway", giveaway_start)],
    states={
        PHOTO: [
            MessageHandler(filters.PHOTO, giveaway_photo),
            CommandHandler("skip", giveaway_skip)
        ],
        DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, giveaway_desc)],
        WINNERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, giveaway_winners)],
        TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, giveaway_time)]
    },
    fallbacks=[]
)

app.add_handler(conv_word)
app.add_handler(conv_give)
app.add_handler(CallbackQueryHandler(join, pattern="join"))
app.add_handler(CallbackQueryHandler(reroll, pattern="reroll"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_word))

app.run_polling()
