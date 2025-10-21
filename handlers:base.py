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

    # Сохраняем входящее сообщение
    save_message(user_id, message_text, 'incoming')
    update_user_activity(user_id)

    logger.info(f"💬 Получено сообщение от {user_id}: {message_text}")

    # Проверяем, является ли сообщение напоминанием
    if any(word in message_text.lower() for word in ['напомни', 'напоминай']):
        from handlers.reminder import handle_reminder_nlp
        await handle_reminder_nlp(update, context)
        return

    # Обработка нажатий на кнопки
    button_handlers = {
        '📊 прогресс': 'progress_command',
        '👤 профиль': 'profile_command',
        '📋 план на сегодня': 'plan_command',
        '🔔 мои напоминания': 'my_reminders_command',
        'ℹ️ помощь': 'help_command',
        '🎮 очки опыта': 'points_info_command',
        '📊 Прогресс': 'progress_command',
        '👤 Профиль': 'profile_command', 
        '📋 План на сегодня': 'plan_command',
        '🔔 Мои напоминания': 'my_reminders_command',
        'ℹ️ Помощь': 'help_command',
        '🎮 Очки опыта': 'points_info_command'
    }

    if message_text.lower() in [key.lower() for key in button_handlers.keys()]:
        # Найдем правильный регистр для вызова функции
        for key, handler_name in button_handlers.items():
            if key.lower() == message_text.lower():
                # Импортируем нужную функцию и вызываем
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

    # Игнорируем самые частые и неважные ошибки
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

    # Только логируем ошибки в файл, НЕ отправляем в Telegram
    logger.error(f"❌ Ошибка в боте: {error}")