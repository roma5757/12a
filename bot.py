import os
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

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

conn.commit()

# --- Команда задать слово ---
async def setword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Использование: /setword слово")
        return

    word = context.args[0].lower()

    cursor.execute("DELETE FROM contest")
    cursor.execute(
        "INSERT INTO contest (word, is_active, winner_id, winner_username) VALUES (?, 1, NULL, NULL)",
        (word,)
    )
    conn.commit()

    await update.message.reply_text(f"✅ Новое слово установлено: {word}")


# --- Статус ---
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    cursor.execute("SELECT word, is_active, winner_username FROM contest")
    data = cursor.fetchone()

    if not data:
        await update.message.reply_text("Конкурс не запущен.")
        return

    word, is_active, winner = data

    if is_active:
        await update.message.reply_text(f"Активно. Слово: {word}")
    else:
        await update.message.reply_text(f"Завершено. Победитель: @{winner}")


# --- Остановка ---
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    cursor.execute("UPDATE contest SET is_active = 0")
    conn.commit()

    await update.message.reply_text("⛔ Конкурс остановлен.")


# --- Проверка комментариев ---
async def check_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text
    if not text:
        return

    cursor.execute("SELECT word, is_active FROM contest")
    data = cursor.fetchone()

    if not data:
        return

    word, is_active = data

    if not is_active:
        return

    if text.lower().strip() == word:
        user = update.effective_user

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
            text=f"🏆 Победитель конкурса:\nUsername: @{user.username}\nID: {user.id}"
        )


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("setword", setword))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_comment))

app.run_polling()
