import os
import logging
import asyncio
import time
import json
import re
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, Optional, Any, List
from contextlib import contextmanager

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
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
from dotenv import load_dotenv
 
# Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False
    print("⚠️ Google Sheets не доступен")

# PostgreSQL поддержка
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import urllib.parse
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False
    print("⚠️ PostgreSQL не доступен")

load_dotenv()

# ========== КОНФИГУРАЦИЯ ==========

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')
YOUR_CHAT_ID = os.environ.get('YOUR_CHAT_ID')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
GOOGLE_SHEETS_ID = os.environ.get('GOOGLE_SHEETS_ID')
DATABASE_URL = os.environ.get('DATABASE_URL')  # Для PostgreSQL на Render

# 🔒 Безопасность: проверяем Google credentials
if GOOGLE_CREDENTIALS_JSON:
    try:
        # Проверяем что это валидный JSON
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        # Проверяем обязательные поля
        required_keys = ['type', 'project_id', 'private_key_id', 'private_key']
        if not all(key in creds_dict for key in required_keys):
            logger.error("❌ Google credentials JSON missing required fields")
            GOOGLE_CREDENTIALS_JSON = None
    except json.JSONDecodeError:
        logger.error("❌ Google credentials JSON is invalid")
        GOOGLE_CREDENTIALS_JSON = None

if not TOKEN:
    logger.error("❌ Токен бота не найден! Установите BOT_TOKEN")
    exit(1)

if not YOUR_CHAT_ID:
    logger.error("❌ Chat ID не найден! Установите YOUR_CHAT_ID")
    exit(1)

# Состояния диалога
GENDER, FIRST_QUESTION = range(2)
ADD_PLAN_USER, ADD_PLAN_DATE, ADD_PLAN_CONTENT = range(3, 6)
SELECT_TEMPLATE, SELECT_USER_FOR_TEMPLATE, SELECT_DATE_FOR_TEMPLATE = range(6, 9)

# Константы для индексов планов
PLAN_FIELDS = {
    'id': 0, 'user_id': 1, 'plan_date': 2, 'morning_ritual1': 4, 'morning_ritual2': 5,
    'task1': 6, 'task2': 7, 'task3': 8, 'task4': 9, 'lunch_break': 10,
    'evening_ritual1': 11, 'evening_ritual2': 12, 'advice': 13, 'sleep_time': 14,
    'water_goal': 15, 'activity_goal': 16
}

QUESTIONS = [
    "Давайте начнем!\nПоследовательно отвечайте на вопросы в свободной форме, как вам удобно.\nНачнем с самого главного\n\nБлок 1: Цель и главный фокус\nКакая ваша главная цель на ближайший месяц? (например, запуск проекта, подготовка к экзамену, улучшение физической формы, обучение новому навыку)\n\nЖду вашего ответа, чтобы двигаться дальше.",
    "Прекрасная цель! Это комплексная задача, где важны и стратегия, и ежедневная энергия, чтобы ее реализовать.\n\nРасскажите почему для вас важна эта цель? Что изменится в вашей жизни, когда вы ее достигнете?",
    "Как вы поняли бы что цель достигнута? Какие конкретные изменения, результаты или показатели скажут вам \"да, я это сделал!\"?\n\nПримеры:\n- \"Когда буду весить 65 кг и влезу в платье 44 размера\"\n- \"Когда мой проект будет приносить 100 000 руб/месяц\"\n- \"Когда смогу свободно разговаривать на английском в путешествии\"",
    "Сколько часов в день вы готовы посвящать работе над этой целью? (важно оценить ресурсы честно)",
    "Есть ли у вас дедлайн по этой цели? Если да – какой именно срок? Если нет – когда бы вы хотели ее достичь? Какие ключевые контрольные точки на этом пути?\n\nКак только вы ответите, мы перейдем к следующему блоку вопросов, чтобы понять текущий ритм жизни и выстроить план, который будет работать именно для вас.",
    
    "Отлично, основа понятна. Теперь давайте перейдем к вашему текущему ритму жизни, чтобы вписать эту цель в ваш день комфортно и без выгорания.\n\nБлок 2: Текущий распорядок и ресурсы\n\nВо сколько вы обычно просыпаетесь и ложитесь спать?",
    "Опишите кратко, как обычно выглядит ваш текущий день (работа, учеба, обязанности)?",
    "В какое время суток вы чувствуете себя наиболее энергичным и продуктивным? (утро, день, вечер)",
    "Сколько часов в день вы обычно тратите на соцсети, просмотр сериалов и другие не основные занятия?",
    "Как часто вы чувствуете себя перегруженным или близким к выгоранию и что это вызывает?",
    
    "Блок 3: Стиль работы\n\nКак вам комфортнее работать?\n□ Длинные непрерывные блоки (2-4 часа)\n□ Короткие сессии (25-50 минут)\n□ Чередование разных задач\n□ Многозадачность",
    "Что вам лучше всего помогает сосредоточиться?\n□ Тишина\n□ Фоновая музыка\n□ Работа в кафе\n□ Таймеры\n□ Дедлайны",
    "Как вы отдыхаете во время перерывов?\n□ Соцсети\n□ Прогулка\n□ Растяжка\n□ Чтение\n□ Ничего не делаю",
    
    "Блок 4: Физическая активность\n\nКакой у вас текущий уровень активности?\n□ Сидячий образ жизни\n□ Легкие прогулки\n□ Регулярные тренировки 1-2 раза\n□ Активные тренировки 3+ раза",
    "Каким видом спорта или физической активности вам нравится заниматься/вы бы хотели заняться? (бег, йога, плавание, силовые, танцы)",
    "Сколько дней в неделю и сколько времени вы готовы выделять на спорт? (Например, 3 раза по 45 минут)",
    "Есть ли у вас ограничения по здоровью, которые нужно учитывать при планировании нагрузки?",
    
    "Блок 5: Питание, сон и вода\n\nОпишите ваш режим питания:\n- Завтрак: □ всегда □ иногда □ редко\n- Обед: □ полноценный □ перекус\n- Ужин: □ легкий □ плотный\n- Перекусы: □ часто □ редко",
    "Сколько воды обычно пьете? □ 1-2 стакана □ 4-5 □ 8+",
    "Хотели бы вы что-то изменить в своем питании? (например, есть больше овощей, готовить заранее, не пропускать обед, пить больше воды)",
    "Сколько времени вы обычно выделяете на приготовление еды?",
    "Как качество вашего сна? □ отлично □ нормально □ плохо\nЧто мешает спать хорошо?",
    
    "🧠 БЛОК 6: ЭМОЦИОНАЛЬНОЕ СОСТОЯНИЕ\n\nЧто вас мотивирует?\n□ Достижения\n□ Одобрение других\n□ Внутренний интерес\n□ Деньги/результаты",
    "Что обычно мешает следовать планам?\n□ Прокрастинация\n□ Перфекционизм\n□ Отсутствие энергии\n□ Неорганизованность",
    "Как справляетесь со стрессом?\n□ Спорт\n□ Разговоры\n□ Уединение\n□ Хобби\n□ Другое: _____",
    
    "Блок 7: Отдых и восстановление\n\nЧто для вас настоящий отдых?\n□ Активность\n□ Пассивный отдых\n□ Общение\n□ Уединение",
    "Как часто вам удается выделять время на эти занятия?",
    "Какие ритуалы помогают вам:\n- Проснуться: __________\n- Настроиться на работу: __________\n- Расслабиться вечером: __________",
    "Планируете ли вы выходные дни или микро-перерывы в течение дня?",
    "Важно ли для вас время на общение с семьей/друзьями? Сколько раз в неделю вы бы хотели это видеть в своем плане?",
    "Сколько времени в неделю вам нужно для личных интересов/хобби?",
    
    "Блок 8: Ритуалы для здоровья и самочувствия\n\nИсходя из вашего режима, предлагаю вам на выбор несколько идей. Что из этого вам откликается?\n\nУтренние ритуалы (на выбор):\n* Стакан теплой воды с лимоном: для запуска метаболизма.\n* Несложная зарядка/растяжка (5-15 мин): чтобы размяться и проснуться.\n* Медитация или ведение дневника (5-10 мин): для настройки на день.\n* Контрастный душ: для бодрости.\n* Полезный завтрак без телефона: осознанное начало дня.\n\nВечерние ритуалы (на выбор):\n* Выключение гаджетов за 1 час до сна: для улучшения качества сна.\n* Ведение дневника благодарности или запись 3х хороших событий дня.\n* Чтение книги (не с экрана).\n* Легкая растяжка или йога перед сном: для расслабления мышц.\n* Планирование главных задач на следующий день (3 дела): чтобы \"выгрузить\" мысли и спать спокойно.\n* Ароматерапия или спокойная музыка.\n\nКакие из этих утренних ритуалов вам были бы интересны?\n\nКакие вечерние ритуалы вы бы хотели внедрить?\n\nЕсть ли ваши личные ритуалы, которые вы хотели бы сохранить?",
    
    "Отлично, остался заключительный блок.\n\nБлок 9: Финальные Уточнения и Гибкость\n\nКакой ваш идеальный баланс между продуктивностью и отдыхом? (например, 70/30, 60/40)",
    "Что чаще всего мешает вам следовать планам? (неожиданные дела, лень, отсутствие мотивации)",
    "Как нам лучше всего предусмотреть \"дни непредвиденных обстоятельств\" или дни с низкой энергией? (Например, запланировать 1-2 таких дня в неделю)"
]

# ========== УНИВЕРСАЛЬНАЯ СИСТЕМА БАЗЫ ДАННЫХ ==========

@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к PostgreSQL"""
    if not DATABASE_URL or not POSTGRESQL_AVAILABLE:
        logger.error("❌ PostgreSQL не настроен или не доступен")
        raise Exception("PostgreSQL не доступен")
    
    conn = None
    try:
        # Parse the database URL for PostgreSQL
        urllib.parse.uses_netloc.append("postgres")
        url = urllib.parse.urlparse(DATABASE_URL)
        
        conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port,
            cursor_factory=RealDictCursor
        )
        logger.info("✅ Подключение к PostgreSQL установлено")
        yield conn
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
        raise
    finally:
        if conn:
            conn.close()

def init_database():
    """Инициализирует таблицы в базе данных PostgreSQL"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица клиентов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clients (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE NOT NULL,
                    first_name TEXT,
                    username TEXT,
                    last_name TEXT,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    gender TEXT,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица ответов анкеты
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questionnaire_answers (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    question_number INTEGER NOT NULL,
                    question_text TEXT,
                    answer_text TEXT NOT NULL,
                    answer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, question_number)
                )
            ''')
            
            # Таблица прогресса
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_progress (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    progress_date DATE NOT NULL,
                    tasks_completed INTEGER DEFAULT 0,
                    mood INTEGER,
                    energy INTEGER,
                    sleep_quality INTEGER,
                    water_intake INTEGER,
                    activity_done TEXT,
                    user_comment TEXT,
                    day_rating INTEGER,
                    challenges TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                )
            ''')
            
            # Таблица напоминаний
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_reminders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    reminder_text TEXT NOT NULL,
                    reminder_time TIME NOT NULL,
                    days_of_week TEXT,
                    reminder_type TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                )
            ''')
            
            # Таблица планов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_plans (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    plan_date DATE NOT NULL,
                    morning_ritual1 TEXT,
                    morning_ritual2 TEXT,
                    task1 TEXT,
                    task2 TEXT,
                    task3 TEXT,
                    task4 TEXT,
                    lunch_break TEXT,
                    evening_ritual1 TEXT,
                    evening_ritual2 TEXT,
                    advice TEXT,
                    sleep_time TEXT,
                    water_goal TEXT,
                    activity_goal TEXT,
                    status TEXT DEFAULT 'active',
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                )
            ''')
            
            # Таблица сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_messages (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    message_text TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                )
            ''')
            
            conn.commit()
            logger.info("✅ Таблицы PostgreSQL инициализированы")
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# Вызываем инициализацию при запуске
init_database()

# ========== СИСТЕМА ШАБЛОНОВ ПЛАНОВ ==========

PLAN_TEMPLATES = {
    "продуктивный_день": {
        "name": "🚀 Продуктивный день",
        "description": "Максимальная концентрация на важных задачах",
        "strategic_tasks": [
            "Работа над основным проектом (3-4 часа глубокой работы)",
            "Планирование следующего дня",
            "Обучение и развитие навыков (1 час)"
        ],
        "critical_tasks": [
            "Самая важная задача дня (съесть лягушку)",
            "Ответить на срочные сообщения",
            "Подвести итоги дня"
        ],
        "priorities": [
            "Фокус на одной задаче за раз",
            "Минимизировать многозадачность",
            "Завершать начатое"
        ],
        "advice": [
            "Начните с самой сложной задачи",
            "Используйте технику Помодоро (25/5)",
            "Отключайте уведомления во время глубокой работы"
        ],
        "special_rituals": [
            "Утреннее планирование дня (10 минут)",
            "Вечерний анализ достижений",
            "Техника '5 почему' для проблем"
        ],
        "time_blocks": [
            "09:00-12:00 - Глубокая работа",
            "12:00-13:00 - Обед и отдых", 
            "13:00-16:00 - Средние задачи",
            "16:00-17:00 - Коммуникации",
            "17:00-18:00 - Планирование завтра"
        ],
        "resources": [
            "Таймер Помодoro",
            "Список приоритетов",
            "Вода на столе"
        ],
        "expected_results": [
            "Выполнена основная задача дня",
            "Четкий план на завтра",
            "Чувство удовлетворенности"
        ],
        "reminders": [
            "Каждый час делать перерыв на 5 минут",
            "Пить воду каждый час",
            "Проверить осанку"
        ],
        "motivation_quote": "Дисциплина — это мост между целями и достижениями."
    },
    
    "творческий_день": {
        "name": "🎨 Творческий день", 
        "description": "Генерация идей и инновационных решений",
        "strategic_tasks": [
            "Мозговой штурм новых идей",
            "Изучение нового инструмента или технологии",
            "Создание прототипа или макета"
        ],
        "critical_tasks": [
            "Зафиксировать все идеи (даже странные)",
            "Создать минимум один рабочий прототип",
            "Поделиться идеями с коллегами"
        ],
        "priorities": [
            "Количество важнее качества на этапе генерации",
            "Не критиковать идеи на старте",
            "Экспериментировать без страха"
        ],
        "advice": [
            "Слушайте музыку для вдохновения",
            "Меняйте обстановку каждые 2 часа",
            "Используйте метод случайного стимула"
        ],
        "special_rituals": [
            "Утренние страницы (писать 3 страницы текста)",
            "Прогулка для генерации идей",
            "Медитация на 10 минут"
        ],
        "time_blocks": [
            "09:00-11:00 - Генерация идей",
            "11:00-13:00 - Разработка концепций",
            "13:00-14:00 - Обед и отдых",
            "14:00-16:00 - Создание прототипов",
            "16:00-17:00 - Тестирование и фидбек"
        ],
        "resources": [
            "Блокнот для идей",
            "Инструменты для прототипирования",
            "Примеры вдохновляющих работ"
        ],
        "expected_results": [
            "10+ новых идей",
            "1-2 рабочих прототипа",
            "Инсайты для развития"
        ],
        "reminders": [
            "Делать перерывы каждые 45 минут",
            "Фиксировать все внезапные идеи",
            "Не удалять 'плохие' идеи сразу"
        ],
        "motivation_quote": "Творчество — это интеллект, получающий удовольствие."
    },
    
    "баланс_работа_отдых": {
        "name": "⚖️ Баланс работа-отдых",
        "description": "Сбалансированный день для предотвращения выгорания",
        "strategic_tasks": [
            "Выполнить ключевые рабочие задачи",
            "Выделить время на хобби и отдых",
            "Практиковать осознанность"
        ],
        "critical_tasks": [
            "Завершить 2-3 важные рабочие задачи",
            "Выделить 1-2 часа на личные интересы",
            "Отдохнуть без чувства вины"
        ],
        "priorities": [
            "Качество отдыха так же важно, как и работы",
            "Четкие границы между работой и личным временем",
            "Регулярные мини-перерывы"
        ],
        "advice": [
            "Используйте технику 'time blocking'",
            "Планируйте отдых так же, как и работу",
            "Отключайте рабочие уведомления после работы"
        ],
        "special_rituals": [
            "Утреннее намерение на день",
            "Обеденный перерыв без гаджетов",
            "Вечерний ритуал завершения дня"
        ],
        "time_blocks": [
            "09:00-12:00 - Рабочий блок 1",
            "12:00-13:00 - Обед и отдых",
            "13:00-16:00 - Рабочий блок 2", 
            "16:00-17:00 - Переход к личному времени",
            "17:00-19:00 - Хобби и отдых",
            "19:00-21:00 - Семья/личное время"
        ],
        "resources": [
            "Таймер для перерывов",
            "Список приятных активностей",
            "График работы/отдыха"
        ],
        "expected_results": [
            "Выполнены рабочие задачи",
            "Качественное время для себя",
            "Чувство баланса и удовлетворения"
        ],
        "reminders": [
            "Каждый час вставать и разминаться",
            "Пить воду регулярно",
            "Благодарить себя за усилия"
        ],
        "motivation_quote": "Лучший способ сделать что-то — это начать делать."
    },
    
    "спортивный_день": {
        "name": "💪 Спортивный день",
        "description": "Фокус на физическом здоровье и активности",
        "strategic_tasks": [
            "Тренировка по плану",
            "Подготовка здорового питания",
            "Восстановление и растяжка"
        ],
        "critical_tasks": [
            "Выполнить запланированную тренировку",
            "Съесть 3 полноценных приема пищи",
            "Выпить 2+ литра воды"
        ],
        "priorities": [
            "Физическая активность как приоритет",
            "Качественное восстановление",
            "Сбалансированное питание"
        ],
        "advice": [
            "Разминка перед тренировкой обязательна",
            "Слушайте свое тело",
            "Не пропускайте завтрак"
        ],
        "special_rituals": [
            "Утренняя зарядка и растяжка",
            "Контрастный душ после тренировки",
            "Вечерняя медитация для восстановления"
        ],
        "time_blocks": [
            "07:00-08:00 - Утренняя активность",
            "08:00-09:00 - Завтрак и подготовка",
            "12:00-13:00 - Обед и отдых",
            "18:00-19:30 - Основная тренировка",
            "19:30-20:30 - Ужин и восстановление"
        ],
        "resources": [
            "Спортивная форма и инвентарь",
            "План тренировок",
            "Питание по расписанию"
        ],
        "expected_results": [
            "Выполнена тренировочная программа",
            "Хорошее самочувствие и энергия",
            "Прогресс в физической форме"
        ],
        "reminders": [
            "Разминка 10 минут перед тренировкой",
            "Заминка и растяжка после",
            "Пить воду во время тренировки"
        ],
        "motivation_quote": "Сила не в том, чтобы никогда не падать, а в том, чтобы подниматься каждый раз."
    },
    
    "обучение_развитие": {
        "name": "📚 День обучения",
        "description": "Интенсивное обучение и развитие новых навыков",
        "strategic_tasks": [
            "Изучение новой темы/навыка",
            "Практическое применение знаний",
            "Анализ прогресса и следующих шагов"
        ],
        "critical_tasks": [
            "Завершить учебный модуль",
            "Выполнить практическое задание",
            "Зафиксировать ключевые инсайты"
        ],
        "priorities": [
            "Понимание важнее запоминания",
            "Практика важнее теории",
            "Регулярные повторения"
        ],
        "advice": [
            "Делайте заметки своими словами",
            "Объясняйте материал как будто другому",
            "Применяйте знания сразу на практике"
        ],
        "special_rituals": [
            "Утренний обзор целей обучения",
            "Техника Фейнмана для сложных тем",
            "Вечерний анализ изученного"
        ],
        "time_blocks": [
            "09:00-11:00 - Изучение теории",
            "11:00-13:00 - Практика и упражнения",
            "13:00-14:00 - Обед и отдых",
            "14:00-16:00 - Углубленное изучение",
            "16:00-17:00 - Применение и проекты"
        ],
        "resources": [
            "Учебные материалы",
            "Тетрадь для заметок",
            "Практические задания"
        ],
        "expected_results": [
            "Освоен новый навык/знание",
            "Выполнено практическое задание",
            "Четкий план дальнейшего обучения"
        ],
        "reminders": [
            "Делать перерывы каждые 45 минут",
            "Повторять ключевые моменты",
            "Задавать вопросы при непонимании"
        ],
        "motivation_quote": "Образование — это то, что остается после того, когда забывается все выученное в школе."
    }
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

# ========== GOOGLE SHEETS ИНТЕГРАЦИЯ ==========

def init_google_sheets():
    """Инициализация Google Sheets с новой структурой"""
    if not GOOGLE_SHEETS_AVAILABLE:
        logger.warning("⚠️ Google Sheets не доступен")
        return None
    
    try:
        if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_SHEETS_ID:
            logger.warning("⚠️ Google Sheets credentials не настроены")
            return None
        
        # Парсим JSON credentials
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        
        # Настраиваем scope
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Создаем credentials
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        
        # Авторизуемся
        client = gspread.authorize(creds)
        
        # Открываем таблицу
        sheet = client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Создаем листы если их нет
        try:
            sheet.worksheet("клиенты_детали")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="клиенты_детали", rows=1000, cols=27)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "старт_работы",
                "пробуждение", "отход_ко_сну", "предпочтения_активности",
                "особенности_питания", "предпочтения_отдыха",
                "постоянные_утренние_ритуалы", "постоянные_вечерние_ритуалы",
                "индивидуальные_привычки", "лекарства_витамины",
                "цели_развиния", "главная_цель", "особые_примечания",
                "дата_последней_активности", "статус",
                "текущий_уровень", "очки_опыта", "текущая_серия_активности",
                "максимальная_серия_активности", "любимый_ритуал", 
                "дата_последнего_прогресса", "ближайшая_цель"
            ])
        
        try:
            sheet.worksheet("индивидуальные_планы_месяц")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="индивидуальные_планы_месяц", rows=1000, cols=40)
            headers = ["id_клиента", "telegram_username", "имя", "месяц"]
            for day in range(1, 32):
                headers.append(f"{day} октября")
            headers.extend(["общие_комментарии_месяца", "последнее_обновление"])
            worksheet.append_row(headers)
        
        try:
            sheet.worksheet("ежедневные_отчеты")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="ежедневные_отчеты", rows=1000, cols=28)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "дата",
                "выполнено_стратегических_задач", "утренние_ритуалы_выполнены",
                "вечерние_ритуалы_выполнены", "настроение", "энергия",
                "уровень_фокуса", "уровень_мотивации", "проблемы_препятствия",
                "вопросы_ассистенту", "что_получилось_хорошо", 
                "ключевые_достижения_дня", "что_можно_улучшить",
                "корректировки_на_завтра", "водный_баланс_факт", "статус_дня",
                "уровень_дня", "серия_активности", "любимый_ритуал_выполнен",
                "прогресс_по_цели", "рекомендации_на_день", "динамика_настроения",
                "динамика_энергии", "динамика_продуктивности"
            ])
        
        try:
            sheet.worksheet("статистика_месяца")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="статистика_месяца", rows=1000, cols=29)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "месяц",
                "среднее_настроение", "средний_уровень_мотивации",
                "процент_выполнения_планов", "прогресс_по_целям",
                "количество_активных_дней", "динамика_настроения",
                "процент_выполнения_утренних_ритуалов",
                "процент_выполнения_вечерних_ритуалов",
                "общее_количество_достижений", "основные_корректировки_месяца",
                "рекомендации_на_следующий_месяц", "итоги_месяца",
                "текущий_уровень", "серия_активности", "любимые_ритуалы",
                "динамика_регулярности", "персональные_рекомендации", 
                "уровень_в_начале_месяца", "уровень_в_конце_месяца",
                "общее_количество_очков", "средняя_продуктивность"
            ])
        
        try:
            sheet.worksheet("админ_панель")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="админ_панель", rows=1000, cols=10)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "текущий_статус",
                "требует_внимания", "последняя_корректировка",
                "следующий_чекап", "приоритет", "заметки_ассистента"
            ])
        
        logger.info("✅ Google Sheets инициализирован с новой структурой")
        return sheet
    
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Google Sheets: {e}")
        return None

google_sheet = init_google_sheets()

# ========== СИСТЕМА АНАЛИЗА ПРОФИЛЯ ==========

def _safe_analyze_text(text: Optional[str]) -> str:
    """Безопасно обрабатывает текст для анализа"""
    return text.lower() if text else ""

def analyze_user_profile(user_id: int) -> Dict[str, Any]:
    """Анализирует профиль пользователя по новой анкете"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT question_number, answer_text FROM questionnaire_answers WHERE user_id = %s", (user_id,))
            
            rows = cursor.fetchall()
            answers = {}
            
            for row in rows:
                answers[row['question_number']] = row['answer_text']
            
            # Базовый анализ
            profile = {
                'user_id': user_id,
                'main_goal': answers.get(1, ''),
                'goal_motivation': answers.get(2, ''),
                'success_criteria': answers.get(3, ''),
                'daily_hours': extract_hours(answers.get(4, '')),
                'deadline_info': analyze_deadlines(answers.get(5, '')),
                'sleep_schedule': answers.get(6, ''),
                'daily_routine': answers.get(7, ''),
                'energy_peaks': answers.get(8, ''),
                'distraction_time': extract_hours(answers.get(9, '')),
                'burnout_frequency': answers.get(10, ''),
                'work_style': analyze_work_style(answers.get(11, '')),
                'focus_aids': analyze_focus_aids(answers.get(12, '')),
                'break_activities': analyze_break_activities(answers.get(13, '')),
                'activity_level': analyze_activity_level(answers.get(14, '')),
                'sport_preferences': answers.get(15, ''),
                'sport_schedule': answers.get(16, ''),
                'health_limitations': answers.get(17, ''),
                'eating_habits': answers.get(18, ''),
                'water_intake': analyze_water_intake(answers.get(19, '')),
                'diet_changes': answers.get(20, ''),
                'cooking_time': answers.get(21, ''),
                'sleep_quality': answers.get(22, ''),
                'motivation_triggers': analyze_motivation(answers.get(23, '')),
                'obstacles': analyze_obstacles(answers.get(24, '')),
                'stress_management': answers.get(25, ''),
                'rest_preferences': analyze_rest_preferences(answers.get(26, '')),
                'rest_frequency': answers.get(27, ''),
                'personal_rituals': answers.get(28, ''),
                'weekend_planning': answers.get(29, ''),
                'social_needs': answers.get(30, ''),
                'hobby_time': answers.get(31, ''),
                'health_rituals': answers.get(32, ''),
                'work_life_balance': answers.get(33, ''),
                'plan_obstacles': answers.get(34, ''),
                'contingency_planning': answers.get(35, ''),
                'personality_type': determine_personality_type(answers),
                'optimal_times': calculate_optimal_times(answers.get(6, ''), answers.get(8, ''))
            }
            
            return profile
            
    except Exception as e:
        logger.error(f"❌ Ошибка анализа профиля пользователя {user_id}: {e}")
        return {}

def analyze_work_style(answer: Optional[str]) -> Dict[str, Any]:
    """Анализирует предпочтения по стилю работы с защитой от ошибок"""
    safe_answer = _safe_analyze_text(answer)
    
    work_style = {
        'prefers_long_blocks': any(word in safe_answer for word in ['длинные', 'непрерывные', '2-4 часа']),
        'prefers_short_sessions': any(word in safe_answer for word in ['короткие', '25-50 минут', 'помодоро']),
        'prefers_variety': any(word in safe_answer for word in ['чередование', 'разные задачи']),
        'prefers_multitasking': 'многозадачность' in safe_answer,
        'focus_aids': []
    }
    
    # Безопасно добавляем focus aids
    if 'тишина' in safe_answer:
        work_style['focus_aids'].append('quiet_environment')
    if 'музыка' in safe_answer:
        work_style['focus_aids'].append('background_music')
    if 'таймеры' in safe_answer:
        work_style['focus_aids'].append('timers')
    if 'дедлайны' in safe_answer:
        work_style['focus_aids'].append('deadlines')
    
    return work_style

def analyze_focus_aids(answer: str) -> List[str]:
    """Анализирует что помогает сосредоточиться"""
    safe_answer = _safe_analyze_text(answer)
    aids = []
    if 'тишина' in safe_answer:
        aids.append('quiet')
    if 'музыка' in safe_answer:
        aids.append('music')
    if 'кафе' in safe_answer:
        aids.append('cafe')
    if 'таймеры' in safe_answer:
        aids.append('timers')
    if 'дедлайны' in safe_answer:
        aids.append('deadlines')
    return aids

def analyze_break_activities(answer: str) -> List[str]:
    """Анализирует активности во время перерывов"""
    safe_answer = _safe_analyze_text(answer)
    activities = []
    if 'соцсети' in safe_answer:
        activities.append('social_media')
    if 'прогулка' in safe_answer:
        activities.append('walk')
    if 'растяжка' in safe_answer:
        activities.append('stretch')
    if 'чтение' in safe_answer:
        activities.append('reading')
    if 'ничего' in safe_answer:
        activities.append('nothing')
    return activities

def analyze_activity_level(answer: str) -> str:
    """Анализирует уровень активности"""
    safe_answer = _safe_analyze_text(answer)
    if 'сидячий' in safe_answer:
        return 'sedentary'
    elif 'прогулки' in safe_answer:
        return 'light'
    elif '1-2 раза' in safe_answer:
        return 'moderate'
    elif '3+ раза' in safe_answer:
        return 'active'
    return 'unknown'

def analyze_water_intake(answer: Optional[str]) -> str:
    """Анализирует потребление воды с защитой от ошибок"""
    if not answer:
        return 'unknown'
        
    if '1-2' in answer:
        return 'low'
    elif '4-5' in answer:
        return 'medium'
    elif '8+' in answer:
        return 'high'
    return 'unknown'

def analyze_motivation(answer: str) -> List[str]:
    """Анализирует триггеры мотивации"""
    safe_answer = _safe_analyze_text(answer)
    triggers = []
    if 'достижения' in safe_answer:
        triggers.append('achievement')
    if 'одобрение' in safe_answer:
        triggers.append('recognition')
    if 'внутренний' in safe_answer:
        triggers.append('intrinsic')
    if 'деньги' in safe_answer or 'результаты' in safe_answer:
        triggers.append('extrinsic')
    return triggers

def analyze_obstacles(answer: str) -> List[str]:
    """Анализирует основные препятствия"""
    safe_answer = _safe_analyze_text(answer)
    obstacles = []
    if 'прокрастинация' in safe_answer:
        obstacles.append('procrastination')
    if 'перфекционизм' in safe_answer:
        obstacles.append('perfectionism')
    if 'энерги' in safe_answer:
        obstacles.append('low_energy')
    if 'организац' in safe_answer:
        obstacles.append('disorganization')
    return obstacles

def analyze_rest_preferences(answer: str) -> List[str]:
    """Анализирует предпочтения по отдыху"""
    safe_answer = _safe_analyze_text(answer)
    preferences = []
    if 'активность' in safe_answer:
        preferences.append('active_rest')
    if 'пассивный' in safe_answer:
        preferences.append('passive_rest')
    if 'общение' in safe_answer:
        preferences.append('social_rest')
    if 'уединение' in safe_answer:
        preferences.append('solitude_rest')
    return preferences

def analyze_deadlines(answer: str) -> Dict[str, Any]:
    """Анализирует дедлайны и контрольные точки"""
    safe_answer = _safe_analyze_text(answer)
    deadline_info = {
        'has_deadline': False,
        'deadline_date': None,
        'milestones': [],
        'urgency_level': 'low'
    }
    
    if any(word in safe_answer for word in ['неделя', '7 дней', 'срочно']):
        deadline_info['urgency_level'] = 'high'
    elif any(word in safe_answer for word in ['месяц', '30 дней']):
        deadline_info['urgency_level'] = 'medium'
    
    # Простой анализ наличия дедлайна
    if any(word in safe_answer for word in ['дедлайн', 'срок', 'до', 'когда']):
        deadline_info['has_deadline'] = True
    
    return deadline_info

def extract_hours(text: str) -> Optional[int]:
    """Извлекает количество часов из текста"""
    match = re.search(r'(\d+)\s*час', text)
    if match:
        return int(match.group(1))
    return None

def determine_personality_type(answers: Dict[int, str]) -> str:
    """Определяет тип личности для персонализации планов"""
    score = 0
    
    # Анализ стиля работы
    work_answer = _safe_analyze_text(answers.get(11, ""))
    if 'длинные' in work_answer:
        score += 2
    if 'многозадачность' in work_answer:
        score -= 1
    
    # Анализ мотивации
    motivation_answer = _safe_analyze_text(answers.get(23, ""))
    if 'внутренний' in motivation_answer:
        score += 1
    if 'достижения' in motivation_answer:
        score += 2
    
    if score >= 4:
        return "deep_focus"
    elif score >= 2:
        return "balanced"
    elif score >= 0:
        return "varied"
    else:
        return "dynamic"

def calculate_optimal_times(sleep_answer: str, energy_answer: str) -> Dict[str, str]:
    """Рассчитывает оптимальное время для разных активностей"""
    safe_sleep_answer = _safe_analyze_text(sleep_answer)
    safe_energy_answer = _safe_analyze_text(energy_answer)
    
    wake_time = "08:00"
    if any(word in safe_sleep_answer for word in ['5', '6']):
        wake_time = "07:00"
    elif any(word in safe_sleep_answer for word in ['9', '10']):
        wake_time = "09:00"
    
    if 'утро' in safe_energy_answer:
        deep_work_start = "09:00"
    elif 'день' in safe_energy_answer:
        deep_work_start = "13:00"
    else:
        deep_work_start = "10:00"
    
    return {
        'wake_up': wake_time,
        'deep_work_start': deep_work_start,
        'creative_work': "15:00",
        'learning_time': "11:00",
        'physical_activity': "18:00",
        'planning_time': "20:00"
    }

# ========== СИСТЕМА ШАБЛОНОВ И ПЕРСОНАЛИЗАЦИИ ==========

def create_personalized_template(template_key: str, user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Создает персонализированный шаблон на основе профиля пользователя"""
    base_template = PLAN_TEMPLATES[template_key].copy()
    
    # Адаптируем под тип личности
    personality = user_profile['personality_type']
    if personality == "deep_focus":
        base_template = adapt_for_deep_focus(base_template, user_profile)
    elif personality == "dynamic":
        base_template = adapt_for_dynamic(base_template, user_profile)
    
    # Адаптируем под цели
    goal_type = user_profile['goal_analysis']['type'] if 'goal_analysis' in user_profile else "unknown"
    if goal_type == "project":
        base_template = adapt_for_project_goal(base_template, user_profile)
    
    # Адаптируем под рабочие предпочтения
    base_template = adapt_work_blocks(base_template, user_profile)
    
    # Адаптируем под энергетические паттерны
    base_template = adapt_energy_patterns(base_template, user_profile)
    
    # Добавляем персонализированные советы
    base_template = add_personalized_advice(base_template, user_profile)
    
    return base_template

def adapt_for_deep_focus(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптация для глубоко сконцентрированного типа"""
    if 'time_blocks' in template:
        new_blocks = []
        for block in template['time_blocks']:
            if 'работа' in block.lower() or 'задач' in block.lower():
                block = block.replace('1 час', '2 часа').replace('60 минут', '120 минут')
            new_blocks.append(block)
        template['time_blocks'] = new_blocks
    
    if 'advice' in template:
        template['advice'].extend([
            "Используйте технику 'глубокой работы' - полная концентрация без отвлечений",
            "Отключайте все уведомления на время рабочих блоков"
        ])
    
    return template

def adapt_for_dynamic(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптация для динамичного типа"""
    if 'time_blocks' in template:
        new_blocks = []
        for block in template['time_blocks']:
            if 'работа' in block.lower() and '2 часа' in block:
                time_part = block.split(' - ')[0]
                task_part = block.split(' - ')[1]
                new_blocks.extend([
                    f"{time_part} - {task_part} (сессия 1)",
                    f"{add_30_min(time_part)} - {task_part} (сессия 2)",
                    f"{add_30_min(add_30_min(time_part))} - Перерыв 10 мин"
                ])
            else:
                new_blocks.append(block)
        template['time_blocks'] = new_blocks
    
    return template

def adapt_work_blocks(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптирует рабочие блоки под предпочтения пользователя"""
    work_style = profile.get('work_style', {})
    optimal_times = profile.get('optimal_times', {})
    
    if 'time_blocks' in template and optimal_times:
        new_blocks = []
        
        for block in template['time_blocks']:
            if 'глубокая работа' in block.lower():
                block = block.replace('09:00', optimal_times.get('deep_work_start', '09:00'))
            new_blocks.append(block)
        
        template['time_blocks'] = new_blocks
    
    return template

def adapt_energy_patterns(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптирует план под энергетические паттерны пользователя"""
    energy_level = profile.get('energy_level', 'medium')
    
    if energy_level == 'low':
        if 'time_blocks' in template:
            enhanced_blocks = []
            for i, block in enumerate(template['time_blocks']):
                enhanced_blocks.append(block)
                if 'работа' in block.lower() and i < len(template['time_blocks']) - 1:
                    enhanced_blocks.append("Короткий перерыв 5-10 минут - размяться, попить воды")
            template['time_blocks'] = enhanced_blocks
    
    return template

def add_personalized_advice(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Добавляет персонализированные советы"""
    obstacles = profile.get('obstacles', [])
    motivation_triggers = profile.get('motivation_triggers', [])
    
    if 'advice' not in template:
        template['advice'] = []
    
    if 'procrastination' in obstacles:
        template['advice'].append("Начните с самой маленькой задачи - принцип '2 минут'")
    
    if 'perfectionism' in obstacles:
        template['advice'].append("Сначала сделайте, потом улучшайте - принцип 'достаточно хорошо'")
    
    if 'achievement' in motivation_triggers:
        template['advice'].append("Отмечайте каждое маленькое достижение")
    
    return template

def add_30_min(time_str: str) -> str:
    """Добавляет 30 минут к времени"""
    try:
        time_obj = datetime.strptime(time_str, "%H:%M")
        new_time = time_obj + timedelta(minutes=30)
        return new_time.strftime("%H:%M")
    except:
        return time_str

def save_daily_plan_to_sheets(user_id: int, date: str, plan: Dict[str, Any]) -> bool:
    """Заглушка для сохранения плана в Google Sheets"""
    logger.info(f"📝 План для пользователя {user_id} на {date} готов к сохранению")
    # Пока просто возвращаем True, реализуем позже
    return True

def generate_highly_personalized_plan(user_id: int, date: str, template_key: str = None) -> bool:
    """Генерирует высоко персонализированный план для пользователя"""
    try:
        # Анализируем профиль пользователя
        user_profile = analyze_user_profile(user_id)
        
        # Определяем шаблон
        if not template_key:
            day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A").lower()
            day_translation = {
                'monday': 'понедельник', 'tuesday': 'вторник', 'wednesday': 'среда',
                'thursday': 'четверг', 'friday': 'пятница', 'saturday': 'суббота', 'sunday': 'воскресенье'
            }
            russian_day = day_translation.get(day_name, 'понедельник')
            template_key = WEEKLY_TEMPLATE_SCHEDULE.get(russian_day, "продуктивный_день")
        
        # Создаем персонализированный шаблон
        personalized_plan = create_personalized_template(template_key, user_profile)
        
        # Добавляем цель пользователя в план
        goal_text = user_profile.get('main_goal', '')
        if goal_text and goal_text != "Цель не установлена":
            if 'strategic_tasks' in personalized_plan:
                personalized_plan['strategic_tasks'].insert(0, f"Движение к цели: {goal_text}")
        
        # Сохраняем план
        success = save_daily_plan_to_sheets(user_id, date, personalized_plan)
        
        if success:
            logger.info(f"✅ Персонализированный план создан для {user_id} на {date}")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания персонализированного плана: {e}")
        return False

# ========== ОСНОВНЫЕ ФУНКЦИИ БАЗЫ ДАННЫХ ==========

def save_user_info(user_id: int, username: str, first_name: str, last_name: Optional[str] = None):
    """Сохраняет информацию о пользователе в базу данных безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            registration_date = datetime.now()
            
            cursor.execute('''INSERT INTO clients 
                             (user_id, username, first_name, last_name, status, registration_date, last_activity) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s)
                             ON CONFLICT (user_id) DO UPDATE SET
                             username = EXCLUDED.username,
                             first_name = EXCLUDED.first_name,
                             last_name = EXCLUDED.last_name,
                             last_activity = EXCLUDED.last_activity''',
                          (user_id, username, first_name, last_name, 'active', registration_date, registration_date))
            
            conn.commit()
            logger.info(f"✅ Информация о пользователе {user_id} сохранена в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")

def update_user_activity(user_id: int):
    """Обновляет время последней активности пользователя безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            last_activity = datetime.now()
            
            cursor.execute('''UPDATE clients SET last_activity = %s WHERE user_id = %s''',
                          (last_activity, user_id))
            
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления активности {user_id}: {e}")

def check_user_registered(user_id: int) -> bool:
    """Проверяет зарегистрирован ли пользователь безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_id FROM clients WHERE user_id = %s", (user_id,))
            
            result = cursor.fetchone()
            return result is not None
            
    except Exception as e:
        logger.error(f"❌ Ошибка проверки регистрации {user_id}: {e}")
        return False

def save_questionnaire_answer(user_id: int, question_number: int, question_text: str, answer_text: str):
    """Сохраняет ответ на вопрос анкеты безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            answer_date = datetime.now()
            
            cursor.execute('''INSERT INTO questionnaire_answers 
                             (user_id, question_number, question_text, answer_text, answer_date) 
                             VALUES (%s, %s, %s, %s, %s)
                             ON CONFLICT (user_id, question_number) 
                             DO UPDATE SET 
                                answer_text = EXCLUDED.answer_text,
                                answer_date = EXCLUDED.answer_date''',
                          (user_id, question_number, question_text, answer_text, answer_date))
            
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения ответа {user_id}: {e}")

def save_message(user_id: int, message_text: str, direction: str):
    """Сохраняет сообщение в базу данных безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            created_at = datetime.now()
            
            cursor.execute('''INSERT INTO user_messages 
                             (user_id, message_text, direction, created_at) 
                             VALUES (%s, %s, %s, %s)''',
                          (user_id, message_text, direction, created_at))
            
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения {user_id}: {e}")

def save_user_plan_to_db(user_id: int, plan_data: Dict[str, Any]):
    """Сохраняет план пользователя в базу данных безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            created_date = datetime.now()
            
            cursor.execute('''INSERT INTO user_plans 
                             (user_id, plan_date, morning_ritual1, morning_ritual2, task1, task2, task3, task4, 
                              lunch_break, evening_ritual1, evening_ritual2, advice, sleep_time, water_goal, 
                              activity_goal, created_date) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                          (user_id, plan_data.get('plan_date'), plan_data.get('morning_ritual1'), 
                           plan_data.get('morning_ritual2'), plan_data.get('task1'), plan_data.get('task2'),
                           plan_data.get('task3'), plan_data.get('task4'), plan_data.get('lunch_break'),
                           plan_data.get('evening_ritual1'), plan_data.get('evening_ritual2'), 
                           plan_data.get('advice'), plan_data.get('sleep_time'), plan_data.get('water_goal'),
                           plan_data.get('activity_goal'), created_date))
            
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения плана {user_id}: {e}")

def get_user_plan_from_db(user_id: int):
    """Получает текущий план пользователя из базы данных безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''SELECT * FROM user_plans 
                             WHERE user_id = %s AND status = 'active' 
                             ORDER BY created_date DESC LIMIT 1''', (user_id,))
            
            plan = cursor.fetchone()
            return plan
    except Exception as e:
        logger.error(f"❌ Ошибка получения плана {user_id}: {e}")
        return None

def save_progress_to_db(user_id: int, progress_data: Dict[str, Any]):
    """Сохраняет прогресс пользователя в базу данных безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            progress_date = datetime.now().date()
            
            cursor.execute('''INSERT INTO user_progress 
                             (user_id, progress_date, tasks_completed, mood, energy, sleep_quality, 
                              water_intake, activity_done, user_comment, day_rating, challenges) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                          (user_id, progress_date, progress_data.get('tasks_completed'), 
                           progress_data.get('mood'), progress_data.get('energy'), 
                           progress_data.get('sleep_quality'), progress_data.get('water_intake'),
                           progress_data.get('activity_done'), progress_data.get('user_comment'),
                           progress_data.get('day_rating'), progress_data.get('challenges')))
            
            conn.commit()
            logger.info(f"✅ Прогресс сохранен в БД для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения прогресса {user_id}: {e}")

def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Возвращает статистику пользователя безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM user_messages WHERE user_id = %s AND direction = 'incoming'", (user_id,))
            messages_count_result = cursor.fetchone()
            messages_count = messages_count_result['count'] if messages_count_result else 0
            
            cursor.execute("SELECT registration_date FROM clients WHERE user_id = %s", (user_id,))
            reg_date_result = cursor.fetchone()
            reg_date = reg_date_result['registration_date'] if reg_date_result else "Неизвестно"
            
            return {
                'messages_count': messages_count,
                'registration_date': reg_date
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики {user_id}: {e}")
        return {'messages_count': 0, 'registration_date': 'Ошибка'}

def has_sufficient_data(user_id: int) -> bool:
    """Проверяет есть ли достаточно данных для статистики (минимум 3 дня) безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            count = result['count'] if result else 0
            
            return count >= 3
    except Exception as e:
        logger.error(f"❌ Ошибка проверки данных {user_id}: {e}")
        return False

def get_user_activity_streak(user_id: int) -> int:
    """Возвращает текущую серию активных дней подряд безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT DISTINCT progress_date FROM user_progress WHERE user_id = %s ORDER BY progress_date DESC", (user_id,))
            dates_result = cursor.fetchall()
            dates = [row['progress_date'] for row in dates_result if row['progress_date']]
            
            if not dates:
                return 0
            
            # Сортируем по убыванию и проверяем последовательность
            dates.sort(reverse=True)
            streak = 0
            today = datetime.now().date()
            
            for i, date in enumerate(dates):
                expected_date = today - timedelta(days=i)
                if date == expected_date:
                    streak += 1
                else:
                    break
            
            return streak
    except Exception as e:
        logger.error(f"❌ Ошибка получения серии {user_id}: {e}")
        return 0

def get_user_main_goal(user_id: int) -> str:
    """Получает главную цель пользователя из анкеты безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT answer_text FROM questionnaire_answers WHERE user_id = %s AND question_number = 1", (user_id,))
            result = cursor.fetchone()
            return result['answer_text'] if result else "Цель не установлена"
    except Exception as e:
        logger.error(f"❌ Ошибка получения цели {user_id}: {e}")
        return "Ошибка загрузки цели"

def get_user_level_info(user_id: int) -> Dict[str, Any]:
    """Возвращает информацию об уровне пользователя безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", (user_id,))
            active_days_result = cursor.fetchone()
            active_days = active_days_result['count'] if active_days_result else 0
            
            cursor.execute("SELECT SUM(tasks_completed) FROM user_progress WHERE user_id = %s", (user_id,))
            total_tasks_result = cursor.fetchone()
            total_tasks = total_tasks_result['sum'] if total_tasks_result else 0
            
            level_points = active_days * 10 + total_tasks * 2
            level_names = {
                0: "Новичок",
                50: "Ученик", 
                100: "Опытный",
                200: "Профессионал",
                500: "Мастер"
            }
            
            current_level = "Новичок"
            next_level_points = 50
            points_to_next = 50
            
            for points, level in sorted(level_names.items()):
                if level_points >= points:
                    current_level = level
                else:
                    next_level_points = points
                    points_to_next = points - level_points
                    break
            
            return {
                'level': current_level,
                'points': level_points,
                'points_to_next': points_to_next,
                'next_level_points': next_level_points
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения уровня {user_id}: {e}")
        return {'level': 'Новичок', 'points': 0, 'points_to_next': 50, 'next_level_points': 50}

def get_favorite_ritual(user_id: int) -> str:
    """Определяет любимый ритуал пользователя безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT answer_text FROM questionnaire_answers WHERE user_id = %s AND question_number = 32", (user_id,))
            result = cursor.fetchone()
            
            if result:
                rituals_text = result['answer_text'].lower() if result['answer_text'] else ""
                
                if "медитация" in rituals_text:
                    return "Утренняя медитация"
                elif "зарядка" in rituals_text or "растяжка" in rituals_text:
                    return "Утренняя зарядка"
                elif "чтение" in rituals_text:
                    return "Вечернее чтение"
                elif "дневник" in rituals_text:
                    return "Ведение дневника"
                elif "планирование" in rituals_text:
                    return "Планирование задач"
            
            return "на основе ваших предпочтений"
    except Exception as e:
        logger.error(f"❌ Ошибка получения ритуала {user_id}: {e}")
        return "на основе ваших предпочтений"

def get_user_usage_days(user_id: int) -> Dict[str, int]:
    """Возвращает статистику дней использования безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT registration_date FROM clients WHERE user_id = %s", (user_id,))
            reg_result = cursor.fetchone()
            
            if not reg_result:
                return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
            
            reg_date = reg_result['registration_date'].date()
            days_since_registration = (datetime.now().date() - reg_date).days + 1
            
            cursor.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", (user_id,))
            active_days_result = cursor.fetchone()
            active_days = active_days_result['count'] if active_days_result else 0
            
            current_streak = get_user_activity_streak(user_id)
            
            return {
                'days_since_registration': days_since_registration,
                'active_days': active_days,
                'current_day': active_days if active_days > 0 else 1,
                'current_streak': current_streak
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения дней использования {user_id}: {e}")
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}

# ========== GOOGLE SHEETS ФУНКЦИИ ==========

def save_client_to_sheets(user_data: Dict[str, Any]):
    """Сохраняет клиента в Google Sheets"""
    if not google_sheet:
        logger.warning("⚠️ Google Sheets не доступен")
        return False
    
    try:
        worksheet = google_sheet.worksheet("клиенты_детали")
        
        # Ищем существующего клиента
        try:
            cell = worksheet.find(str(user_data['user_id']))
            row = cell.row
            worksheet.update(f'A{row}:Y{row}', [[
                user_data['user_id'],
                user_data.get('telegram_username', ''),
                user_data.get('first_name', ''),
                user_data.get('start_date', datetime.now().strftime("%Y-%m-%d")),
                user_data.get('wake_time', ''),
                user_data.get('sleep_time', ''),
                user_data.get('activity_preferences', ''),
                user_data.get('diet_features', ''),
                user_data.get('rest_preferences', ''),
                user_data.get('morning_rituals', ''),
                user_data.get('evening_rituals', ''),
                user_data.get('personal_habits', ''),
                user_data.get('medications', ''),
                user_data.get('development_goals', ''),
                user_data.get('main_goal', ''),
                user_data.get('special_notes', ''),
                user_data.get('last_activity', datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                'active',
                user_data.get('текущий_уровень', 'Новичок'),
                user_data.get('очки_опыта', '0'),
                user_data.get('текущая_серия_активности', '0'),
                user_data.get('максимальная_серия_активности', '0'),
                user_data.get('любимый_ритуал', ''),
                user_data.get('дата_последнего_прогресса', datetime.now().strftime("%Y-%m-%d")),
                user_data.get('ближайшая_цель', '')
            ]])
        except Exception:
            # Создаем новую запись
            worksheet.append_row([
                user_data['user_id'],
                user_data.get('telegram_username', ''),
                user_data.get('first_name', ''),
                user_data.get('start_date', datetime.now().strftime("%Y-%m-%d")),
                user_data.get('wake_time', ''),
                user_data.get('sleep_time', ''),
                user_data.get('activity_preferences', ''),
                user_data.get('diet_features', ''),
                user_data.get('rest_preferences', ''),
                user_data.get('morning_rituals', ''),
                user_data.get('evening_rituals', ''),
                user_data.get('personal_habits', ''),
                user_data.get('medications', ''),
                user_data.get('development_goals', ''),
                user_data.get('main_goal', ''),
                user_data.get('special_notes', ''),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'active',
                user_data.get('текущий_уровень', 'Новичок'),
                user_data.get('очки_опыта', '0'),
                user_data.get('текущая_серия_активности', '0'),
                user_data.get('максимальная_серия_активности', '0'),
                user_data.get('любимый_ритуал', ''),
                datetime.now().strftime("%Y-%m-%d"),
                user_data.get('ближайшая_цель', '')
            ])
        
        logger.info(f"✅ Клиент {user_data['user_id']} сохранен в Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения клиента в Google Sheets: {e}")
        return False

def format_enhanced_plan(plan_data: Dict[str, Any]) -> str:
    """Форматирует план с улучшенной структурой"""
    plan_text = f"🏁 {plan_data.get('name', 'Индивидуальный план')}\n\n"
    plan_text += f"📝 {plan_data.get('description', '')}\n\n"
    
    if plan_data.get('strategic_tasks'):
        plan_text += "🎯 СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
        for i, task in enumerate(plan_data['strategic_tasks'], 1):
            plan_text += f"{i}️⃣ {task}\n"
        plan_text += "\n"
    
    if plan_data.get('critical_tasks'):
        plan_text += "⚠️ КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
        for i, task in enumerate(plan_data['critical_tasks'], 1):
            plan_text += f"🔴 {task}\n"
        plan_text += "\n"
    
    if plan_data.get('priorities'):
        plan_text += "🎯 ПРИОРИТЕТЫ ДНЯ:\n"
        for priority in plan_data['priorities']:
            plan_text += f"⭐ {priority}\n"
        plan_text += "\n"
    
    if plan_data.get('time_blocks'):
        plan_text += "⏰ ВРЕМЕННЫЕ БЛОКИ:\n"
        for block in plan_data['time_blocks']:
            plan_text += f"🕒 {block}\n"
        plan_text += "\n"
    
    if plan_data.get('advice'):
        plan_text += "💡 СОВЕТЫ АССИСТЕНТА:\n"
        for advice in plan_data['advice']:
            plan_text += f"💫 {advice}\n"
        plan_text += "\n"
    
    if plan_data.get('motivation_quote'):
        plan_text += f"💫 МОТИВАЦИОННАЯ ЦИТАТА:\n{plan_data['motivation_quote']}\n"
    
    return plan_text.strip()

def save_daily_report_to_sheets(user_id: int, report_data: Dict[str, Any]):
    """Сохраняет ежедневный отчет в Google Sheets"""
    if not google_sheet:
        logger.warning("⚠️ Google Sheets не доступен")
        return False
    
    try:
        worksheet = google_sheet.worksheet("ежедневные_отчеты")
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, first_name FROM clients WHERE user_id = %s", (user_id,))
            user_info = cursor.fetchone()
        
        username = user_info['username'] if user_info and user_info['username'] else ""
        first_name = user_info['first_name'] if user_info and user_info['first_name'] else ""
        
        worksheet.append_row([
            user_id,
            username,
            first_name,
            report_data.get('date', datetime.now().strftime("%Y-%m-%d")),
            report_data.get('strategic_tasks_done', ''),
            report_data.get('morning_rituals_done', ''),
            report_data.get('evening_rituals_done', ''),
            report_data.get('mood', ''),
            report_data.get('energy', ''),
            report_data.get('focus_level', ''),
            report_data.get('motivation_level', ''),
            report_data.get('problems', ''),
            report_data.get('questions', ''),
            report_data.get('what_went_well', ''),
            report_data.get('key_achievements', ''),
            report_data.get('what_to_improve', ''),
            report_data.get('adjustments', ''),
            report_data.get('water_intake', ''),
            report_data.get('day_status', ''),
            report_data.get('уровень_дня', ''),
            report_data.get('серия_активности', ''),
            report_data.get('любимый_ритуал_выполнен', ''),
            report_data.get('прогресс_по_цели', ''),
            report_data.get('рекомендации_на_день', ''),
            report_data.get('динамика_настроения', ''),
            report_data.get('динамика_энергии', ''),
            report_data.get('динамика_продуктивности', '')
        ])
        
        logger.info(f"✅ Отчет сохранен в Google Sheets для пользователя {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения отчета: {e}")
        return False

def get_daily_plan_from_sheets(user_id: int, date: str) -> Dict[str, Any]:
    """Получает план на день из Google Sheets"""
    if not google_sheet:
        logger.warning("⚠️ Google Sheets не доступен")
        return {}
    
    try:
        worksheet = google_sheet.worksheet("индивидуальные_планы_месяц")
        
        # Ищем пользователя
        try:
            cell = worksheet.find(str(user_id))
            row = cell.row
        except Exception:
            logger.warning(f"⚠️ Пользователь {user_id} не найден в Google Sheets")
            return {}
        
        # Получаем все данные строки
        row_data = worksheet.row_values(row)
        
        # Определяем колонку для нужной даты
        day = datetime.strptime(date, "%Y-%m-%d").day
        date_column_index = 4 + day - 1  # 4 базовые колонки + день месяца
        
        if date_column_index >= len(row_data):
            logger.warning(f"⚠️ Для даты {date} нет данных в Google Sheets")
            return {}
        
        plan_text = row_data[date_column_index]
        
        # Парсим структурированный текст плана
        plan_data = parse_structured_plan(plan_text)
        
        return plan_data
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения плана: {e}")
        return {}

def parse_structured_plan(plan_text: str) -> Dict[str, Any]:
    """Парсит структурированный текст плана на компоненты"""
    if not plan_text:
        return {}
    
    sections = {
        'strategic_tasks': [],
        'critical_tasks': [],
        'priorities': [],
        'advice': [],
        'special_rituals': [],
        'time_blocks': [],
        'resources': [],
        'expected_results': [],
        'reminders': [],
        'motivation_quote': ''
    }
    
    current_section = None
    
    for line in plan_text.split('\n'):
        line = line.strip()
        
        if not line:
            continue
            
        # Определяем секции
        if 'СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:' in line:
            current_section = 'strategic_tasks'
            continue
        elif 'КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:' in line:
            current_section = 'critical_tasks'
            continue
        elif 'ПРИОРИТЕТЫ ДНЯ:' in line:
            current_section = 'priorities'
            continue
        elif 'СОВЕТЫ АССИСТЕНТА:' in line:
            current_section = 'advice'
            continue
        elif 'СПЕЦИАЛЬНЫЕ РИТУАЛЫ:' in line:
            current_section = 'special_rituals'
            continue
        elif 'ВРЕМЕННЫЕ БЛОКИ:' in line:
            current_section = 'time_blocks'
            continue
        elif 'РЕСУРСЫ И МАТЕРИАЛЫ:' in line:
            current_section = 'resources'
            continue
        elif 'ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ:' in line:
            current_section = 'expected_results'
            continue
        elif 'ДОПОЛНИТЕЛЬНЫЕ НАПОМИНАНИЯ:' in line:
            current_section = 'reminders'
            continue
        elif 'МОТИВАЦИОННАя ЦИТАТА:' in line:
            current_section = 'motivation_quote'
            continue
            
        # Добавляем данные в текущую секцию
        if current_section and line.startswith('- '):
            content = line[2:].strip()
            if current_section == 'motivation_quote':
                sections[current_section] = content
            else:
                sections[current_section].append(content)
    
    return sections

# ========== СИСТЕМА НАПОМИНАНИЙ ==========

def parse_time_input(time_text: str) -> Dict[str, Any]:
    """Парсит различные форматы времени - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    time_text = time_text.lower().strip()
    
    logger.info(f"🕒 Парсим время: {time_text}")
    
    # Словарь для преобразования относительного времени
    time_mapping = {
        'утром': '08:00',
        'утро': '08:00', 
        'утра': '08:00',
        'днем': '13:00',
        'день': '13:00',
        'вечером': '20:00',
        'вечер': '20:00',
        'ночью': '22:00',
        'ночь': '22:00',
        'в обед': '13:00',
        'перед сном': '22:00',
        'после работы': '18:00',
        'в полдень': '12:00'
    }
    
    # 1. Проверяем точное время с двоеточием (14:30, 9:00)
    exact_time_match = re.search(r'(\d{1,2}):(\d{2})', time_text)
    if exact_time_match:
        hours = int(exact_time_match.group(1))
        minutes = int(exact_time_match.group(2))
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            time_str = f"{hours:02d}:{minutes:02d}"
            logger.info(f"✅ Распознано точное время: {time_str}")
            return {'time': time_str, 'type': 'exact'}
    
    # 2. Проверяем форматы типа "11 часов вечера", "7 утра", "3 ночи"
    hour_time_match = re.search(r'(\d{1,2})\s*(?:час\w*)?\s*(утра|вечера|ночи|дня)', time_text)
    if hour_time_match:
        hour = int(hour_time_match.group(1))
        period = hour_time_match.group(2)
        
        if period == 'утра':
            if 1 <= hour <= 12:
                time_str = f"{hour:02d}:00"
                logger.info(f"✅ Распознано время утра: {time_str}")
                return {'time': time_str, 'type': '12h'}
        elif period == 'вечера':
            if 1 <= hour <= 11:
                time_str = f"{hour + 12:02d}:00"
                logger.info(f"✅ Распознано время вечера: {time_str}")
                return {'time': time_str, 'type': '12h'}
            elif hour == 12:
                time_str = "12:00"
                logger.info(f"✅ Распознано время вечера: {time_str}")
                return {'time': time_str, 'type': '12h'}
        elif period == 'ночи':
            if 1 <= hour <= 11:
                time_str = f"{hour + 12:02d}:00"
                logger.info(f"✅ Распознано время ночи: {time_str}")
                return {'time': time_str, 'type': '12h'}
            elif hour == 12:
                time_str = "00:00"
                logger.info(f"✅ Распознано время ночи: {time_str}")
                return {'time': time_str, 'type': '12h'}
        elif period == 'дня':
            if 1 <= hour <= 11:
                time_str = f"{hour + 12:02d}:00"
                logger.info(f"✅ Распознано время дня: {time_str}")
                return {'time': time_str, 'type': '12h'}
            elif hour == 12:
                time_str = "12:00"
                logger.info(f"✅ Распознано время дня: {time_str}")
                return {'time': time_str, 'type': '12h'}
    
    # 3. Проверяем простые форматы "11 вечера", "7 утра" (без слова "час")
    simple_time_match = re.search(r'(\d{1,2})\s+(утра|вечера|ночи)', time_text)
    if simple_time_match:
        hour = int(simple_time_match.group(1))
        period = simple_time_match.group(2)
        
        if period == 'утра' and 1 <= hour <= 12:
            time_str = f"{hour:02d}:00"
            logger.info(f"✅ Распознано простое время утра: {time_str}")
            return {'time': time_str, 'type': 'simple'}
        elif period == 'вечера' and 1 <= hour <= 11:
            time_str = f"{hour + 12:02d}:00"
            logger.info(f"✅ Распознано простое время вечера: {time_str}")
            return {'time': time_str, 'type': 'simple'}
        elif period == 'ночи' and 1 <= hour <= 11:
            time_str = f"{hour + 12:02d}:00"
            logger.info(f"✅ Распознано простое время ночи: {time_str}")
            return {'time': time_str, 'type': 'simple'}
    
    # 4. Проверяем относительное время (утром, вечером и т.д.)
    if time_text in time_mapping:
        time_str = time_mapping[time_text]
        logger.info(f"✅ Распознано относительное время: {time_str}")
        return {'time': time_str, 'type': 'relative'}
    
    # 5. 🔧 ИСПРАВЛЕННЫЙ БЛОК: "через X часов/минут" - ТОЛЬКО ДЛЯ РАЗОВЫХ НАПОМИНАНИЙ
    future_match = re.search(r'через\s+(\d+)\s*(час|часа|часов|минут|минуты)', time_text)
    if future_match:
        amount = int(future_match.group(1))
        unit = future_match.group(2)
        
        now = datetime.now()
        if 'час' in unit:
            future_time = now + timedelta(hours=amount)
        else:
            future_time = now + timedelta(minutes=amount)
        
        # 🔧 ИСПРАВЛЕНИЕ: Сохраняем как разовое напоминание с ОТЛОЖЕННЫМ ВРЕМЕНЕМ
        time_str = future_time.strftime("%H:%M")
        logger.info(f"✅ Распознано будущее время: {time_str} (через {amount} {unit})")
        
        # Возвращаем специальный тип для обработки в напоминаниях
        return {
            'time': time_str, 
            'type': 'future_relative',
            'delay_minutes': amount * (60 if 'час' in unit else 1),
            'original_text': time_text
        }
    
    logger.warning(f"❌ Не удалось распознать время: {time_text}")
    return None

def detect_reminder_type(text: str) -> str:
    """Определяет тип напоминания по тексту"""
    text_lower = text.lower()
    
    # Ключевые слова для регулярных напоминаний (только целые слова)
    regular_keywords = [
        'каждый', 'каждое', 'ежедневно', 'регулярно', 'каждую', 
        'напоминай'  # "напоминай" - для регулярных
    ]
    
    # Дни недели
    days_keywords = [
        'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье',
        'пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'
    ]
    
    # Проверяем наличие ключевых слов для регулярных напоминаний
    for keyword in regular_keywords:
        # Ищем целые слова
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            logger.info(f"✅ Обнаружено ключевое слово для регулярного напоминания: {keyword}")
            return 'regular'
    
    # Проверяем дни недели
    for day in days_keywords:
        if day in text_lower:
            logger.info(f"✅ Обнаружен день недели: {day}")
            return 'regular'
    
    # Если нет признаков регулярности - разовое напоминание
    logger.info("✅ Определено как разовое напоминание")
    return 'once'

def parse_reminder_text(text: str) -> Dict[str, Any]:
    """Парсит текст напоминания и возвращает структурированные данные - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    original_text = text
    text_lower = text.lower()
    
    logger.info(f"🔍 Начинаем парсинг напоминания: {text}")
    
    # Определяем тип напоминания
    reminder_type = detect_reminder_type(text_lower)
    logger.info(f"📝 Тип напоминания: {reminder_type}")
    
    # 🔧 ИСКЛЮЧЕНИЕ: для "через X минут" всегда разовое напоминание
    if re.search(r'через\s+(\d+)\s*(минут|минуты)', text_lower):
        reminder_type = 'once'
        logger.info("🔧 Принудительно установлен тип 'once' для напоминания через минуты")
    
    # Удаляем ключевые слова из текста для извлечения времени и текста напоминания
    clean_text = text_lower
    
    # Удаляем слова для напоминаний
    reminder_words = ['напомни', 'напоминай', 'мне']
    for word in reminder_words:
        clean_text = re.sub(r'\b' + re.escape(word) + r'\b', '', clean_text)
    
    # Удаляем слова для регулярности (если это разовое напоминание)
    if reminder_type == 'once':
        regular_words = ['каждый', 'каждое', 'ежедневно', 'регулярно', 'каждую']
        for word in regular_words:
            clean_text = re.sub(r'\b' + re.escape(word) + r'\b', '', clean_text)
    
    clean_text = clean_text.strip()
    
    # Извлекаем время
    time_data = parse_time_input(clean_text)
    
    # Если время не найдено, пробуем парсить весь текст
    if not time_data:
        time_data = parse_time_input(original_text)
    
    # Если время так и не найдено, используем время по умолчанию
    if not time_data:
        time_data = {'time': '09:00', 'type': 'default'}
        logger.warning("⚠️ Время не распознано, используется время по умолчанию: 09:00")
    
    # 🔧 ПЕРЕНОСИМ параметры из time_data в reminder_data
    reminder_data = {
        'type': reminder_type,
        'time': time_data['time'],
        'text': '',
        'days': [],
        'original_text': original_text
    }
    
    # Добавляем дополнительные параметры из time_data
    if 'delay_minutes' in time_data:
        reminder_data['delay_minutes'] = time_data['delay_minutes']
    
    # Извлекаем дни недели для регулярных напоминаний (только если не относительное)
    if reminder_type == 'regular' and 'delay_minutes' not in time_data:
        days_map = {
            'понедельник': 'пн', 'вторник': 'вт', 'среда': 'ср', 'среду': 'ср',
            'четверг': 'чт', 'пятница': 'пт', 'пятницу': 'пт', 
            'суббота': 'сб', 'субботу': 'сб', 'воскресенье': 'вс',
            'пн': 'пн', 'вт': 'вт', 'ср': 'ср', 'чт': 'чт', 'пт': 'пт', 'сб': 'сб', 'вс': 'вс'
        }
        
        for day_full, day_short in days_map.items():
            if day_full in text_lower:
                reminder_data['days'].append(day_short)
                # Удаляем день из чистого текста
                clean_text = re.sub(r'\b' + re.escape(day_full) + r'\b', '', clean_text)
        
        # Если дни не указаны, но это регулярное напоминание - значит ежедневно
        if not reminder_data['days'] and reminder_type == 'regular':
            reminder_data['days'] = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
            logger.info("📅 Дни недели не указаны, установлено ежедневно")
    
    # Очищаем текст напоминания от лишних пробелов
    reminder_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    # Если текст пустой, используем оригинальный текст без первых слов
    if not reminder_text:
        # Удаляем первые слова напоминания
        temp_text = text_lower
        for word in ['напомни', 'напоминай', 'мне']:
            temp_text = re.sub(r'\b' + re.escape(word) + r'\b', '', temp_text)
        reminder_text = re.sub(r'\s+', ' ', temp_text).strip()
    
    reminder_data['text'] = reminder_text
    
    logger.info(f"✅ Результат парсинга: время={reminder_data['time']}, текст={reminder_text}, тип={reminder_type}, дни={reminder_data['days']}")
    
    return reminder_data

def add_reminder_to_db(user_id: int, reminder_data: Dict[str, Any]) -> bool:
    """Добавляет напоминание в базу данных - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 🔧 ОБРАБОТКА ОТНОСИТЕЛЬНЫХ НАПОМИНАНИЙ
            if reminder_data.get('type') == 'once' and 'delay_minutes' in reminder_data:
                # Для относительных напоминаний вычисляем точное время
                from datetime import datetime, timedelta
                reminder_time = (datetime.now() + timedelta(minutes=reminder_data['delay_minutes'])).strftime("%H:%M")
            else:
                reminder_time = reminder_data['time']
            
            days_str = ','.join(reminder_data['days']) if reminder_data['days'] else 'ежедневно'
            created_date = datetime.now()
            
            cursor.execute('''INSERT INTO user_reminders 
                             (user_id, reminder_text, reminder_time, days_of_week, reminder_type, created_date)
                             VALUES (%s, %s, %s, %s, %s, %s)''',
                          (user_id, reminder_data['text'], reminder_time, 
                           days_str, reminder_data['type'], created_date))
            
            conn.commit()
            logger.info(f"✅ Напоминание добавлено для пользователя {user_id} на {reminder_time}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка добавления напоминания: {e}")
        return False
    
def get_user_reminders(user_id: int) -> List[Dict]:
    """Возвращает список напоминаний пользователя безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''SELECT id, reminder_text, reminder_time, days_of_week, reminder_type 
                             FROM user_reminders 
                             WHERE user_id = %s AND is_active = TRUE 
                             ORDER BY created_date DESC''', (user_id,))
            
            reminders = []
            for row in cursor.fetchall():
                reminders.append({
                    'id': row['id'],
                    'text': row['reminder_text'],
                    'time': row['reminder_time'],
                    'days': row['days_of_week'],
                    'type': row['reminder_type']
                })
            
            return reminders
    except Exception as e:
        logger.error(f"❌ Ошибка получения напоминаний {user_id}: {e}")
        return []

def delete_reminder_from_db(reminder_id: int) -> bool:
    """Удаляет напоминание по ID безопасно"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''UPDATE user_reminders SET is_active = FALSE WHERE id = %s''', (reminder_id,))
            
            conn.commit()
            logger.info(f"✅ Напоминание {reminder_id} удалено")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка удаления напоминания: {e}")
        return False

# ========== СИСТЕМА ОТПРАВКИ НАПОМИНАНИЙ ==========

async def send_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет напоминания пользователям безопасно"""
    try:
        async with get_db_connection() as conn:
            # Получаем текущее время и день недели
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            current_day_rus = now.strftime("%A").lower()
            day_translation = {
                'monday': 'пн', 'tuesday': 'вт', 'wednesday': 'ср',
                'thursday': 'чт', 'friday': 'пт', 'saturday': 'сб', 'sunday': 'вс'
            }
            current_day = day_translation.get(current_day_rus, 'пн')
            
            # Ищем напоминания для текущего времени (PostgreSQL)
            async with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                await cursor.execute('''
                    SELECT ur.id, ur.user_id, ur.reminder_text, c.first_name, ur.reminder_type
                    FROM user_reminders ur 
                    JOIN clients c ON ur.user_id = c.user_id 
                    WHERE ur.is_active = TRUE AND ur.reminder_time = %s 
                    AND (ur.days_of_week LIKE %s OR ur.days_of_week = 'ежедневно' OR ur.days_of_week = '')
                ''', (current_time, f'%{current_day}%'))
                
                reminders = await cursor.fetchall()
                
                for reminder in reminders:
                    reminder_id = reminder['id']
                    user_id = reminder['user_id']
                    reminder_text = reminder['reminder_text']
                    first_name = reminder['first_name']
                    reminder_type = reminder['reminder_type']
                    
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"🔔 Напоминание: {reminder_text}"
                        )
                        logger.info(f"✅ Напоминание отправлено пользователю {user_id}")
                        
                        # Если это разовое напоминание - деактивируем его
                        if reminder_type == 'once':
                            await cursor.execute(
                                'UPDATE user_reminders SET is_active = FALSE WHERE id = %s',
                                (reminder_id,)
                            )
                            await conn.commit()
                            logger.info(f"📝 Разовое напоминание {reminder_id} деактивировано")
                            
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки напоминания {user_id}: {e}")
                            
    except Exception as e:
        logger.error(f"❌ Ошибка в send_reminder_job: {e}")

def schedule_reminders(application):
    """Настраивает периодическую проверку напоминаний"""
    try:
        job_queue = application.job_queue
        if job_queue:
            # Проверяем напоминания каждую минуту
            job_queue.run_repeating(
                callback=send_reminder_job,
                interval=60,  # 60 секунд
                first=10,     # начать через 10 секунд после запуска
                name="reminder_checker"
            )
            logger.info("✅ Система напоминаний запущена")
    except Exception as e:
        logger.error(f"❌ Ошибка настройки напоминаний: {e}")

# ========== GOOGLE SHEETS МЕНЕДЖЕР ==========

class GoogleSheetsManager:
    """Менеджер для работы с Google Sheets"""
    def __init__(self):
        self.client = None
        self.sheet = None
        self.connect()
    
    def connect(self):
        """Подключается к Google Sheets безопасно"""
        try:
            if not GOOGLE_SHEETS_AVAILABLE:
                logger.warning("⚠️ Google Sheets не доступен")
                return None
                
            if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_SHEETS_ID:
                logger.warning("⚠️ GOOGLE_CREDENTIALS_JSON или GOOGLE_SHEETS_ID не найден")
                return None
            
            # 🔒 Безопасная проверка credentials
            try:
                creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
                required_keys = ['type', 'project_id', 'private_key_id', 'private_key']
                if not all(key in creds_dict for key in required_keys):
                    logger.error("❌ Invalid Google credentials structure")
                    return None
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"❌ Invalid Google credentials JSON: {e}")
                return None
            
            scope = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            self.client = gspread.authorize(creds)
            
            self.sheet = self.client.open_by_key(GOOGLE_SHEETS_ID)
            logger.info("✅ Google Sheets менеджер подключен безопасно")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
            return None
    
    def save_daily_data(self, user_id: int, data_type: str, value: str) -> bool:
        """Сохраняет ежедневные данные в новую структуру безопасно"""
        if not self.sheet:
            logger.warning("⚠️ Google Sheets не подключен")
            return False
            
        try:
            worksheet = self.sheet.worksheet("ежедневные_отчеты")
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Ищем существующую запись на сегодня
            records = worksheet.get_all_records()
            row_index = None
            
            for i, record in enumerate(records, start=2):
                if (str(record.get('id_клиента', '')) == str(user_id) and 
                    record.get('дата', '') == today):
                    row_index = i
                    break
            
            if not row_index:
                # Создаем новую запись
                user_info = self.get_user_info(user_id)
                if not user_info:
                    return False
                
                worksheet.append_row([
                    user_id,
                    user_info['username'],
                    user_info['first_name'],
                    today
                ])
                
                # Получаем индекс новой строки
                records = worksheet.get_all_records()
                for i, record in enumerate(records, start=2):
                    if (str(record.get('id_клиента', '')) == str(user_id) and 
                        record.get('дата', '') == today):
                        row_index = i
                        break
            
            if not row_index:
                return False
            
            # Обновляем соответствующую колонку
            column_mapping = {
                'настроение': 8,
                'энергия': 9,
                'уровень_фокуса': 10,
                'уровень_мотивации': 11,
                'водный_баланс': 18
            }
            
            if data_type in column_mapping:
                col_index = column_mapping[data_type]
                worksheet.update_cell(row_index, col_index, value)
                logger.info(f"✅ Данные сохранены в Google Sheets: {user_id} - {data_type}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения данных в Google Sheets: {e}")
            return False
    
    def get_user_info(self, user_id: int) -> Optional[Dict[str, str]]:
        """Получает информацию о пользователе безопасно"""
        conn = get_db_connection()
        if not conn:
            return None
            
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, first_name FROM clients WHERE user_id = %s", 
                (user_id,)
            )
            result = cursor.fetchone()
            if result:
                return {
                    'username': result['username'] or '', 
                    'first_name': result['first_name'] or ''
                }
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о пользователе {user_id}: {e}")
            return None
        finally:
            if conn:
                conn.close()

sheets_manager = GoogleSheetsManager()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def update_user_activity(user_id: int):
    """Обновляет время последней активности пользователя"""
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE clients SET last_activity = %s WHERE user_id = %s",
            (datetime.now(), user_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления активности {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def check_user_registered(user_id: int) -> bool:
    """Проверяет, зарегистрирован ли пользователь"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM clients WHERE user_id = %s", 
            (user_id,)
        )
        result = cursor.fetchone()
        return result[0] > 0 if result else False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки регистрации {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def save_questionnaire_answer(user_id: int, question_number: int, question: str, answer: str):
    """Сохраняет ответ на вопрос анкеты"""
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO questionnaire_answers (user_id, question_number, question_text, answer_text, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, question_number) 
            DO UPDATE SET 
                answer_text = EXCLUDED.answer_text,
                created_at = EXCLUDED.created_at
        ''', (user_id, question_number, question, answer, datetime.now()))
        conn.commit()
        logger.info(f"✅ Ответ на вопрос {question_number} пользователя {user_id} сохранен")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения ответа {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def save_message(user_id: int, message_text: str, direction: str):
    """Сохраняет сообщение в базу"""
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (user_id, message_text, direction, created_at) VALUES (%s, %s, %s, %s)",
            (user_id, message_text, direction, datetime.now())
        )
        conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения {user_id}: {e}")
    finally:
        if conn:
            conn.close()

# ========== ВОССТАНОВЛЕНИЕ АНКЕТЫ ==========

def restore_questionnaire_state(user_id: int) -> Dict[str, Any]:
    """Восстанавливает состояние анкеты пользователя из PostgreSQL"""
    conn = get_db_connection()
    if not conn:
        return {'current_question': 0, 'answers': {}, 'has_previous_answers': False}
        
    try:
        cursor = conn.cursor()
        
        # Получаем все ответы пользователя
        cursor.execute('''
            SELECT question_number, answer_text 
            FROM questionnaire_answers 
            WHERE user_id = %s 
            ORDER BY question_number
        ''', (user_id,))
        
        answers_data = cursor.fetchall()
        answers = {}
        for row in answers_data:
            answers[row['question_number']] = row['answer_text']
        
        if answers:
            # Определяем текущий вопрос
            last_question = max(answers.keys())
            current_question = last_question + 1 if last_question < len(QUESTIONS) - 1 else last_question
            
            return {
                'current_question': current_question,
                'answers': answers,
                'has_previous_answers': True
            }
        
        return {'current_question': 0, 'answers': {}, 'has_previous_answers': False}
        
    except Exception as e:
        logger.error(f"❌ Ошибка БД при восстановлении анкеты {user_id}: {e}")
        return {'current_question': 0, 'answers': {}, 'has_previous_answers': False}
    finally:
        if conn:
            conn.close()

# ========== ОСНОВНЫЕ КОМАНДЫ БОТА ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start с восстановлением состояния"""
    user = update.effective_user
    user_id = user.id
    
    save_user_info(user_id, user.username, user.first_name, user.last_name)
    update_user_activity(user_id)
    
    # Восстанавливаем состояние анкеты
    questionnaire_state = restore_questionnaire_state(user_id)
    
    has_answers = False
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM questionnaire_answers WHERE user_id = %s", 
                (user_id,)
            )
            result = cursor.fetchone()
            has_answers = result[0] > 0 if result else False
        except Exception as e:
            logger.error(f"❌ Ошибка проверки анкеты пользователя {user_id}: {e}")
            has_answers = False
        finally:
            conn.close()
    
    if has_answers and questionnaire_state['current_question'] >= len(QUESTIONS):
        # Анкета уже полностью заполнена
        keyboard = [
            ['📊 Прогресс', '👤 Профиль'],
            ['📋 План на сегодня', '🔔 Мои напоминания'],
            ['ℹ️ Помощь', '🎮 Очки опыта']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "✅ Вы уже заполнили анкету!\n\n"
            "Добро пожаловать обратно! Что хотите сделать?",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
        
    elif has_answers and questionnaire_state['current_question'] < len(QUESTIONS):
        # Анкета заполнена частично - предлагаем продолжить
        keyboard = [
            ['✅ Продолжить анкету', '🔄 Начать заново'],
            ['❌ Отменить']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            f"📋 У вас есть незавершенная анкета!\n\n"
            f"Заполнено вопросов: {questionnaire_state['current_question']} из {len(QUESTIONS)}\n"
            f"Хотите продолжить или начать заново?",
            reply_markup=reply_markup
        )
        
        context.user_data['questionnaire_state'] = questionnaire_state
        return GENDER
        
    else:
        # Новая анкета
        keyboard = [['👨 Мужской', '👩 Женский']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности.\n\n'
            'Для начала выберите пол ассистента:',
            reply_markup=reply_markup
        )
        
        return GENDER

async def gender_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик выбора пола ассистента"""
    gender = update.message.text.replace('👨 ', '').replace('👩 ', '')
    context.user_data['assistant_gender'] = gender
    
    if gender == 'Мужской':
        assistant_name = 'Антон'
    else:
        assistant_name = 'Валерия'
    
    context.user_data['assistant_name'] = assistant_name
    context.user_data['current_question'] = 0
    context.user_data['answers'] = {}
    
    await update.message.reply_text(
        f'🧌 Привет! Меня зовут {assistant_name}. Я ваш персональный ассистент.\n\n'
        f'Моя задача – помочь структурировать ваш день для максимальной продуктивности и достижения целей без стресса и выгорания.\n\n'
        f'Я составлю для вас сбалансированный план на месяц, а затем мы будем ежедневно отслеживать прогресс и ваше состояние, '
        f'чтобы вы двигались к цели уверенно и эффективно и с заботой о главных ресурсах: сне, спорте и питании.\n\n'
        f'Для составления плана, который будет работать именно для вас, мне нужно понять ваш ритм жизни и цели. '
        f'Это займет около 25-30 минут. Но в результате вы получите персональную стратегию на месяц, а не шаблонный список дел.\n\n'
        f'Готовы начать?',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return FIRST_QUESTION

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик ответов на вопросы анкеты"""
    user_id = update.effective_user.id
    answer_text = update.message.text
    
    # Сохраняем ответ
    current_question = context.user_data['current_question']
    save_questionnaire_answer(user_id, current_question, QUESTIONS[current_question], answer_text)
    context.user_data['answers'][current_question] = answer_text
    
    # Переходим к следующему вопросу
    context.user_data['current_question'] += 1
    if context.user_data['current_question'] < len(QUESTIONS):
        await update.message.reply_text(QUESTIONS[context.user_data['current_question']])
        return FIRST_QUESTION
    else:
        return await finish_questionnaire(update, context)

async def finish_questionnaire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает анкету и отправляет данные"""
    user = update.effective_user
    assistant_name = context.user_data['assistant_name']
    
    # Сохраняем данные анкеты в Google Sheets
    user_data = {
        'user_id': user.id,
        'telegram_username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'start_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'main_goal': context.user_data['answers'].get(1, ''),
        'last_activity': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'текущий_уровень': 'Новичок',
        'очки_опыта': '0',
        'текущая_серия_активности': '0',
        'максимальная_серия_активности': '0',
        'любимый_ритуал': '',
        'дата_последнего_прогресса': datetime.now().strftime("%Y-%m-%d"),
        'ближайшая_цель': 'Заполнить первую неделю активности'
    }
    
    save_client_to_sheets(user_data)
    
    # Формируем анкету для отправки админу
    questionnaire = f"📋 Новая анкета от пользователя:\n\n"
    questionnaire += f"👤 ID: {user.id}\n"
    questionnaire += f"📛 Имя: {user.first_name}\n"
    if user.last_name:
        questionnaire += f"📛 Фамилия: {user.last_name}\n"
    if user.username:
        questionnaire += f"🔗 Username: @{user.username}\n"
    questionnaire += f"📅 Дата: {update.message.date.strftime('%Y-%m-%d %H:%M')}\n"
    questionnaire += f"👨‍💼 Ассистент: {assistant_name}\n\n"
    
    questionnaire += "📝 Ответы на вопросы:\n\n"
    
    for i, question in enumerate(QUESTIONS):
        answer = context.user_data['answers'].get(i, '❌ Нет ответа')
        questionnaire += f"❓ {i+1}. {question}:\n"
        questionnaire += f"💬 {answer}\n\n"
    
    # Отправляем админу
    max_length = 4096
    if len(questionnaire) > max_length:
        parts = [questionnaire[i:i+max_length] for i in range(0, len(questionnaire), max_length)]
        for part in parts:
            try:
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=part)
            except Exception as e:
                logger.error(f"❌ Ошибка отправки части анкеты: {e}")
    else:
        try:
            await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=questionnaire)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки анкеты: {e}")
    
    # Отправляем кнопки админу
    try:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Ответить пользователю", callback_data=f"reply_{user.id}")],
            [InlineKeyboardButton("👁️ Просмотреть анкету", callback_data=f"view_questionnaire_{user.id}")],
            [InlineKeyboardButton("📊 Статистика пользователя", callback_data=f"stats_{user.id}")],
            [InlineKeyboardButton("📋 Создать план", callback_data=f"create_plan_{user.id}")]
        ])
        
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=f"✅ Пользователь {user.first_name} завершил анкету!",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"❌ Ошибка отправки кнопки ответа: {e}")
    
    # Сообщение пользователю
    keyboard = [
        ['📊 Прогресс', '👤 Профиль'],
        ['📋 План на сегодня', '🔔 Мои напоминания'],
        ['ℹ️ Помощь', '🎮 Очки опыта']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🎉 Спасибо за ответы!\n\n"
        "✅ Я передал всю информацию нашему специалисту. В течение 24 часов он проанализирует ваши данные и составит для вас индивидуальный план.\n\n"
        "🔔 Теперь у вас есть доступ к персональному ассистенту!\n\n"
        "💡 Вы можете писать напоминания естественным языком:\n"
        "'напомни мне в 20:00 сходить в душ'\n"
        "'напоминай каждый день в 8:00 делать зарядку'\n\n"
        "Или использовать команды из меню ниже:",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

# ========== КОМАНДЫ АДМИНА ==========

async def admin_add_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс добавления плана (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📋 ДОБАВЛЕНИЕ ПЕРСОНАЛЬНОГО ПЛАНА\n\n"
        "Введите ID пользователя:"
    )
    return ADD_PLAN_USER

async def add_plan_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ID пользователя для добавления плана"""
    try:
        user_id = int(update.message.text)
        context.user_data['plan_user_id'] = user_id
        
        # Проверяем существование пользователя
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text(
                f"❌ Ошибка подключения к базе данных. Попробуйте снова:"
            )
            return ADD_PLAN_USER
            
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT first_name FROM clients WHERE user_id = %s", 
                (user_id,)
            )
            user_info = cursor.fetchone()
            if not user_info:
                await update.message.reply_text(
                    f"❌ Пользователь с ID {user_id} не найден.\n"
                    "Проверьте ID и попробуйте снова:"
                )
                return ADD_PLAN_USER
            
            context.user_data['user_name'] = user_info['first_name']
        except Exception as e:
            logger.error(f"❌ Ошибка проверки пользователя {user_id}: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при проверке пользователя. Попробуйте снова:"
            )
            return ADD_PLAN_USER
        finally:
            conn.close()
        
        await update.message.reply_text(
            f"👤 Пользователь: {user_info['first_name']} (ID: {user_id})\n\n"
            "Введите дату для плана (формат: ГГГГ-ММ-ДД):"
        )
        return ADD_PLAN_DATE
        
    except ValueError:
        await update.message.reply_text(
            "❌ ID пользователя должен быть числом.\n"
            "Введите корректный ID:"
        )
        return ADD_PLAN_USER

async def add_plan_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает дату для добавления плана"""
    date_str = update.message.text
    
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        context.user_data['plan_date'] = date_str
        
        await update.message.reply_text(
            f"📅 Дата: {date_str}\n\n"
            "Теперь введите содержание плана.\n\n"
            "💡 Вы можете использовать структурированный формат:\n"
            "СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
            "- Задача 1\n"
            "- Задача 2\n"
            "КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
            "- Срочная задача\n"
            "СОВЕТЫ АССИСТЕНТА:\n"
            "- Ваш совет"
        )
        return ADD_PLAN_CONTENT
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты.\n"
            "Используйте формат: ГГГГ-ММ-ДД\n"
            "Попробуйте снова:"
        )
        return ADD_PLAN_DATE

async def add_plan_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает содержание плана и сохраняет его"""
    plan_content = update.message.text
    user_id = context.user_data['plan_user_id']
    date_str = context.user_data['plan_date']
    user_name = context.user_data['user_name']
    
    # Парсим структурированный план
    plan_data = parse_structured_plan(plan_content)
    
    # Сохраняем в Google Sheets
    success = save_daily_plan_to_sheets(user_id, date_str, plan_data)
    
    if success:
        # Сохраняем в PostgreSQL
        save_user_plan_to_db(user_id, {
            'plan_date': date_str,
            'task1': plan_data.get('strategic_tasks', [''])[0] if plan_data.get('strategic_tasks') else '',
            'task2': plan_data.get('strategic_tasks', [''])[1] if len(plan_data.get('strategic_tasks', [])) > 1 else '',
            'task3': plan_data.get('strategic_tasks', [''])[2] if len(plan_data.get('strategic_tasks', [])) > 2 else '',
            'task4': plan_data.get('critical_tasks', [''])[0] if plan_data.get('critical_tasks') else '',
            'advice': plan_data.get('advice', [''])[0] if plan_data.get('advice') else ''
        })
        
        await update.message.reply_text(
            f"✅ План успешно добавлен!\n\n"
            f"👤 Пользователь: {user_name}\n"
            f"📅 Дата: {date_str}\n"
            f"📋 План сохранен в Google Sheets"
        )
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 У вас новый персональный план на {date_str}!\n\n"
                     f"Используйте команду /plan чтобы посмотреть его."
            )
        except Exception as e:
            logger.warning(f"⚠️ Не удалось отправить уведомление пользователю {user_id}: {e}")
            
    else:
        await update.message.reply_text(
            "❌ Ошибка при сохранении плана.\n"
            "Проверьте подключение к Google Sheets."
        )
    
    return ConversationHandler.END

def save_user_plan_to_db(user_id: int, plan_data: Dict[str, Any]):
    """Сохраняет план пользователя в PostgreSQL"""
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_plans (user_id, plan_date, task1, task2, task3, task4, advice, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, plan_data['plan_date'], plan_data['task1'], plan_data['task2'],
           plan_data['task3'], plan_data['task4'], plan_data['advice'], 'active', datetime.now()))
        conn.commit()
        logger.info(f"✅ План пользователя {user_id} сохранен в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения плана {user_id}: {e}")
    finally:
        if conn:
            conn.close()

# ========== СИСТЕМА НАПОМИНАНИЙ ==========

def add_reminder_to_db(user_id: int, reminder_data: Dict[str, Any]) -> bool:
    """Добавляет напоминание в базу данных"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_reminders 
            (user_id, reminder_text, reminder_time, days_of_week, reminder_type, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, reminder_data['text'], reminder_data['time'], 
           ','.join(reminder_data.get('days', [])), reminder_data['type'], True, datetime.now()))
        conn.commit()
        logger.info(f"✅ Напоминание добавлено для пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка добавления напоминания {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_reminders(user_id: int) -> List[Dict]:
    """Возвращает список напоминаний пользователя"""
    conn = get_db_connection()
    if not conn:
        return []
        
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, reminder_text, reminder_time, days_of_week, reminder_type 
            FROM user_reminders 
            WHERE user_id = %s AND is_active = true 
            ORDER BY created_at DESC
        ''', (user_id,))
        
        reminders_data = cursor.fetchall()
        reminders = []
        for row in reminders_data:
            reminders.append({
                'id': row['id'],
                'text': row['reminder_text'],
                'time': row['reminder_time'],
                'days': row['days_of_week'],
                'type': row['reminder_type']
            })
        
        return reminders
    except Exception as e:
        logger.error(f"❌ Ошибка БД при получении напоминаний {user_id}: {e}")
        return []
    finally:
        if conn:
            conn.close()

def delete_reminder_from_db(reminder_id: int) -> bool:
    """Удаляет напоминание по ID"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE user_reminders SET is_active = false WHERE id = %s', 
            (reminder_id,)
        )
        conn.commit()
        logger.info(f"✅ Напоминание {reminder_id} удалено")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка удаления напоминания: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ========== КОМАНДЫ ТРЕКИНГА ==========

async def done_command(update: Update, context: CallbackContext):
    """Отмечает выполнение задачи"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите номер задачи:\n"
            "/done 1 - отметить задачу 1 выполненной\n"
            "/done 2 - отметить задачу 2 выполненной"
        )
        return
    
    try:
        task_number = int(context.args[0])
        if task_number < 1 or task_number > 4:
            await update.message.reply_text("❌ Номер задачи должен быть от 1 до 4")
            return
        
        task_names = {1: "первую", 2: "вторую", 3: "третью", 4: "четвертую"}
        
        await update.message.reply_text(
            f"✅ Отлично! Вы выполнили {task_names[task_number]} задачу!\n"
            f"🎉 Продолжайте в том же духе!"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Номер задачи должен быть числом")

async def mood_command(update: Update, context: CallbackContext):
    """Оценка настроения"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        await update.message.reply_text(
            "❌ Оцените ваше настроение от 1 до 10:\n"
            "/mood 1 - очень плохое\n"
            "/mood 5 - нейтральное\n" 
            "/mood 10 - отличное"
        )
        return
    
    try:
        mood = int(context.args[0])
        if mood < 1 or mood > 10:
            await update.message.reply_text("❌ Оценка должна быть от 1 до 10")
            return
        
        progress_data = {
            'mood': mood,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
        # Сохраняем в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'mood': mood
        }
        save_daily_report_to_sheets(user_id, report_data)
        
        mood_responses = {
            1: "😔 Мне жаль, что у вас плохое настроение.",
            2: "😟 Надеюсь, завтра будет лучше!",
            3: "🙁 Не отчаивайтесь, трудности временны!",
            4: "😐 Спасибо за честность!",
            5: "😊 Нейтрально - это тоже нормально!",
            6: "😄 Хорошее настроение - это здорово!",
            7: "😁 Отлично! Рад за вас!",
            8: "🤩 Прекрасное настроение!",
            9: "🥳 Восхитительно!",
            10: "🎉 Идеально!"
        }
        
        response = mood_responses.get(mood, "Спасибо за оценку!")
        await update.message.reply_text(f"{response}\n\n📊 Данные сохранены!")
        
    except ValueError:
        await update.message.reply_text("❌ Оценка должна быть числом от 1 до 10")

async def energy_command(update: Update, context: CallbackContext):
    """Оценка уровня энергии"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        await update.message.reply_text(
            "❌ Оцените ваш уровень энергии от 1 до 10:\n"
            "/energy 1 - совсем нет сил\n"
            "/energy 5 - средний уровень\n"
            "/energy 10 - полон энергии!"
        )
        return
    
    try:
        energy = int(context.args[0])
        if energy < 1 or energy > 10:
            await update.message.reply_text("❌ Оценка должна быть от 1 до 10")
            return
        
        progress_data = {
            'energy': energy,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
        # Сохраняем в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'energy': energy
        }
        save_daily_report_to_sheets(user_id, report_data)
        
        energy_responses = {
            1: "💤 Важно отдыхать! Может, стоит сделать перерыв?",
            2: "😴 Похоже, сегодня тяжелый день. Берегите себя!",
            3: "🛌 Отдых - это тоже продуктивно!",
            4: "🧘 Небольшая зарядка может помочь!",
            5: "⚡ Средний уровень - нормально для рабочего дня!",
            6: "💪 Хорошая энергия! Так держать!",
            7: "🚀 Отличный уровень энергии!",
            8: "🔥 Прекрасно! Используйте эту энергию!",
            9: "🌟 Восхитительная энергия!",
            10: "🎯 Идеально! Вы полны сил!"
        }
        
        response = energy_responses.get(energy, "Спасибо за оценку!")
        await update.message.reply_text(f"{response}\n\n📊 Данные сохранены!")
        
    except ValueError:
        await update.message.reply_text("❌ Оценка должна быть числом от 1 до 10")

async def water_command(update: Update, context: CallbackContext):
    """Отслеживание водного баланса"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите количество стаканов: /water 6\n\n"
            "Пример: /water 8 - выпито 8 стаканов воды"
        )
        return
    
    try:
        water = int(context.args[0])
        if water < 0 or water > 20:
            await update.message.reply_text("❌ Укажите разумное количество стаканов (0-20)")
            return
        
        progress_data = {
            'water_intake': water,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
        # Сохраняем в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'water_intake': water
        }
        save_daily_report_to_sheets(user_id, report_data)
        
        responses = {
            0: "💧 Напомнить выпить воды?",
            1: "💧 Мало воды, нужно больше!",
            2: "💧 Продолжайте в том же духе!",
            3: "💧 Хорошее начало!",
            4: "💧 Неплохо, но можно лучше!",
            5: "💧 Хорошо, но можно лучше!",
            6: "💧 Отлично! Так держать!",
            7: "💧 Прекрасно!",
            8: "💧 Идеально! Вы молодец!"
        }
        response = responses.get(water, f"💧 Записано: {water} стаканов")
        await update.message.reply_text(f"{response}\n\n📊 Данные сохранены!")
        
    except ValueError:
        await update.message.reply_text("❌ Количество должно быть числом")

# ========== СИСТЕМА ПРОГРЕССА И СТАТИСТИКИ ==========

def save_progress_to_db(user_id: int, progress_data: Dict[str, Any]):
    """Сохраняет прогресс пользователя в базу данных"""
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cursor = conn.cursor()
        progress_date = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute('''
            INSERT INTO user_progress 
            (user_id, progress_date, tasks_completed, mood, energy, sleep_quality, 
             water_intake, activity_done, user_comment, day_rating, challenges) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, progress_date, progress_data.get('tasks_completed'), 
           progress_data.get('mood'), progress_data.get('energy'), 
           progress_data.get('sleep_quality'), progress_data.get('water_intake'),
           progress_data.get('activity_done'), progress_data.get('user_comment'),
           progress_data.get('day_rating'), progress_data.get('challenges')))
        conn.commit()
        logger.info(f"✅ Прогресс сохранен в БД для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения прогресса для {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def has_sufficient_data(user_id: int) -> bool:
    """Проверяет есть ли достаточно данных для статистики (минимум 3 дня)"""
    conn = get_db_connection()
    if not conn:
        return False
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", 
            (user_id,)
        )
        result = cursor.fetchone()
        count = result[0] if result else 0
        return count >= 3
    except Exception as e:
        logger.error(f"❌ Ошибка проверки данных для {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_activity_streak(user_id: int) -> int:
    """Возвращает текущую серию активных дней подряд"""
    conn = get_db_connection()
    if not conn:
        return 0
        
    try:
        cursor = conn.cursor()
        # Получаем все даты активности пользователя
        cursor.execute(
            "SELECT DISTINCT progress_date FROM user_progress WHERE user_id = %s ORDER BY progress_date DESC", 
            (user_id,)
        )
        dates_data = cursor.fetchall()
        dates = [row[0] for row in dates_data]
        
        if not dates:
            return 0
        
        # Сортируем по убыванию и проверяем последовательность
        dates.sort(reverse=True)
        streak = 0
        today = datetime.now().date()
        
        for i, date in enumerate(dates):
            expected_date = today - timedelta(days=i)
            if date == expected_date:
                streak += 1
            else:
                break
        
        return streak
    except Exception as e:
        logger.error(f"❌ Ошибка расчета серии для {user_id}: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def get_user_main_goal(user_id: int) -> str:
    """Получает главную цель пользователя из анкеты"""
    conn = get_db_connection()
    if not conn:
        return "Цель не установлена"
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT answer_text FROM questionnaire_answers WHERE user_id = %s AND question_number = 1", 
            (user_id,)
        )
        result = cursor.fetchone()
        return result['answer_text'] if result else "Цель не установлена"
    except Exception as e:
        logger.error(f"❌ Ошибка получения цели для {user_id}: {e}")
        return "Цель не установлена"
    finally:
        if conn:
            conn.close()

def get_favorite_ritual(user_id: int) -> str:
    """Определяет любимый ритуал пользователя"""
    conn = get_db_connection()
    if not conn:
        return "личные ритуалы"
        
    try:
        cursor = conn.cursor()
        # Получаем ответы о ритуалах из анкеты
        cursor.execute(
            "SELECT answer_text FROM questionnaire_answers WHERE user_id = %s AND question_number = 22", 
            (user_id,)
        )
        result = cursor.fetchone()
        
        if result:
            rituals_text = result['answer_text']
            # Простой анализ текста для определения предпочтений
            if "медитация" in rituals_text.lower():
                return "Утренняя медитация"
            elif "зарядка" in rituals_text.lower() or "растяжка" in rituals_text.lower():
                return "Утренняя зарядка"
            elif "чтение" in rituals_text.lower():
                return "Вечернее чтение"
            elif "дневник" in rituals_text.lower():
                return "Ведение дневника"
            elif "планирование" in rituals_text.lower():
                return "Планирование задач"
        
        return "на основе ваших предпочтений"
    except Exception as e:
        logger.error(f"❌ Ошибка определения ритуала для {user_id}: {e}")
        return "личные ритуалы"
    finally:
        if conn:
            conn.close()

def get_user_level_info(user_id: int) -> Dict[str, Any]:
    """Возвращает информацию об уровне пользователя"""
    conn = get_db_connection()
    if not conn:
        return {'level': 'Новичок', 'points': 0, 'points_to_next': 50, 'next_level_points': 50}
        
    try:
        cursor = conn.cursor()
        # Считаем количество дней активности
        cursor.execute(
            "SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", 
            (user_id,)
        )
        active_days_result = cursor.fetchone()
        active_days = active_days_result[0] if active_days_result else 0
        
        # Считаем выполненные задачи
        cursor.execute(
            "SELECT SUM(tasks_completed) FROM user_progress WHERE user_id = %s", 
            (user_id,)
        )
        total_tasks_result = cursor.fetchone()
        total_tasks = total_tasks_result[0] if total_tasks_result else 0
        
        # Простая система уровней
        level_points = active_days * 10 + total_tasks * 2
        level_names = {
            0: "Новичок",
            50: "Ученик", 
            100: "Опытный",
            200: "Профессионал",
            500: "Мастер"
        }
        
        current_level = "Новичок"
        next_level_points = 50
        points_to_next = 50
        
        for points, level in sorted(level_names.items()):
            if level_points >= points:
                current_level = level
            else:
                next_level_points = points
                points_to_next = points - level_points
                break
        
        return {
            'level': current_level,
            'points': level_points,
            'points_to_next': points_to_next,
            'next_level_points': next_level_points
        }
    except Exception as e:
        logger.error(f"❌ Ошибка расчета уровня для {user_id}: {e}")
        return {'level': 'Новичок', 'points': 0, 'points_to_next': 50, 'next_level_points': 50}
    finally:
        if conn:
            conn.close()

def get_user_usage_days(user_id: int) -> Dict[str, int]:
    """Возвращает статистику дней использования"""
    conn = get_db_connection()
    if not conn:
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
        
    try:
        cursor = conn.cursor()
        # Дни с регистрации
        cursor.execute(
            "SELECT registration_date FROM clients WHERE user_id = %s", 
            (user_id,)
        )
        reg_result = cursor.fetchone()
        if not reg_result:
            return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
        
        reg_date = reg_result['registration_date']
        days_since_registration = (datetime.now().date() - reg_date.date()).days + 1
        
        # Активные дни (когда был прогресс)
        cursor.execute(
            "SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", 
            (user_id,)
        )
        active_days_result = cursor.fetchone()
        active_days = active_days_result[0] if active_days_result else 0
        
        # Текущая серия
        current_streak = get_user_activity_streak(user_id)
        
        return {
            'days_since_registration': days_since_registration,
            'active_days': active_days,
            'current_day': active_days if active_days > 0 else 1,
            'current_streak': current_streak
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики дней для {user_id}: {e}")
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
    finally:
        if conn:
            conn.close()

# ========== ОСНОВНЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ==========

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий план пользователя"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    # Получаем план из Google Sheets
    today = datetime.now().strftime("%Y-%m-%d")
    plan_data = get_daily_plan_from_sheets(user_id, today)
    
    if not plan_data:
        await update.message.reply_text(
            "📋 Индивидуальный план еще не готов.\n\n"
            "Наш ассистент анализирует вашу анкету и скоро составит для вас "
            "персональный план. Обычно это занимает до 24 часов.\n\n"
            "А пока вы можете использовать общие рекомендации для продуктивного дня!"
        )
        return
    
    # Формируем сообщение с планом
    plan_text = f"📋 Ваш индивидуальный план на {today}:\n\n"
    
    if plan_data.get('strategic_tasks'):
        plan_text += "🎯 СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
        for task in plan_data['strategic_tasks']:
            plan_text += f"• {task}\n"
        plan_text += "\n"
    
    if plan_data.get('critical_tasks'):
        plan_text += "⚠️ КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
        for task in plan_data['critical_tasks']:
            plan_text += f"• {task}\n"
        plan_text += "\n"
    
    if plan_data.get('priorities'):
        plan_text += "🎯 ПРИОРИТЕТЫ ДНЯ:\n"
        for priority in plan_data['priorities']:
            plan_text += f"• {priority}\n"
        plan_text += "\n"
    
    if plan_data.get('advice'):
        plan_text += "💡 СОВЕТЫ АССИСТЕНТА:\n"
        for advice in plan_data['advice']:
            plan_text += f"• {advice}\n"
        plan_text += "\n"
    
    if plan_data.get('motivation_quote'):
        plan_text += f"💫 МОТИВАЦИЯ: {plan_data['motivation_quote']}\n"
    
    await update.message.reply_text(plan_text)

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает персонализированный прогресс"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    if not has_sufficient_data(user_id):
        # Показываем сообщение о недостатке данных
        usage_days = get_user_usage_days(user_id)
        
        await update.message.reply_text(
            f"📊 ВАШ ПРОГРЕСС ФОРМИРУЕТСЯ!\n\n"
            f"📅 День {usage_days['current_day']} • Всего дней: {usage_days['days_since_registration']} • Серия: {usage_days['current_streak']}\n\n"
            f"Пока данных недостаточно для полной статистики.\n"
            f"Отслеживаемые показатели:\n\n"
            f"✓ Выполненные задачи: 0/∞\n"
            f"✓ Настроение: пока нет оценок\n"
            f"✓ Энергия: собираем данные\n"
            f"✓ Водный баланс: отслеживается\n"
            f"✓ Активность: мониторим с {usage_days['days_since_registration']} дней\n\n"
            f"Продолжайте работать с ботом ежедневно!\n"
            f"Уже через 3 дня появится персональная статистика."
        )
    else:
        # Получаем данные за последние 7 дней
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ Ошибка подключения к базе данных")
            return
            
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_days,
                    AVG(tasks_completed) as avg_tasks,
                    AVG(mood) as avg_mood,
                    AVG(energy) as avg_energy,
                    AVG(water_intake) as avg_water,
                    COUNT(DISTINCT progress_date) as active_days
                FROM user_progress 
                WHERE user_id = %s AND progress_date >= CURRENT_DATE - INTERVAL '7 days'
            """, (user_id,))
            
            result = cursor.fetchone()
            
            total_days = result['total_days'] or 0
            avg_tasks = result['avg_tasks'] or 0
            avg_mood = result['avg_mood'] or 0
            avg_energy = result['avg_energy'] or 0
            avg_water = result['avg_water'] or 0
            active_days = result['active_days'] or 0

            # Рассчитываем проценты и динамику
            tasks_completed = f"{int(avg_tasks * 10)}/10" if avg_tasks else "0/10"
            mood_str = f"{avg_mood:.1f}/10" if avg_mood else "0/10"
            energy_str = f"{avg_energy:.1f}/10" if avg_energy else "0/10"
            water_str = f"{avg_water:.1f} стаканов/день" if avg_water else "0 стаканов/день"
            activity_str = f"{active_days}/7 дней"

            # Динамика
            mood_dynamics = "↗ улучшается" if avg_mood and avg_mood > 6 else "→ стабильно"
            energy_dynamics = "↗ растет" if avg_energy and avg_energy > 6 else "→ стабильно"
            productivity_dynamics = "↗ растет" if avg_tasks and avg_tasks > 5 else "→ стабильно"

            # Получаем дополнительную информацию для профиля
            usage_days = get_user_usage_days(user_id)
            level_info = get_user_level_info(user_id)

            # Персональный совет
            advice = "Продолжайте в том же духе! Вы на правильном пути."
            if avg_water and avg_water < 6:
                advice = "Попробуйте увеличить потребление воды до 8 стаканов - это может повысить энергию!"
            elif avg_mood and avg_mood < 6:
                advice = "Попробуйте добавить короткие перерывы для отдыха - это улучшит настроение!"

            await update.message.reply_text(
                f"📊 ВАШ ПЕРСОНАЛЬНЫЙ ПРОГРЕСС\n\n"
                f"📅 День {usage_days['current_day']} • Всего дней: {usage_days['days_since_registration']} • Серия: {usage_days['current_streak']}\n\n"
                f"✅ Выполнено задач: {tasks_completed}\n"
                f"😊 Среднее настроение: {mood_str}\n"
                f"⚡ Уровень энергии: {energy_str}\n"
                f"💧 Вода в среднем: {water_str}\n"
                f"🏃 Активность: {activity_str}\n\n"
                f"📈 ДИНАМИКА:\n"
                f"• Настроение: {mood_dynamics}\n"
                f"• Энергия: {energy_dynamics}\n"
                f"• Продуктивность: {productivity_dynamics}\n\n"
                f"🎯 СОВЕТ: {advice}"
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения прогресса для {user_id}: {e}")
            await update.message.reply_text("❌ Ошибка при получении статистики. Попробуйте позже.")
        finally:
            conn.close()

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает профиль пользователя"""
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    # Получаем данные для профиля
    main_goal = get_user_main_goal(user_id)
    usage_days = get_user_usage_days(user_id)
    level_info = get_user_level_info(user_id)
    favorite_ritual = get_favorite_ritual(user_id)
    
    # Получаем статистику по планам
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("❌ Ошибка подключения к базе данных")
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_plans WHERE user_id = %s", 
            (user_id,)
        )
        total_plans_result = cursor.fetchone()
        total_plans = total_plans_result[0] if total_plans_result else 0

        cursor.execute(
            "SELECT COUNT(*) FROM user_plans WHERE user_id = %s AND status = 'completed'", 
            (user_id,)
        )
        completed_plans_result = cursor.fetchone()
        completed_plans = completed_plans_result[0] if completed_plans_result else 0

        # Вычисляем процент выполнения планов
        plans_percentage = (completed_plans / total_plans * 100) if total_plans > 0 else 0
        
        # Формируем профиль
        profile_text = (
            f"👤 ВАШ ПРОФИЛЬ\n\n"
            f"📅 День {usage_days['current_day']} • Всего дней: {usage_days['days_since_registration']} • Серия: {usage_days['current_streak']}\n\n"
            f"🎯 ТЕКУЩАЯ ЦЕЛЬ: {main_goal}\n"
            f"📊 ВЫПОЛНЕНО: {plans_percentage:.1f}% на пути к цели\n\n"
            f"🏆 ДОСТИЖЕНИЯ:\n"
            f"• Выполнено планов: {completed_plans} из {total_plans} ({plans_percentage:.1f}%)\n"
            f"• Максимальная регулярность: {usage_days['current_streak']} дней\n"
            f"• Любимый ритуал: {favorite_ritual}\n\n"
            f"🎮 УРОВЕНЬ: {level_info['level']}\n"
            f"⭐ ОЧКОВ: {level_info['points']} из {level_info['next_level_points']} до следующего уровня\n\n"
            f"💡 РЕКОМЕНДАЦИИ:\n"
            f"Продолжайте ежедневно отслеживать прогресс для лучших результатов!"
        )
        
        await update.message.reply_text(profile_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения профиля для {user_id}: {e}")
        await update.message.reply_text("❌ Ошибка при получении профиля. Попробуйте позже.")
    finally:
        conn.close()

async def points_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Объясняет систему очков"""
    help_text = (
        "🎮 СИСТЕМА ОЧКОВ И УРОВНЕЙ:\n\n"
        "📊 Как начисляются очки:\n"
        "• +10 очков за каждый активный день\n"
        "• +2 очка за каждую выполненную задачу\n"
        "• +5 очков за заполнение дневника прогресса\n"
        "• +15 очков за серию из 7 дней подряд\n\n"
        "🏆 Уровни:\n"
        "• Новичок (0 очков)\n"
        "• Ученик (50 очков)\n"
        "• Опытный (100 очков)\n"
        "• Профессионал (200 очков)\n"
        "• Мастер (500 очков)\n\n"
        "💡 Советы:\n"
        "• Регулярность важнее количества!\n"
        "• Даже маленькие шаги приносят очки\n"
        "• Не пропускайте дни для сохранения серии"
    )
    await update.message.reply_text(help_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает справку по командам"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    help_text = (
        "ℹ️ Справка по командам:\n\n"
        
        "🔹 Основные команды:\n"
        "/start - Начать работу с ботом\n"
        "/plan - План на сегодня\n"
        "/progress - Статистика прогресса\n"
        "/profile - Ваш профиль\n"
        "/points_info - Объяснение системы очков\n"
        "/help - Эта справка\n\n"
        
        "🔹 Команды для отслеживания:\n"
        "/done <1-4> - Отметить задачу выполненной\n"
        "/mood <1-10> - Оценить настроение\n"
        "/energy <1-10> - Оценить уровень энергии\n"
        "/water <стаканы> - Отслеживание воды\n\n"
        
        "🔹 Напоминания:\n"
        "/remind_me <время> <текст> - Разовое напоминание\n"
        "/regular_remind <время> <дни> <текст> - Регулярное напоминание\n"
        "/my_reminders - Показать активные напоминания\n"
        "/delete_remind <id> - Удалить напоминание\n\n"
        
        "💡 Также вы можете писать напоминания естественным языком:\n"
        "'напомни мне в 20:00 постирать купальник'\n"
        "'напоминай каждый день в 8:00 делать зарядку'\n"
        "'напомни в 11 вечера принять лекарство'\n\n"
        
        "💬 Просто напишите сообщение, чтобы связаться с ассистентом!"
    )
    
    await update.message.reply_text(help_text)

# ========== СИСТЕМА НАПОМИНАНИЙ - КОМАНДЫ ==========

async def remind_me_command(update: Update, context: CallbackContext):
    """Установка разового напоминания"""
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⏰ Установка разового напоминания:\n\n"
            "Формат:\n"
            "/remind_me <время> <текст>\n\n"
            "Примеры:\n"
            "/remind_me 20:30 принять лекарство\n"
            "/remind_me 9 утра позвонить врачу\n"
            "/remind_me 11 вечера постирать купальник\n"
            "/remind_me вечером вынести мусор\n\n"
            "⏱️ Время можно указывать в разных форматах:\n"
            "• 20:30, 09:00\n"
            "• 9 утра, 7 вечера, 11 ночи\n"
            "• 11 часов вечера, 3 часа дня\n"
            "• утром, днем, вечером, ночью"
        )
        return
    
    time_str = context.args[0]
    reminder_text = " ".join(context.args[1:])
    
    logger.info(f"🕒 Пользователь {user_id} устанавливает напоминание: {time_str} - {reminder_text}")
    
    # Парсим время
    time_data = parse_time_input(time_str)
    
    if not time_data:
        await update.message.reply_text(
            "❌ Не удалось распознать время.\n"
            "Пожалуйста, укажите время в одном из форматов:\n"
            "• 20:30 или 09:00\n"
            "• 9 утра или 7 вечера\n"
            "• 11 часов вечера\n"
            "• утром, днем, вечером"
        )
        return
    
    reminder_data = {
        'type': 'once',
        'time': time_data['time'],
        'text': reminder_text,
        'days': []
    }
    
    success = add_reminder_to_db(user_id, reminder_data)
    
    if success:
        await update.message.reply_text(
            f"✅ Напоминание установлено на {time_data['time']}:\n"
            f"📝 {reminder_text}\n\n"
            f"Я пришлю уведомление в указанное время!"
        )
    else:
        await update.message.reply_text("❌ Не удалось установить напоминание")

async def regular_remind_command(update: Update, context: CallbackContext):
    """Установка регулярного напоминания"""
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "🔄 Установка регулярного напоминания:\n\n"
            "Формат:\n"
            "/regular_remind <время> <дни> <текст>\n\n"
            "Примеры:\n"
            "/regular_remind 08:00 пн,ср,пт утренняя зарядка\n"
            "/regular_remind 09:00 ежедневно принимать витамины\n"
            "/regular_remind 20:00 вт,чт йога\n\n"
            "📅 Дни недели:\n"
            "пн, вт, ср, чт, пт, сб, вс\n"
            "или 'ежедневно' для всех дней"
        )
        return
    
    time_str = context.args[0]
    days_str = context.args[1]
    reminder_text = " ".join(context.args[2:])
    
    # Парсим время
    time_data = parse_time_input(time_str)
    
    if not time_data:
        await update.message.reply_text(
            "❌ Не удалось распознать время.\n"
            "Пожалуйста, укажите время в формате ЧЧ:MM"
        )
        return
    
    # Парсим дни недели
    days_map = {
        'пн': 'пн', 'вт': 'вт', 'ср': 'ср', 'чт': 'чт',
        'пт': 'пт', 'сб': 'сб', 'вс': 'вс',
        'ежедневно': ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'],
        'понедельник': 'пн', 'вторник': 'вт', 'среда': 'ср', 'четверг': 'чт',
        'пятница': 'пт', 'суббота': 'сб', 'воскресенье': 'вс'
    }
    
    if days_str.lower() == 'ежедневно':
        days = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    else:
        days = []
        for day_part in days_str.split(','):
            day_clean = day_part.strip().lower()
            if day_clean in days_map:
                if isinstance(days_map[day_clean], list):
                    days.extend(days_map[day_clean])
                else:
                    days.append(days_map[day_clean])
    
    if not days:
        await update.message.reply_text(
            "❌ Не удалось распознать дни недели.\n"
            "Укажите дни в формате: пн,ср,пт или 'ежедневно'"
        )
        return
    
    # Убираем дубликаты
    days = list(set(days))
    
    reminder_data = {
        'type': 'regular',
        'time': time_data['time'],
        'text': reminder_text,
        'days': days
    }
    
    success = add_reminder_to_db(user_id, reminder_data)
    
    if success:
        days_display = ', '.join(days) if days != ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'] else 'ежедневно'
        await update.message.reply_text(
            f"✅ Регулярное напоминание установлено:\n"
            f"⏰ {time_data['time']} {days_display}\n"
            f"📝 {reminder_text}\n\n"
            f"Я буду напоминать вам по установленному расписанию!"
        )
    else:
        await update.message.reply_text("❌ Не удалось установить напоминание")

async def my_reminders_command(update: Update, context: CallbackContext):
    """Показывает активные напоминания"""
    user_id = update.effective_user.id
    
    reminders = get_user_reminders(user_id)
    
    if not reminders:
        await update.message.reply_text(
            "📭 У вас нет активных напоминаний\n\n"
            "💡 Чтобы установить напоминание:\n"
            "• Используйте команды /remind_me или /regular_remind\n"
            "• Или напишите естественным языком:\n"
            "  'напомни мне в 20:00 постирать купальник'\n"
            "  'напоминай каждый день в 8:00 делать зарядку'"
        )
        return
    
    reminders_text = "📋 Ваши активные напоминания:\n\n"
    
    for i, reminder in enumerate(reminders, 1):
        type_icon = "🔄" if reminder['type'] == 'regular' else "⏰"
        days_info = f" ({reminder['days']})" if reminder['type'] == 'regular' else ""
        
        reminders_text += f"{i}. {type_icon} {reminder['time']}{days_info}\n"
        reminders_text += f"   📝 {reminder['text']}\n"
        reminders_text += f"   🆔 ID: {reminder['id']}\n\n"
    
    reminders_text += "❌ Чтобы удалить напоминание:\n/delete_remind <ID>"
    
    await update.message.reply_text(reminders_text)

async def delete_remind_command(update: Update, context: CallbackContext):
    """Удаляет напоминание"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите ID напоминания для удаления:\n"
            "/delete_remind <ID>\n\n"
            "📋 Посмотреть ID ваших напоминаний:\n"
            "/my_reminders"
        )
        return
    
    try:
        reminder_id = int(context.args[0])
        success = delete_reminder_from_db(reminder_id)
        
        if success:
            await update.message.reply_text(
                f"✅ Напоминание {reminder_id} удалено!\n\n"
                f"📋 Текущий список напоминаний:\n"
                f"/my_reminders"
            )
        else:
            await update.message.reply_text(
                "❌ Не удалось удалить напоминание.\n"
                "Проверьте правильность ID."
            )
        
    except ValueError:
        await update.message.reply_text("❌ ID напоминания должен быть числом")

# ========== АДМИН СТАТИСТИКА ==========

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика для администратора"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("❌ Ошибка подключения к базе данных")
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clients")
        total_users_result = cursor.fetchone()
        total_users = total_users_result[0] if total_users_result else 0
        
        cursor.execute(
            "SELECT COUNT(*) FROM clients WHERE DATE(last_activity) = CURRENT_DATE"
        )
        active_today_result = cursor.fetchone()
        active_today = active_today_result[0] if active_today_result else 0
        
        cursor.execute(
            "SELECT COUNT(*) FROM messages WHERE direction = 'incoming'"
        )
        total_messages_result = cursor.fetchone()
        total_messages = total_messages_result[0] if total_messages_result else 0
        
        cursor.execute("SELECT COUNT(*) FROM questionnaire_answers")
        total_answers_result = cursor.fetchone()
        total_answers = total_answers_result[0] if total_answers_result else 0
        
        cursor.execute("SELECT COUNT(*) FROM user_plans")
        total_plans_result = cursor.fetchone()
        total_plans = total_plans_result[0] if total_plans_result else 0
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        total_users = active_today = total_messages = total_answers = total_plans = 0
    finally:
        conn.close()
    
    stats_text = f"📊 Статистика бота:\n\n"
    stats_text += f"👥 Всего пользователей: {total_users}\n"
    stats_text += f"🟢 Активных сегодня: {active_today}\n"
    stats_text += f"📨 Всего сообщений: {total_messages}\n"
    stats_text += f"📝 Ответов в анкетах: {total_answers}\n"
    stats_text += f"📋 Индивидуальных планов: {total_plans}\n\n"
    
    if sheets_manager.sheet:
        stats_text += f"📊 Google Sheets: ✅ подключен\n"
    else:
        stats_text += f"📊 Google Sheets: ❌ не доступен\n"
    
    await update.message.reply_text(stats_text)

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список пользователей"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("❌ Ошибка подключения к базе данных")
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, username, first_name, last_activity FROM clients ORDER BY last_activity DESC LIMIT 20"
        )
        users = cursor.fetchall()
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка пользователей: {e}")
        users = []
    finally:
        conn.close()
    
    if not users:
        await update.message.reply_text("📭 Пользователей не найдено.")
        return
    
    users_text = "👥 ПОСЛЕДНИЕ ПОЛЬЗОВАТЕЛИ:\n\n"
    
    for user in users:
        user_id = user['user_id']
        username = user['username']
        first_name = user['first_name']
        last_activity = user['last_activity']
        
        username_display = f"@{username}" if username else "без username"
        users_text += f"🆔 {user_id} - {first_name} ({username_display})\n"
        users_text += f"   📅 Активен: {last_activity}\n\n"
    
    users_text += "💡 Для добавления плана используйте: /add_plan"
    
    await update.message.reply_text(users_text)

# ========== ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ ==========

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
        await handle_reminder_nlp(update, context)
        return
    
    # Обработка нажатий на кнопки
    button_handlers = {
        '📊 прогресс': progress_command,
        '👤 профиль': profile_command,
        '📋 план на сегодня': plan_command,
        '🔔 мои напоминания': my_reminders_command,
        'ℹ️ помощь': help_command,
        '🎮 очки опыта': points_info_command,
        '📊 Прогресс': progress_command,
        '👤 Профиль': profile_command, 
        '📋 План на сегодня': plan_command,
        '🔔 Мои напоминания': my_reminders_command,
        'ℹ️ Помощь': help_command,
        '🎮 Очки опыта': points_info_command
    }
    
    if message_text.lower() in [key.lower() for key in button_handlers.keys()]:
        # Найдем правильный регистр для вызова функции
        for key, handler in button_handlers.items():
            if key.lower() == message_text.lower():
                await handler(update, context)
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

# ========== ВОССТАНОВЛЕНИЕ ПРОДОЛЖЕНИЯ АНКЕТЫ ==========

async def handle_continue_choice(update: Update, context: CallbackContext) -> int:
    """Обрабатывает выбор продолжения анкеты"""
    choice = update.message.text
    questionnaire_state = context.user_data.get('questionnaire_state', {})
    
    if choice == '✅ Продолжить анкету':
        # Восстанавливаем данные из базы
        context.user_data['current_question'] = questionnaire_state['current_question']
        context.user_data['answers'] = questionnaire_state['answers']
        
        await update.message.reply_text(
            f"🔄 Продолжаем анкету с вопроса {questionnaire_state['current_question'] + 1}...",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Отправляем текущий вопрос
        await update.message.reply_text(QUESTIONS[questionnaire_state['current_question']])
        return FIRST_QUESTION
        
    elif choice == '🔄 Начать заново':
        # Очищаем старые ответы
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM questionnaire_answers WHERE user_id = %s", 
                    (update.effective_user.id,)
                )
                conn.commit()
            except Exception as e:
                logger.error(f"❌ Ошибка удаления ответов: {e}")
            finally:
                conn.close()
        
        # Начинаем заново
        context.user_data['current_question'] = 0
        context.user_data['answers'] = {}
        
        await update.message.reply_text(
            "🔄 Начинаем анкету заново...",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await update.message.reply_text(QUESTIONS[0])
        return FIRST_QUESTION
        
    else:
        await update.message.reply_text("❌ Операция отменена.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

# ========== АВТОМАТИЧЕСКИЕ СООБЩЕНИЯ ==========

async def send_morning_plan(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет утренний план пользователям"""
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, first_name, username FROM clients WHERE status = 'active'"
        )
        users = cursor.fetchall()
        
        for user in users:
            user_id = user['user_id']
            first_name = user['first_name']
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Получаем план из Google Sheets
            plan_data = get_daily_plan_from_sheets(user_id, today)
            
            if plan_data:
                # Формируем сообщение
                message = f"🌅 Доброе утро, {first_name}!\n\n"
                message += "📋 Ваш план на сегодня:\n\n"
                
                if plan_data.get('strategic_tasks'):
                    message += "🎯 СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
                    for task in plan_data['strategic_tasks']:
                        message += f"• {task}\n"
                    message += "\n"
                
                if plan_data.get('critical_tasks'):
                    message += "⚠️ КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
                    for task in plan_data['critical_tasks']:
                        message += f"• {task}\n"
                    message += "\n"
                
                if plan_data.get('priorities'):
                    message += "🎯 ПРИОРИТЕТЫ ДНЯ:\n"
                    for priority in plan_data['priorities']:
                        message += f"• {priority}\n"
                    message += "\n"
                
                if plan_data.get('advice'):
                    message += "💡 СОВЕТЫ АССИСТЕНТА:\n"
                    for advice in plan_data['advice']:
                        message += f"• {advice}\n"
                    message += "\n"
                
                if plan_data.get('motivation_quote'):
                    message += f"💫 МОТИВАЦИЯ: {plan_data['motivation_quote']}\n\n"
                
                message += "💪 Удачи в достижении ваших целей!"
                
                try:
                    await context.bot.send_message(chat_id=user_id, text=message)
                    logger.info(f"✅ Утренний план отправлен пользователю {user_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки утреннего плана пользователю {user_id}: {e}")
                    
    except Exception as e:
        logger.error(f"❌ Ошибка в send_morning_plan: {e}")
    finally:
        conn.close()

async def send_evening_survey(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет вечерний опрос пользователям"""
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, first_name FROM clients WHERE status = 'active'"
        )
        users = cursor.fetchall()
        
        for user in users:
            user_id = user['user_id']
            first_name = user['first_name']
            
            message = (
                f"🌙 Добрый вечер, {first_name}!\n\n"
                "📊 Как прошел ваш день?\n\n"
                "1. 🎯 Выполнили стратегические задачи? (да/нет/частично)\n"
                "2. 🌅 Выполнили утренние ритуалы? (да/нет/частично)\n"
                "3. 🌙 Выполнили вечерние ритуалы? (да/нет/частично)\n"
                "4. 😊 Настроение от 1 до 10?\n"
                "5. ⚡ Энергия от 1 до 10?\n"
                "6. 🎯 Уровень фокуса от 1 до 10?\n"
                "7. 🔥 Уровень мотивации от 1 до 10?\n"
                "8. 🏆 Ключевые достижения сегодня?\n"
                "9. 🚧 Были проблемы или препятствия?\n"
                "10. 🌟 Что получилось хорошо?\n"
                "11. 📈 Что можно улучшить?\n"
                "12. 🔄 Корректировки на завтра?\n"
                "13. 💧 Сколько воды выпили? (стаканов)\n\n"
            )
            
            try:
                await context.bot.send_message(chat_id=user_id, text=message)
                logger.info(f"✅ Вечерний опрос отправлен пользователю {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки вечернего опроса пользователю {user_id}: {e}")
                
    except Exception as e:
        logger.error(f"❌ Ошибка в send_evening_survey: {e}")
    finally:
        conn.close()

# ========== ОБРАБОТЧИК ЕСТЕСТВЕННЫХ НАПОМИНАНИЙ ==========

async def handle_reminder_nlp(update: Update, context: CallbackContext):
    """Обрабатывает естественные запросы на напоминания"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    logger.info(f"🔍 Обработка естественного запроса: {message_text}")
    
    # Проверяем лимит напоминаний (максимум 20 на пользователя)
    reminders = get_user_reminders(user_id)
    if len(reminders) >= 20:
        await update.message.reply_text(
            "❌ Достигнут лимит напоминаний (20).\n"
            "Удалите старые напоминания: /my_reminders"
        )
        return
    
    # Парсим текст напоминания
    reminder_data = parse_reminder_text(message_text)
    
    if not reminder_data:
        await update.message.reply_text(
            "❌ Не понял формат напоминания.\n\n"
            "💡 Попробуйте так:\n"
            "'напомни мне в 20:00 постирать купальник'\n"
            "'напоминай каждый день в 8:00 делать зарядку'\n"
            "'напомни завтра утром позвонить врачу'\n"
            "'напомни в 11 вечера принять лекарство'"
        )
        return
    
    # Добавляем напоминание в базу
    success = add_reminder_to_db(user_id, reminder_data)
    
    if success:
        if reminder_data['type'] == 'regular':
            days_display = ', '.join(reminder_data['days']) if reminder_data['days'] != ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'] else 'ежедневно'
            response = (
                f"✅ Регулярное напоминание установлено!\n"
                f"⏰ {reminder_data['time']} {days_display}\n"
                f"📝 {reminder_data['text']}\n\n"
                f"Я буду напоминать вам по установленному расписанию!"
            )
        else:
            response = (
                f"✅ Напоминание установлено!\n"
                f"⏰ {reminder_data['time']}\n"
                f"📝 {reminder_data['text']}\n\n"
                f"Я пришлю уведомление в указанное время!"
            )
        
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("❌ Не удалось установить напоминание")

# ========== ОБРАБОТЧИК ОШИБОК ==========

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

async def cancel(update: Update, context: CallbackContext) -> int:
    """Отменяет текущий диалог"""
    await update.message.reply_text(
        '❌ Операция отменена.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# ========== INLINE КНОПКИ ==========

async def button_callback(update: Update, context: CallbackContext):
    """Обработчик нажатий на inline-кнопки"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data.startswith('reply_'):
        user_id = callback_data.replace('reply_', '')
        await query.edit_message_text(f"✍️ Ответ пользователю {user_id}. Используйте /send {user_id} <сообщение>")
    
    elif callback_data.startswith('view_questionnaire_'):
        user_id = callback_data.replace('view_questionnaire_', '')
        await query.edit_message_text(f"📋 Просмотр анкеты пользователя {user_id}. Функция в разработке.")
    
    elif callback_data.startswith('stats_'):
        user_id = callback_data.replace('stats_', '')
        await query.edit_message_text(f"📊 Статистика пользователя {user_id}. Функция в разработке.")
    
    elif callback_data.startswith('create_plan_'):
        user_id = callback_data.replace('create_plan_', '')
        await query.edit_message_text(f"📋 Создание плана для пользователя {user_id}. Используйте /add_plan")

# ========== ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА ==========

def main():
    """Основная функция запуска бота для Render"""
    try:
        application = Application.builder().token(TOKEN).build()
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