"""
Telegram Bot Assistant
Главный файл запуска бота с поддержкой PostgreSQL и Google Sheets
"""

import logging
import asyncio
import signal
import sys
from datetime import time as dt_time
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Конфигурация
from config import (
    TOKEN, YOUR_CHAT_ID, GENDER, READY_CONFIRMATION, QUESTIONNAIRE,
    ADD_PLAN_USER, ADD_PLAN_DATE, ADD_PLAN_CONTENT, logger,
    POSTGRESQL_AVAILABLE, GOOGLE_SHEETS_AVAILABLE
)

# Обработчики
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
    handle_reminder_nlp, schedule_reminders,
    send_morning_plan, send_evening_survey
)
from handlers.base import handle_all_messages

# База данных
from database import initialize_database, close_connection_pool


class TelegramBot:
    """
    Главный класс управления Telegram ботом.
    Реализует полный жизненный цикл бота с graceful shutdown.
    """
    
    def __init__(self, token: str, admin_chat_id: int):
        """
        Инициализация бота.
        
        Args:
            token: Токен бота от BotFather
            admin_chat_id: ID администратора для уведомлений
        """
        self.token = token
        self.admin_chat_id = admin_chat_id
        self.application: Optional[Application] = None
        self.shutdown_event = asyncio.Event()
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Настройка системы логирования."""
        # Логирование уже настроено в config.py, но дублируем на случай проблем
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO,
            handlers=[
                logging.FileHandler('bot_runtime.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Глобальный обработчик ошибок.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст вызова
        """
        error = context.error
        
        # Игнорируем незначительные ошибки
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
        
        error_str = str(error)
        for ignore in ignore_errors:
            if ignore in error_str:
                self.logger.warning(f"⚠️ Игнорируем ошибку: {error_str[:100]}")
                return
        
        # Логируем серьезные ошибки
        self.logger.error(f"❌ Необработанная ошибка: {error_str}", exc_info=True)
        
        # Отправляем уведомление администратору
        try:
            if self.application:
                await self.application.bot.send_message(
                    chat_id=self.admin_chat_id,
                    text=f"⚠️ Ошибка в боте:\n{error_str[:1000]}"
                )
        except Exception as e:
            self.logger.error(f"❌ Не удалось отправить уведомление об ошибке: {e}")
    
    def _setup_signal_handlers(self) -> None:
        """
        Настройка обработчиков сигналов для graceful shutdown.
        """
        loop = asyncio.get_running_loop()
        
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(self._handle_shutdown(s))
            )
    
    async def _handle_shutdown(self, signal_name: str) -> None:
        """
        Обработка сигналов завершения работы.
        
        Args:
            signal_name: Имя полученного сигнала
        """
        self.logger.info(f"🛑 Получен сигнал {signal_name}. Инициируем graceful shutdown...")
        self.shutdown_event.set()
        
        if self.application and self.application.running:
            await self.application.stop()
            await self.application.shutdown()
        
        # Закрываем пул соединений с БД
        await close_connection_pool()
        
        self.logger.info("✅ Бот корректно завершил работу")
    
    async def _setup_handlers(self) -> None:
        """Регистрация всех обработчиков команд."""
        # ConversationHandler для анкеты
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [
                    MessageHandler(
                        filters.Regex('^(🧌 Мужской|🧝🏽‍♀️ Женский|Мужской|Женский)$'),
                        gender_choice
                    )
                ],
                READY_CONFIRMATION: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        handle_ready_confirmation
                    )
                ],
                QUESTIONNAIRE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        handle_question
                    )
                ],
                ADD_PLAN_USER: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        add_plan_user
                    )
                ],
                ADD_PLAN_DATE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        add_plan_date
                    )
                ],
                ADD_PLAN_CONTENT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        add_plan_content
                    )
                ],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True,
            name="main_conversation"
        )
        
        # Регистрируем ConversationHandler первым
        self.application.add_handler(conv_handler)
        
        # Команды пользователей
        user_commands = [
            ("plan", plan_command),
            ("progress", progress_command),
            ("profile", profile_command),
            ("points_info", points_info_command),
            ("help", help_command),
            ("done", done_command),
            ("mood", mood_command),
            ("energy", energy_command),
            ("water", water_command),
        ]
        
        for command, handler in user_commands:
            self.application.add_handler(CommandHandler(command, handler))
        
        # Команды напоминаний
        reminder_commands = [
            ("remind_me", remind_me_command),
            ("regular_remind", regular_remind_command),
            ("my_reminders", my_reminders_command),
            ("delete_remind", delete_remind_command),
        ]
        
        for command, handler in reminder_commands:
            self.application.add_handler(CommandHandler(command, handler))
        
        # Команды администратора
        admin_commands = [
            ("add_plan", admin_add_plan),
            ("admin_stats", admin_stats),
            ("admin_users", admin_users),
        ]
        
        for command, handler in admin_commands:
            self.application.add_handler(CommandHandler(command, handler))
        
        # Обработчики кнопок
        self.application.add_handler(CallbackQueryHandler(button_callback))
        
        # Обработчик всех сообщений (должен быть последним)
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                handle_all_messages
            ),
            group=1  # Более низкий приоритет
        )
    
    async def _setup_job_queue(self) -> None:
        """Настройка JobQueue для периодических задач."""
        try:
            job_queue = self.application.job_queue
            if not job_queue:
                self.logger.warning("⚠️ JobQueue не доступен")
                return
            
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
            
            self.logger.info("✅ JobQueue настроен для автоматических сообщений")
            
        except Exception as e:
            self.logger.error(f"❌ Настройка JobQueue не удалась: {e}", exc_info=True)
    
    async def _initialize_services(self) -> None:
        """Инициализация всех сервисов (БД, Google Sheets и т.д.)."""
        self.logger.info("=== ИНИЦИАЛИЗАЦИЯ СЕРВИСОВ ===")
        self.logger.info(f"✅ PostgreSQL доступен: {POSTGRESQL_AVAILABLE}")
        self.logger.info(f"✅ Google Sheets доступен: {GOOGLE_SHEETS_AVAILABLE}")
        
        # Проверка обязательных переменных
        if not self.token or ':' not in self.token:
            raise ValueError(
                "❌ Неверный формат токена! "
                "Токен должен быть в формате '123456789:ABCdef...'"
            )
        
        if not self.admin_chat_id:
            raise ValueError("❌ Chat ID администратора не указан!")
        
        # Инициализация базы данных
        if POSTGRESQL_AVAILABLE:
            self.logger.info("🔄 Инициализация базы данных...")
            await initialize_database()
            self.logger.info("✅ База данных инициализирована")
        else:
            self.logger.warning("⚠️ Пропускаем инициализацию БД - PostgreSQL не доступен")
    
    async def setup(self) -> None:
        """
        Полная настройка бота перед запуском.
        """
        try:
            # Создаем приложение
            self.application = Application.builder().token(self.token).build()
            
            # Регистрируем глобальный обработчик ошибок
            self.application.add_error_handler(self.error_handler)
            
            # Настраиваем обработчики сигналов
            self._setup_signal_handlers()
            
            # Инициализируем сервисы
            await self._initialize_services()
            
            # Регистрируем обработчики команд
            await self._setup_handlers()
            
            # Настраиваем JobQueue
            await self._setup_job_queue()
            
            # Настраиваем систему напоминаний
            self.logger.info("🔄 Настройка системы напоминаний...")
            schedule_reminders(self.application)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка настройки бота: {e}", exc_info=True)
            raise
    
    async def run(self) -> None:
        """
        Запуск бота и бесконечный цикл обработки сообщений.
        """
        if not self.application:
            raise RuntimeError("Бот не настроен. Вызовите setup() перед run().")
        
        try:
            self.logger.info("🤖 Запуск бота...")
            self.logger.info("=== ВСЕ СИСТЕМЫ ЗАПУЩЕНЫ ===")
            
            # Запускаем бота
            await self.application.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                close_loop=False
            )
            
            # Ждем сигнала завершения
            await self.shutdown_event.wait()
            
        except asyncio.CancelledError:
            self.logger.info("🛑 Работа бота прервана")
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка в работе бота: {e}", exc_info=True)
            raise
        finally:
            # Гарантируем завершение работы
            await self._handle_shutdown("shutdown_final")
    
    async def stop(self) -> None:
        """
        Принудительная остановка бота.
        """
        self.logger.info("🛑 Принудительная остановка бота...")
        self.shutdown_event.set()


async def main() -> None:
    """
    Точка входа в приложение.
    """
    try:
        # Создаем экземпляр бота
        bot = TelegramBot(
            token=TOKEN,
            admin_chat_id=YOUR_CHAT_ID
        )
        
        # Настраиваем бота
        await bot.setup()
        
        # Запускаем бота
        await bot.run()
        
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except ValueError as e:
        logger.error(f"❌ Ошибка конфигурации: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    # Запускаем главную асинхронную функцию
    asyncio.run(main())
