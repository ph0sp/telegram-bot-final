import os
import logging
import logging.config
import json
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from enum import IntEnum
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


class ConfigValidator:
    """Валидатор конфигурации"""
    
    @staticmethod
    def safe_path_join(base_dir: str, filename: str) -> str:
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
        if not filename:
            raise ValueError("Имя файла не может быть пустым")
        if '..' in filename or filename.startswith('/') or '~' in filename:
            raise ValueError(f"Недопустимое имя файла: {filename}")
        return os.path.join(base_dir, filename)
    
    @staticmethod
    def validate_google_credentials(creds_path: str) -> bool:
        """Проверяет валидность Google credentials файла"""
        if not os.path.exists(creds_path):
            logging.warning(f"Google credentials not found: {creds_path}")
            return False
        
        try:
            with open(creds_path, 'r', encoding='utf-8') as f:
                json.load(f)
            return True
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logging.error(f"Invalid JSON in credentials file {creds_path}: {e}")
            return False
    
    @staticmethod
    def validate_templates(templates: Dict[str, Any]) -> bool:
        """Валидирует структуру шаблонов планов"""
        required_keys = {'name', 'description', 'strategic_tasks', 'critical_tasks'}
        
        for template_name, template in templates.items():
            for key in required_keys:
                if key not in template:
                    logging.error(f"Missing required key '{key}' in template '{template_name}'")
                    return False
            
            if not isinstance(template['strategic_tasks'], list):
                logging.error(f"strategic_tasks must be a list in template '{template_name}'")
                return False
                
        return True
    
    @staticmethod
    def validate_weekly_schedule(schedule: Dict[str, str], templates: Dict[str, Any]) -> bool:
        """Валидирует недельное расписание шаблонов"""
        days_of_week = {"понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"}
        
        for day in days_of_week:
            if day not in schedule:
                logging.error(f"Missing day in weekly schedule: {day}")
                return False
            if schedule[day] not in templates:
                logging.error(f"Unknown template for day '{day}': {schedule[day]}")
                return False
                
        return True


class ConfigLoader:
    """Загрузчик и инициализатор конфигурации"""
    
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.validator = ConfigValidator()
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Настройка системы логирования"""
        logging_config = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'detailed': {
                    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    'datefmt': '%Y-%m-%d %H:%M:%S'
                },
            },
            'handlers': {
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': self.validator.safe_path_join(self.base_dir, 'bot.log'),
                    'maxBytes': 10 * 1024 * 1024,  # 10MB
                    'backupCount': 3,
                    'formatter': 'detailed',
                    'encoding': 'utf-8'
                },
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'detailed',
                    'level': 'INFO'
                }
            },
            'root': {
                'level': 'INFO',
                'handlers': ['file', 'console']
            }
        }
        
        logging.config.dictConfig(logging_config)
        self.logger = logging.getLogger(__name__)
    
    def load_environment(self) -> None:
        """Загрузка переменных окружения"""
        env_path = self.validator.safe_path_join(self.base_dir, '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
            self.logger.info("✅ Environment variables loaded from .env")
        else:
            self.logger.warning("⚠️ .env file not found, using system environment variables")
    
    def create_bot_config(self) -> BotConfig:
        """Создание конфигурации бота из переменных окружения"""
        token = os.getenv('BOT_TOKEN')
        chat_id = os.getenv('YOUR_CHAT_ID')
        database_url = os.getenv('DATABASE_URL')
        google_sheets_id = os.getenv('GOOGLE_SHEETS_ID')
        google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        
        # Валидация обязательных полей
        if not token:
            self.logger.error("❌ Bot token not found! Set BOT_TOKEN in .env file")
            raise ValueError("BOT_TOKEN is required")
        
        if not chat_id:
            self.logger.error("❌ Chat ID not found! Set YOUR_CHAT_ID in .env file")
            raise ValueError("YOUR_CHAT_ID is required")
        
        try:
            chat_id_int = int(chat_id)
        except (ValueError, TypeError):
            self.logger.error("❌ YOUR_CHAT_ID must be a number")
            raise ValueError("YOUR_CHAT_ID must be a valid integer")
        
        if not database_url:
            self.logger.error("❌ DATABASE_URL not found! Set DATABASE_URL in .env file")
            raise ValueError("DATABASE_URL is required")
        
        # Проверка Google Sheets
        google_sheets_available = False
        if google_sheets_id and google_credentials_json:
            creds_path = self.validator.safe_path_join(self.base_dir, google_credentials_json)
            if creds_path.endswith('.json') and os.path.exists(creds_path):
                if self.validator.validate_google_credentials(creds_path):
                    google_sheets_available = True
                    self.logger.info("✅ Google Sheets credentials validated")
                else:
                    self.logger.warning("⚠️ Google Sheets credentials file is invalid")
            else:
                self.logger.warning(f"⚠️ Google credentials file not found: {creds_path}")
        else:
            if not google_sheets_id:
                self.logger.info("ℹ️ GOOGLE_SHEETS_ID not set")
            if not google_credentials_json:
                self.logger.info("ℹ️ GOOGLE_CREDENTIALS_JSON not set")
        
        return BotConfig(
            token=token,
            chat_id=chat_id_int,
            database_url=database_url,
            google_sheets_id=google_sheets_id,
            google_credentials_json=google_credentials_json,
            google_sheets_available=google_sheets_available,
            postgresql_available=bool(database_url)
        )


# Инициализация конфигурации
config_loader = ConfigLoader()
config_loader.load_environment()

try:
    CONFIG = config_loader.create_bot_config()
    config_loader.logger.info("✅ Bot configuration loaded successfully")
except ValueError as e:
    config_loader.logger.error(f"❌ Configuration error: {e}")
    exit(1)

# Глобальные переменные для обратной совместимости
TOKEN = CONFIG.token
YOUR_CHAT_ID = CONFIG.chat_id
DATABASE_URL = CONFIG.database_url
GOOGLE_SHEETS_ID = CONFIG.google_sheets_id
GOOGLE_CREDENTIALS_JSON = CONFIG.google_credentials_json
GOOGLE_SHEETS_AVAILABLE = CONFIG.google_sheets_available
POSTGRESQL_AVAILABLE = CONFIG.postgresql_available

# Импорт вопросов
try:
    from questions import QUESTIONS
    config_loader.logger.info(f"✅ Loaded {len(QUESTIONS)} questions")
except ImportError as e:
    config_loader.logger.error(f"❌ Failed to load questions: {e}")
    exit(1)

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
    
    # Проверка обязательных полей плана
    required_fields = ['id', 'user_id', 'plan_date']
    for field in required_fields:
        if field not in PLAN_FIELDS:
            config_loader.logger.error(f"❌ Missing required field in PLAN_FIELDS: {field}")
            return False
    
    # Валидация шаблонов
    if not validator.validate_templates({k: v.__dict__ for k, v in PLAN_TEMPLATES.items()}):
        return False
    
    # Валидация недельного расписания
    if not validator.validate_weekly_schedule(WEEKLY_TEMPLATE_SCHEDULE, PLAN_TEMPLATES):
        return False
    
    # Проверка количества вопросов
    expected_questions_count = 35
    if len(QUESTIONS) != expected_questions_count:
        config_loader.logger.error(
            f"❌ Invalid number of questions: {len(QUESTIONS)}, expected: {expected_questions_count}"
        )
        return False
    
    config_loader.logger.info("✅ All configuration validated successfully")
    return True


# Финальная валидация при импорте модуля
if not validate_configuration():
    config_loader.logger.error("❌ Configuration validation failed!")
    exit(1)

config_loader.logger.info("✅ Configuration module loaded and validated")
