import logging
from telegram import Update
from telegram.ext import ContextTypes, CallbackContext

from config import logger
from database import update_user_activity, save_message

logger = logging.getLogger(__name__)

async def handle_all_messages(update: Update, context: CallbackContext):
    """Обрабатывает все текстовые сообщения включая кнопки"""
    user_id = update.effective_user.id
    message_text = update.message.text

    if context.user_data.get('questionnaire_started'):
        logger.info(f"🔇 Игнорируем сообщение во время анкеты: {message_text}")
        return

    # Проверяем конкретные состояния анкеты:
    current_question = context.user_data.get('current_question', -2)
    has_assistant_data = context.user_data.get('assistant_gender') or context.user_data.get('assistant_name')
    questionnaire_started = context.user_data.get('questionnaire_started', False)
    
    # Если пользователь в ЛЮБОМ из этих состояний анкеты - пропускаем обработку
    if current_question >= -1 or has_assistant_data or questionnaire_started:
        logger.info(f"⏩ Пропускаем сообщение в состоянии анкеты (вопрос {current_question}): {message_text}")
        return
    
    # Только если пользователь НЕ в анкете - продолжаем обработку
    save_message(user_id, message_text, 'incoming')
    update_user_activity(user_id)

    logger.info(f"💬 Получено сообщение от {user_id}: {message_text}")

    # Проверяем, является ли сообщение напоминанием
    if any(word in message_text.lower() for word in ['напомни', 'напоминай', 'напомни мне']):
        from handlers.reminder import handle_reminder_nlp
        await handle_reminder_nlp(update, context)
        return

    # Обработка нажатий на кнопки
    button_handlers = {
        '📊 Прогресс': 'progress_command',
        '👤 Профиль': 'profile_command',
        '📋 План на сегодня': 'plan_command',
        '🔔 Мои напоминания': 'my_reminders_command',
        'ℹ️ Помощь': 'help_command',
        '🎮 Очки опыта': 'points_info_command'
    }

    # Проверяем кнопки в независимости от регистра
    normalized_text = message_text.lower().strip()
    for button_text, handler_name in button_handlers.items():
        if button_text.lower() == normalized_text:
            logger.info(f"🔄 Обрабатываем нажатие кнопки: {button_text}")
            
            if handler_name == 'progress_command':
                from handlers.user import progress_command
                await progress_command(update, context)
            elif handler_name == 'profile_command':
                from handlers.user import profile_command
                await profile_command(update, context)
            elif handler_name == 'plan_command':
                from handlers.user import plan_command
                await plan_command(update, context)
            elif handler_name == 'my_reminders_command':
                from handlers.reminder import my_reminders_command
                await my_reminders_command(update, context)
            elif handler_name == 'help_command':
                from handlers.user import help_command
                await help_command(update, context)
            elif handler_name == 'points_info_command':
                from handlers.user import points_info_command
                await points_info_command(update, context)
            return

    # Если это не команда и не напоминание, отвечаем стандартным сообщением
    await update.message.reply_text(
        "🤖 Я ваш ассистент по продуктивности!\n\n"
        "Используйте кнопки меню или команды:\n"
        "• /start - начать работу\n"  
        "• /plan - план на сегодня\n"
        "• /progress - ваш прогресс\n"
        "• /help - все команды\n\n"
        "Или напишите напоминание:\n"
        "'напомни мне в 20:00 сделать зарядку'"
    )

async def error_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает ошибки бота БЕЗ отправки в Telegram"""
    error = context.error

    ignore_errors = [
        "terminated by other getUpdates request",
        "Conflict", 
        "ConnectionError",
        "Timed out",
        "RetryAfter",
        "Restarting",
        "Connection lost",
        "Connection aborted",
        "Read timed out",
        "Bad Request",
        "Forbidden",
        "Not Found",
        "Unauthorized",
        "Chat not found"
    ]

    # Проверяем, нужно ли игнорировать эту ошибку
    for ignore in ignore_errors:
        if ignore in str(error):
            logger.warning(f"⚠️ Игнорируем ошибку: {error}")
            return

    logger.error(f"❌ Ошибка в боте: {error}")
