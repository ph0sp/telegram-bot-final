import os
import logging
import sqlite3
import asyncio
import time
import json
import re
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, Optional, Any, List

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

if not TOKEN:
    logger.error("❌ Токен бота не найден! Установите BOT_TOKEN")
    exit(1)

if not YOUR_CHAT_ID:
    logger.error("❌ Chat ID не найден! Установите YOUR_CHAT_ID")
    exit(1)

# Состояния диалога
GENDER, FIRST_QUESTION = range(2)

# Константы для индексов планов
PLAN_FIELDS = {
    'id': 0, 'user_id': 1, 'plan_date': 2, 'morning_ritual1': 4, 'morning_ritual2': 5,
    'task1': 6, 'task2': 7, 'task3': 8, 'task4': 9, 'lunch_break': 10,
    'evening_ritual1': 11, 'evening_ritual2': 12, 'advice': 13, 'sleep_time': 14,
    'water_goal': 15, 'activity_goal': 16
}

# Полный список вопросов
QUESTIONS = [
    "Готовы начать?",
    "Давайте начнем!\nПоследовательно отвечайте на вопросы в свободной форме, как вам удобно.\n\nНачнем с самого главного\n\nБлок 1: Цель и главный фокус\n\nКакая ваша главная цель на ближайший месяц? (например, запуск проекта, подготовка к экзамену, улучшение физической формы, обучение новому навыку)\n\nЖду вашего ответа, чтобы двигаться дальше.",
    "Прекрасная цель! Это комплексная задача, где важны и стратегия, и ежедневная энергия, чтобы ее реализовать.\n\nРасскажите почему для вас важна эта цель? (Это поможет понять мотивацию)",
    "Сколько часов в день вы готовы посвящать работе над этой целью? (Важно оценить ресурсы честно)",
    "Есть ли у вас дедлайн или ключевые точки контроля на этом пути?\n\nКак только вы ответите, мы перейдем к следующему блоку вопросов, чтобы понять текущий ритм жизни и выстроить план, который будет работать именно для вас.",
    "Отлично, основа понятна. Теперь давайте перейдем к вашему текущему ритму жизни, чтобы вписать эту цель в ваш день комфортно и без выгорания. \n\nБлок 2: Текущий распорядок и ресурсы\n\nВо сколько вы обычно просыпаетесь и ложитесь спать?",
    "Опишите кратко, как обычно выглядит ваш текущий день (работа, учеба, обязанности)?",
    "В какое время суток вы чувствуете себя наиболее энергичным и продуктивным? (утро, день, вечер)",
    "Сколько часов в день вы обычно тратите на соцсети, просмотр сериалов и другие не основные занятия?",
    "Как часто вы чувствуете себя перегруженным или близким к выгоранию?\n\nКак только вы ответите на эти вопросы, мы перейдем к следующим блокам (спорт, питание, отдых), чтобы сделать план по-настоящему сбалансированным. ",
    "Блок 3: Физическая активность и спорт\n\nКакой у вас текущий уровень физической активности? (сидячий, легкие прогулки, тренировки 1-2 раза в неделю, регулярные тренировки)",
    "Каким видом спорта или физической активности вам нравится заниматься/вы бы хотели заняться? (бег, йога, плавание, тренажерный зал, домашние тренировки)",
    "Сколько дней в неделю и сколько времени вы готовы выделять на спорт? (Например, 3 раза по 45 минут)",
    "Есть ли у вас ограничения по здоровью, которые нужно учитывать при планировании нагрузки?",
    "Блок 4: Питание и вода\n\nКак обычно выглядит ваш режим питания? (полноценные приемы пищи, перекусы на бегу, пропуск завтрака/ужина)",
    "Сколько стаканов воды вы примерно выпиваете за день?",
    "Хотели бы вы что-то изменить в своем питании? (например, есть больше овощей, готовить заранее, не пропускать обед, пить больше воды)",
    "Сколько времени вы обычно выделяете на приготовление еды?",
    "Хорошо, переходим к следующему блоку.\n\nБлок 5: Отдых и восстановление (критически важно во избежание выгорания)\n\nЧто помогает вам по-настоящему расслабиться и восстановить силы? (чтение, прогулка, хобби, музыка, медитация, общение с близких, полное ничегонеделание)",
    "Как часто вам удается выделять время на эти занятия?",
    "Планируете ли вы выходные дни или микро-перерывы в течение дня?",
    "Важно ли для вас время на общение с семьей/друзьями? Сколько раз в неделю вы бы хотели это видеть в своем плане?",
    "Блок 6: Ритуалы для здоровья и самочувствия\n\nИсходя из вашего режима, предлагаю вам на выбор несколько идей. Что из этого вам откликается?\n\nУтренние ритуалы (на выбор):\n* Стакан теплой воды с лимоном: для запуска метаболизма.\n* Несложная зарядка/растяжка (5-15 мин): чтобы размяться и проснуться.\n* Медитация или ведение дневника (5-10 мин): для настройки на день.\n* Контрастный душ: для бодрости.\n* Полезный завтрак без телефона: осознанное начало дня.\n\nВечерние ритуалы (на выбор):\n* Выключение гаджетов за 1 час до сна: для улучшения качества сна.\n* Ведение дневника благодарности или запись 3х хороших событий дня.\n* Чтение книги (не с экрана).\n* Легкая растяжка или йога перед сном: для расслабления мышц.\n* Планирование главных задач на следующий день (3 дела): чтобы выгрузить мысли и спать спокойно.\n* Ароматерапия или спокойная музыка.\n\nКакие из этих утренних ритуалы вам были бы интересны?\n\nКакие вечерние ритуалы вы бы хотели внедрить?\n\nЕсть ли ваши личные ритуалы, которые вы хотели бы сохранить?",
    "Отлично, остался заключительный блок.\n\nБлок 7: Финальные Уточнения и Гибкость\n\nКакой ваш идеальный баланс между продуктивностью и отдыхом? (например, 70/30, 60/40)",
    "Что чаще всего мешает вам следовать планам? (неожиданные дела, лень, отсутствие мотивации)",
    "Как нам лучше всего предусмотреть дни непредвиденных обстоятельств или дни с низкой энергией? (Например, запланировать 1-2 таких дня в неделю)"
]

# ========== БАЗА ДАННЫХ ==========

def init_db():
    """Инициализация базы данных SQLite"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    # Таблица клиентов
    c.execute('''CREATE TABLE IF NOT EXISTS clients
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT,
                  first_name TEXT,
                  last_name TEXT,
                  status TEXT DEFAULT 'active',
                  registration_date TEXT,
                  last_activity TEXT)''')
    
    # Таблица ответов на анкету
    c.execute('''CREATE TABLE IF NOT EXISTS questionnaire_answers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  question_number INTEGER,
                  question_text TEXT,
                  answer_text TEXT,
                  answer_date TEXT,
                  FOREIGN KEY (user_id) REFERENCES clients (user_id))''')
    
    # Таблица планов
    c.execute('''CREATE TABLE IF NOT EXISTS user_plans
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  plan_date TEXT,
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
                  created_date TEXT,
                  FOREIGN KEY (user_id) REFERENCES clients (user_id))''')
    
    # Таблица прогресса
    c.execute('''CREATE TABLE IF NOT EXISTS user_progress
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  progress_date TEXT,
                  tasks_completed INTEGER,
                  mood INTEGER,
                  energy INTEGER,
                  sleep_quality INTEGER,
                  water_intake INTEGER,
                  activity_done TEXT,
                  user_comment TEXT,
                  day_rating INTEGER,
                  challenges TEXT,
                  FOREIGN KEY (user_id) REFERENCES clients (user_id))''')
    
    # Таблица сообщений
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  message_text TEXT,
                  message_date TEXT,
                  direction TEXT)''')
    
    # Таблица напоминаний (новая структура)
    c.execute('''CREATE TABLE IF NOT EXISTS user_reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  reminder_text TEXT,
                  reminder_time TEXT,
                  days_of_week TEXT,
                  reminder_type TEXT,
                  is_active BOOLEAN DEFAULT 1,
                  created_date TEXT,
                  FOREIGN KEY (user_id) REFERENCES clients (user_id))''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

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
                "цели_развития", "главная_цель", "особые_примечания",
                "дата_последней_активности", "статус",
                "текущий_уровень", "очки_опыта", "текущая_серия_активности",
                "максимальная_серия_активности", "любимый_ритуал", 
                "дата_последнего_прогресса", "ближайшая_цель"
            ])
        
        try:
            sheet.worksheet("индивидуальные_планы_месяц")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="индивидуальные_планы_месяц", rows=1000, cols=40)
            # Базовые колонки
            headers = ["id_клиента", "telegram_username", "имя", "месяц"]
            # Добавляем колонки для дат (1-31)
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
        
        logger.info("✅ Google Sheets инициализирован с новой структураой")
        return sheet
    
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Google Sheets: {e}")
        return None

google_sheet = init_google_sheets()

# ========== НОВЫЕ ФУНКЦИИ GOOGLE SHEETS ==========

def save_client_to_sheets(user_data: Dict[str, Any]):
    """Сохраняет клиента в лист 'клиенты_детали'"""
    if not google_sheet:
        logger.error("❌ Google Sheets не доступен - google_sheet is None")
        return False
    
    try:
        logger.info(f"🔄 Попытка сохранить данные пользователя {user_data['user_id']} в Google Sheets")
        worksheet = google_sheet.worksheet("клиенты_детали")
        logger.info("✅ Лист 'клиенты_детали' найден")
        
        # Ищем существующего клиента
        try:
            cell = worksheet.find(str(user_data['user_id']))
            row = cell.row
            # Обновляем существующую запись
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
            logger.info(f"✅ Данные пользователя {user_data['user_id']} обновлены в Google Sheets")
        except Exception as e:
            logger.info(f"👤 Пользователь {user_data['user_id']} не найден, создаем новую запись: {e}")
            # Добавляем нового клиента
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
            logger.info(f"✅ Новый пользователь {user_data['user_id']} добавлен в Google Sheets")
        
        logger.info(f"✅ Клиент {user_data['user_id']} сохранен в Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения клиента в Google Sheets: {e}")
        return False

def save_daily_report_to_sheets(user_id: int, report_data: Dict[str, Any]):
    """Сохраняет ежедневный отчет в Google Sheets"""
    if not google_sheet:
        logger.error("❌ Google Sheets не доступен")
        return False
    
    try:
        worksheet = google_sheet.worksheet("ежедневные_отчеты")
        
        # Получаем информацию о пользователе
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT username, first_name FROM clients WHERE user_id = ?", (user_id,))
        user_info = c.fetchone()
        conn.close()
        
        username = user_info[0] if user_info else ""
        first_name = user_info[1] if user_info else ""
        
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
        
        logger.info(f"✅ Ежедневный отчет {user_id} сохранен в Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения отчета: {e}")
        return False

def get_daily_plan_from_sheets(user_id: int, date: str) -> Dict[str, Any]:
    """Получает план на день из Google Sheets"""
    if not google_sheet:
        return {}
    
    try:
        worksheet = google_sheet.worksheet("индивидуальные_планы_месяц")
        
        # Ищем пользователя
        try:
            cell = worksheet.find(str(user_id))
            row = cell.row
        except Exception:
            return {}
        
        # Получаем все данные строки
        row_data = worksheet.row_values(row)
        
        # Определяем колонку для нужной даты
        day = datetime.strptime(date, "%Y-%m-%d").day
        date_column_index = 4 + day - 1  # 4 базовые колонки + день месяца
        
        if date_column_index >= len(row_data):
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
        elif 'МОТИВАЦИОННАЯ ЦИТАТА:' in line:
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

# ========== ОБНОВЛЕННЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def save_user_info(user_id: int, username: str, first_name: str, last_name: Optional[str] = None):
    """Сохраняет информацию о пользователе в базу данных и Google Sheets"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT OR REPLACE INTO clients 
                 (user_id, username, first_name, last_name, status, registration_date, last_activity) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (user_id, username, first_name, last_name, 'active', registration_date, registration_date))
    conn.commit()
    conn.close()
    logger.info(f"✅ Информация о пользователе {user_id} сохранена в БД")
    
    # Сохраняем в Google Sheets
    user_data = {
        'user_id': user_id,
        'telegram_username': username,
        'first_name': first_name,
        'last_name': last_name,
        'start_date': registration_date,
        'last_activity': registration_date,
        'текущий_уровень': 'Новичок',
        'очки_опыта': '0',
        'текущая_серия_активности': '0',
        'максимальная_серия_активности': '0',
        'любимый_ритуал': '',
        'дата_последнего_прогресса': datetime.now().strftime("%Y-%m-%d"),
        'ближайшая_цель': 'Заполнить анкету'
    }
    success = save_client_to_sheets(user_data)
    if success:
        logger.info(f"✅ Данные пользователя {user_id} сохранены в Google Sheets")
    else:
        logger.error(f"❌ Ошибка сохранения данных пользователя {user_id} в Google Sheets")

def update_user_activity(user_id: int):
    """Обновляет время последней активности пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    last_activity = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''UPDATE clients SET last_activity = ? WHERE user_id = ?''',
              (last_activity, user_id))
    conn.commit()
    conn.close()

def check_user_registered(user_id: int) -> bool:
    """Проверяет зарегистрирован ли пользователь"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM clients WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def save_questionnaire_answer(user_id: int, question_number: int, question_text: str, answer_text: str):
    """Сохраняет ответ на вопрос анкеты"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    answer_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT INTO questionnaire_answers 
                 (user_id, question_number, question_text, answer_text, answer_date) 
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id, question_number, question_text, answer_text, answer_date))
    conn.commit()
    conn.close()

def save_message(user_id: int, message_text: str, direction: str):
    """Сохраняет сообщение в базу данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    message_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT INTO messages 
                 (user_id, message_text, message_date, direction) 
                 VALUES (?, ?, ?, ?)''',
              (user_id, message_text, message_date, direction))
    conn.commit()
    conn.close()

def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Возвращает статистику пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM messages WHERE user_id = ? AND direction = 'incoming'", (user_id,))
    messages_count = c.fetchone()[0]
    
    c.execute("SELECT registration_date FROM clients WHERE user_id = ?", (user_id,))
    reg_date_result = c.fetchone()
    reg_date = reg_date_result[0] if reg_date_result else "Неизвестно"
    
    conn.close()
    
    return {
        'messages_count': messages_count,
        'registration_date': reg_date
    }

def save_user_plan_to_db(user_id: int, plan_data: Dict[str, Any]):
    """Сохраняет план пользователя в базу данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    created_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT INTO user_plans 
                 (user_id, plan_date, morning_ritual1, morning_ritual2, task1, task2, task3, task4, 
                  lunch_break, evening_ritual1, evening_ritual2, advice, sleep_time, water_goal, 
                  activity_goal, created_date) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (user_id, plan_data.get('plan_date'), plan_data.get('morning_ritual1'), 
               plan_data.get('morning_ritual2'), plan_data.get('task1'), plan_data.get('task2'),
               plan_data.get('task3'), plan_data.get('task4'), plan_data.get('lunch_break'),
               plan_data.get('evening_ritual1'), plan_data.get('evening_ritual2'), 
               plan_data.get('advice'), plan_data.get('sleep_time'), plan_data.get('water_goal'),
               plan_data.get('activity_goal'), created_date))
    conn.commit()
    conn.close()
    logger.info(f"✅ План сохранен в БД для пользователя {user_id}")

def get_user_plan_from_db(user_id: int):
    """Получает текущий план пользователя из базы данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute('''SELECT * FROM user_plans 
                 WHERE user_id = ? AND status = 'active' 
                 ORDER BY created_date DESC LIMIT 1''', (user_id,))
    plan = c.fetchone()
    conn.close()
    
    return plan

def save_progress_to_db(user_id: int, progress_data: Dict[str, Any]):
    """Сохраняет прогресс пользователя в базу данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    progress_date = datetime.now().strftime("%Y-%m-%d")
    
    c.execute('''INSERT INTO user_progress 
                 (user_id, progress_date, tasks_completed, mood, energy, sleep_quality, 
                  water_intake, activity_done, user_comment, day_rating, challenges) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (user_id, progress_date, progress_data.get('tasks_completed'), 
               progress_data.get('mood'), progress_data.get('energy'), 
               progress_data.get('sleep_quality'), progress_data.get('water_intake'),
               progress_data.get('activity_done'), progress_data.get('user_comment'),
               progress_data.get('day_rating'), progress_data.get('challenges')))
    conn.commit()
    conn.close()
    logger.info(f"✅ Прогресс сохранен в БД для пользователя {user_id}")

# ========== НОВЫЕ ФУНКЦИИ ДЛЯ ПРОВЕРКИ ДАННЫХ ==========

def has_sufficient_data(user_id: int) -> bool:
    """Проверяет есть ли достаточно данных для статистики (минимум 3 дня)"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count >= 3

def get_user_activity_streak(user_id: int) -> int:
    """Возвращает текущую серию активных дней подряд"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    # Получаем все даты активности пользователя
    c.execute("SELECT DISTINCT progress_date FROM user_progress WHERE user_id = ? ORDER BY progress_date DESC", (user_id,))
    dates = [datetime.strptime(row[0], "%Y-%m-%d").date() for row in c.fetchall()]
    conn.close()
    
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

def get_user_main_goal(user_id: int) -> str:
    """Получает главную цель пользователя из анкеты"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT answer_text FROM questionnaire_answers WHERE user_id = ? AND question_number = 1", (user_id,))
    result = c.fetchone()
    conn.close()
    
    return result[0] if result else "Цель не установлена"

def get_user_level_info(user_id: int) -> Dict[str, Any]:
    """Возвращает информацию об уровне пользователя"""
    # Базовая реализация системы уровней
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    # Считаем количество дней активности
    c.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = ?", (user_id,))
    active_days = c.fetchone()[0] or 0
    
    # Считаем выполненные задачи
    c.execute("SELECT SUM(tasks_completed) FROM user_progress WHERE user_id = ?", (user_id,))
    total_tasks = c.fetchone()[0] or 0
    
    conn.close()
    
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

def get_favorite_ritual(user_id: int) -> str:
    """Определяет любимый ритуал пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    # Получаем ответы о ритуалах из анкеты
    c.execute("SELECT answer_text FROM questionnaire_answers WHERE user_id = ? AND question_number = 22", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        rituals_text = result[0]
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

def save_extended_user_data(user_id: int, extended_data: Dict[str, Any]):
    """Сохраняет расширенные данные пользователя в Google Sheets"""
    if not google_sheet:
        return False
    
    try:
        worksheet = google_sheet.worksheet("клиенты_детали")
        
        # Ищем пользователя
        try:
            cell = worksheet.find(str(user_id))
            row = cell.row
        except Exception:
            logger.warning(f"Пользователь {user_id} не найден в Google Sheets")
            return False
        
        # Получаем текущие заголовки
        headers = worksheet.row_values(1)
        
        # Подготавливаем данные для обновления
        update_data = []
        for header in headers:
            if header in extended_data:
                update_data.append(extended_data[header])
            else:
                # Оставляем существующее значение или пустую строку
                update_data.append("")
        
        # Обновляем строку
        worksheet.update(f'A{row}:{chr(65 + len(headers) - 1)}{row}', [update_data])
        
        logger.info(f"✅ Расширенные данные пользователя {user_id} сохранены в Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения расширенных данных: {e}")
        return False

# ========== НОВЫЕ ФУНКЦИИ ДЛЯ ПРОФИЛЯ ==========

def get_user_usage_days(user_id: int) -> Dict[str, int]:
    """Возвращает статистику дней использования"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    # Дни с регистрации
    c.execute("SELECT registration_date FROM clients WHERE user_id = ?", (user_id,))
    reg_result = c.fetchone()
    if not reg_result:
        conn.close()
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
    
    reg_date = datetime.strptime(reg_result[0], "%Y-%m-%d %H:%M:%S").date()
    days_since_registration = (datetime.now().date() - reg_date).days + 1
    
    # Активные дни (когда был прогресс)
    c.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = ?", (user_id,))
    active_days = c.fetchone()[0] or 0
    
    # Текущая серия
    current_streak = get_user_activity_streak(user_id)
    
    conn.close()
    
    return {
        'days_since_registration': days_since_registration,
        'active_days': active_days,
        'current_day': active_days if active_days > 0 else 1,  # Текущий день использования
        'current_streak': current_streak
    }

def get_user_balance(user_id: int) -> str:
    """Получает баланс работа/отдых из анкеты"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT answer_text FROM questionnaire_answers WHERE user_id = ? AND question_number = 25", (user_id,))
    result = c.fetchone()
    conn.close()
    
    # Если в ответе есть цифры, извлекаем их
    if result and result[0]:
        answer = result[0]
        # Ищем паттерн типа "60/40" в тексте
        match = re.search(r'(\d+)[/\s]+\s*(\d+)', answer)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    
    return "60/40"  # Значение по умолчанию

def get_most_productive_day(user_id: int) -> str:
    """Определяет самый продуктивный день (только при наличии данных)"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    # Проверяем, есть ли достаточно данных
    c.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = ?", (user_id,))
    if c.fetchone()[0] < 7:  # Меньше недели данных
        conn.close()
        return "еще не определен"
    
    # Здесь можно добавить логику определения продуктивного дня по данным
    # Пока вернем заглушку
    conn.close()
    return "понедельник"

# ========== НОВАЯ СИСТЕМА НАПОМИНАНИЙ ==========

def parse_time_input(time_text: str) -> Dict[str, Any]:
    """Парсит различные форматы времени"""
    time_text = time_text.lower().strip()
    
    # Словарь для преобразования
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
    
    # Если есть точное время с :
    if ':' in time_text:
        # Обработка "9:00", "21:30" и т.д.
        try:
            time_str = time_text.split()[0]  # Берем первую часть до пробела
            datetime.strptime(time_str, "%H:%M")
            return {'time': time_str, 'type': 'exact'}
        except ValueError:
            pass
    
    # Если относительное время
    if time_text in time_mapping:
        return {'time': time_mapping[time_text], 'type': 'relative'}
    
    # Если "9 утра", "7 вечера" и т.д.
    time_match = re.search(r'(\d+)\s+(утра|вечера|ночи)', time_text)
    if time_match:
        hour = int(time_match.group(1))
        period = time_match.group(2)
        
        if period == 'утра':
            return {'time': f"{hour:02d}:00", 'type': '12h'}
        elif period == 'вечера' and hour < 12:
            return {'time': f"{hour + 12:02d}:00", 'type': '12h'}
        elif period == 'ночи':
            return {'time': f"{hour:02d}:00", 'type': '12h'}
    
    # Если "через X часов/минут"
    future_match = re.search(r'через\s+(\d+)\s*(час|часа|часов|минут|минуты)', time_text)
    if future_match:
        amount = int(future_match.group(1))
        unit = future_match.group(2)
        
        now = datetime.now()
        if 'час' in unit:
            future_time = now + timedelta(hours=amount)
        else:
            future_time = now + timedelta(minutes=amount)
        
        return {'time': future_time.strftime("%H:%M"), 'type': 'future'}
    
    return None

def detect_reminder_type(message_text: str) -> str:
    """Определяет тип напоминания по тексту"""
    text = message_text.lower()
    
    # Ключевые слова для регулярных напоминаний
    regular_keywords = ['каждый', 'каждое', 'ежедневно', 'регулярно', 'по', 'каждую', 'напоминай']
    days_keywords = ['понедельник', 'вторник', 'сред', 'четверг', 'пятниц', 'суббот', 'воскресенье']
    
    # Если есть слова "каждый" или дни недели - это регулярное напоминание
    if any(keyword in text for keyword in regular_keywords + days_keywords):
        return 'regular'
    else:
        return 'once'

def parse_reminder_text(text: str) -> Dict[str, Any]:
    """Парсит текст напоминания и возвращает структурированные данные"""
    text_lower = text.lower()
    
    # Определяем тип напоминания
    reminder_type = detect_reminder_type(text)
    
    # Извлекаем время
    time_match = re.search(r'(\d{1,2}:\d{2})|(\d+\s+(утра|вечера|ночи))|(утром|днем|вечером|ночью)', text_lower)
    time_data = None
    
    if time_match:
        time_text = time_match.group(0)
        time_data = parse_time_input(time_text)
    
    # Извлекаем текст напоминания (убираем ключевые слова и время)
    reminder_text = text_lower
    keywords = ['напомни', 'напоминай', 'мне', 'в', 'каждый', 'каждое', 'ежедневно']
    for keyword in keywords:
        reminder_text = reminder_text.replace(keyword, '')
    
    if time_match:
        reminder_text = reminder_text.replace(time_match.group(0), '')
    
    reminder_text = reminder_text.strip()
    
    # Извлекаем дни недели для регулярных напоминаний
    days_of_week = []
    if reminder_type == 'regular':
        days_map = {
            'понедельник': 'пн', 'вторник': 'вт', 'сред': 'ср', 'четверг': 'чт',
            'пятниц': 'пт', 'суббот': 'сб', 'воскресенье': 'вс'
        }
        
        for day_full, day_short in days_map.items():
            if day_full in text_lower:
                days_of_week.append(day_short)
        
        # Если дни не указаны, значит ежедневно
        if not days_of_week and 'каждый день' in text_lower:
            days_of_week = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    
    return {
        'type': reminder_type,
        'time': time_data['time'] if time_data else '09:00',  # По умолчанию
        'text': reminder_text,
        'days': days_of_week if days_of_week else ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'],
        'original_text': text
    }

def add_reminder_to_db(user_id: int, reminder_data: Dict[str, Any]) -> bool:
    """Добавляет напоминание в базу данных"""
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        
        days_str = ','.join(reminder_data['days']) if reminder_data['days'] else 'ежедневно'
        created_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute('''INSERT INTO user_reminders 
                     (user_id, reminder_text, reminder_time, days_of_week, reminder_type, created_date)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (user_id, reminder_data['text'], reminder_data['time'], 
                   days_str, reminder_data['type'], created_date))
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Напоминание добавлено для пользователя {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления напоминания: {e}")
        return False

def get_user_reminders(user_id: int) -> List[Dict]:
    """Возвращает список напоминаний пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute('''SELECT id, reminder_text, reminder_time, days_of_week, reminder_type 
                 FROM user_reminders 
                 WHERE user_id = ? AND is_active = 1 
                 ORDER BY created_date DESC''', (user_id,))
    
    reminders = []
    for row in c.fetchall():
        reminders.append({
            'id': row[0],
            'text': row[1],
            'time': row[2],
            'days': row[3],
            'type': row[4]
        })
    
    conn.close()
    return reminders

def delete_reminder_from_db(reminder_id: int) -> bool:
    """Удаляет напоминание по ID"""
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        
        c.execute('''UPDATE user_reminders SET is_active = 0 WHERE id = ?''', (reminder_id,))
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Напоминание {reminder_id} удалено")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления напоминания: {e}")
        return False

# ========== GOOGLE SHEETS МЕНЕДЖЕР ==========

class GoogleSheetsManager:
    """Менеджер для работы с Google Sheets"""
    def __init__(self):
        self.client = None
        self.sheet = None
        self.connect()
    
    def connect(self):
        """Подключается к Google Sheets"""
        try:
            if not GOOGLE_SHEETS_AVAILABLE:
                return None
                
            if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_SHEETS_ID:
                logger.warning("⚠️ GOOGLE_CREDENTIALS_JSON или GOOGLE_SHEETS_ID не найден")
                return None
            
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
            scope = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            self.client = gspread.authorize(creds)
            
            self.sheet = self.client.open_by_key(GOOGLE_SHEETS_ID)
            logger.info("✅ Google Sheets менеджер подключен")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
            return None
    
    def save_daily_data(self, user_id: int, data_type: str, value: str) -> bool:
        """Сохраняет ежедневные данные в новую структуру"""
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
        """Получает информацию о пользователе"""
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT username, first_name FROM clients WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        
        if result:
            return {'username': result[0], 'first_name': result[1]}
        return None

sheets_manager = GoogleSheetsManager()

# ========== ОБНОВЛЕННЫЕ КОМАНДЫ ==========

async def start(update: Update, context: CallbackContext) -> int:
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    save_user_info(user_id, user.username, user.first_name, user.last_name)
    update_user_activity(user_id)
    
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM questionnaire_answers WHERE user_id = ?", (user_id,))
    has_answers = c.fetchone()[0] > 0
    conn.close()
    
    if has_answers:
        keyboard = [
            ['📊 Прогресс', '👤 Профиль'],
            ['📋 План на сегодня', '🔔 Мои напоминания'],
            ['ℹ️ Помощь', '🎮 Очки опыта']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "✅ Вы уже зарегистрированы!\n\n"
            "Добро пожаловать обратно! Что хотите сделать?",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
    else:
        keyboard = [['👨 Мужской', '👩 Женский']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности.\n\n'
            'Для начала выберите пол ассистента:',
            reply_markup=reply_markup
        )
        
        return GENDER

async def gender_choice(update: Update, context: CallbackContext) -> int:
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
        f'👋 Привет! Меня зовут {assistant_name}. Я ваш персональный ассистент.\n\n'
        f'{QUESTIONS[0]}',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return FIRST_QUESTION

def save_answer(user_id: int, context: CallbackContext, answer_text: str):
    """Сохраняет ответ пользователя"""
    current_question = context.user_data['current_question']
    save_questionnaire_answer(user_id, current_question, QUESTIONS[current_question], answer_text)
    context.user_data['answers'][current_question] = answer_text

async def process_next_question(update: Update, context: CallbackContext):
    """Обрабатывает переход к следующему вопросу"""
    context.user_data['current_question'] += 1
    if context.user_data['current_question'] < len(QUESTIONS):
        await update.message.reply_text(QUESTIONS[context.user_data['current_question']])

async def handle_question(update: Update, context: CallbackContext) -> int:
    """Обработчик ответов на вопросы анкеты"""
    user_id = update.effective_user.id
    answer_text = update.message.text
    
    save_answer(user_id, context, answer_text)
    await process_next_question(update, context)
    
    if context.user_data['current_question'] >= len(QUESTIONS):
        return await finish_questionnaire(update, context)
    
    return FIRST_QUESTION

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
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
        'motivation': context.user_data['answers'].get(2, ''),
        'wake_time': context.user_data['answers'].get(5, ''),
        'sleep_time': context.user_data['answers'].get(5, ''),
        'activity_preferences': context.user_data['answers'].get(10, ''),
        'diet_features': context.user_data['answers'].get(14, ''),
        'rest_preferences': context.user_data['answers'].get(18, ''),
        'morning_rituals': context.user_data['answers'].get(22, ''),
        'evening_rituals': context.user_data['answers'].get(22, ''),
        'personal_habits': context.user_data['answers'].get(22, ''),
        'development_goals': context.user_data['answers'].get(1, ''),
        'special_notes': context.user_data['answers'].get(29, ''),
        # Новые поля
        'текущий_уровень': 'Новичок',
        'очки_опыта': '0',
        'текущая_серия_активности': '0',
        'максимальная_серия_активности': '0',
        'любимый_ритуал': get_favorite_ritual(user.id),
        'дата_последнего_прогресса': datetime.now().strftime("%Y-%m-%d"),
        'ближайшая_цель': 'Заполнить первую неделю активности'
    }
    
    logger.info(f"🔄 Сохранение данных анкеты пользователя {user.id} в Google Sheets")
    success = save_client_to_sheets(user_data)
    if success:
        logger.info(f"✅ Данные анкеты пользователя {user.id} успешно сохранены в Google Sheets")
    else:
        logger.error(f"❌ Ошибка сохранения данных анкеты пользователя {user.id} в Google Sheets")
    
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
        if i == 0:
            continue
        answer = context.user_data['answers'].get(i, '❌ Нет ответа')
        questionnaire += f"❓ {i}. {question}:\n"
        questionnaire += f"💬 {answer}\n\n"
    
    max_length = 4096
    if len(questionnaire) > max_length:
        parts = [questionnaire[i:i+max_length] for i in range(0, len(questionnaire), max_length)]
        for part in parts:
            try:
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=part)
            except Exception as e:
                logger.error(f"Ошибка отправки части анкеты: {e}")
    else:
        try:
            await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=questionnaire)
        except Exception as e:
            logger.error(f"Ошибка отправки анкеты: {e}")
    
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
        logger.error(f"Ошибка отправки кнопки ответа: {e}")
    
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
        "'напомни мне в 20:00 постирать купальник'\n"
        "'напоминай каждый день в 8:00 делать зарядку'\n\n"
        "Или использовать команды из меню ниже:",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

# ========== ОБНОВЛЕННЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ==========

async def plan_command(update: Update, context: CallbackContext):
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

async def progress_command(update: Update, context: CallbackContext):
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
        
        # Сохраняем данные в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'серия_активности': str(usage_days['current_streak']),
            'рекомендации_на_день': 'Продолжайте собирать данные',
            'динамика_настроения': 'недостаточно данных',
            'динамика_энергии': 'недостаточно данных',
            'динамика_продуктивности': 'недостаточно данных'
        }
        save_daily_report_to_sheets(user_id, report_data)
    else:
        # Получаем данные за последние 7 дней
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("""
            SELECT 
                COUNT(*) as total_days,
                AVG(tasks_completed) as avg_tasks,
                AVG(mood) as avg_mood,
                AVG(energy) as avg_energy,
                AVG(water_intake) as avg_water,
                COUNT(DISTINCT progress_date) as active_days
            FROM user_progress 
            WHERE user_id = ? AND progress_date >= date('now', '-7 days')
        """, (user_id,))
        result = c.fetchone()
        conn.close()

        total_days = result[0] or 0
        avg_tasks = result[1] or 0
        avg_mood = result[2] or 0
        avg_energy = result[3] or 0
        avg_water = result[4] or 0
        active_days = result[5] or 0

        # Рассчитываем проценты и динамику
        tasks_completed = f"{int(avg_tasks * 10)}/10" if avg_tasks else "0/10"
        mood_str = f"{avg_mood:.1f}/10" if avg_mood else "0/10"
        energy_str = f"{avg_energy:.1f}/10" if avg_energy else "0/10"
        water_str = f"{avg_water:.1f} стаканов/день" if avg_water else "0 стаканов/день"
        activity_str = f"{active_days}/7 дней"

        # Динамика (упрощенная логика)
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
        
        # Сохраняем расширенные данные в Google Sheets
        extended_data = {
            'user_id': user_id,
            'текущий_уровень': level_info['level'],
            'очки_опыта': str(level_info['points']),
            'текущая_серия_активности': str(usage_days['current_streak']),
            'дата_последнего_прогресса': datetime.now().strftime("%Y-%m-%d")
        }
        save_extended_user_data(user_id, extended_data)
        
        # Сохраняем отчет в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'серия_активности': str(usage_days['current_streak']),
            'уровень_дня': level_info['level'],
            'рекомендации_на_день': advice,
            'динамика_настроения': mood_dynamics,
            'динамика_энергии': energy_dynamics,
            'динамика_продуктивности': productivity_dynamics
        }
        save_daily_report_to_sheets(user_id, report_data)

async def profile_command(update: Update, context: CallbackContext):
    """Показывает новый профиль пользователя"""
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
    balance = get_user_balance(user_id)
    
    # Получаем статистику по планам
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM user_plans WHERE user_id = ?", (user_id,))
    total_plans = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(*) FROM user_plans WHERE user_id = ? AND status = 'completed'", (user_id,))
    completed_plans = c.fetchone()[0] or 0

    # Вычисляем процент выполнения планов
    plans_percentage = (completed_plans / total_plans * 100) if total_plans > 0 else 0
    
    # Получаем средние метрики
    c.execute("SELECT AVG(mood), AVG(energy) FROM user_progress WHERE user_id = ?", (user_id,))
    metrics_result = c.fetchone()
    avg_mood = metrics_result[0] or 0
    avg_energy = metrics_result[1] or 0
    
    conn.close()
    
    # Формируем профиль
    profile_text = (
        f"👤 ВАШ ПРОФИЛЬ\n\n"
        f"📅 День {usage_days['current_day']} • Всего дней: {usage_days['days_since_registration']} • Серия: {usage_days['current_streak']}\n\n"
        f"🎯 ТЕКУЩАЯ ЦЕЛЬ: {main_goal}\n"
        f"📊 ВЫПОЛНЕНО: {plans_percentage:.1f}% на пути к цели\n\n"
        f"⚖️ БАЛАНС РАБОТА/ОТДЫХ: {balance}\n\n"
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
    
    # Сохраняем расширенные данные в Google Sheets
    extended_data = {
        'user_id': user_id,
        'текущий_уровень': level_info['level'],
        'очки_опыта': str(level_info['points']),
        'текущая_серия_активности': str(usage_days['current_streak']),
        'любимый_ритуал': favorite_ritual,
        'ближайшая_цель': f"Следующий шаг к '{main_goal}'"
    }
    save_extended_user_data(user_id, extended_data)

async def points_info_command(update: Update, context: CallbackContext):
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

async def help_command(update: Update, context: CallbackContext):
    """Показывает обновленную справку по командам"""
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
        "'напоминай каждый день в 8:00 делать зарядку'\n\n"
        
        "💬 Просто напишите сообщение, чтобы связаться с ассистентом!"
    )
    
    await update.message.reply_text(help_text)

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
        
        sheets_manager.save_daily_data(user_id, "настроение", f"{mood}/10")
        
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
        
        sheets_manager.save_daily_data(user_id, "энергия", f"{energy}/10")
        
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
        
        sheets_manager.save_daily_data(user_id, "водный_баланс", f"{water} стаканов")
        
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

# ========== НОВЫЕ КОМАНДЫ НАПОМИНАНИЙ ==========

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
            "/remind_me вечером постирать купальник\n\n"
            "⏱️ Время можно указывать в разных форматах:\n"
            "• 20:30, 09:00\n"
            "• 9 утра, 7 вечера\n"
            "• утром, днем, вечером\n"
            "• через 2 часа"
        )
        return
    
    time_str = context.args[0]
    reminder_text = " ".join(context.args[1:])
    
    # Парсим время
    time_data = parse_time_input(time_str)
    
    if not time_data:
        await update.message.reply_text(
            "❌ Не удалось распознать время.\n"
            "Пожалуйста, укажите время в одном из форматов:\n"
            "• 20:30 или 09:00\n"
            "• 9 утра или 7 вечера\n"
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
        'ежедневно': ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    }
    
    if days_str.lower() == 'ежедневно':
        days = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    else:
        days = []
        for day_part in days_str.split(','):
            day_clean = day_part.strip().lower()
            if day_clean in days_map:
                days.append(days_map[day_clean])
    
    if not days:
        await update.message.reply_text(
            "❌ Не удалось распознать дни недели.\n"
            "Укажите дни в формате: пн,ср,пт или 'ежедневно'"
        )
        return
    
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

async def handle_reminder_nlp(update: Update, context: CallbackContext):
    """Обрабатывает естественные запросы на напоминания"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Парсим текст напоминания
    reminder_data = parse_reminder_text(message_text)
    
    if not reminder_data:
        await update.message.reply_text(
            "❌ Не понял формат напоминания.\n\n"
            "💡 Попробуйте так:\n"
            "'напомни мне в 20:00 постирать купальник'\n"
            "'напоминай каждый день в 8:00 делать зарядку'\n"
            "'напомни завтра утром позвонить врачу'"
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

# ========== АДМИН КОМАНДЫ ==========

async def send_to_user(update: Update, context: CallbackContext):
    """Отправляет сообщение пользователю от имени ассистента"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Формат команды:\n"
            "/send <user_id> <сообщение>\n\n"
            "Пример:\n"
            "/send 12345678 Привет! Как твои успехи?"
        )
        return
    
    user_id = context.args[0]
    message = " ".join(context.args[1:])
    
    try:
        save_message(user_id, message, 'outgoing')
        
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"💌 Сообщение от вашего ассистента:\n\n{message}"
        )
        await update.message.reply_text("✅ Сообщение отправлено пользователю!")
        
        logger.info(f"Администратор отправил сообщение пользователю {user_id}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка отправки: {e}"
        await update.message.reply_text(error_msg)
        logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")

async def admin_stats(update: Update, context: CallbackContext):
    """Статистика для администратора"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM clients")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM clients WHERE date(last_activity) = date('now')")
    active_today = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM messages WHERE direction = 'incoming'")
    total_messages = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM questionnaire_answers")
    total_answers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM user_plans")
    total_plans = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM user_progress")
    total_progress = c.fetchone()[0]
    
    conn.close()
    
    stats_text = f"📊 Статистика бота:\n\n"
    stats_text += f"👥 Всего пользователей: {total_users}\n"
    stats_text += f"🟢 Активных сегодня: {active_today}\n"
    stats_text += f"📨 Всего сообщений: {total_messages}\n"
    stats_text += f"📝 Ответов в анкетах: {total_answers}\n"
    stats_text += f"📋 Индивидуальных планов: {total_plans}\n"
    stats_text += f"📈 Записей прогресса: {total_progress}\n\n"
    
    if google_sheet:
        stats_text += f"📊 Google Sheets: ✅ подключен\n"
    else:
        stats_text += f"📊 Google Sheets: ❌ не доступен\n"
    
    stats_text += f"📈 Бот работает стабильно! ✅"
    
    await update.message.reply_text(stats_text)

async def create_plan_command(update: Update, context: CallbackContext):
    """Создает индивидуальный план для пользователя"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Укажите ID пользователя:\n"
            "/create_plan <user_id>\n\n"
            "Пример: /create_plan 123456789"
        )
        return
    
    user_id = context.args[0]
    
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name, username FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_name, username = user_data
        
        await update.message.reply_text(
            f"📋 Создание плана для пользователя:\n"
            f"👤 Имя: {user_name}\n"
            f"🔗 Username: @{username if username else 'нет'}\n"
            f"🆔 ID: {user_id}\n\n"
            f"Для создания плана используйте команду:\n"
            f"/set_plan {user_id} утренний_ритуал1|утренний_ритуал2|задача1|задача2|задача3|задача4|обед|вечерний_ритуал1|вечерний_ритуал2|совет|сон|вода|активность"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def set_plan_command(update: Update, context: CallbackContext):
    """Устанавливает план для пользователя"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Неправильный формат команды.\n\n"
            "Использование:\n"
            "/set_plan <user_id> утренний_ритуал1|утренний_ритуал2|задача1|задача2|задача3|задача4|обед|вечерний_ритуал1|вечерний_ритуал2|совет|сон|вода|активность"
        )
        return
    
    user_id = context.args[0]
    plan_parts = " ".join(context.args[1:]).split("|")
    
    if len(plan_parts) < 13:
        await update.message.reply_text("❌ Недостаточно частей плана. Нужно 13 частей, разделенных |")
        return
    
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_name = user_data[0]
        
        plan_data = {
            'plan_date': datetime.now().strftime("%Y-%m-%d"),
            'morning_ritual1': plan_parts[0],
            'morning_ritual2': plan_parts[1],
            'task1': plan_parts[2],
            'task2': plan_parts[3],
            'task3': plan_parts[4],
            'task4': plan_parts[5],
            'lunch_break': plan_parts[6],
            'evening_ritual1': plan_parts[7],
            'evening_ritual2': plan_parts[8],
            'advice': plan_parts[9],
            'sleep_time': plan_parts[10],
            'water_goal': plan_parts[11],
            'activity_goal': plan_parts[12]
        }
        
        save_user_plan_to_db(user_id, plan_data)
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 Ваш индивидуальный план готов!\n\n"
                     "Посмотреть его можно командой: /plan\n\n"
                     "Ассистент составил для вас персональный план на основе вашей анкеты. "
                     "Удачи в выполнении! 💪"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
        await update.message.reply_text(
            f"✅ Индивидуальный план для {user_name} создан и сохранен!\n\n"
            f"Пользователь получил уведомление."
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка создания плана: {e}")

# ========== УЛУЧШЕННЫЕ АДМИН КОМАНДЫ ==========

async def admin_help(update: Update, context: CallbackContext):
    """Помощь для администратора"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    help_text = (
        "🛠️ КОМАНДЫ ДЛЯ АДМИНИСТРАТОРА:\n\n"
        
        "👥 Управление пользователями:\n"
        "/admin_stats - Статистика бота\n"
        "/user_info <user_id> - Информация о пользователе\n"
        "/user_plan <user_id> - План пользователя\n"
        "/user_progress <user_id> - Прогресс пользователя\n\n"
        
        "📋 Управление планами:\n"
        "/create_plan <user_id> - Начать создание плана\n"
        "/set_plan <user_id> ритуал1|ритуал2|... - Установить план\n"
        "/quick_plan <user_id> <текст> - Быстрый план\n\n"
        
        "💬 Общение:\n"
        "/send <user_id> <сообщение> - Отправить сообщение\n"
        "/broadcast <сообщение> - Рассылка всем\n\n"
        
        "📊 Google Sheets:\n"
        "/update_sheets <user_id> - Обновить данные в таблице\n"
        "/check_sheets <user_id> - Проверить данные в таблице\n"
    )
    
    await update.message.reply_text(help_text)

async def user_info_command(update: Update, context: CallbackContext):
    """Информация о пользователе"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /user_info <user_id>")
        return
    
    user_id = context.args[0]
    
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        
        # Основная информация
        c.execute("SELECT * FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        # Статистика сообщений
        c.execute("SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,))
        messages_count = c.fetchone()[0]
        
        # Анкета
        c.execute("SELECT COUNT(*) FROM questionnaire_answers WHERE user_id = ?", (user_id,))
        answers_count = c.fetchone()[0]
        
        # Прогресс
        c.execute("SELECT COUNT(*) FROM user_progress WHERE user_id = ?", (user_id,))
        progress_count = c.fetchone()[0]
        
        # Последняя активность
        c.execute("SELECT last_activity FROM clients WHERE user_id = ?", (user_id,))
        last_activity = c.fetchone()[0]
        
        conn.close()
        
        user_info = (
            f"👤 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:\n\n"
            f"🆔 ID: {user_data[0]}\n"
            f"📛 Имя: {user_data[2]} {user_data[3] or ''}\n"
            f"🔗 Username: @{user_data[1] or 'нет'}\n"
            f"📅 Регистрация: {user_data[5]}\n"
            f"🕐 Последняя активность: {last_activity}\n"
            f"📊 Статистика:\n"
            f"  • Сообщений: {messages_count}\n"
            f"  • Ответов в анкете: {answers_count}\n"
            f"  • Записей прогресса: {progress_count}\n"
        )
        
        # Кнопки быстрых действий
        keyboard = [
            [InlineKeyboardButton("📋 Создать план", callback_data=f"create_plan_{user_id}")],
            [InlineKeyboardButton("💬 Написать сообщение", callback_data=f"message_{user_id}")],
            [InlineKeyboardButton("📊 Посмотреть прогресс", callback_data=f"progress_{user_id}")],
            [InlineKeyboardButton("📝 Посмотреть анкету", callback_data=f"questionnaire_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(user_info, reply_markup=reply_markup)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def quick_plan_command(update: Update, context: CallbackContext):
    """Быстрое создание плана через бота"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Формат команды:\n"
            "/quick_plan <user_id> <текст плана>\n\n"
            "Пример:\n"
            "/quick_plan 12345678 Утренняя медитация|Зарядка|Важная задача|Вторая задача|Третья задача|Четвертая задача|Обед в 13:00|Чтение|Планирование|Хорошо выспитесь|23:00|8 стаканов|Прогулка 30 мин"
        )
        return
    
    user_id = context.args[0]
    plan_text = " ".join(context.args[1:])
    
    try:
        # Парсим текст плана
        plan_parts = plan_text.split("|")
        if len(plan_parts) < 13:
            await update.message.reply_text(
                "❌ Недостаточно частей плана. Нужно 13 частей, разделенных |\n\n"
                "Формат: утренний_ритуал1|утренний_ритуал2|задача1|задача2|задача3|задача4|обед|вечерний_ритуал1|вечерний_ритуал2|совет|сон|вода|активность"
            )
            return
        
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_name = user_data[0]
        
        plan_data = {
            'plan_date': datetime.now().strftime("%Y-%m-%d"),
            'morning_ritual1': plan_parts[0],
            'morning_ritual2': plan_parts[1],
            'task1': plan_parts[2],
            'task2': plan_parts[3],
            'task3': plan_parts[4],
            'task4': plan_parts[5],
            'lunch_break': plan_parts[6],
            'evening_ritual1': plan_parts[7],
            'evening_ritual2': plan_parts[8],
            'advice': plan_parts[9],
            'sleep_time': plan_parts[10],
            'water_goal': plan_parts[11],
            'activity_goal': plan_parts[12]
        }
        
        save_user_plan_to_db(user_id, plan_data)
        
        # Отправляем уведомление пользователю
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 {user_name}, ваш план на сегодня готов!\n\n"
                     f"📋 Посмотреть: /plan\n\n"
                     f"💪 Удачи в выполнении! Если есть вопросы, пишите мне."
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
        # Сохраняем в Google Sheets
        today = datetime.now().strftime("%Y-%m-%d")
        sheets_plan_data = {
            'date': today,
            'strategic_tasks_done': '0%',
            'morning_rituals_done': 'не выполнено',
            'evening_rituals_done': 'не выполнено',
            'mood': '',
            'energy': '',
            'water_intake': '0'
        }
        save_daily_report_to_sheets(user_id, sheets_plan_data)
        
        await update.message.reply_text(
            f"✅ План для {user_name} создан и сохранен!\n\n"
            f"📋 Пользователь получил уведомление.\n"
            f"📊 Данные сохранены в Google Sheets."
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка создания плана: {e}")

async def broadcast_command(update: Update, context: CallbackContext):
    """Рассылка сообщений всем пользователям"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите сообщение для рассылки:\n"
            "/broadcast <текст сообщения>"
        )
        return
    
    message_text = " ".join(context.args)
    
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT user_id, first_name FROM clients WHERE status = 'active'")
        users = c.fetchall()
        conn.close()
        
        total_users = len(users)
        successful_sends = 0
        failed_sends = 0
        
        await update.message.reply_text(f"📤 Начинаю рассылку для {total_users} пользователей...")
        
        for user_id, first_name in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 СООБЩЕНИЕ ОТ АССИСТЕНТА:\n\n{message_text}"
                )
                successful_sends += 1
                
                # Логируем отправку
                save_message(user_id, f"РАССЫЛКА: {message_text}", 'outgoing')
                
                # Небольшая задержка чтобы не превысить лимиты Telegram
                await asyncio.sleep(0.1)
                
            except Exception as e:
                failed_sends += 1
                logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
        
        # Отчет о рассылке
        report_text = (
            f"📊 ОТЧЕТ О РАССЫЛКЕ:\n\n"
            f"✅ Успешно отправлено: {successful_sends}\n"
            f"❌ Не удалось отправить: {failed_sends}\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"📝 Текст сообщения: {message_text[:100]}..."
        )
        
        await update.message.reply_text(report_text)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка рассылки: {e}")

async def update_sheets_command(update: Update, context: CallbackContext):
    """Принудительное обновление данных в Google Sheets"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя: /update_sheets <user_id>")
        return
    
    user_id = context.args[0]
    
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        
        # Получаем данные пользователя
        c.execute("SELECT * FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        # Получаем последний прогресс
        c.execute("SELECT * FROM user_progress WHERE user_id = ? ORDER BY progress_date DESC LIMIT 1", (user_id,))
        progress_data = c.fetchone()
        
        conn.close()
        
        # Подготавливаем данные для Google Sheets
        user_info = {
            'user_id': user_id,
            'telegram_username': user_data[1],
            'first_name': user_data[2],
            'last_name': user_data[3],
            'start_date': user_data[5],
            'last_activity': user_data[6]
        }
        
        # Сохраняем в Google Sheets
        success = save_client_to_sheets(user_info)
        
        if success:
            # Если есть данные прогресса, сохраняем и их
            if progress_data:
                report_data = {
                    'date': progress_data[2],
                    'mood': progress_data[4] or '',
                    'energy': progress_data[5] or '',
                    'water_intake': progress_data[7] or '',
                    'strategic_tasks_done': f"{progress_data[3] or 0}/4"
                }
                save_daily_report_to_sheets(user_id, report_data)
            
            await update.message.reply_text(
                f"✅ Данные пользователя {user_id} обновлены в Google Sheets!\n\n"
                f"📊 Можно проверить в таблице 'клиенты_детали'"
            )
        else:
            await update.message.reply_text("❌ Ошибка обновления данных в Google Sheets")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка обновления: {e}")

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

async def handle_all_messages(update: Update, context: CallbackContext):
    """Обработчик для всех входящих сообщений"""
    if update.message.text and update.message.text.startswith('/'):
        return
    
    user = update.effective_user
    user_id = user.id
    
    # Обработка кнопок
    text = update.message.text
    if text == '📊 Прогресс':
        return await progress_command(update, context)
    elif text == 'ℹ️ Помощь':
        return await help_command(update, context)
    elif text == '👤 Профиль':
        return await profile_command(update, context)
    elif text == '📋 План на сегодня':
        return await plan_command(update, context)
    elif text == '🔔 Мои напоминания':
        return await my_reminders_command(update, context)
    elif text == '🎮 Очки опыта':
        return await points_info_command(update, context)
    
    # Обработка естественного языка для напоминаний
    if text and any(word in text.lower() for word in ['напомни', 'напоминай']):
        return await handle_reminder_nlp(update, context)
    
    # Остальная логика обработки сообщений
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("👋 Для начала работы с персональным ассистентом отправьте команду /start")
        return
    
    message_text = update.message.text or "Сообщение без текста"
    
    save_message(user_id, message_text, 'incoming')
    
    user_info = f"📩 Новое сообщение от пользователя:\n"
    user_info += f"👤 ID: {user.id}\n"
    user_info += f"📛 Имя: {user.first_name}\n"
    if user.last_name:
        user_info += f"📛 Фамилия: {user.last_name}\n"
    if user.username:
        user_info += f"🔗 Username: @{user.username}\n"
    user_info += f"💬 Текст: {message_text}\n"
    user_info += f"🕐 Время: {update.message.date.strftime('%Y-%m-%d %H:%M')}\n"
    
    stats = get_user_stats(user_id)
    user_info += f"\n📊 Статистика пользователя:\n"
    user_info += f"📨 Сообщений: {stats['messages_count']}\n"
    user_info += f"📅 Зарегистрирован: {stats['registration_date']}\n"
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Ответить пользователю", callback_data=f"reply_{user.id}")],
        [InlineKeyboardButton("👁️ Просмотреть анкету", callback_data=f"view_questionnaire_{user.id}")],
        [InlineKeyboardButton("📊 Статистика пользователя", callback_data=f"stats_{user.id}")]
    ])
    
    try:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=user_info,
            reply_markup=reply_markup
        )
        await update.message.reply_text("✅ Ваше сообщение отправлено ассистенту! Ответим в ближайшее время.")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения администратору: {e}")
        await update.message.reply_text("❌ Произошла ошибка при отправке сообщения. Попробуйте позже.")

async def button_callback(update: Update, context: CallbackContext):
    """Обработчик callback кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('reply_'):
        user_id = query.data.replace('reply_', '')
        context.user_data['reply_user_id'] = user_id
        await query.edit_message_text(
            text=f"💌 Ответ пользователю\n\n"
                 f"👤 ID пользователя: {user_id}\n\n"
                 f"📝 Чтобы ответить, используйте команду:\n"
                 f"/send {user_id} ваш текст сообщения\n\n"
                 f"⚡ Или быстрые команды:\n"
                 f"/user_info {user_id} - Информация о пользователе\n"
                 f"/quick_plan {user_id} - Быстрый план"
        )
    
    elif query.data.startswith('create_plan_'):
        user_id = query.data.replace('create_plan_', '')
        await query.edit_message_text(
            text=f"📋 Создание плана для пользователя {user_id}\n\n"
                 f"Используйте команду:\n"
                 f"/create_plan {user_id}\n\n"
                 f"⚡ Или быстрый вариант:\n"
                 f"/quick_plan {user_id} утренний_ритуал1|утренний_ритуал2|задача1|задача2|задача3|задача4|обед|вечерний_ритуал1|вечерний_ритуал2|совет|сон|вода|активность"
        )
    
    elif query.data.startswith('message_'):
        user_id = query.data.replace('message_', '')
        context.user_data['reply_user_id'] = user_id
        await query.edit_message_text(
            text=f"💌 Написать пользователю {user_id}\n\n"
                 f"Используйте команду:\n"
                 f"/send {user_id} ваш текст сообщения"
        )
    
    elif query.data.startswith('progress_'):
        user_id = query.data.replace('progress_', '')
        await query.edit_message_text(
            text=f"📊 Просмотр прогресса пользователя {user_id}\n\n"
                 f"Используйте команду:\n"
                 f"/user_progress {user_id}"
        )
    
    elif query.data.startswith('questionnaire_'):
        user_id = query.data.replace('questionnaire_', '')
        await query.edit_message_text(
            text=f"📝 Просмотр анкеты пользователя {user_id}\n\n"
                 f"Чтобы просмотреть анкету, используйте команду:\n"
                 f"/get_questionnaire {user_id}\n\n"
                 f"📋 Или создайте план на основе анкеты:\n"
                 f"/create_plan {user_id}"
        )
    
    elif query.data.startswith('view_questionnaire_'):
        user_id = query.data.replace('view_questionnaire_', '')
        await query.edit_message_text(
            text=f"📋 Просмотр анкеты пользователя {user_id}\n\n"
                 f"📝 Для просмотра анкеты используйте команду:\n"
                 f"/get_questionnaire {user_id}"
        )
    
    elif query.data.startswith('stats_'):
        user_id = query.data.replace('stats_', '')
        stats = get_user_stats(user_id)
        
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name, registration_date FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if user_data:
            user_name = user_data[0]
            reg_date = user_data[1]
            
            keyboard = [
                [InlineKeyboardButton("📋 Создать план", callback_data=f"create_plan_{user_id}")],
                [InlineKeyboardButton("💬 Написать", callback_data=f"message_{user_id}")],
                [InlineKeyboardButton("📊 Прогресс", callback_data=f"progress_{user_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=f"📊 Статистика пользователя:\n\n"
                     f"👤 Имя: {user_name}\n"
                     f"🆔 ID: {user_id}\n"
                     f"📅 Регистрация: {reg_date}\n"
                     f"📨 Сообщений: {stats['messages_count']}\n\n"
                     f"💌 Чтобы ответить:\n"
                     f"/send {user_id} ваш текст\n\n"
                     f"📋 Создать план:\n"
                     f"/create_plan {user_id}",
                reply_markup=reply_markup
            )

async def cancel(update: Update, context: CallbackContext) -> int:
    """Отмена диалога"""
    await update.message.reply_text(
        '❌ Диалог прерван. Чтобы начать заново, отправьте /start',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: CallbackContext):
    """Обрабатывает ошибки в боте"""
    logger.error(msg="Исключение при обработке обновления:", exc_info=context.error)
    
    if "Conflict" in str(context.error):
        logger.warning("🔄 Обнаружена ошибка Conflict - другой экземпляр бота уже запущен")
        return
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

def main():
    """Основная функция запуска бота"""
    try:
        application = Application.builder().token(TOKEN).build()

        application.add_error_handler(error_handler)

        # Основной обработчик диалога
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [MessageHandler(filters.Regex('^(👨 Мужской|👩 Женский|Мужской|Женский)$'), gender_choice)],
                FIRST_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        application.add_handler(conv_handler)
        
        # Основные команды
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("points_info", points_info_command))
        application.add_handler(CommandHandler("stats", admin_stats))
        application.add_handler(CommandHandler("send", send_to_user))
        application.add_handler(CommandHandler("questionnaire", start))
        
        # Команды для пользователей
        application.add_handler(CommandHandler("done", done_command))
        application.add_handler(CommandHandler("mood", mood_command))
        application.add_handler(CommandHandler("energy", energy_command))
        application.add_handler(CommandHandler("water", water_command))
        
        # Новые команды для напоминаний
        application.add_handler(CommandHandler("remind_me", remind_me_command))
        application.add_handler(CommandHandler("regular_remind", regular_remind_command))
        application.add_handler(CommandHandler("my_reminders", my_reminders_command))
        application.add_handler(CommandHandler("delete_remind", delete_remind_command))
        
        # Команды для администратора
        application.add_handler(CommandHandler("create_plan", create_plan_command))
        application.add_handler(CommandHandler("set_plan", set_plan_command))
        application.add_handler(CommandHandler("admin_help", admin_help))
        application.add_handler(CommandHandler("user_info", user_info_command))
        application.add_handler(CommandHandler("quick_plan", quick_plan_command))
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        application.add_handler(CommandHandler("update_sheets", update_sheets_command))
        
        # Обработчики кнопок и сообщений
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
        
        # Настройка JobQueue для автоматических сообщений
        try:
            job_queue = application.job_queue
            if job_queue:
                # Удаляем старые задачи
                current_jobs = job_queue.jobs()
                for job in current_jobs:
                    job.schedule_removal()
                
                # Утреннее сообщение в 6:00
                job_queue.run_daily(
                    callback=send_morning_plan,
                    time=dt_time(hour=3, minute=0),  # 6:00 MSK (UTC+3)
                    days=tuple(range(7)),
                    name="morning_plan"
                )
                
                # Вечерний опрос в 21:00
                job_queue.run_daily(
                    callback=send_evening_survey,
                    time=dt_time(hour=18, minute=0),  # 21:00 MSK (UTC+3)
                    days=tuple(range(7)),
                    name="evening_survey"
                )
                
                logger.info("✅ JobQueue настроен для автоматических сообщений")
                
        except Exception as e:
            logger.error(f"❌ Ошибка настройки JobQueue: {e}")

        logger.info("🤖 Бот запускается...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")

async def send_morning_plan(context: CallbackContext):
    """Отправляет утренний план пользователям"""
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT user_id, first_name, username FROM clients WHERE status = 'active'")
        users = c.fetchall()
        conn.close()
        
        for user in users:
            user_id, first_name, username = user
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

async def send_evening_survey(context: CallbackContext):
    """Отправляет вечерний опрос пользователям"""
    try:
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT user_id, first_name FROM clients WHERE status = 'active'")
        users = c.fetchall()
        conn.close()
        
        for user in users:
            user_id, first_name = user
            
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

if __name__ == '__main__':
    main()
