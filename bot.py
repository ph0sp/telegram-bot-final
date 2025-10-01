import os
import logging
import sqlite3
import asyncio
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, Optional, Any, List

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    filters
)
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')
YOUR_CHAT_ID = os.environ.get('YOUR_CHAT_ID')

if not TOKEN:
    logger.error("❌ Токен бота не найден! Установите BOT_TOKEN")
    exit(1)

if not YOUR_CHAT_ID:
    logger.error("❌ Chat ID не найден! Установите YOUR_CHAT_ID")
    exit(1)

# Состояния диалога
GENDER, FIRST_QUESTION = range(2)

# Упрощенный список вопросов для начала
QUESTIONS = [
    "Готовы начать?",
    "Какая ваша главная цель на ближайший месяц?",
    "Почему эта цель важна для вас?",
    "Сколько часов в день вы готовы уделять этой цели?",
    "Расскажите о вашем текущем распорядке дня:"
]

# ========== БАЗА ДАННЫХ ==========

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS clients
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT,
                  first_name TEXT,
                  last_name TEXT,
                  status TEXT DEFAULT 'active',
                  registration_date TEXT,
                  last_activity TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS questionnaire_answers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  question_number INTEGER,
                  question_text TEXT,
                  answer_text TEXT,
                  answer_date TEXT)''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def save_user_info(user_id: int, username: str, first_name: str, last_name: Optional[str] = None):
    """Сохраняет информацию о пользователе"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT OR REPLACE INTO clients 
                 (user_id, username, first_name, last_name, registration_date, last_activity) 
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, username, first_name, last_name, registration_date, registration_date))
    conn.commit()
    conn.close()
    logger.info(f"✅ Пользователь {user_id} сохранен")

def update_user_activity(user_id: int):
    """Обновляет активность пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    last_activity = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''UPDATE clients SET last_activity = ? WHERE user_id = ?''',
              (last_activity, user_id))
    conn.commit()
    conn.close()

def save_questionnaire_answer(user_id: int, question_number: int, question_text: str, answer_text: str):
    """Сохраняет ответ на вопрос"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    answer_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT INTO questionnaire_answers 
                 (user_id, question_number, question_text, answer_text, answer_date) 
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id, question_number, question_text, answer_text, answer_date))
    conn.commit()
    conn.close()

def check_user_registered(user_id: int) -> bool:
    """Проверяет регистрацию пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM clients WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

# ========== ОСНОВНЫЕ КОМАНДЫ ==========

async def start(update: Update, context: CallbackContext) -> int:
    """Начало работы с ботом"""
    user = update.effective_user
    save_user_info(user.id, user.username, user.first_name, user.last_name)
    
    # Проверяем, заполнял ли пользователь анкету
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM questionnaire_answers WHERE user_id = ?", (user.id,))
    has_answers = c.fetchone()[0] > 0
    conn.close()
    
    if has_answers:
        await update.message.reply_text(
            "✅ Вы уже зарегистрированы!\n\n"
            "Используйте команды:\n"
            "/plan - Ваш план\n"
            "/progress - Прогресс\n"
            "/profile - Профиль\n"
            "/help - Помощь"
        )
        return ConversationHandler.END
    else:
        keyboard = [['👨 Мужской', '👩 Женский']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности!\n\n'
            'Для начала выберите пол ассистента:',
            reply_markup=reply_markup
        )
        
        return GENDER

async def gender_choice(update: Update, context: CallbackContext) -> int:
    """Выбор пола ассистента"""
    gender = update.message.text.replace('👨 ', '').replace('👩 ', '')
    context.user_data['assistant_gender'] = gender
    
    if gender == 'Мужской':
        assistant_name = 'Антон'
    else:
        assistant_name = 'Валерия'
    
    context.user_data['assistant_name'] = assistant_name
    context.user_data['current_question'] = 0
    context.user_data['answers'] = {}
    
    await update.message.reply_text(
        f'👋 Привет! Меня зовут {assistant_name}. Я помогу тебе стать более продуктивным!\n\n'
        f'{QUESTIONS[0]}',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return FIRST_QUESTION

async def handle_question(update: Update, context: CallbackContext) -> int:
    """Обработка ответов на вопросы"""
    user = update.effective_user
    answer_text = update.message.text
    current_question = context.user_data['current_question']
    
    # Сохраняем ответ
    save_questionnaire_answer(user.id, current_question, QUESTIONS[current_question], answer_text)
    context.user_data['answers'][current_question] = answer_text
    
    # Переходим к следующему вопросу
    context.user_data['current_question'] += 1
    
    if context.user_data['current_question'] < len(QUESTIONS):
        await update.message.reply_text(QUESTIONS[context.user_data['current_question']])
        return FIRST_QUESTION
    else:
        # Завершаем анкету
        return await finish_questionnaire(update, context)

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    """Завершение анкеты"""
    user = update.effective_user
    assistant_name = context.user_data['assistant_name']
    
    # Отправляем уведомление админу
    try:
        admin_message = (
            f"📋 Новая анкета от пользователя:\n\n"
            f"👤 Имя: {user.first_name}\n"
            f"🆔 ID: {user.id}\n"
            f"🔗 Username: @{user.username if user.username else 'нет'}\n"
            f"👨‍💼 Ассистент: {assistant_name}"
        )
        
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=admin_message,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💌 Ответить", callback_data=f"reply_{user.id}")
            ]])
        )
    except Exception as e:
        logger.error(f"Ошибка отправки админу: {e}")
    
    await update.message.reply_text(
        "🎉 Анкета завершена! Спасибо за ответы!\n\n"
        "📊 Я проанализирую ваши ответы и скоро пришлю персонализированный план.\n\n"
        "💡 А пока можете использовать команды:\n"
        "/plan - Общий план на день\n"
        "/progress - Статистика прогресса\n"
        "/help - Справка по командам"
    )
    
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    """Отмена диалога"""
    await update.message.reply_text(
        'Диалог прерван. Чтобы начать заново, отправьте /start',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ==========

async def plan_command(update: Update, context: CallbackContext):
    """Показывает план на день"""
    user = update.effective_user
    update_user_activity(user.id)
    
    if not check_user_registered(user.id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    plan_text = (
        "📋 Ваш план на сегодня:\n\n"
        "🌅 Утро (8:00 - 12:00):\n"
        "• Зарядка и медитация\n"
        "• Работа над главной задачей\n"
        "• Полезный завтрак\n\n"
        "🌞 День (12:00 - 18:00):\n"
        "• Обед и отдых\n"
        "• Второстепенные задачи\n"
        "• Обучение и развитие\n\n"
        "🌙 Вечер (18:00 - 22:00):\n"
        "• Спорт или прогулка\n"
        "• Ужин и отдых\n"
        "• Планирование следующего дня"
    )
    
    await update.message.reply_text(plan_text)

async def progress_command(update: Update, context: CallbackContext):
    """Показывает прогресс"""
    user = update.effective_user
    update_user_activity(user.id)
    
    if not check_user_registered(user.id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    progress_text = (
        "📊 Ваш прогресс:\n\n"
        "✅ Выполнено задач: 15/20\n"
        "🏃 Активность: 4/5 дней\n"
        "📚 Обучение: 5/7 часов\n"
        "💤 Сон: 7.5 часов в среднем\n\n"
        "🎯 Отличные результаты!"
    )
    
    await update.message.reply_text(progress_text)

async def profile_command(update: Update, context: CallbackContext):
    """Показывает профиль"""
    user = update.effective_user
    update_user_activity(user.id)
    
    if not check_user_registered(user.id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    profile_text = (
        f"👤 Ваш профиль:\n\n"
        f"📛 Имя: {user.first_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: @{user.username if user.username else 'не указан'}\n"
        f"💎 Статус: Активный пользователь"
    )
    
    await update.message.reply_text(profile_text)

async def help_command(update: Update, context: CallbackContext):
    """Показывает справку"""
    help_text = (
        "ℹ️ Справка по командам:\n\n"
        "/start - Начать работу\n"
        "/plan - План на день\n"
        "/progress - Статистика\n"
        "/profile - Профиль\n"
        "/help - Эта справка\n\n"
        "💬 Просто напишите сообщение для связи с ассистентом!"
    )
    
    await update.message.reply_text(help_text)

# ========== АДМИН КОМАНДЫ ==========

async def send_to_user(update: Update, context: CallbackContext):
    """Отправка сообщения пользователю"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /send <user_id> <сообщение>")
        return
    
    user_id = context.args[0]
    message = " ".join(context.args[1:])
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💌 Сообщение от ассистента:\n\n{message}"
        )
        await update.message.reply_text("✅ Сообщение отправлено!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def stats_command(update: Update, context: CallbackContext):
    """Статистика бота"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ Нет прав")
        return
    
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM clients")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM questionnaire_answers")
    total_answers = c.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📝 Ответов в анкетах: {total_answers}\n"
        f"🟢 Статус: Работает ✅"
    )
    
    await update.message.reply_text(stats_text)

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

async def handle_message(update: Update, context: CallbackContext):
    """Обработка обычных сообщений"""
    user = update.effective_user
    update_user_activity(user.id)
    
    if not check_user_registered(user.id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    # Пересылаем сообщение админу
    try:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=f"📩 Сообщение от {user.first_name}:\n\n{update.message.text}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💌 Ответить", callback_data=f"reply_{user.id}")
            ]])
        )
        await update.message.reply_text("✅ Сообщение отправлено ассистенту!")
    except Exception as e:
        logger.error(f"Ошибка пересылки: {e}")

async def button_handler(update: Update, context: CallbackContext):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('reply_'):
        user_id = query.data.replace('reply_', '')
        await query.edit_message_text(
            f"💌 Ответ пользователю {user_id}\n\n"
            f"Используйте: /send {user_id} ваше сообщение"
        )

# ========== ЗАПУСК БОТА ==========

def main():
    """Запускает бота"""
    try:
        # Создаем Application (важно - без Updater!)
        application = Application.builder().token(TOKEN).build()
        
        # Обработчик диалога
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [MessageHandler(filters.Regex('^(👨 Мужской|👩 Женский)$'), gender_choice)],
                FIRST_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        
        # Основные команды
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("help", help_command))
        
        # Админ команды
        application.add_handler(CommandHandler("send", send_to_user))
        application.add_handler(CommandHandler("stats", stats_command))
        
        # Обработчики кнопок и сообщений
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Запуск
        logger.info("🤖 Бот запускается...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска: {e}")

if __name__ == '__main__':
    main()
