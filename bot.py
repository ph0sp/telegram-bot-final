import logging
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

# Автоматические импорты из наших модулей
from config import (
    TOKEN, GENDER, FIRST_QUESTION, ADD_PLAN_USER, 
    ADD_PLAN_DATE, ADD_PLAN_CONTENT, logger,
    POSTGRESQL_AVAILABLE, GOOGLE_SHEETS_AVAILABLE
)
# БД автоматически инициализируется при импорте database.py
from database import (
    save_user_info, update_user_activity, check_user_registered,
    save_questionnaire_answer, save_message, save_user_plan_to_db,
    get_user_plan_from_db, save_progress_to_db, get_user_stats,
    has_sufficient_data, get_user_activity_streak, get_user_main_goal,
    get_user_level_info, get_favorite_ritual, get_user_usage_days,
    add_reminder_to_db, get_user_reminders, delete_reminder_from_db,
    restore_questionnaire_state
)
from handlers.start import (
    start, gender_choice, handle_question, finish_questionnaire, 
    handle_continue_choice, cancel
)
from handlers.user import (
    plan_command, progress_command, profile_command, 
    points_info_command, help_command,
    done_command, mood_command, energy_command, water_command
)
from handlers.admin import (
    admin_add_plan, add_plan_user, add_plan_date, 
    add_plan_content, admin_stats, admin_users
)
from handlers.reminder import (
    remind_me_command, regular_remind_command, 
    my_reminders_command, delete_remind_command,
    handle_reminder_nlp
)
from handlers.admin import button_callback
from handlers.base import handle_all_messages
from handlers.reminder import (
    schedule_reminders, send_morning_plan, send_evening_survey
)

async def error_handler(update: Update, context: CallbackContext) -> None:
    """Автоматически обрабатывает ошибки бота БЕЗ отправки в Telegram"""
    error = context.error
    
    # Автоматически игнорируем самые частые и неважные ошибки
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
    
    # Автоматически проверяем, нужно ли игнорировать эту ошибку
    for ignore in ignore_errors:
        if ignore in str(error):
            logger.warning(f"⚠️ Автоматически игнорируем ошибку: {error}")
            return
    
    # Только автоматически логируем ошибки в файл, НЕ отправляем в Telegram
    logger.error(f"❌ Автоматически обработана ошибка в боте: {error}")

def main():
    """Автоматическая функция запуска бота"""
    try:
        # Автоматическое логирование информации о доступных сервисах
        logger.info("=== АВТОМАТИЧЕСКИЙ ЗАПУСК БОТА ===")
        logger.info(f"✅ PostgreSQL доступен: {POSTGRESQL_AVAILABLE}")
        logger.info(f"✅ Google Sheets доступен: {GOOGLE_SHEETS_AVAILABLE}")
        logger.info(f"✅ Токен бота: {'установлен' if TOKEN else 'ОТСУТСТВУЕТ'}")
        logger.info(f"✅ Chat ID: {'установлен' if TOKEN else 'ОТСУТСТВУЕТ'}")
        
        # Автоматическая проверка обязательных переменных
        if not TOKEN or ':' not in TOKEN:
            logger.error("❌ Неверный формат токена! Токен должен быть в формате '123456789:ABCdef...'")
            return

        # БД автоматически инициализируется при импорте database.py
        # Ничего не нужно вызывать вручную!

        # Автоматическое создание приложения
        logger.info("🔄 Автоматическое создание приложения Telegram...")
        application = Application.builder().token(TOKEN).build()
        
        # Автоматическая регистрация обработчика ошибок
        application.add_error_handler(error_handler)

        # Автоматическая настройка обработчика диалога
        logger.info("🔄 Автоматическая регистрация обработчиков команд...")
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
        
        # Автоматическая регистрация команд для пользователей
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("points_info", points_info_command))
        application.add_handler(CommandHandler("help", help_command))
        
        # Автоматическая регистрация команд для отслеживания прогресса
        application.add_handler(CommandHandler("done", done_command))
        application.add_handler(CommandHandler("mood", mood_command))
        application.add_handler(CommandHandler("energy", energy_command))
        application.add_handler(CommandHandler("water", water_command))
        
        # Автоматическая регистрация команд для напоминаний
        application.add_handler(CommandHandler("remind_me", remind_me_command))
        application.add_handler(CommandHandler("regular_remind", regular_remind_command))
        application.add_handler(CommandHandler("my_reminders", my_reminders_command))
        application.add_handler(CommandHandler("delete_remind", delete_remind_command))

        # Автоматическая регистрация команд для администратора
        application.add_handler(CommandHandler("add_plan", admin_add_plan))
        application.add_handler(CommandHandler("admin_stats", admin_stats))
        application.add_handler(CommandHandler("admin_users", admin_users))
        
        # Автоматическая регистрация обработчиков кнопок и сообщений
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
        
        # Автоматическая настройка системы напоминаний
        logger.info("🔄 Автоматическая настройка системы напоминаний...")
        schedule_reminders(application)
        
        # Автоматическая настройка JobQueue
        logger.info("🔄 Автоматическая настройка JobQueue...")
        try:
            job_queue = application.job_queue
            if job_queue:
                # Автоматическое удаление старых задач
                current_jobs = job_queue.jobs()
                for job in current_jobs:
                    job.schedule_removal()
                
                # Автоматическое утреннее сообщение в 6:00 (3:00 UTC для UTC+3)
                job_queue.run_daily(
                    callback=send_morning_plan,
                    time=dt_time(hour=3, minute=0, second=0),
                    days=tuple(range(7)),
                    name="morning_plan"
                )
                
                # Автоматическое вечерний опрос в 21:00 (18:00 UTC для UTC+3)
                job_queue.run_daily(
                    callback=send_evening_survey,
                    time=dt_time(hour=18, minute=0, second=0),
                    days=tuple(range(7)),
                    name="evening_survey"
                )
                
                logger.info("✅ JobQueue автоматически настроен для автоматических сообщений")
            else:
                logger.warning("⚠️ JobQueue не доступен для автоматической настройки")
                
        except Exception as e:
            logger.error(f"❌ Автоматическая настройка JobQueue не удалась: {e}")

        logger.info("🤖 Бот автоматически запускается...")
        logger.info("=== ВСЕ СИСТЕМЫ АВТОМАТИЧЕСКИ ЗАПУЩЕНЫ ===")
        
        # Автоматический запуск бота
        application.run_polling(
            poll_interval=1.0,
            timeout=20,
            drop_pending_updates=True,
            allowed_updates=[
                "message", 
                "callback_query",
                "edited_message"
            ]
        )
        
    except Exception as e:
        logger.error(f"❌ Автоматический запуск бота не удался: {e}")
        raise

if __name__ == '__main__':
    main()
