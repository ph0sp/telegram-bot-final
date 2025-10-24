import logging
from datetime import datetime, time as dt_time
import signal
import sys
import asyncio

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
    TOKEN, YOUR_CHAT_ID, GENDER, READY_CONFIRMATION, QUESTIONNAIRE, 
    ADD_PLAN_USER, ADD_PLAN_DATE, ADD_PLAN_CONTENT, logger,
    POSTGRESQL_AVAILABLE, GOOGLE_SHEETS_AVAILABLE
)

# ЯВНЫЙ ИМПОРТ всех функций из handlers.start
from handlers.start import (
    start, gender_choice, handle_ready_confirmation, 
    handle_question, finish_questionnaire, cancel
)

from handlers.user import (
    plan_command, progress_command, profile_command, 
    points_info_command, help_command,
    done_command, mood_command, energy_command, water_command
)
from handlers.admin import (
    admin_add_plan, add_plan_user, add_plan_date, 
    add_plan_content, admin_stats, admin_users, button_callback
)
from handlers.reminder import (
    remind_me_command, regular_remind_command, 
    my_reminders_command, delete_remind_command,
    handle_reminder_nlp, schedule_reminders, send_morning_plan, send_evening_survey
)
from handlers.base import handle_all_messages

# Импорт асинхронной инициализации БД
from database import initialize_database

# Глобальная переменная для graceful shutdown
application = None

def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    logger.info("🛑 Получен сигнал остановки...")
    if application:
        application.stop()
    sys.exit(0)

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
    
    # Логируем ошибки в файл
    logger.error(f"❌ Ошибка в боте: {error}")

async def main():
    """Асинхронная функция запуска бота"""
    global application
    
    try:
        # Настройка обработчиков сигналов
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Логирование информации о доступных сервисах
        logger.info("=== ЗАПУСК БОТА ===")
        logger.info(f"✅ PostgreSQL доступен: {POSTGRESQL_AVAILABLE}")
        logger.info(f"✅ Google Sheets доступен: {GOOGLE_SHEETS_AVAILABLE}")
        logger.info(f"✅ Токен бота: {'установлен' if TOKEN else 'ОТСУТСТВУЕТ'}")
        logger.info(f"✅ Chat ID: {'установлен' if YOUR_CHAT_ID else 'ОТСУТСТВУЕТ'}")
        
        # Проверка обязательных переменных
        if not TOKEN or ':' not in TOKEN:
            logger.error("❌ Неверный формат токена! Токен должен быть в формате '123456789:ABCdef...'")
            return

        if not YOUR_CHAT_ID:
            logger.error("❌ Chat ID не указан! Установите YOUR_CHAT_ID в .env файле")
            return

        # ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (АСИНХРОННАЯ)
        if POSTGRESQL_AVAILABLE:
            logger.info("🔄 Инициализация базы данных...")
            await initialize_database()
            logger.info("✅ База данных инициализирована")
        else:
            logger.warning("⚠️ Пропускаем инициализацию БД - PostgreSQL не доступен")

        # Создание приложения
        logger.info("🔄 Создание приложения Telegram...")
        application = Application.builder().token(TOKEN).build()
        
        # Регистрация обработчика ошибок
        application.add_error_handler(error_handler)

        # Настройка обработчика диалога
        logger.info("🔄 Регистрация обработчиков команд...")
        
        # ConversationHandler - единственный обработчик для /start
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [
                    MessageHandler(filters.Regex('^(🧌 Мужской|🧝🏽‍♀️ Женский|Мужской|Женский)$'), gender_choice)
                ],
                READY_CONFIRMATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ready_confirmation)
                ],
                QUESTIONNAIRE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)
                ],
                ADD_PLAN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_user)],
                ADD_PLAN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_date)],
                ADD_PLAN_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_content)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True,
            name="main_conversation"
        )

        # ConversationHandler должен быть первым
        application.add_handler(conv_handler)
        
        # Регистрация команд для пользователей
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
        
        # Обработчики кнопок
        application.add_handler(CallbackQueryHandler(button_callback))
        
        # Обработчик всех сообщений - последним
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages), group=1)
        
        # Настройка системы напоминаний
        logger.info("🔄 Настройка системы напоминаний...")
        schedule_reminders(application)
        
        # Настройка JobQueue
        logger.info("🔄 Настройка JobQueue...")
        try:
            job_queue = application.job_queue
            if job_queue:
                # Удаляем только наши старые задачи
                our_jobs = [job for job in job_queue.jobs() if job.name in ["morning_plan", "evening_survey"]]
                for job in our_jobs:
                    job.schedule_removal()
                logger.info(f"🧹 Удалено {len(our_jobs)} старых задач")
                
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
            else:
                logger.warning("⚠️ JobQueue не доступен")
                
        except Exception as e:
            logger.error(f"❌ Настройка JobQueue не удалась: {e}")

        logger.info("🤖 Бот запускается...")
        logger.info("=== ВСЕ СИСТЕМЫ ЗАПУЩЕНЫ ===")
        
        # Запуск бота
        await application.run_polling(
            poll_interval=1.0,
            timeout=20,
            drop_pending_updates=True,
            allowed_updates=[
                "message", 
                "callback_query",
                "edited_message"
            ]
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Запуск бота не удался: {e}")
        raise

if __name__ == "__main__":
    try:
        # Запускаем асинхронную функцию main
        asyncio.run(main())
    except Exception as e:
        logging.error(f"❌ Ошибка запуска бота: {e}")
