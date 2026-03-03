import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import httpx

# Получаем переменные окружения
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Список правильных слов
CORRECT_WORDS = ["кот", "собака", "птица"]
used_words = set()  # уже угаданные слова

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Введи слово, и я проверю его."
    )

async def check_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_word = update.message.text.lower().strip()

    if user_word in CORRECT_WORDS:
        if user_word in used_words:
            await update.message.reply_text("Это слово уже угадано! 😕")
        else:
            used_words.add(user_word)
            await update.message.reply_text("Правильно! 🎉")
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"Пользователь {update.message.from_user.full_name} угадал слово: {user_word}"
                )
            except Exception as e:
                print(f"Ошибка при отправке админу: {e}")
    else:
        await update.message.reply_text("Неправильное слово 😕")

if __name__ == "__main__":
    # Создаём приложение с увеличенным таймаутом для надежности
    app = ApplicationBuilder().token(TOKEN)\
        .connect_timeout(60)\
        .read_timeout(60)\
        .write_timeout(60)\
        .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_word))

    print("Бот запущен...")
    app.run_polling()