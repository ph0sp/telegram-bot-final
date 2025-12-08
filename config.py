import os
import sys
import logging
import logging.config
import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional, Union
from enum import IntEnum
from pathlib import Path
from dotenv import load_dotenv


class ConversationState(IntEnum):
    """Состояния диалога с пользователем"""
    GENDER = 0
    READY_CONFIRMATION = 1
    QUESTIONNAIRE = 2
    ADD_PLAN_USER = 3
    ADD_PLAN_DATE = 4
    ADD_PLAN_CONTENT = 5
    SELECT_TEMPLATE = 6
    SELECT_USER_FOR_TEMPLATE = 7
    SELECT_DATE_FOR_TEMPLATE = 8


class PlanFields:
    """Поля плана в базе данных"""
    ID = 0
    USER_ID = 1
    PLAN_DATE = 2
    MORNING_RITUAL1 = 4
    MORNING_RITUAL2 = 5
    TASK1 = 6
    TASK2 = 7
    TASK3 = 8
    TASK4 = 9
    LUNCH_BREAK = 10
    EVENING_RITUAL1 = 11
    EVENING_RITUAL2 = 12
    ADVICE = 13
    SLEEP_TIME = 14
    WATER_GOAL = 15
    ACTIVITY_GOAL = 16
    
    REQUIRED_FIELDS = ['id', 'user_id', 'plan_date']
    
    @classmethod
    def get_field_mapping(cls) -> Dict[str, int]:
        """Возвращает маппинг полей для обратной совместимости"""
        return {
            'id': cls.ID,
            'user_id': cls.USER_ID,
            'plan_date': cls.PLAN_DATE,
            'morning_ritual1': cls.MORNING_RITUAL1,
            'morning_ritual2': cls.MORNING_RITUAL2,
            'task1': cls.TASK1,
            'task2': cls.TASK2,
            'task3': cls.TASK3,
            'task4': cls.TASK4,
            'lunch_break': cls.LUNCH_BREAK,
            'evening_ritual1': cls.EVENING_RITUAL1,
            'evening_ritual2': cls.EVENING_RITUAL2,
            'advice': cls.ADVICE,
            'sleep_time': cls.SLEEP_TIME,
            'water_goal': cls.WATER_GOAL,
            'activity_goal': cls.ACTIVITY_GOAL
        }


@dataclass(frozen=True)
class TemplateConfig:
    """Конфигурация шаблона плана"""
    name: str
    description: str
    strategic_tasks: List[str]
    critical_tasks: List[str]
    priorities: List[str]
    advice: List[str]
    special_rituals: List[str]
    time_blocks: List[str]
    resources: List[str]
    expected_results: List[str]
    reminders: List[str]
    motivation_quote: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует датакласс в словарь"""
        return asdict(self)


@dataclass(frozen=True)
class BotConfig:
    """Основная конфигурация бота"""
    token: str
    chat_id: int
    database_url: str
    google_sheets_id: Optional[str]
    google_credentials_json: Optional[str]
    google_sheets_available: bool = False
    postgresql_available: bool = True
    log_level: str = "INFO"
    bot_name: str = "Productivity Assistant"
    
    @property
    def is_valid(self) -> bool:
        """Проверяет, является ли конфигурация валидной"""
        return bool(
            self.token 
            and self.chat_id 
            and self.database_url 
            and len(self.token) > 30  # Минимальная длина токена
        )


class ConfigValidator:
    """Валидатор конфигурации"""
    
    @staticmethod
    def safe_path_join(base_dir: Union[str, Path], filename: str) -> Path:
        """
        Безопасное объединение путей с защитой от traversal attacks.
        
        Args:
            base_dir: Базовая директория
            filename: Имя файла (без относительных путей)
            
        Returns:
            Абсолютный путь к файлу
            
        Raises:
            ValueError: При недопустимом имени файла
        """
        base_path = Path(base_dir).resolve()
        if not filename:
            raise ValueError("Имя файла не может быть пустым")
        
        # Проверяем на попытки выхода за пределы директории
        if '..' in filename or filename.startswith('/') or filename.startswith('~'):
            raise ValueError(f"Недопустимое имя файла: {filename}")
        
        result_path = (base_path / filename).resolve()
        
        # Проверяем, что итоговый путь находится внутри базовой директории
        if not str(result_path).startswith(str(base_path)):
            raise ValueError(f"Путь выходит за пределы базовой директории: {filename}")
        
        return result_path
    
    @staticmethod
    def validate_google_credentials(creds_path: Path) -> bool:
        """Проверяет валидность Google credentials файла"""
        if not creds_path.exists():
            logging.warning(f"Google credentials not found: {creds_path}")
            return False
        
        try:
            with open(creds_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
            
            # Проверяем обязательные поля для service account
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
            if all(field in content for field in required_fields):
                return True
            else:
                logging.error(f"Missing required fields in Google credentials: {creds_path}")
                return False
                
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logging.error(f"Invalid JSON in credentials file {creds_path}: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error reading credentials {creds_path}: {e}")
            return False
    
    @staticmethod
    def validate_templates(templates: Dict[str, TemplateConfig]) -> bool:
        """Валидирует структуру шаблонов планов"""
        if not templates:
            logging.error("Templates dictionary is empty")
            return False
        
        required_keys = {'name', 'description', 'strategic_tasks', 'critical_tasks'}
        
        for template_name, template in templates.items():
            template_dict = template.to_dict()
            
            # Проверяем наличие обязательных ключей
            for key in required_keys:
                if key not in template_dict:
                    logging.error(f"Missing required key '{key}' in template '{template_name}'")
                    return False
            
            # Проверяем типы значений
            if not isinstance(template_dict['strategic_tasks'], list):
                logging.error(f"strategic_tasks must be a list in template '{template_name}'")
                return False
            
            if not isinstance(template_dict['critical_tasks'], list):
                logging.error(f"critical_tasks must be a list in template '{template_name}'")
                return False
            
            # Проверяем, что списки не пустые
            if not template_dict['strategic_tasks']:
                logging.warning(f"strategic_tasks is empty in template '{template_name}'")
            
            if not template_dict['critical_tasks']:
                logging.warning(f"critical_tasks is empty in template '{template_name}'")
                
        return True
    
    @staticmethod
    def validate_weekly_schedule(schedule: Dict[str, str], templates: Dict[str, TemplateConfig]) -> bool:
        """Валидирует недельное расписание шаблонов"""
        days_of_week = {"понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"}
        
        # Проверяем все дни недели
        for day in days_of_week:
            if day not in schedule:
                logging.error(f"Missing day in weekly schedule: {day}")
                return False
            
            template_name = schedule[day]
            if template_name not in templates:
                logging.error(f"Unknown template for day '{day}': {template_name}")
                return False
        
        # Проверяем, нет ли лишних дней
        extra_days = set(schedule.keys()) - days_of_week
        if extra_days:
            logging.warning(f"Extra days in schedule: {extra_days}")
            
        return True


class ConfigLoader:
    """Загрузчик и инициализатор конфигурации"""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent.absolute()
        self.validator = ConfigValidator()
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Настройка системы логирования"""
        log_dir = self.base_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / "bot.log"
        
        logging_config = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'detailed': {
                    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    'datefmt': '%Y-%m-%d %H:%M:%S'
                },
                'simple': {
                    'format': '%(levelname)s - %(message)s'
                }
            },
            'handlers': {
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': str(log_file),
                    'maxBytes': 10 * 1024 * 1024,  # 10MB
                    'backupCount': 5,
                    'formatter': 'detailed',
                    'encoding': 'utf-8',
                    'level': 'DEBUG'
                },
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'simple',
                    'level': 'INFO',
                    'stream': sys.stdout
                },
                'error_file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': str(log_dir / "errors.log"),
                    'maxBytes': 5 * 1024 * 1024,  # 5MB
                    'backupCount': 3,
                    'formatter': 'detailed',
                    'encoding': 'utf-8',
                    'level': 'ERROR'
                }
            },
            'loggers': {
                '': {  # root logger
                    'handlers': ['file', 'console'],
                    'level': 'INFO',
                    'propagate': False
                },
                'telegram': {
                    'handlers': ['file'],
                    'level': 'INFO',
                    'propagate': False
                },
                'asyncpg': {
                    'handlers': ['file'],
                    'level': 'WARNING',
                    'propagate': False
                },
                'gspread': {
                    'handlers': ['file'],
                    'level': 'INFO',
                    'propagate': False
                }
            }
        }
        
        logging.config.dictConfig(logging_config)
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"✅ Logging configured. Log file: {log_file}")
    
    def load_environment(self) -> None:
        """Загрузка переменных окружения"""
        env_path = self.base_dir / ".env"
        
        if env_path.exists():
            load_dotenv(env_path)
            self.logger.info(f"✅ Environment variables loaded from {env_path}")
        else:
            self.logger.warning("⚠️ .env file not found, using system environment variables")
            
            # Создаем пример .env файла, если его нет
            example_env = self.base_dir / ".env.example"
            if not example_env.exists():
                self._create_example_env(example_env)
    
    def _create_example_env(self, example_path: Path) -> None:
        """Создает пример .env файла"""
        example_content = """# Telegram Bot Configuration
BOT_TOKEN=your_bot_token_here
YOUR_CHAT_ID=your_telegram_chat_id_here

# Database Configuration
DATABASE_URL=postgresql://user:password@localhost:5432/telegram_bot

# Google Sheets Configuration (optional)
GOOGLE_SHEETS_ID=your_google_sheet_id_here
GOOGLE_CREDENTIALS_JSON=credentials.json

# Bot Settings
LOG_LEVEL=INFO
BOT_NAME=Productivity Assistant

# Timezone Settings (for scheduling)
TIMEZONE=Europe/Moscow

# Admin Settings
ADMIN_USER_IDS=123456789,987654321  # Comma-separated list of admin IDs

# Feature Flags
ENABLE_GOOGLE_SHEETS=true
ENABLE_POSTGRESQL=true
ENABLE_REMINDERS=true
"""
        
        try:
            with open(example_path, 'w', encoding='utf-8') as f:
                f.write(example_content)
            self.logger.info(f"✅ Created example .env file: {example_path}")
        except Exception as e:
            self.logger.error(f"❌ Failed to create example .env file: {e}")
    
    def create_bot_config(self) -> BotConfig:
        """Создание конфигурации бота из переменных окружения"""
        # Обязательные параметры
        token = os.getenv('BOT_TOKEN')
        chat_id_str = os.getenv('YOUR_CHAT_ID')
        database_url = os.getenv('DATABASE_URL')
        
        # Опциональные параметры
        google_sheets_id = os.getenv('GOOGLE_SHEETS_ID')
        google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        bot_name = os.getenv('BOT_NAME', 'Productivity Assistant')
        
        # Валидация обязательных полей
        validation_errors = []
        
        if not token:
            validation_errors.append("BOT_TOKEN не найден! Установите BOT_TOKEN в .env файле")
        elif len(token) < 30:
            validation_errors.append("BOT_TOKEN слишком короткий (должен быть длиннее 30 символов)")
        
        if not chat_id_str:
            validation_errors.append("YOUR_CHAT_ID не найден! Установите YOUR_CHAT_ID в .env файле")
        else:
            try:
                chat_id = int(chat_id_str)
                if chat_id <= 0:
                    validation_errors.append("YOUR_CHAT_ID должен быть положительным числом")
            except (ValueError, TypeError):
                validation_errors.append("YOUR_CHAT_ID должен быть целым числом")
        
        if not database_url:
            validation_errors.append("DATABASE_URL не найден! Установите DATABASE_URL в .env файле")
        
        if validation_errors:
            for error in validation_errors:
                self.logger.error(f"❌ {error}")
            raise ValueError("Ошибки конфигурации: " + "; ".join(validation_errors))
        
        chat_id = int(chat_id_str)
        
        # Проверка Google Sheets
        google_sheets_available = False
        if google_sheets_id and google_credentials_json:
            try:
                creds_path = self.validator.safe_path_join(self.base_dir, google_credentials_json)
                if self.validator.validate_google_credentials(creds_path):
                    google_sheets_available = True
                    self.logger.info("✅ Google Sheets credentials validated")
                else:
                    self.logger.warning("⚠️ Google Sheets credentials file is invalid")
            except ValueError as e:
                self.logger.warning(f"⚠️ Invalid Google credentials path: {e}")
            except Exception as e:
                self.logger.warning(f"⚠️ Error validating Google credentials: {e}")
        else:
            if not google_sheets_id:
                self.logger.info("ℹ️ GOOGLE_SHEETS_ID не установлен, интеграция с Google Sheets отключена")
            if not google_credentials_json:
                self.logger.info("ℹ️ GOOGLE_CREDENTIALS_JSON не установлен, интеграция с Google Sheets отключена")
        
        # Проверка доступности PostgreSQL
        postgresql_available = bool(database_url and database_url.startswith('postgresql://'))
        if not postgresql_available:
            self.logger.warning("⚠️ DATABASE_URL должен начинаться с 'postgresql://'")
        
        # Настройка уровня логирования
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if log_level not in valid_log_levels:
            self.logger.warning(f"⚠️ Invalid LOG_LEVEL '{log_level}', using 'INFO'")
            log_level = 'INFO'
        
        # Обновляем уровень логирования
        logging.getLogger().setLevel(log_level)
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'setLevel'):
                handler.setLevel(log_level)
        
        config = BotConfig(
            token=token,
            chat_id=chat_id,
            database_url=database_url,
            google_sheets_id=google_sheets_id,
            google_credentials_json=google_credentials_json,
            google_sheets_available=google_sheets_available,
            postgresql_available=postgresql_available,
            log_level=log_level,
            bot_name=bot_name
        )
        
        self.logger.info("✅ Bot configuration created successfully")
        self.logger.debug(f"Config details: {config}")
        
        return config


# Инициализация конфигурации
config_loader = ConfigLoader()
config_loader.load_environment()

try:
    CONFIG = config_loader.create_bot_config()
    config_loader.logger.info("✅ Bot configuration loaded successfully")
except ValueError as e:
    config_loader.logger.error(f"❌ Configuration error: {e}")
    sys.exit(1)
except Exception as e:
    config_loader.logger.error(f"❌ Unexpected configuration error: {e}")
    sys.exit(1)

# Глобальные переменные для обратной совместимости
TOKEN = CONFIG.token
YOUR_CHAT_ID = CONFIG.chat_id
DATABASE_URL = CONFIG.database_url
GOOGLE_SHEETS_ID = CONFIG.google_sheets_id
GOOGLE_CREDENTIALS_JSON = CONFIG.google_credentials_json
GOOGLE_SHEETS_AVAILABLE = CONFIG.google_sheets_available
POSTGRESQL_AVAILABLE = CONFIG.postgresql_available
LOG_LEVEL = CONFIG.log_level
BOT_NAME = CONFIG.bot_name

# Импорт вопросов
try:
    # Пробуем импортировать из отдельного файла
    from questions import QUESTIONS
    config_loader.logger.info(f"✅ Loaded {len(QUESTIONS)} questions from questions.py")
except ImportError:
    # Если файла нет, создаем вопросы inline
    config_loader.logger.warning("⚠️ questions.py not found, creating inline questions")
    
    QUESTIONS = [
        {"block": "personal", "text": "Как вас зовут?"},
        {"block": "personal", "text": "Сколько вам лет?"},
        {"block": "personal", "text": "Какой у вас пол?"},
        {"block": "personal", "text": "Где вы живете (город/страна)?"},
        {"block": "personal", "text": "Ваш род деятельности (профессия)?"},
        {"block": "goals", "text": "Какие ваши главные цели на ближайший год?"},
        {"block": "goals", "text": "Что вы хотите изменить в своей жизни?"},
        {"block": "goals", "text": "Какие у вас есть мечты или амбиции?"},
        {"block": "health", "text": "Как вы оцениваете свое физическое здоровье (1-10)?"},
        {"block": "health", "text": "Как вы оцениваете свое ментальное здоровье (1-10)?"},
        {"block": "health", "text": "Какие у вас есть привычки, связанные со здоровьем?"},
        {"block": "health", "text": "Что вы хотели бы улучшить в своем здоровье?"},
        {"block": "productivity", "text": "Как вы организуете свой рабочий день?"},
        {"block": "productivity", "text": "Какие инструменты планирования вы используете?"},
        {"block": "productivity", "text": "Что обычно отвлекает вас от работы?"},
        {"block": "productivity", "text": "Как вы боретесь с прокрастинацией?"},
        {"block": "habits", "text": "Какие у вас утренние ритуалы?"},
        {"block": "habits", "text": "Какие у вас вечерние ритуалы?"},
        {"block": "habits", "text": "Какие полезные привычки вы хотите развить?"},
        {"block": "habits", "text": "От каких вредных привычек хотите избавиться?"},
        {"block": "time", "text": "Во сколько вы обычно просыпаетесь?"},
        {"block": "time", "text": "Во сколько вы обычно ложитесь спать?"},
        {"block": "time", "text": "Сколько часов в день вы работаете?"},
        {"block": "time", "text": "Сколько свободного времени у вас есть ежедневно?"},
        {"block": "motivation", "text": "Что вас мотивирует больше всего?"},
        {"block": "motivation", "text": "Что вас демотивирует?"},
        {"block": "motivation", "text": "Как вы справляетесь с неудачами?"},
        {"block": "motivation", "text": "Что придает вам энергию?"},
        {"block": "challenges", "text": "С какими основными трудностями вы сталкиваетесь?"},
        {"block": "challenges", "text": "Что мешает вам достигать целей?"},
        {"block": "challenges", "text": "Как вы справляетесь со стрессом?"},
        {"block": "challenges", "text": "Что для вас самое сложное в самоорганизации?"},
        {"block": "support", "text": "Какой тип поддержки вы ищете от ассистента?"},
        {"block": "support", "text": "Как часто вы хотите получать напоминания?"},
        {"block": "support", "text": "Что для вас идеальный помощник?"}
    ]
    config_loader.logger.info(f"✅ Created {len(QUESTIONS)} inline questions")

# Константы для обратной совместимости
(GENDER, READY_CONFIRMATION, QUESTIONNAIRE,
 ADD_PLAN_USER, ADD_PLAN_DATE, ADD_PLAN_CONTENT,
 SELECT_TEMPLATE, SELECT_USER_FOR_TEMPLATE, SELECT_DATE_FOR_TEMPLATE) = range(9)

PLAN_FIELDS = PlanFields.get_field_mapping()

# ПОЛНЫЕ ШАБЛОНЫ ПЛАНОВ
PLAN_TEMPLATES = {
    "продуктивный_день": TemplateConfig(
        name="🚀 Продуктивный день",
        description="Максимальная концентрация на важных задачах",
        strategic_tasks=[
            "Работа над основным проектом (3-4 часа глубокой работы)",
            "Планирование следующего дня",
            "Обучение и развитие навыков (1 час)"
        ],
        critical_tasks=[
            "Самая важная задача дня (съесть лягушку)",
            "Ответить на срочные сообщения",
            "Подвести итоги дня"
        ],
        priorities=[
            "Фокус на одной задаче за раз",
            "Минимизировать многозадачность",
            "Завершать начатое"
        ],
        advice=[
            "Начните с самой сложной задача",
            "Используйте технику Помодоро (25/5)",
            "Отключайте уведомления во время глубокой работы"
        ],
        special_rituals=[
            "Утреннее планирование дня (10 минут)",
            "Вечерний анализ достижений",
            "Техника '5 почему' для проблем"
        ],
        time_blocks=[
            "09:00-12:00 - Глубокая работа",
            "12:00-13:00 - Обед и отдых",
            "13:00-16:00 - Средние задачи",
            "16:00-17:00 - Коммуникации",
            "17:00-18:00 - Планирование завтра"
        ],
        resources=[
            "Таймер Помодоро",
            "Список приоритетов",
            "Вода на столе"
        ],
        expected_results=[
            "Выполнена основная задача дня",
            "Четкий план на завтра",
            "Чувство удовлетворенности"
        ],
        reminders=[
            "Каждый час делать перерыв на 5 минут",
            "Пить воду каждый час",
            "Проверить осанку"
        ],
        motivation_quote="Дисциплина — это мост между целями и достижениями."
    ),
    
    "творческий_день": TemplateConfig(
        name="🎨 Творческий день",
        description="Генерация идей и инновационных решений",
        strategic_tasks=[
            "Мозговой штурм новых идей",
            "Изучение нового инструмента или технологии",
            "Создание прототипа или макета"
        ],
        critical_tasks=[
            "Зафиксировать все идеи (даже странные)",
            "Создать минимум один рабочий прототип",
            "Поделиться идеями с коллегами"
        ],
        priorities=[
            "Количество важнее качества на этапе генерации",
            "Не критиковать идеи на старте",
            "Экспериментировать без страха"
        ],
        advice=[
            "Слушайте музыку для вдохновения",
            "Меняйте обстановку каждые 2 часа",
            "Используйте метод случайного стимула"
        ],
        special_rituals=[
            "Утренние страницы (писать 3 страницы текста)",
            "Прогулка для генерации идей",
            "Медитация на 10 минут"
        ],
        time_blocks=[
            "09:00-11:00 - Генерация идей",
            "11:00-13:00 - Разработка концепций",
            "13:00-14:00 - Обед и отдых",
            "14:00-16:00 - Создание прототипов",
            "16:00-17:00 - Тестирование и фидбек"
        ],
        resources=[
            "Блокнот для идей",
            "Инструменты для прототипирования",
            "Примеры вдохновляющих работ"
        ],
        expected_results=[
            "10+ новых идей",
            "1-2 рабочих прототипа",
            "Инсайты для развития"
        ],
        reminders=[
            "Делать перерывы каждые 45 минут",
            "Фиксировать все внезапные идеи",
            "Не удалять 'плохие' идеи сразу"
        ],
        motivation_quote="Творчество — это интеллект, получающий удовольствие."
    ),
    
    "баланс_работа_отдых": TemplateConfig(
        name="⚖️ Баланс работа-отдых",
        description="Сбалансированный день для предотвращения выгорания",
        strategic_tasks=[
            "Выполнить ключевые рабочие задачи",
            "Выделить время на хобби и отдых",
            "Практиковать осознанность"
        ],
        critical_tasks=[
            "Завершить 2-3 важные рабочие задачи",
            "Выделить 1-2 часа на личные интересы",
            "Отдохнуть без чувства вины"
        ],
        priorities=[
            "Качество отдыха так же важно, как и работы",
            "Четкие границы между работой и личным временем",
            "Регулярные мини-перерывы"
        ],
        advice=[
            "Используйте технику 'time blocking'",
            "Планируйте отдых так же, как и работу",
            "Отключайте рабочие уведомления после работы"
        ],
        special_rituals=[
            "Утреннее намерение на день",
            "Обеденный перерыв без гаджетов",
            "Вечерний ритуал завершения дня"
        ],
        time_blocks=[
            "09:00-12:00 - Рабочий блок 1",
            "12:00-13:00 - Обед и отдых",
            "13:00-16:00 - Рабочий блок 2",
            "16:00-17:00 - Переход к личному времени",
            "17:00-19:00 - Хобби и отдых",
            "19:00-21:00 - Семья/личное время"
        ],
        resources=[
            "Таймер для перерывов",
            "Список приятных активностей",
            "График работы/отдыха"
        ],
        expected_results=[
            "Выполнены рабочие задачи",
            "Качественное время для себя",
            "Чувство баланса и удовлетворения"
        ],
        reminders=[
            "Каждый час вставать и разминаться",
            "Пить воду регулярно",
            "Благодарить себя за усилия"
        ],
        motivation_quote="Лучший способ сделать что-то — это начать делать."
    ),
    
    "спортивный_день": TemplateConfig(
        name="💪 Спортивный день",
        description="Фокус на физическом здоровье и активности",
        strategic_tasks=[
            "Тренировка по плану",
            "Подготовка здорового питания",
            "Восстановление и растяжка"
        ],
        critical_tasks=[
            "Выполнить запланированную тренировку",
            "Съесть 3 полноценных приема пищи",
            "Выпить 2+ литра воды"
        ],
        priorities=[
            "Физическая активность как приоритет",
            "Качественное восстановление",
            "Сбалансированное питание"
        ],
        advice=[
            "Разминка перед тренировкой обязательна",
            "Слушайте свое тело",
            "Не пропускайте завтрак"
        ],
        special_rituals=[
            "Утренняя зарядка и растяжка",
            "Контрастный душ после тренировки",
            "Вечерняя медитация для восстановления"
        ],
        time_blocks=[
            "07:00-08:00 - Утренняя активность",
            "08:00-09:00 - Завтрак и подготовка",
            "12:00-13:00 - Обед и отдых",
            "18:00-19:30 - Основная тренировка",
            "19:30-20:30 - Ужин и восстановление"
        ],
        resources=[
            "Спортивная форма и инвентарь",
            "План тренировок",
            "Питание по расписанию"
        ],
        expected_results=[
            "Выполнена тренировочная программа",
            "Хорошее самочувствие и энергия",
            "Прогресс в физической форме"
        ],
        reminders=[
            "Разминка 10 минут перед тренировкой",
            "Заминка и растяжка после",
            "Пить воду во время тренировки"
        ],
        motivation_quote="Сила не в том, чтобы никогда не падать, а в том, чтобы подниматься каждый раз."
    ),
    
    "обучение_развитие": TemplateConfig(
        name="📚 День обучения",
        description="Интенсивное обучение и развитие новых навыков",
        strategic_tasks=[
            "Изучение новой темы/навыка",
            "Практическое применение знаний",
            "Анализ прогресса и следующих шагов"
        ],
        critical_tasks=[
            "Завершить учебный модуль",
            "Выполнить практическое задание",
            "Зафиксировать ключевые инсайты"
        ],
        priorities=[
            "Понимание важнее запоминания",
            "Практика важнее теории",
            "Регулярные повторения"
        ],
        advice=[
            "Делайте заметки своими словами",
            "Объясняйте материал как будто другому",
            "Применяйте знания сразу на практике"
        ],
        special_rituals=[
            "Утренний обзор целей обучения",
            "Техника Фейнмана для сложных тем",
            "Вечерний анализ изученного"
        ],
        time_blocks=[
            "09:00-11:00 - Изучение теории",
            "11:00-13:00 - Практика и упражнения",
            "13:00-14:00 - Обед и отдых",
            "14:00-16:00 - Углубленное изучение",
            "16:00-17:00 - Применение и проекты"
        ],
        resources=[
            "Учебные материалы",
            "Тетрадь для заметок",
            "Практические задания"
        ],
        expected_results=[
            "Освоен новый навык/знание",
            "Выполнено практическое задание",
            "Четкий план дальнейшего обучения"
        ],
        reminders=[
            "Делать перерывы каждые 45 минут",
            "Повторять ключевые моменты",
            "Задавать вопросы при непонимании"
        ],
        motivation_quote="Образование — это то, что остается после того, когда забывается все выученное в школе."
    )
}

WEEKLY_TEMPLATE_SCHEDULE = {
    "понедельник": "продуктивный_день",
    "вторник": "обучение_развитие",
    "среда": "творческий_день",
    "четверг": "продуктивный_день",
    "пятница": "баланс_работа_отдых",
    "суббота": "спортивный_день",
    "воскресенье": "баланс_работа_отдых"
}


def validate_configuration() -> bool:
    """
    Финальная валидация всей конфигурации.
    
    Returns:
        bool: True если конфигурация валидна, иначе False
    """
    validator = ConfigValidator()
    
    # Проверка конфигурации бота
    if not CONFIG.is_valid:
        config_loader.logger.error("❌ Invalid bot configuration")
        return False
    
    # Проверка обязательных полей плана
    required_fields = ['id', 'user_id', 'plan_date']
    for field in required_fields:
        if field not in PLAN_FIELDS:
            config_loader.logger.error(f"❌ Missing required field in PLAN_FIELDS: {field}")
            return False
    
    # Валидация шаблонов
    if not validator.validate_templates(PLAN_TEMPLATES):
        config_loader.logger.error("❌ Template validation failed")
        return False
    
    # Валидация недельного расписания
    if not validator.validate_weekly_schedule(WEEKLY_TEMPLATE_SCHEDULE, PLAN_TEMPLATES):
        config_loader.logger.error("❌ Weekly schedule validation failed")
        return False
    
    # Проверка количества вопросов
    expected_questions_count = 35
    if len(QUESTIONS) != expected_questions_count:
        config_loader.logger.error(
            f"❌ Invalid number of questions: {len(QUESTIONS)}, expected: {expected_questions_count}"
        )
        return False
    
    # Проверка структуры вопросов
    for i, question in enumerate(QUESTIONS):
        if 'block' not in question or 'text' not in question:
            config_loader.logger.error(f"❌ Invalid question structure at index {i}")
            return False
    
    config_loader.logger.info("✅ All configuration validated successfully")
    return True


# Финальная валидация при импорте модуля
if not validate_configuration():
    config_loader.logger.error("❌ Configuration validation failed!")
    sys.exit(1)

config_loader.logger.info("✅ Configuration module loaded and validated")
