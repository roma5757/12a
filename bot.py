import os
import sqlite3
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # например: @mychannel

ANTI_SPAM_SECONDS = 10  # можно изменить

# --- БАЗА ---
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

conn.commit()

# --- Проверка подписки ---
async def is_subscribed(user_id, context):
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# --- Установка слова ---
async def setword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Использование: /setword слово")
        return

    word = context.args[0].lower()

    cursor.execute("DELETE FROM contest")
    cursor.execute("""
        INSERT INTO contest (word, is_active, winner_id, winner_username)
        VALUES (?, 1, NULL, NULL)
    """, (word,))
    conn.commit()

    await update.message.reply_text(f"✅ Новое слово установлено: {word}")

# --- Проверка комментариев ---
async def check_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.lower().strip()

    # Проверка подписки
    if not await is_subscribed(user.id, context):
        await update.message.reply_text(
            f"❌ Чтобы участвовать, подпишитесь на {CHANNEL_USERNAME}"
        )
        return

    # Антиспам
    current_time = int(time.time())
    cursor.execute("SELECT last_attempt FROM attempts WHERE user_id = ?", (user.id,))
    data = cursor.fetchone()

    if data:
        last_attempt = data[0]
        if current_time - last_attempt < ANTI_SPAM_SECONDS:
            return  # молча игнорируем спам

    cursor.execute("""
        INSERT OR REPLACE INTO attempts (user_id, last_attempt)
        VALUES (?, ?)
    """, (user.id, current_time))
    conn.commit()

    # Проверяем конкурс
    cursor.execute("SELECT word, is_active FROM contest")
    contest = cursor.fetchone()

    if not contest:
        return

    word, is_active = contest

    if not is_active:
        return

    if text == word:
        # фиксируем победителя
        cursor.execute("""
            UPDATE contest
            SET is_active = 0,
                winner_id = ?,
                winner_username = ?
        """, (user.id, user.username or user.first_name))
        conn.commit()

        # сообщение в комментариях
        await update.message.reply_text(
            f"🎉 Победитель: @{user.username or user.first_name}\nКонкурс завершён!"
        )

        # сообщение админу
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🏆 Победитель:\nUsername: @{user.username}\nID: {user.id}"
        )

# --- Запуск ---
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("setword", setword))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_comment))

app.run_polling()
