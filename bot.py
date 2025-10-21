import os
import logging
import asyncio
from datetime import datetime, time as dt_time

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Импорты из наших модулей
from config import (
    TOKEN, GENDER, FIRST_QUESTION, ADD_PLAN_USER, 
    ADD_PLAN_DATE, ADD_PLAN_CONTENT, logger
)
from database import init_database
from handlers.start_handlers import (
    start, gender_choice, handle_question, finish_questionnaire, 
    handle_continue_choice, cancel
)
from handlers.user_handlers import (
    plan_command, progress_command, profile_command, 
    points_info_command, help_command,
    done_command, mood_command, energy_command, water_command
)
from handlers.admin_handlers import (
    admin_add_plan, add_plan_user, add_plan_date, 
    add_plan_content, admin_stats, admin_users
)
from handlers.reminder_handlers import (
    remind_me_command, regular_remind_command, 
    my_reminders_command, delete_remind_command,
    handle_reminder_nlp, handle_all_messages, button_callback
)
from services.reminder_service import (
    schedule_reminders, send_morning_plan, send_evening_survey
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

def main():
    """Основная функция запуска бота для Render"""
    try:
        # Инициализируем базу данных
        init_database()
        
        # Создаем приложение
        application = Application.builder().token(TOKEN).build()
        
        # Регистрируем обработчик ошибок
        application.add_error_handler(error_handler)

        # ОБНОВЛЕННЫЙ обработчик диалога
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [
                    MessageHandler(filters.Regex('^(👨 Мужской|👩 Женский|Мужской|Женский)$'), gender_choice),
                    MessageHandler(filters.Regex('^(✅ Продолжить анкету|🔄 Начать заново|❌ Отменить)$'), handle_continue_choice)
                ],
                FIRST_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)],
                ADD_PLAN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_user)],
                ADD_PLAN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_date)],
                ADD_PLAN_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_content)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        application.add_handler(conv_handler)
        
        # Команды для пользователей
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("points_info", points_info_command))
        application.add_handler(CommandHandler("help", help_command))
        
        # Команды для отслеживания прогресса
        application.add_handler(CommandHandler("done", done_command))
        application.add_handler(CommandHandler("mood", mood_command))
        application.add_handler(CommandHandler("energy", energy_command))
        application.add_handler(CommandHandler("water", water_command))
        
        # Команды для напоминаний
        application.add_handler(CommandHandler("remind_me", remind_me_command))
        application.add_handler(CommandHandler("regular_remind", regular_remind_command))
        application.add_handler(CommandHandler("my_reminders", my_reminders_command))
        application.add_handler(CommandHandler("delete_remind", delete_remind_command))

        # Команды для администратора
        application.add_handler(CommandHandler("add_plan", admin_add_plan))
        application.add_handler(CommandHandler("admin_stats", admin_stats))
        application.add_handler(CommandHandler("admin_users", admin_users))
        
        # Обработчики кнопок и сообщений
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
        
        # ✅ ДОБАВЛЯЕМ СИСТЕМУ НАПОМИНАНИЙ
        schedule_reminders(application)
        
        # УПРОЩЕННАЯ настройка JobQueue для Render Starter
        try:
            job_queue = application.job_queue
            if job_queue:
                # Удаляем старые задачи
                current_jobs = job_queue.jobs()
                for job in current_jobs:
                    job.schedule_removal()
                
                # Утреннее сообщение в 6:00 (3:00 UTC для UTC+3)
                job_queue.run_daily(
                    callback=send_morning_plan,
                    time=dt_time(hour=3, minute=0, second=0),
                    days=tuple(range(7)),
                    name="morning_plan"
                )
                
                # Вечерний опрос в 21:00 (18:00 UTC для UTC+3)
                job_queue.run_daily(
                    callback=send_evening_survey,
                    time=dt_time(hour=18, minute=0, second=0),
                    days=tuple(range(7)),
                    name="evening_survey"
                )
                
                logger.info("✅ JobQueue настроен для автоматических сообщений")
                
        except Exception as e:
            logger.error(f"❌ Ошибка настройки JobQueue: {e}")

        logger.info("🤖 Бот запускается на Render с PostgreSQL...")
        application.run_polling(
            poll_interval=1.0,
            timeout=20,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка запуска бота: {e}")
        raise

if __name__ == '__main__':
    main()