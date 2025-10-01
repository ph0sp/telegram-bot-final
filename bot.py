import os
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ConversationHandler,
    filters
)

# ========== КОНФИГУРАЦИЯ ==========

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен из переменных окружения
TOKEN = os.environ.get('BOT_TOKEN')

if not TOKEN:
    logger.error("❌ Токен бота не найден! Установите BOT_TOKEN в настройках Render")
    exit(1)

# Состояния диалога
GENDER, BIO = range(2)

# ========== ОСНОВНЫЕ КОМАНДЫ ==========

async def start(update: Update, context: CallbackContext) -> int:
    """Начало работы с ботом"""
    user = update.effective_user
    
    keyboard = [['👨 Мужской', '👩 Женский']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        '👋 Привет! Я твой персональный ассистент по продуктивности!\n\n'
        'Для начала выбери пол ассистента:',
        reply_markup=reply_markup
    )
    
    return GENDER

async def gender_choice(update: Update, context: CallbackContext) -> int:
    """Обработка выбора пола ассистента"""
    gender = update.message.text
    
    if 'Мужской' in gender:
        assistant_name = 'Антон'
    else:
        assistant_name = 'Валерия'
    
    context.user_data['assistant_name'] = assistant_name
    
    await update.message.reply_text(
        f'👋 Отлично! Меня зовут {assistant_name}. '
        f'Я буду твоим персональным ассистентом!\n\n'
        f'Расскажи, какие у тебя цели и чем я могу помочь?',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return BIO

async def bio(update: Update, context: CallbackContext) -> int:
    """Обработка информации о пользователе"""
    user_bio = update.message.text
    assistant_name = context.user_data['assistant_name']
    
    await update.message.reply_text(
        f'🎉 Спасибо, что поделился! Теперь я, {assistant_name}, буду помогать тебе '
        f'достигать твоих целей!\n\n'
        f'Вот что я могу для тебя сделать:\n\n'
        '📋 /plan - Показать твой план на день\n'
        '📊 /progress - Статистика твоего прогресса\n'
        '👤 /profile - Информация о твоем профиле\n'
        'ℹ️ /help - Получить справку по командам\n\n'
        '💬 Ты всегда можешь просто написать мне сообщение - я на связи!'
    )
    
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    """Отмена диалога"""
    await update.message.reply_text(
        'Диалог прерван. Напиши /start чтобы начать заново.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def plan_command(update: Update, context: CallbackContext):
    """Показывает план на день"""
    plan_text = (
        "📋 Твой план на сегодня:\n\n"
        "🌅 Утро (8:00 - 12:00):\n"
        "• Зарядка и медитация - 20 мин\n"
        "• Работа над главной задачей - 3 часа\n"
        "• Полезный завтрак\n\n"
        "🌞 День (12:00 - 18:00):\n"
        "• Обед и отдых - 1 час\n"
        "• Второстепенные задачи - 2 часа\n"
        "• Обучение и развитие - 1 час\n\n"
        "🌙 Вечер (18:00 - 22:00):\n"
        "• Спорт или прогулка - 1 час\n"
        "• Ужин и отдых\n"
        "• Планирование следующего дня\n\n"
        "💡 Совет: Делай перерывы каждые 45 минут работы!"
    )
    
    await update.message.reply_text(plan_text)

async def progress_command(update: Update, context: CallbackContext):
    """Показывает прогресс"""
    progress_text = (
        "📊 Твой прогресс:\n\n"
        "✅ Выполнено задач за неделю: 15/20\n"
        "🏃 Физическая активность: 4/5 дней\n"
        "📚 Обучение: 5/7 часов\n"
        "💤 Средний сон: 7.5 часов\n\n"
        "🎯 Отличные результаты! Продолжай в том же духе!"
    )
    
    await update.message.reply_text(progress_text)

async def profile_command(update: Update, context: CallbackContext):
    """Показывает профиль"""
    user = update.effective_user
    
    profile_text = (
        f"👤 Твой профиль:\n\n"
        f"📛 Имя: {user.first_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: @{user.username if user.username else 'не указан'}\n"
        f"💎 Статус: Активный пользователь\n\n"
        f"✨ Ты на правильном пути к своей цели!"
    )
    
    await update.message.reply_text(profile_text)

async def help_command(update: Update, context: CallbackContext):
    """Показывает справку"""
    help_text = (
        "ℹ️ Справка по командам:\n\n"
        "🔹 Основные команды:\n"
        "/start - Начать работу с ботом\n"
        "/plan - План на сегодня\n"
        "/progress - Статистика прогресса\n"
        "/profile - Твой профиль\n"
        "/help - Эта справка\n\n"
        "💡 Просто напиши сообщение для общения с ассистентом!"
    )
    
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: CallbackContext):
    """Обработка обычных сообщений"""
    await update.message.reply_text(
        "✅ Получил твое сообщение! Скоро отвечу 💬\n\n"
        "А пока можешь посмотреть:\n"
        "📋 /plan - твой план на день\n"
        "📊 /progress - статистику прогресса"
    )

# ========== ЗАПУСК БОТА ==========

def main():
    """Запускает бота"""
    try:
        # Создаем Application
        application = Application.builder().token(TOKEN).build()
        
        # Обработчик диалога
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [MessageHandler(filters.Regex('^(👨 Мужской|👩 Женский)$'), gender_choice)],
                BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bio)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        
        # Добавляем обработчики команд
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("help", help_command))
        
        # Обработчик обычных сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Запускаем бота
        logger.info("🤖 Бот запускается...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
