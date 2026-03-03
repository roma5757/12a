import os
import sqlite3
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

ANTI_SPAM_SECONDS = 10

# --- База данных ---
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS contest (
    id INTEGER PRIMARY KEY,
    word TEXT,
    is_active INTEGER,
    winner_id INTEGER,
    winner_username TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS attempts (
    user_id INTEGER PRIMARY KEY,
    last_attempt INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS attempt_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    message TEXT,
    is_correct INTEGER,
    timestamp TEXT
)
""")
conn.commit()

# --- Проверка подписки ---
async def is_subscribed(user_id, context):
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# --- Админ-панель ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("🟢 Начать конкурс", callback_data="start_contest")],
        [InlineKeyboardButton("⛔ Остановить конкурс", callback_data="stop_contest")],
        [InlineKeyboardButton("🔄 Сбросить конкурс", callback_data="reset_contest")],
        [InlineKeyboardButton("📊 Просмотр логов", callback_data="show_logs")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Панель администратора:", reply_markup=reply_markup)

# --- Обработка кнопок ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    if query.data == "start_contest":
        await query.edit_message_text("Введите новое слово для конкурса:")
        return "WAIT_WORD"

    elif query.data == "stop_contest":
        cursor.execute("UPDATE contest SET is_active = 0")
        conn.commit()
        await query.edit_message_text("⛔ Конкурс остановлен.")

    elif query.data == "reset_contest":
        cursor.execute("DELETE FROM contest")
        conn.commit()
        await query.edit_message_text("🔄 Конкурс сброшен.")

    elif query.data == "show_logs":
        cursor.execute("""
            SELECT username, message, is_correct, timestamp
            FROM attempt_logs
            ORDER BY id DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()
        if not rows:
            await query.edit_message_text("Логов пока нет.")
            return
        text = ""
        for row in rows:
            username, message, is_correct, timestamp = row
            status = "✅" if is_correct else "❌"
            text += f"{status} @{username} → {message} ({timestamp})\n"
        await query.edit_message_text(text[:4000])

# --- Ввод слова после кнопки ---
async def set_new_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = update.message.text.lower()
    cursor.execute("DELETE FROM contest")
    cursor.execute(
        "INSERT INTO contest (word, is_active, winner_id, winner_username) VALUES (?, 1, NULL, NULL)",
        (word,)
    )
    conn.commit()
    await update.message.reply_text(f"✅ Новое слово установлено: {word}")
    return ConversationHandler.END

# --- Проверка комментариев ---
async def check_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.lower().strip()

    # Проверка подписки
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(f"❌ Подпишитесь на {CHANNEL_USERNAME}")
        return

    # Антиспам
    current_time = int(time.time())
    cursor.execute("SELECT last_attempt FROM attempts WHERE user_id = ?", (user.id,))
    data = cursor.fetchone()
    if data:
        if current_time - data[0] < ANTI_SPAM_SECONDS:
            return
    cursor.execute("INSERT OR REPLACE INTO attempts (user_id, last_attempt) VALUES (?, ?)", (user.id, current_time))
    conn.commit()

    # Проверяем конкурс
    cursor.execute("SELECT word, is_active FROM contest")
    contest = cursor.fetchone()
    if not contest:
        return
    word, is_active = contest
    is_correct = 1 if text == word and is_active else 0

    # Логирование
    cursor.execute("""
        INSERT INTO attempt_logs (user_id, username, message, is_correct, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (user.id, user.username or user.first_name, text, is_correct, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()

    if not is_active:
        return

    if text == word:
        cursor.execute("""
            UPDATE contest
            SET is_active = 0, winner_id = ?, winner_username = ?
        """, (user.id, user.username or user.first_name))
        conn.commit()

        await update.message.reply_text(f"🎉 Победитель: @{user.username or user.first_name}")

        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🏆 Победитель:\n@{user.username}\nID: {user.id}")

# --- Запуск ---
app = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(button_handler, pattern="start_contest")],
    states={"WAIT_WORD": [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_word)]},
    fallbacks=[]
)

app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(conv_handler)
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_comment))

app.run_polling()
