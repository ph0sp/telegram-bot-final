import logging
from typing import Dict, Any, Optional
from telegram import Update
from telegram.ext import ContextTypes, CallbackContext

from config import logger
from database import update_user_activity, save_message, get_connection_pool

async def handle_all_messages(update: Update, context: CallbackContext) -> None:
    """Обрабатывает все текстовые сообщения включая кнопки"""
    if not update.message or not update.message.text:
        return
        
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Получаем данные пользователя для проверки состояния анкеты
    user_data = context.user_data or {}
    
    # Проверяем различные состояния анкеты
    questionnaire_states = [
        user_data.get('questionnaire_started', False),
        user_data.get('current_question', -2) >= -1,
        bool(user_data.get('assistant_gender')),
        bool(user_data.get('assistant_name')),
        bool(user_data.get('waiting_for_gender')),
        bool(user_data.get('waiting_for_ready'))
    ]
    
    # Если пользователь в ЛЮБОМ из этих состояний анкеты - пропускаем обработку
    if any(questionnaire_states):
        logger.info(f"⏩ Пропускаем сообщение в состоянии анкеты: {message_text}")
        return
    
    try:
        # Сохраняем сообщение и обновляем активность
        await save_message(user_id, message_text, 'incoming')
        await update_user_activity(user_id)
        
        logger.info(f"💬 Получено сообщение от {user_id}: {message_text}")
        
        # Проверяем, является ли сообщение напоминанием
        if is_reminder_request(message_text):
            from handlers.reminder import handle_reminder_nlp
            await handle_reminder_nlp(update, context)
            return
        
        # Обработка нажатий на кнопки
        button_handler = await handle_button_press(update, context, message_text)
        if button_handler:
            return
        
        # Если это не команда и не напоминание, отвечаем стандартным сообщением
        await send_default_response(update, context)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_all_messages: {e}")
        await update.message.reply_text(
            "⚠️ Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте еще раз."
        )


def is_reminder_request(message_text: str) -> bool:
    """Проверяет, является ли сообщение запросом напоминания"""
    reminder_keywords = ['напомни', 'напоминай', 'напомни мне', 'напоминание']
    message_lower = message_text.lower()
    
    for keyword in reminder_keywords:
        if keyword in message_lower:
            return True
    return False


async def handle_button_press(update: Update, context: CallbackContext, message_text: str) -> bool:
    """Обрабатывает нажатия на кнопки, возвращает True если кнопка обработана"""
    button_handlers = {
        '📊 прогресс': 'progress_command',
        '👤 профиль': 'profile_command',
        '📋 план на сегодня': 'plan_command',
        '🔔 мои напоминания': 'my_reminders_command',
        'ℹ️ помощь': 'help_command',
        '🎮 очки опыта': 'points_info_command',
        'прогресс': 'progress_command',
        'профиль': 'profile_command',
        'план': 'plan_command',
        'напоминания': 'my_reminders_command',
        'помощь': 'help_command',
        'очки': 'points_info_command'
    }
    
    normalized_text = message_text.lower().strip()
    
    if normalized_text in button_handlers:
        handler_name = button_handlers[normalized_text]
        logger.info(f"🔄 Обрабатываем нажатие кнопки: {message_text}")
        
        try:
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
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке кнопки {message_text}: {e}")
            await update.message.reply_text("❌ Произошла ошибка при обработке запроса. Попробуйте еще раз.")
        
        return True
    
    return False


async def send_default_response(update: Update, context: CallbackContext) -> None:
    """Отправляет стандартный ответ на неизвестное сообщение"""
    response = (
        "🤖 Я ваш ассистент по продуктивности!\n\n"
        "📋 **Основные команды:**\n"
        "• /start – начать работу\n"  
        "• /plan – план на сегодня\n"
        "• /progress – ваш прогресс\n"
        "• /profile – ваш профиль\n"
        "• /remind_me – установить напоминание\n"
        "• /help – все команды\n\n"
        "📝 **Напоминания естественным языком:**\n"
        "• 'Напомни мне в 20:00 сделать зарядку'\n"
        "• 'Напоминай каждый день в 8:00 пить витамины'\n"
        "• 'Напомни завтра утром позвонить врачу'\n\n"
        "🎯 **Отслеживание:**\n"
        "• /done – отметить выполненную задачу\n"
        "• /mood – настроение (1-10)\n"
        "• /energy – энергия (1-10)\n"
        "• /water – выпитая вода\n\n"
        "Выберите команду из меню или напишите мне!"
    )
    
    await update.message.reply_text(response, parse_mode='Markdown')


async def error_handler(update: Update, context: CallbackContext) -> None:
    """Обрабатывает ошибки бота БЕЗ отправки в Telegram"""
    error = context.error
    
    if not error:
        return
    
    error_str = str(error)
    
    # Список ошибок для игнорирования
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
        "Chat not found",
        "Message to delete not found",
        "Message can't be deleted",
        "Chat not found",
        "User is deactivated",
        "User not found",
        "bot was blocked by the user"
    ]
    
    # Проверяем, нужно ли игнорировать эту ошибку
    for ignore in ignore_errors:
        if ignore.lower() in error_str.lower():
            logger.warning(f"⚠️ Игнорируем ошибку: {error_str[:100]}...")
            return
    
    # Логируем серьезные ошибки
    logger.error(f"❌ Критическая ошибка в боте: {error_str}", exc_info=error)
    
    # Для отладки можно добавить отправку админу (если нужно)
    try:
        from config import YOUR_CHAT_ID
        
        # Формируем краткое сообщение об ошибке
        error_summary = (
            f"⚠️ **Ошибка в боте:**\n"
            f"Тип: {type(error).__name__}\n"
            f"Сообщение: {error_str[:200]}\n"
            f"Update: {update.update_id if update else 'N/A'}"
        )
        
        # Пытаемся отправить админу
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=error_summary
        )
    except Exception as e:
        logger.error(f"❌ Не удалось отправить ошибку админу: {e}")
