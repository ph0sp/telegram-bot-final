import os
import logging
import sqlite3
import asyncio
import time
import json
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, Optional, Any, List

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    JobQueue
)

from dotenv import load_dotenv

# Попробуем импортировать Google Sheets (опционально)
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False
    print("⚠️ Google Sheets не доступен. Установите: pip install gspread google-auth")

load_dotenv()

# ========== КОНСТАНТЫ ==========

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Получение переменных окружения
TOKEN = os.environ.get('BOT_TOKEN')
YOUR_CHAT_ID = os.environ.get('YOUR_CHAT_ID')
GOOGLE_SHEETS_CREDENTIALS = os.environ.get('GOOGLE_SHEETS_CREDENTIALS')

# Проверка наличия токена
if not TOKEN:
    logger.error("Токен бота не найден! Установите переменную BOT_TOKEN")
    exit(1)

if not YOUR_CHAT_ID:
    logger.error("Chat ID не найден! Установите переменную YOUR_CHAT_ID")
    exit(1)

# Константы для состояний диалога
GENDER, FIRST_QUESTION = range(2)

# Константы для индексов планов
PLAN_FIELDS = {
    'id': 0, 'user_id': 1, 'plan_date': 2, 'morning_ritual1': 4, 'morning_ritual2': 5,
    'task1': 6, 'task2': 7, 'task3': 8, 'task4': 9, 'lunch_break': 10,
    'evening_ritual1': 11, 'evening_ritual2': 12, 'advice': 13, 'sleep_time': 14,
    'water_goal': 15, 'activity_goal': 16
}

# Список вопросов (полная версия)
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
    "Блок 6: Ритуалы для здоровья и самочувствия\n\nИсходя из вашего режима, предлагаю вам на выбор несколько идей. Что из этого вам откликается?\n\nУтренние ритуалы (на выбор):\n* Стакан теплой воды с лимоном: для запуска метаболизма.\n* Несложная зарядка/растяжка (5-15 мин): чтобы размяться и проснуться.\n* Медитация или ведение дневника (5-10 мин): для настройки на день.\n* Контрастный душ: для бодрости.\n* Полезный завтрак без телефона: осознанное начало дня.\n\nВечерние ритуалы (на выбор):\n* Выключение гаджетов за 1 час до сна: для улучшения качества сна.\n* Ведение дневника благодарности или запись 3х хороших событий дня.\n* Чтение книги (не с экрана).\n* Легкая растяжка или йога перед сном: для расслабления мышц.\n* Планирование главных задач на следующий день (3 дела): чтобы выгрузить мысли и спать спокойно.\n* Ароматерапия или спокойная музыка.\n\nКакие из этих утренних ритуалов вам были бы интересны?\n\nКакие вечерние ритуалы вы бы хотели внедрить?\n\nЕсть ли ваши личные ритуалы, которые вы хотели бы сохранить?",
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
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

init_db()

# ========== GOOGLE SHEETS ==========

def init_google_sheets():
    """Инициализация Google Sheets"""
    if not GOOGLE_SHEETS_AVAILABLE:
        logger.warning("⚠️ Google Sheets не доступен")
        return None
    
    try:
        if GOOGLE_SHEETS_CREDENTIALS and os.path.exists(GOOGLE_SHEETS_CREDENTIALS):
            # Используем файл credentials
            scope = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS, scopes=scope)
        else:
            # Пытаемся использовать переменную окружения с JSON
            credentials_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
            if credentials_json:
                creds_dict = json.loads(credentials_json)
                scope = ['https://www.googleapis.com/auth/spreadsheets']
                creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            else:
                logger.warning("⚠️ Google Sheets credentials не найдены")
                return None
        
        client = gspread.authorize(creds)
        
        # Пытаемся открыть существующую таблицу или создать новую
        try:
            sheet = client.open("Планы_пользователей_бота")
        except gspread.SpreadsheetNotFound:
            # Создаем новую таблицу
            sheet = client.create("Планы_пользователей_бота")
            # Настраиваем листы
            worksheet1 = sheet.sheet1
            worksheet1.title = "Анкеты"
            worksheet1.append_row([
                "ID", "Имя", "Username", "Дата регистрации", "Ассистент",
                "Главная цель", "Мотивация", "Время в день", "Дедлайн",
                "Режим сна", "Текущий день", "Пик продуктивности", 
                "Время соцсетей", "Уровень выгорания", "Физ активность",
                "Любимый спорт", "Дни тренировок", "Ограничения по здоровью",
                "Режим питания", "Вода в день", "Изменения в питании",
                "Время готовки", "Отдых", "Частота отдыха", "Перерывы",
                "Общение", "Утренние ритуалы", "Вечерние ритуалы",
                "Баланс", "Препятствия", "Дни низкой энергии"
            ])
            
            # Создаем лист для планов
            worksheet2 = sheet.add_worksheet(title="Планы", rows=1000, cols=20)
            worksheet2.append_row([
                "ID", "Имя", "Дата плана", "Статус", "Утренний ритуал 1",
                "Утренний ритуал 2", "Задача 1", "Задача 2", "Задача 3",
                "Задача 4", "Обеденный перерыв", "Вечерний ритуал 1",
                "Вечерний ритуал 2", "Совет ассистента", "Время сна",
                "Вода", "Физ активность", "Примечания"
            ])
            
            # Создаем лист для прогресса
            worksheet3 = sheet.add_worksheet(title="Прогресс", rows=1000, cols=15)
            worksheet3.append_row([
                "ID", "Имя", "Дата", "Выполнено задач", "Настроение (1-10)",
                "Энергия (1-10)", "Качество сна", "Выпито воды", 
                "Выполнена активность", "Комментарий пользователя",
                "Оценка дня", "Трудности"
            ])
            
            logger.info("✅ Новая Google таблица создана")
        
        logger.info("✅ Google Sheets инициализирован")
        return sheet
    
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Google Sheets: {e}")
        return None

# Инициализируем Google Sheets
google_sheet = init_google_sheets()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def save_user_info(user_id: int, username: str, first_name: str, last_name: Optional[str] = None):
    """Сохраняет информацию о пользователе в базу данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT OR REPLACE INTO clients 
                 (user_id, username, first_name, last_name, status, registration_date, last_activity) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (user_id, username, first_name, last_name, 'active', registration_date, registration_date))
    conn.commit()
    conn.close()
    logger.info(f"Сохранена информация о пользователе {user_id}")

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
    
    # Количество сообщений от пользователя
    c.execute("SELECT COUNT(*) FROM messages WHERE user_id = ? AND direction = 'incoming'", (user_id,))
    messages_count = c.fetchone()[0]
    
    # Дата регистрации
    c.execute("SELECT registration_date FROM clients WHERE user_id = ?", (user_id,))
    reg_date = c.fetchone()[0]
    
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
    logger.info(f"План сохранен в БД для пользователя {user_id}")

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
    logger.info(f"Прогресс сохранен в БД для пользователя {user_id}")

def save_questionnaire_to_sheets(user_id: int, user_data: Dict[str, Any], assistant_name: str, answers: Dict[int, str]):
    """Сохраняет анкету в Google Sheets"""
    if not google_sheet:
        return
    
    try:
        worksheet = google_sheet.worksheet("Анкеты")
        
        # Подготавливаем данные для строки
        row_data = [
            user_id,
            user_data.get('first_name', ''),
            user_data.get('username', ''),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            assistant_name
        ]
        
        # Добавляем ответы на вопросы (с 1 по 30)
        for i in range(1, 31):
            if i < len(QUESTIONS):
                answer = answers.get(i, '')
                # Обрезаем длинные ответы
                if len(str(answer)) > 100:
                    answer = str(answer)[:100] + "..."
                row_data.append(answer)
            else:
                row_data.append('')
        
        worksheet.append_row(row_data)
        logger.info(f"Анкета пользователя {user_id} сохранена в Google Sheets")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения анкеты в Google Sheets: {e}")

def save_plan_to_sheets(user_id: int, user_name: str, plan_data: Dict[str, Any]):
    """Сохраняет план в Google Sheets"""
    if not google_sheet:
        return
    
    try:
        worksheet = google_sheet.worksheet("Планы")
        
        row_data = [
            user_id,
            user_name,
            plan_data.get('plan_date', ''),
            'active',
            plan_data.get('morning_ritual1', ''),
            plan_data.get('morning_ritual2', ''),
            plan_data.get('task1', ''),
            plan_data.get('task2', ''),
            plan_data.get('task3', ''),
            plan_data.get('task4', ''),
            plan_data.get('lunch_break', ''),
            plan_data.get('evening_ritual1', ''),
            plan_data.get('evening_ritual2', ''),
            plan_data.get('advice', ''),
            plan_data.get('sleep_time', ''),
            plan_data.get('water_goal', ''),
            plan_data.get('activity_goal', ''),
            plan_data.get('notes', '')
        ]
        
        worksheet.append_row(row_data)
        logger.info(f"План пользователя {user_id} сохранен в Google Sheets")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения плана в Google Sheets: {e}")

# ========== НОВЫЙ GOOGLE SHEETS МЕНЕДЖЕР ==========

class GoogleSheetsManager:
    """Дополнительный менеджер для сохранения в новые таблицы"""
    def __init__(self):
        self.client = None
        self.sheet = None
        self.connect()
    
    def connect(self):
        """Подключается к Google Sheets"""
        try:
            if not GOOGLE_SHEETS_AVAILABLE:
                return None
                
            credentials_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
            if not credentials_json:
                logger.warning("GOOGLE_CREDENTIALS_JSON не найден")
                return None
            
            creds_dict = json.loads(credentials_json)
            scope = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            self.client = gspread.authorize(creds)
            
            SPREADSHEET_ID = os.environ.get('GOOGLE_SHEETS_ID')
            if not SPREADSHEET_ID:
                logger.warning("GOOGLE_SHEETS_ID не найден")
                return None
            
            self.sheet = self.client.open_by_key(SPREADSHEET_ID)
            logger.info("✅ Новый Google Sheets менеджер подключен")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
            return None
    
    def save_daily_data(self, user_id: int, data_type: str, value: str) -> bool:
        """Сохраняет ежедневные данные в лист 'планы октябрь'"""
        try:
            worksheet = self.sheet.worksheet("планы октябрь")
            today = datetime.now().strftime("%d.%m.%Y")
            
            # Находим строку для этого пользователя и даты
            records = worksheet.get_all_records()
            row_index = None
            
            for i, record in enumerate(records, start=2):
                if (str(record.get('ID клиента', '')) == str(user_id) and 
                    record.get('дата', '') == today):
                    row_index = i
                    break
            
            # Если строка не найдена, создаем новую
            if not row_index:
                user_info = self.get_user_info(user_id)
                if not user_info:
                    return False
                
                new_row = [user_id, user_info['first_name'], today]
                new_row.extend([""] * 17)  # 17 колонок после даты
                worksheet.append_row(new_row)
                
                # Получаем индекс новой строки
                records = worksheet.get_all_records()
                for i, record in enumerate(records, start=2):
                    if (str(record.get('ID клиента', '')) == str(user_id) and 
                        record.get('дата', '') == today):
                        row_index = i
                        break
            
            if not row_index:
                return False
            
            # Маппинг типов данных на колонки
            column_mapping = {
                'настроение': 12,  # колонка L
                'самочувствие': 13,  # колонка M
                'водный_баланс': 14,  # колонка N
                'привычки': 15,  # колонка O
                'лекарства': 16,  # колонка P
                'развитие': 17,  # колонка Q
                'прогресс': 18,  # колонка R
                'примечание': 19,  # колонка S
                'баланс': 11,  # колонка K
                'напоминание': 20  # колонка T
            }
            
            if data_type in column_mapping:
                col_index = column_mapping[data_type]
                cell = worksheet.cell(row_index, col_index)
                
                # Если в ячейке уже есть данные, добавляем новую строку
                current_value = cell.value or ""
                if current_value:
                    new_value = f"{current_value}\n{datetime.now().strftime('%H:%M')}: {value}"
                else:
                    new_value = f"{datetime.now().strftime('%H:%M')}: {value}"
                
                worksheet.update_cell(row_index, col_index, new_value)
                logger.info(f"✅ Данные сохранены в Google Sheets: {user_id} - {data_type}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения данных в Google Sheets: {e}")
            return False
    
    def get_user_info(self, user_id: int) -> Optional[Dict[str, str]]:
        """Получает информацию о пользователе из базы данных"""
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name, username FROM clients WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        
        if result:
            return {'first_name': result[0], 'username': result[1]}
        return None

# Глобальный экземпляр Google Sheets
sheets_manager = GoogleSheetsManager()

# ========== СИСТЕМА НАПОМИНАНИЙ ==========

class SmartReminderSystem:
    def __init__(self, updater):
        self.updater = updater
        self.reminder_settings = {}
        self.active_reminders = {}
    
    def load_user_settings(self, user_id: int) -> Dict[str, bool]:
        """Загружает настройки напоминаний пользователя"""
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS reminder_settings
                     (user_id INTEGER PRIMARY KEY,
                      morning_rituals BOOLEAN DEFAULT 0,
                      evening_rituals BOOLEAN DEFAULT 0, 
                      medications BOOLEAN DEFAULT 0,
                      water BOOLEAN DEFAULT 0,
                      activity BOOLEAN DEFAULT 0,
                      rest BOOLEAN DEFAULT 0,
                      progress_check BOOLEAN DEFAULT 0,
                      created_date TEXT)''')
        
        c.execute("SELECT * FROM reminder_settings WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if result:
            settings = {
                'morning_rituals': bool(result[1]),
                'evening_rituals': bool(result[2]),
                'medications': bool(result[3]),
                'water': bool(result[4]),
                'activity': bool(result[5]),
                'rest': bool(result[6]),
                'progress_check': bool(result[7])
            }
        else:
            # Настройки по умолчанию
            settings = {
                'morning_rituals': False,
                'evening_rituals': False,
                'medications': False, 
                'water': False,
                'activity': False,
                'rest': False,
                'progress_check': False
            }
        
        conn.close()
        return settings
    
    def save_user_settings(self, user_id: int, settings: Dict[str, bool]):
        """Сохраняет настройки напоминаний"""
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        
        c.execute('''INSERT OR REPLACE INTO reminder_settings 
                     (user_id, morning_rituals, evening_rituals, medications, 
                      water, activity, rest, progress_check, created_date)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user_id, settings['morning_rituals'], settings['evening_rituals'],
                   settings['medications'], settings['water'], settings['activity'],
                   settings['rest'], settings['progress_check'], 
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        conn.commit()
        conn.close()
    
    def setup_reminders(self, update: Update, context: CallbackContext):
        """Настройка автоматических напоминаний"""
        user_id = update.effective_user.id
        
        # Загружаем текущие настройки
        settings = self.load_user_settings(user_id)
        context.user_data['reminder_settings'] = settings
        context.user_data['reminder_setup_step'] = 0
        
        update.message.reply_text(
            "🔔 Давайте настроим автоматические напоминания!\n\n"
            "Я могу напоминать вам о важных вещах в течение дня. "
            "Выберите, о чем вам нужно напоминать:\n\n"
            "1. Утренние ритуалы (8:00)\n"
            "2. Вечерние ритуалы (21:00)\n" 
            "3. Прием лекарств/витаминов (9:00 и 20:00)\n"
            "4. Питье воды (4 раза в день)\n"
            "5. Физическая активность (11:00)\n"
            "6. Отдых и перерывы (15:00)\n"
            "7. Проверка прогресса по целям (19:00)\n\n"
            "Отвечайте 'да' или 'нет' на каждый пункт.\n\n"
            "Начнем? Нужны ли вам напоминания об утренних ритуалах в 8:00?"
        )
        
        return "REMINDER_SETUP"
    
    def handle_reminder_setup(self, update: Update, context: CallbackContext):
        """Обрабатывает ответы при настройке напоминаний"""
        user_id = update.effective_user.id
        user_response = update.message.text.lower()
        settings = context.user_data['reminder_settings']
        step = context.user_data['reminder_setup_step']
        
        reminder_types = [
            ('morning_rituals', "утренних ритуалах", "вечерних ритуалах в 21:00?"),
            ('evening_rituals', "вечерних ритуалах", "приеме лекарств/витаминов в 9:00 и 20:00?"),
            ('medications', "приеме лекарств", "питье воды (4 раза в день)?"),
            ('water', "питье воды", "физической активности в 11:00?"),
            ('activity', "физической активности", "отдыхе и перерывах в 15:00?"),
            ('rest', "отдыхе", "проверке прогресса по целям в 19:00?"),
            ('progress_check', "проверке прогресса", "настройка завершена!")
        ]
        
        if step < len(reminder_types):
            current_type, current_text, next_text = reminder_types[step]
            
            # Обрабатываем ответ
            if user_response in ['да', 'yes', 'нужно', 'хочу']:
                settings[current_type] = True
                response = "✅ Хорошо, буду напоминать!"
            elif user_response in ['нет', 'no', 'не нужно', 'не надо']:
                settings[current_type] = False
                response = "❌ Хорошо, не буду напоминать."
            else:
                update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'")
                return "REMINDER_SETUP"
            
            context.user_data['reminder_setup_step'] += 1
            
            if step + 1 < len(reminder_types):
                next_type, next_text, after_text = reminder_types[step + 1]
                update.message.reply_text(
                    f"{response}\n\nНужны ли вам напоминания о {after_text}"
                )
            else:
                # Сохраняем настройки
                self.save_user_settings(user_id, settings)
                self.schedule_reminders(user_id, settings)
                
                enabled_reminders = [rt[1] for rt in reminder_types if settings[rt[0]]]
                
                if enabled_reminders:
                    reminders_text = "\n".join([f"• {reminder}" for reminder in enabled_reminders])
                    update.message.reply_text(
                        f"🎉 Напоминания настроены!\n\n"
                        f"Я буду напоминать вам о:\n{reminders_text}\n\n"
                        f"Вы всегда можете изменить настройки: /reminder_settings\n"
                        f"Или установить разовое напоминание: /remind"
                    )
                else:
                    update.message.reply_text(
                        "❌ Автоматические напоминания отключены.\n\n"
                        "Вы можете установить разовое напоминание: /remind\n"
                        "Или настроить автоматические позже: /reminder_settings"
                    )
                
                return ConversationHandler.END
        
        return "REMINDER_SETUP"
    
    def schedule_reminders(self, user_id: int, settings: Dict[str, bool]):
        """Планирует автоматические напоминания"""
        reminder_times = {
            'morning_rituals': [(8, 0)],  # 8:00
            'evening_rituals': [(21, 0)],  # 21:00
            'medications': [(9, 0), (20, 0)],  # 9:00 и 20:00
            'water': [(10, 0), (13, 0), (16, 0), (19, 0)],  # 4 раза
            'activity': [(11, 0)],  # 11:00
            'rest': [(15, 0)],  # 15:00
            'progress_check': [(19, 0)]  # 19:00
        }
        
        reminder_texts = {
            'morning_rituals': "🌅 Время для утренних ритуалов! Начните день с энергии!",
            'evening_rituals': "🌙 Время для вечерних ритуалов! Подготовьтесь к спокойному сну.",
            'medications': "💊 Время принять лекарства/витамины!",
            'water': "💧 Время выпить стакан воды! Поддерживайте водный баланс.",
            'activity': "🏃 Время для физической активности! Подвигайтесь немного.",
            'rest': "☕ Время для отдыха! Сделайте перерыв и восстановите силы.",
            'progress_check': "📊 Время проверить прогресс по целям! Что удалось сегодня?"
        }
        
        # Удаляем старые напоминания
        for job_name in list(self.active_reminders.keys()):
            if job_name.startswith(f"auto_{user_id}_"):
                try:
                    job = self.updater.job_queue.get_jobs_by_name(job_name)
                    if job:
                        job[0].schedule_removal()
                    del self.active_reminders[job_name]
                except:
                    pass
        
        # Добавляем новые напоминания
        for reminder_type, enabled in settings.items():
            if enabled and reminder_type in reminder_times:
                for time_tuple in reminder_times[reminder_type]:
                    hour, minute = time_tuple
                    
                    job_name = f"auto_{user_id}_{reminder_type}_{hour}_{minute}"
                    
                    try:
                        self.updater.job_queue.run_daily(
                            callback=lambda ctx, uid=user_id, text=reminder_texts[reminder_type]: self.send_auto_reminder(ctx, uid, text),
                            time=dt_time(hour=hour-3, minute=minute),  # UTC+3
                            days=tuple(range(7)),
                            name=job_name
                        )
                        
                        self.active_reminders[job_name] = {
                            'user_id': user_id,
                            'type': reminder_type,
                            'time': f"{hour:02d}:{minute:02d}"
                        }
                        
                        logger.info(f"✅ Автонапоминание установлено: {user_id} - {reminder_type} в {hour:02d}:{minute:02d}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка установки автонапоминания: {e}")
    
    def send_auto_reminder(self, context: CallbackContext, user_id: int, text: str):
        """Отправляет автоматическое напоминание"""
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"🔔 НАПОМИНАНИЕ:\n\n{text}\n\n"
                     f"✅ Отметьте выполнение соответствующей командой"
            )
            
            # Сохраняем в Google Sheets
            sheets_manager.save_daily_data(user_id, "напоминание", f"Авто: {text}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки автонапоминания: {e}")
    
    def set_custom_reminder(self, user_id: int, reminder_time: str, text: str) -> bool:
        """Устанавливает кастомное напоминание"""
        try:
            # Парсим время
            remind_time = datetime.strptime(reminder_time, "%H:%M").time()
            now = datetime.now().time()
            
            # Вычисляем время до напоминания
            remind_datetime = datetime.combine(datetime.now().date(), remind_time)
            if remind_time < now:
                remind_datetime += timedelta(days=1)
            
            delay = (remind_datetime - datetime.now()).total_seconds()
            
            if delay < 0:
                return False
            
            # Сохраняем в Google Sheets
            sheets_manager.save_daily_data(user_id, "напоминание", 
                                         f"Кастом: {reminder_time} - {text}")
            
            # Создаем отложенную задачу
            job_name = f"custom_{user_id}_{datetime.now().timestamp()}"
            
            self.updater.job_queue.run_once(
                callback=lambda ctx, uid=user_id, t=text: self.send_custom_reminder(ctx, uid, t),
                when=delay,
                name=job_name
            )
            
            self.active_reminders[job_name] = {
                'user_id': user_id,
                'time': reminder_time,
                'text': text,
                'type': 'custom'
            }
            
            logger.info(f"✅ Кастомное напоминание: {user_id} на {reminder_time}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка установки напоминания: {e}")
            return False
    
    def send_custom_reminder(self, context: CallbackContext, user_id: int, text: str):
        """Отправляет кастомное напоминание"""
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"🔔 ВАШЕ НАПОМИНАНИЕ:\n\n{text}\n\n"
                     f"✅ Выполнено? /done"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки напоминания: {e}")

# Глобальный экземпляр системы напоминаний
reminder_system = None

# ========== ОСНОВНЫЕ КОМАНДЫ ==========

def start(update: Update, context: CallbackContext) -> int:
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем пользователя в базу
    save_user_info(user_id, user.username, user.first_name, user.last_name)
    update_user_activity(user_id)
    
    # Проверяем, заполнял ли пользователь уже анкету
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM questionnaire_answers WHERE user_id = ?", (user_id,))
    has_answers = c.fetchone()[0] > 0
    conn.close()
    
    if has_answers:
        # Предлагаем настроить напоминания
        keyboard = [['⚙️ Настроить напоминания', '📋 Мой план']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        update.message.reply_text(
            "✅ Вы уже зарегистрированы!\n\n"
            "🔔 Хотите настроить автоматические напоминания? Это поможет вам "
            "не забывать о важных делах в течение дня.",
            reply_markup=reply_markup
        )
        
        # Сохраняем состояние для обработки кнопки
        context.user_data['waiting_for_reminder_setup'] = True
        return ConversationHandler.END
    else:
        # Начинаем анкету
        keyboard = [['👨 Мужской', '👩 Женский']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        update.message.reply_text(
            '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности.\n\n'
            'Для начала выберите пол ассистента:',
            reply_markup=reply_markup
        )
        
        return GENDER

def gender_choice(update: Update, context: CallbackContext) -> int:
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
    
    update.message.reply_text(
        f'👋 Привет! Меня зовут {assistant_name}. Я ваш персональный ассистент. '
        f'Моя задача – помочь структурировать ваш день для максимальной продуктивности и достижения целей без стресса и выгорания.\n\n'
        f'Я составлю для вас сбалансированный план на месяц, а затем мы будем ежедневно отслеживать прогресс и ваше состояние, '
        f'чтобы вы двигались к цели уверенно и эффективно и с заботой о главных ресурсах: сне, спорте и питании.\n\n'
        f'Для составления плана, который будет работать именно для вас, мне нужно понять ваш ритм жизни и цели. '
        f'Это займет около 25-30 минут. Но в результате вы получите персональную стратегию на месяц, а не шаблонный список дел.\n\n'
        f'{QUESTIONS[0]}',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return FIRST_QUESTION

def save_answer(user_id: int, context: CallbackContext, answer_text: str):
    """Сохраняет ответ пользователя"""
    current_question = context.user_data['current_question']
    save_questionnaire_answer(user_id, current_question, QUESTIONS[current_question], answer_text)
    context.user_data['answers'][current_question] = answer_text

def process_next_question(update: Update, context: CallbackContext):
    """Обрабатывает переход к следующему вопросу"""
    context.user_data['current_question'] += 1
    if context.user_data['current_question'] < len(QUESTIONS):
        update.message.reply_text(QUESTIONS[context.user_data['current_question']])

def handle_question(update: Update, context: CallbackContext) -> int:
    """Обработчик ответов на вопросы анкеты"""
    user_id = update.effective_user.id
    answer_text = update.message.text
    
    # Сохраняем ответ
    save_answer(user_id, context, answer_text)
    
    # Переходим к следующему вопросу
    process_next_question(update, context)
    
    # Проверяем завершение анкеты
    if context.user_data['current_question'] >= len(QUESTIONS):
        return finish_questionnaire(update, context)
    
    return FIRST_QUESTION

def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    """Завершает анкету и отправляет данные"""
    user = update.effective_user
    assistant_name = context.user_data['assistant_name']
    
    # Сохраняем анкету в Google Sheets
    if google_sheet:
        user_data = {
            'first_name': user.first_name,
            'username': user.username
        }
        save_questionnaire_to_sheets(user.id, user_data, assistant_name, context.user_data['answers'])
    
    # Создаем заголовок с информацией о пользователе
    questionnaire = f"📋 Новая анкета от пользователя:\n\n"
    questionnaire += f"👤 Информация о пользователе:\n"
    questionnaire += f"🆔 ID: {user.id}\n"
    questionnaire += f"📛 Имя: {user.first_name}\n"
    if user.last_name:
        questionnaire += f"📛 Фамилия: {user.last_name}\n"
    if user.username:
        questionnaire += f"🔗 Username: @{user.username}\n"
    questionnaire += f"📅 Дата заполнения: {update.message.date.strftime('%Y-%m-%d %H:%M')}\n"
    questionnaire += f"👨‍💼 Ассистент: {assistant_name}\n\n"
    
    questionnaire += "📝 Ответы на вопросы:\n\n"
    
    # Добавляем ответы на вопросы
    for i, question in enumerate(QUESTIONS):
        if i == 0:  # Пропускаем первый вопрос "Готовы начать?"
            continue
        answer = context.user_data['answers'].get(i, '❌ Нет ответа')
        questionnaire += f"❓ {i}. {question}:\n"
        questionnaire += f"💬 {answer}\n\n"
    
    # Разбиваем анкету на части, если она слишком длинная
    max_length = 4096
    if len(questionnaire) > max_length:
        parts = [questionnaire[i:i+max_length] for i in range(0, len(questionnaire), max_length)]
        for part in parts:
            try:
                context.bot.send_message(chat_id=YOUR_CHAT_ID, text=part)
            except Exception as e:
                logger.error(f"Ошибка отправки части анкеты: {e}")
    else:
        try:
            context.bot.send_message(chat_id=YOUR_CHAT_ID, text=questionnaire)
        except Exception as e:
            logger.error(f"Ошибка отправки анкеты: {e}")
    
    # Отправляем кнопки для взаимодействия с пользователем
    try:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Ответить пользователю", callback_data=f"reply_{user.id}")],
            [InlineKeyboardButton("👁️ Просмотреть анкету", callback_data=f"view_questionnaire_{user.id}")],
            [InlineKeyboardButton("📊 Статистика пользователя", callback_data=f"stats_{user.id}")],
            [InlineKeyboardButton("📋 Создать план", callback_data=f"create_plan_{user.id}")]
        ])
        
        context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=f"✅ Пользователь {user.first_name} завершил анкету!\n\n"
                 f"Чтобы ответить пользователю, используйте команду:\n"
                 f"<code>/send {user.id} ваш текст</code>\n\n"
                 f"Чтобы создать индивидуальный план:\n"
                 f"<code>/create_plan {user.id}</code>",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка отправки кнопки ответа: {e}")
    
    # Отправляем сообщение пользователю
    update.message.reply_text(
        "🎉 Спасибо за ответы!\n\n"
        "✅ Я передал всю информацию нашему специалисту. В течение 24 часов он проанализирует ваши данные и составит для вас индивидуальный план.\n\n"
        "🔔 Теперь у вас есть доступ к персональному ассистенту!\n\n"
        "📋 Доступные команды:\n"
        "/my_plan - Ваш индивидуальный план (будет доступен после составления)\n"
        "/plan - Общий план на сегодня\n"
        "/progress - Статистика прогресса\n"
        "/chat - Связь с ассистентом\n"
        "/help - Помощь\n"
        "/profile - Ваш профиль\n\n"
        "💬 Вы также можете просто написать сообщение, и ассистент ответит вам!"
    )
    
    return ConversationHandler.END

# ========== СУЩЕСТВУЮЩИЕ КОМАНДЫ ==========

def plan_command(update: Update, context: CallbackContext):
    """Показывает текущий план пользователя"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    update.message.reply_text(
        "📋 Ваш персональный план на сегодня:\n\n"
        "🕘 Утро (8:00 - 12:00):\n"
        "• 🏃 Зарядка и контрастный душ - 20 мин\n"
        "• 🍳 Полезный завтрак - 30 мин\n"
        "• 🎯 Работа над главной задачей - 3 часа\n\n"
        "🕐 День (12:00 - 18:00):\n"
        "• 🥗 Обед и отдых - 1 час\n"
        "• 📚 Обучение и развитие - 2 часа\n"
        "• 💼 Второстепенные задачи - 2 часа\n\n"
        "🕢 Вечер (18:00 - 22:00):\n"
        "• 🏋️ Тренировка - 1 час\n"
        "• 🍲 Ужин - 30 мин\n"
        "• 📖 Чтение и планирование - 1 час\n\n"
        "✅ Статус: 🔄 в процессе выполнения\n\n"
        "💡 Для корректировки плана напишите ассистенту!\n\n"
        "🎯 Если у вас есть индивидуальный план, используйте: /my_plan"
    )

def progress_command(update: Update, context: CallbackContext):
    """Показывает статистику прогресса"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    stats = get_user_stats(user_id)
    
    update.message.reply_text(
        f"📊 Ваша статистика прогресса:\n\n"
        f"✅ Выполнено задач за неделю: 18/25 (72%)\n"
        f"🏃 Физическая активность: 4/5 дней\n"
        f"📚 Обучение: 6/7 часов\n"
        f"💤 Сон в среднем: 7.2 часа\n"
        f"📨 Сообщений ассистенту: {stats['messages_count']}\n"
        f"📅 С нами с: {stats['registration_date']}\n\n"
        f"🎯 Отличные результаты! Продолжайте в том же духе!\n\n"
        f"💡 Советы для улучшения:\n"
        f"• Старайтесь ложиться спать до 23:00\n"
        f"• Делайте перерывы каждые 45 минут работы\n"
        f"• Пейте больше воды в течение дня\n\n"
        f"📝 Отмечайте свой прогресс:\n"
        f"/mood <1-10> - оценить настроение\n"
        f"/energy <1-10> - оценить энергию"
    )

def profile_command(update: Update, context: CallbackContext):
    """Показывает профиль пользователя"""
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    stats = get_user_stats(user_id)
    
    profile_text = f"👤 Ваш профиль:\n\n"
    profile_text += f"📛 Имя: {user.first_name}\n"
    if user.last_name:
        profile_text += f"📛 Фамилия: {user.last_name}\n"
    if user.username:
        profile_text += f"🔗 Username: @{user.username}\n"
    profile_text += f"🆔 ID: {user.id}\n"
    profile_text += f"📅 Зарегистрирован: {stats['registration_date']}\n"
    profile_text += f"📨 Отправлено сообщений: {stats['messages_count']}\n\n"
    profile_text += f"💎 Статус: Активный пользователь\n\n"
    profile_text += f"🔧 Доступные команды:\n"
    profile_text += f"/my_plan - Индивидуальный план\n"
    profile_text += f"/plan - Общий план\n"
    profile_text += f"/progress - Статистика\n"
    profile_text += f"/questionnaire - Заполнить анкету заново\n"
    profile_text += f"/help - Помощь\n\n"
    profile_text += f"🎯 Новые команды:\n"
    profile_text += f"/done <номер> - отметить задачу\n"
    profile_text += f"/mood <1-10> - настроение\n"
    profile_text += f"/energy <1-10> - энергия"
    
    update.message.reply_text(profile_text)

def chat_command(update: Update, context: CallbackContext):
    """Начинает чат с ассистентом"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    update.message.reply_text(
        "💬 Чат с ассистентом открыт!\n\n"
        "📝 Напишите ваш вопрос или сообщение, и ассистент ответит вам в ближайшее время.\n\n"
        "⏰ Обычно ответ занимает не более 15-30 минут в рабочее время (9:00 - 18:00).\n\n"
        "🔔 Вы также можете просто писать сообщения без команды /chat - я всегда на связи!"
    )

def help_command(update: Update, context: CallbackContext):
    """Показывает справку по командам"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    help_text = "ℹ️ Справка по командам:\n\n"
    
    help_text += "🔹 Основные команды:\n"
    help_text += "/start - Начать работу с ботом (заполнить анкету)\n"
    help_text += "/my_plan - Индивидуальный план (если есть)\n"
    help_text += "/plan - Общий план на сегодня\n"
    help_text += "/progress - Статистика вашего прогресса\n"
    help_text += "/profile - Ваш профиль\n"
    help_text += "/chat - Связаться с ассистентом\n"
    help_text += "/help - Эта справка\n\n"
    
    help_text += "🔹 Новые команды для отслеживания:\n"
    help_text += "/done <1-4> - Отметить задачу выполненной\n"
    help_text += "/mood <1-10> - Оценить настроение\n"
    help_text += "/energy <1-10> - Оценить уровень энергии\n\n"
    
    help_text += "🔹 Дополнительные команды:\n"
    help_text += "/questionnaire - Заполнить анкету заново\n\n"
    
    help_text += "💡 Просто напишите сообщение, чтобы связаться с ассистентом!\n\n"
    help_text += "📞 По всем вопросам обращайтесь к вашему ассистенту через команду /chat или просто напишите сообщение."
    
    update.message.reply_text(help_text)

def questionnaire_command(update: Update, context: CallbackContext):
    """Запускает анкету заново"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    # Сбрасываем состояние анкеты
    context.user_data.clear()
    
    keyboard = [['👨 Мужской', '👩 Женский']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    update.message.reply_text(
        '🔄 Заполнение анкеты заново\n\n'
        'Выберите пол ассистента:',
        reply_markup=reply_markup
    )
    
    return GENDER

# ========== НОВЫЕ КОМАНДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========

def my_plan_command(update: Update, context: CallbackContext):
    """Показывает индивидуальный план пользователя"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    plan = get_user_plan_from_db(user_id)
    
    if not plan:
        update.message.reply_text(
            "📋 Индивидуальный план еще не готов.\n\n"
            "Наш ассистент анализирует вашу анкету и скоро составит для вас "
            "персональный план. Обычно это занимает до 24 часов.\n\n"
            "А пока вы можете посмотреть общий план: /plan"
        )
        return
    
    # Используем константы для индексов
    plan_text = f"📋 Ваш индивидуальный план на {plan[PLAN_FIELDS['plan_date']]}:\n\n"
    
    plan_text += "🌅 Утренние ритуалы:\n"
    if plan[PLAN_FIELDS['morning_ritual1']]: 
        plan_text += f"• {plan[PLAN_FIELDS['morning_ritual1']]}\n"
    if plan[PLAN_FIELDS['morning_ritual2']]: 
        plan_text += f"• {plan[PLAN_FIELDS['morning_ritual2']]}\n"
    
    plan_text += "\n🎯 Основные задачи:\n"
    if plan[PLAN_FIELDS['task1']]: plan_text += f"1. {plan[PLAN_FIELDS['task1']]}\n"
    if plan[PLAN_FIELDS['task2']]: plan_text += f"2. {plan[PLAN_FIELDS['task2']]}\n" 
    if plan[PLAN_FIELDS['task3']]: plan_text += f"3. {plan[PLAN_FIELDS['task3']]}\n"
    if plan[PLAN_FIELDS['task4']]: plan_text += f"4. {plan[PLAN_FIELDS['task4']]}\n"
    
    if plan[PLAN_FIELDS['lunch_break']]:
        plan_text += f"\n🍽 Обеденный перерыв: {plan[PLAN_FIELDS['lunch_break']]}\n"
    
    plan_text += "\n🌙 Вечерние ритуалы:\n"
    if plan[PLAN_FIELDS['evening_ritual1']]: plan_text += f"• {plan[PLAN_FIELDS['evening_ritual1']]}\n"
    if plan[PLAN_FIELDS['evening_ritual2']]: plan_text += f"• {plan[PLAN_FIELDS['evening_ritual2']]}\n"
    
    if plan[PLAN_FIELDS['advice']]:
        plan_text += f"\n💡 Совет ассистента: {plan[PLAN_FIELDS['advice']]}\n"
    
    if plan[PLAN_FIELDS['sleep_time']]:
        plan_text += f"\n💤 Рекомендуемое время сна: {plan[PLAN_FIELDS['sleep_time']]}\n"
    
    if plan[PLAN_FIELDS['water_goal']]:
        plan_text += f"💧 Цель по воде: {plan[PLAN_FIELDS['water_goal']]}\n"
    
    if plan[PLAN_FIELDS['activity_goal']]:
        plan_text += f"🏃 Активность: {plan[PLAN_FIELDS['activity_goal']]}\n"
    
    plan_text += "\n📝 Отмечайте выполнение командой /done <номер задачи>"
    plan_text += "\n😊 Оцените настроение: /mood <1-10>"
    plan_text += "\n⚡ Оцените энергию: /energy <1-10>"
    
    update.message.reply_text(plan_text)

def done_command(update: Update, context: CallbackContext):
    """Отмечает выполнение задачи"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Укажите номер задачи:\n"
            "/done 1 - отметить задачу 1 выполненной\n"
            "/done 2 - отметить задачу 2 выполненной\n"
            "и т.д."
        )
        return
    
    try:
        task_number = int(context.args[0])
        if task_number < 1 or task_number > 4:
            update.message.reply_text("❌ Номер задачи должен быть от 1 до 4")
            return
        
        # Здесь можно сохранить отметку о выполнении в базу
        task_names = {1: "первую", 2: "вторую", 3: "третью", 4: "четвертую"}
        
        update.message.reply_text(
            f"✅ Отлично! Вы выполнили {task_names[task_number]} задачу!\n"
            f"🎉 Продолжайте в том же духе!\n\n"
            f"Оцените свое состояние:\n"
            f"/mood <1-10> - ваше настроение\n"
            f"/energy <1-10> - уровень энергии"
        )
        
    except ValueError:
        update.message.reply_text("❌ Номер задачи должен быть числом")

def mood_command(update: Update, context: CallbackContext):
    """Оценка настроения"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Оцените ваше настроение от 1 до 10:\n"
            "/mood 1 - очень плохое\n"
            "/mood 5 - нейтральное\n" 
            "/mood 10 - отличное"
        )
        return
    
    try:
        mood = int(context.args[0])
        if mood < 1 or mood > 10:
            update.message.reply_text("❌ Оценка должна быть от 1 до 10")
            return
        
        # Сохраняем оценку настроения
        progress_data = {
            'mood': mood,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
        # ДОПОЛНИТЕЛЬНО: Сохраняем в Google Sheets
        sheets_manager.save_daily_data(user_id, "настроение", f"{mood}/10")
        
        mood_responses = {
            1: "😔 Мне жаль, что у вас плохое настроение. Что-то случилось?",
            2: "😟 Надеюсь, завтра будет лучше!",
            3: "🙁 Не отчаивайтесь, трудности временны!",
            4: "😐 Спасибо за честность!",
            5: "😊 Нейтрально - это тоже нормально!",
            6: "😄 Хорошее настроение - это здорово!",
            7: "😁 Отлично! Рад за вас!",
            8: "🤩 Прекрасное настроение!",
            9: "🥳 Восхитительно!",
            10: "🎉 Идеально! Поделитесь секретом!"
        }
        
        response = mood_responses.get(mood, "Спасибо за оценку!")
        update.message.reply_text(f"{response}\n\n📊 Данные сохранены в таблицу!")
        
    except ValueError:
        update.message.reply_text("❌ Оценка должна быть числом от 1 до 10")

def energy_command(update: Update, context: CallbackContext):
    """Оценка уровня энергии"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Оцените ваш уровень энергии от 1 до 10:\n"
            "/energy 1 - совсем нет сил\n"
            "/energy 5 - средний уровень\n"
            "/energy 10 - полон энергии!"
        )
        return
    
    try:
        energy = int(context.args[0])
        if energy < 1 or energy > 10:
            update.message.reply_text("❌ Оценка должна быть от 1 до 10")
            return
        
        # Сохраняем оценку энергии
        progress_data = {
            'energy': energy,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
        # ДОПОЛНИТЕЛЬНО: Сохраняем в Google Sheets
        sheets_manager.save_daily_data(user_id, "самочувствие", f"{energy}/10")
        
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
        update.message.reply_text(f"{response}\n\n📊 Данные сохранены в таблицу!")
        
    except ValueError:
        update.message.reply_text("❌ Оценка должна быть числом от 1 до 10")

# ========== НОВЫЕ КОМАНДЫ ДЛЯ ТРЕКИНГА ==========

def water_command(update: Update, context: CallbackContext):
    """Отслеживание водного баланса"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Укажите количество стаканов: /water 6\n\n"
            "Пример: /water 8 - выпито 8 стаканов воды"
        )
        return
    
    try:
        water = int(context.args[0])
        if water < 0 or water > 20:
            update.message.reply_text("❌ Укажите разумное количество стаканов (0-20)")
            return
        
        # Сохраняем в основную базу
        progress_data = {
            'water_intake': water,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
        # ДОПОЛНИТЕЛЬНО: Сохраняем в Google Sheets
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
        update.message.reply_text(f"{response}\n\n📊 Данные сохранены в таблицу!")
        
    except ValueError:
        update.message.reply_text("❌ Количество должно быть числом")

def medication_command(update: Update, context: CallbackContext):
    """Отслеживание приема лекарств"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Укажите лекарство: /medication витамин С\n\n"
            "Пример: /medication принял аспирин"
        )
        return
    
    medication = " ".join(context.args)
    
    # Сохраняем в Google Sheets
    sheets_manager.save_daily_data(user_id, "лекарства", medication)
    update.message.reply_text(f"💊 Информация о лекарствах сохранена!\n\n📊 Данные записаны в таблицу")

def habit_command(update: Update, context: CallbackContext):
    """Отслеживание привычек"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Укажите привычку: /habit без сахара\n\n"
            "Пример: /habit не ел сладкое"
        )
        return
    
    habit = " ".join(context.args)
    sheets_manager.save_daily_data(user_id, "привычки", habit)
    update.message.reply_text(f"🔄 Привычка сохранена!\n\n📊 Данные записаны в таблицу")

def development_command(update: Update, context: CallbackContext):
    """Отслеживание развития"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Укажите что изучили: /development изучил Python\n\n"
            "Пример: /development прочитал книгу"
        )
        return
    
    development = " ".join(context.args)
    sheets_manager.save_daily_data(user_id, "развитие", development)
    update.message.reply_text(f"📚 Развитие сохранено!\n\n📊 Данные записаны в таблицу")

def progress_note_command(update: Update, context: CallbackContext):
    """Отслеживание прогресса по целям"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Укажите прогресс: /progress_note изучил Python\n\n"
            "Пример: /progress_note прочитал 50 страниц"
        )
        return
    
    progress = " ".join(context.args)
    sheets_manager.save_daily_data(user_id, "прогресс", progress)
    update.message.reply_text(f"📈 Прогресс сохранен!\n\n📊 Данные записаны в таблицу")

def note_command(update: Update, context: CallbackContext):
    """Добавление примечаний"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Добавьте примечание: /note устал сегодня\n\n"
            "Пример: /note сегодня был продуктивный день"
        )
        return
    
    note = " ".join(context.args)
    sheets_manager.save_daily_data(user_id, "примечание", note)
    update.message.reply_text(f"📝 Примечание сохранено!\n\n📊 Данные записаны в таблицу")

def balance_command(update: Update, context: CallbackContext):
    """Оценка баланса дня"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        update.message.reply_text(
            "❌ Оцените баланс: /balance хороший\n\n"
            "Пример: /balance сбалансированный день"
        )
        return
    
    balance = " ".join(context.args)
    sheets_manager.save_daily_data(user_id, "баланс", balance)
    update.message.reply_text(f"⚖️ Баланс дня сохранен!\n\n📊 Данные записаны в таблицу")

# ========== КОМАНДЫ ДЛЯ НАПОМИНАНИЙ ==========

def remind_command(update: Update, context: CallbackContext):
    """Установка разового напоминания"""
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) < 2:
        update.message.reply_text(
            "❌ Формат команды:\n"
            "/remind ВРЕМЯ ТЕКСТ\n\n"
            "💡 Примеры:\n"
            "/remind 20:00 принять лекарство\n"
            "/remind 09:30 позвонить врачу\n"
            "/remind 14:00 сделать зарядку\n\n"
            "⏰ Время в формате ЧЧ:MM (24-часовой)"
        )
        return
    
    time_str = context.args[0]
    reminder_text = " ".join(context.args[1:])
    
    # Проверяем формат времени
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        update.message.reply_text(
            "❌ Неправильный формат времени.\n"
            "Используйте: ЧЧ:MM (например, 20:00 или 09:30)"
        )
        return
    
    success = reminder_system.set_custom_reminder(user_id, time_str, reminder_text)
    
    if success:
        update.message.reply_text(
            f"✅ Напоминание установлено на {time_str}:\n"
            f"📝 {reminder_text}\n\n"
            f"Я пришлю уведомление в указанное время!"
        )
    else:
        update.message.reply_text("❌ Не удалось установить напоминание")

def reminders_command(update: Update, context: CallbackContext):
    """Показывает активные напоминания"""
    user_id = update.effective_user.id
    
    user_reminders = []
    for job_name, job_data in reminder_system.active_reminders.items():
        if job_data['user_id'] == user_id:
            if job_data['type'] == 'custom':
                user_reminders.append(f"⏰ {job_data['time']}: {job_data['text']}")
            else:
                user_reminders.append(f"🔄 {job_data['time']}: {job_data['type']}")
    
    if user_reminders:
        update.message.reply_text(
            "📋 Ваши напоминания:\n\n" + "\n".join(user_reminders) +
            "\n\n⚙️ Изменить настройки: /reminder_settings"
        )
    else:
        update.message.reply_text(
            "📭 У вас нет активных напоминаний\n\n"
            "⚙️ Настроить автоматические: /reminder_settings\n"
            "⏰ Установить разовое: /remind"
        )

def reminder_settings_command(update: Update, context: CallbackContext):
    """Настройка напоминаний"""
    return reminder_system.setup_reminders(update, context)

def cancel_reminder_setup(update: Update, context: CallbackContext):
    """Отмена настройки напоминаний"""
    update.message.reply_text(
        "❌ Настройка напоминаний отменена.\n\n"
        "Вы всегда можете настроить их позже: /reminder_settings"
    )
    return ConversationHandler.END

# ========== КОМАНДЫ ДЛЯ АДМИНИСТРАТОРА ==========

def create_plan_command(update: Update, context: CallbackContext):
    """Создает индивидуальный план для пользователя (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 1:
        update.message.reply_text(
            "❌ Укажите ID пользователя:\n"
            "/create_plan <user_id>\n\n"
            "Пример: /create_plan 123456789"
        )
        return
    
    user_id = context.args[0]
    
    try:
        # Получаем информацию о пользователе
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name, username FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_name, username = user_data
        
        # Здесь ассистент должен вручную создать план
        update.message.reply_text(
            f"📋 Создание плана для пользователя:\n"
            f"👤 Имя: {user_name}\n"
            f"🔗 Username: @{username if username else 'нет'}\n"
            f"🆔 ID: {user_id}\n\n"
            f"Для создания плана используйте команду:\n"
            f"<code>/set_plan {user_id} утренний_ритуал1|утренний_ритуал2|задача1|задача2|задача3|задача4|обед|вечерний_ритуал1|вечерний_ритуал2|совет|сон|вода|активность</code>\n\n"
            f"Пример:\n"
            f"<code>/set_plan {user_id} Медитация|Зарядка|Работа над проектом|Изучение Python|Чтение книги|Прогулка|13:00-14:00|Выключение гаджетов|Чтение|Отлично начали!|23:00|8 стаканов|Йога 30 мин</code>",
            parse_mode='HTML'
        )
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {e}")

def set_plan_command(update: Update, context: CallbackContext):
    """Устанавливает план для пользователя (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 2:
        update.message.reply_text(
            "❌ Неправильный формат команды.\n\n"
            "Использование:\n"
            "/set_plan <user_id> утренний_ритуал1|утренний_ритуал2|задача1|задача2|задача3|задача4|обед|вечерний_ритуал1|вечерний_ритуал2|совет|сон|вода|активность\n\n"
            "Пример:\n"
            "/set_plan 123456789 Медитация|Зарядка|Работа|Учеба|Чтение|Прогулка|13:00-14:00|Выключение гаджетов|Чтение|Молодец!|23:00|8 стаканов|Йога"
        )
        return
    
    user_id = context.args[0]
    plan_parts = " ".join(context.args[1:]).split("|")
    
    if len(plan_parts) < 13:
        update.message.reply_text("❌ Недостаточно частей плана. Нужно 13 частей, разделенных |")
        return
    
    try:
        # Получаем информацию о пользователе
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_name = user_data[0]
        
        # Создаем план
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
        
        # Сохраняем в базу данных
        save_user_plan_to_db(user_id, plan_data)
        
        # Сохраняем в Google Sheets
        save_plan_to_sheets(user_id, user_name, plan_data)
        
        # Отправляем уведомление пользователю
        try:
            context.bot.send_message(
                chat_id=user_id,
                text="🎉 Ваш индивидуальный план готов!\n\n"
                     "Посмотреть его можно командой: /my_plan\n\n"
                     "Ассистент составил для вас персональный план на основе вашей анкеты. "
                     "Удачи в выполнении! 💪"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
        
        update.message.reply_text(
            f"✅ Индивидуальный план для {user_name} создан и сохранен!\n\n"
            f"Пользователь получил уведомление.\n\n"
            f"Для просмотра прогресса: /view_progress {user_id}"
        )
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка создания плана: {e}")

def view_progress_command(update: Update, context: CallbackContext):
    """Показывает прогресс пользователя (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 1:
        update.message.reply_text(
            "❌ Укажите ID пользователя:\n"
            "/view_progress <user_id>\n\n"
            "Пример: /view_progress 123456789"
        )
        return
    
    user_id = context.args[0]
    
    try:
        # Получаем информацию о пользователе
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name, username, registration_date FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        
        if not user_data:
            update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_name, username, reg_date = user_data
        
        # Получаем прогресс
        c.execute('''SELECT progress_date, mood, energy, tasks_completed, user_comment 
                     FROM user_progress 
                     WHERE user_id = ? 
                     ORDER BY progress_date DESC LIMIT 7''', (user_id,))
        progress_data = c.fetchall()
        
        conn.close()
        
        progress_text = f"📊 Прогресс пользователя:\n\n"
        progress_text += f"👤 Имя: {user_name}\n"
        progress_text += f"🔗 Username: @{username if username else 'нет'}\n"
        progress_text += f"🆔 ID: {user_id}\n"
        progress_text += f"📅 Зарегистрирован: {reg_date}\n\n"
        
        if progress_data:
            progress_text += "Последние оценки:\n"
            for progress in progress_data:
                date, mood, energy, tasks, comment = progress
                progress_text += f"📅 {date}: Настроение {mood}/10, Энергия {energy}/10"
                if tasks:
                    progress_text += f", Задач: {tasks}"
                if comment:
                    progress_text += f"\n   💬 {comment}"
                progress_text += "\n"
        else:
            progress_text += "📭 Данные о прогрессе отсутствуют\n\n"
        
        progress_text += f"\n💡 Команды:\n"
        progress_text += f"/create_plan {user_id} - создать новый план\n"
        progress_text += f"/get_questionnaire {user_id} - посмотреть анкету"
        
        update.message.reply_text(progress_text)
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {e}")

# ========== РАССЫЛКИ И СИСТЕМНЫЕ КОМАНДЫ ==========

def send_daily_plan(context: CallbackContext):
    """Отправляет ежедневный план всем зарегистрированным пользователям"""
    try:
        logger.info("🕘 Запуск ежедневной рассылки...")
        
        with sqlite3.connect('clients.db') as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM clients WHERE status = 'active'")
            active_users = c.fetchall()
        
        logger.info(f"📊 Найдено активных пользователей: {len(active_users)}")
        
        success_count = 0
        error_count = 0
        
        for user in active_users:
            try:
                user_id = user[0]
                plan = get_user_plan_from_db(user_id)
                
                if plan:
                    # Пользователь имеет индивидуальный план
                    message_text = "🌅 Доброе утро! Ваш индивидуальный план готов: /my_plan"
                else:
                    # Стандартное уведомление
                    message_text = "🌅 Доброе утро! Ваш план на сегодня готов к просмотру: /plan"
                
                context.bot.send_message(chat_id=user_id, text=message_text)
                success_count += 1
                time.sleep(0.1)
                
            except Exception as e:
                error_count += 1
                logger.error(f"Ошибка отправки уведомления пользователю {user[0]}: {e}")
        
        logger.info(f"✅ Рассылка завершена: {success_count} успешно, {error_count} ошибок")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в ежедневной рассылке: {e}")

def test_daily(update: Update, context: CallbackContext):
    """Тестовая команда для проверки рассылки (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    update.message.reply_text("🔄 Запуск тестовой рассылки...")
    send_daily_plan(context)
    update.message.reply_text("✅ Тестовая рассылка завершена!")

def job_info(update: Update, context: CallbackContext):
    """Показывает информацию о запланированных заданиях (для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    try:
        updater = context.dispatcher.updater
        job_queue = updater.job_queue
        
        if not job_queue:
            update.message.reply_text("❌ JobQueue не доступен")
            return
        
        jobs = job_queue.jobs()
        if not jobs:
            update.message.reply_text("📭 Нет активных заданий в JobQueue")
            return
        
        info = "📋 Активные задания JobQueue:\n\n"
        for i, job in enumerate(jobs, 1):
            info += f"{i}. {job.name or 'Без имени'}\n"
            if hasattr(job, 'next_t') and job.next_t:
                info += f"   Следующий запуск: {job.next_t}\n"
            info += f"   Интервал: {getattr(job, 'interval', 'Неизвестно')}\n\n"
        
        info += f"🕐 Текущее время сервера: {datetime.now()}"
        
        update.message.reply_text(info)
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка получения информации: {e}")

def setup_jobs(update: Update, context: CallbackContext):
    """Принудительно настраивает JobQueue (для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    try:
        updater = context.dispatcher.updater
        job_queue = updater.job_queue
        
        if not job_queue:
            update.message.reply_text("❌ JobQueue не доступен")
            return
        
        # Очищаем старые задания
        current_jobs = job_queue.jobs()
        for job in current_jobs:
            job.schedule_removal()
        
        # Добавляем новое задание
        job_queue.run_daily(
            send_daily_plan,
            time=dt_time(hour=6, minute=0),  # 9:00 по Москве (UTC+3)
            days=tuple(range(7)),
            name="daily_plan_notification"
        )
        
        # Тестовое задание через 1 минуту
        job_queue.run_once(
            lambda ctx: logger.info("🧪 Тестовое задание выполнено!"),
            60,
            name="test_job"
        )
        
        update.message.reply_text(
            "✅ JobQueue перезапущен!\n\n"
            "📅 Ежедневные уведомления настроены на 9:00 по Москве\n"
            "🧪 Тестовое задание запланировано через 1 минуту\n\n"
            "Используйте /jobinfo для проверки"
        )
        logger.info("JobQueue принудительно перезапущен через команду /setup_jobs")
        
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка настройки JobQueue: {e}")

def admin_stats(update: Update, context: CallbackContext):
    """Статистика для администратора"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    # Общая статистика
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
    
    update.message.reply_text(stats_text)

def get_questionnaire(update: Update, context: CallbackContext):
    """Получает анкету пользователя (для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 1:
        update.message.reply_text(
            "❌ Неправильный формат команды.\n\n"
            "✅ Использование:\n"
            "<code>/get_questionnaire &lt;user_id&gt;</code>\n\n"
            "💡 Пример:\n"
            "<code>/get_questionnaire 12345678</code>",
            parse_mode='HTML'
        )
        return
    
    user_id = context.args[0]
    
    try:
        with sqlite3.connect('clients.db') as conn:
            c = conn.cursor()
            
            # Получаем информацию о пользователе
            c.execute("SELECT first_name, last_name, username FROM clients WHERE user_id = ?", (user_id,))
            user_data = c.fetchone()
            
            if not user_data:
                update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден.")
                return
            
            first_name, last_name, username = user_data
            
            # Получаем ответы на анкету
            c.execute('''SELECT question_number, question_text, answer_text, answer_date 
                         FROM questionnaire_answers 
                         WHERE user_id = ? 
                         ORDER BY question_number''', (user_id,))
            answers = c.fetchall()
        
        # Фильтруем ответы, убирая вопрос №0
        visible_answers = [a for a in answers if a[0] != 0]
        if not visible_answers:
            update.message.reply_text(f"❌ Пользователь {first_name} еще не заполнял анкету или нет видимых ответов.")
            return
        
        # Формируем анкету
        questionnaire = f"📋 Анкета пользователя:\n\n"
        questionnaire += f"👤 Имя: {first_name}\n"
        if last_name:
            questionnaire += f"📛 Фамилия: {last_name}\n"
        if username:
            questionnaire += f"🔗 Username: @{username}\n"
        questionnaire += f"🆔 ID: {user_id}\n\n"
        questionnaire += "📝 Ответы:\n\n"
        
        for answer in visible_answers:
            question_num, question_text, answer_text, answer_date = answer
            questionnaire += f"❓ {question_num}. {question_text}:\n"
            questionnaire += f"💬 {answer_text}\n"
            questionnaire += f"🕐 {answer_date}\n\n"
        
        # Разбиваем на части если нужно
        max_length = 4096
        if len(questionnaire) > max_length:
            parts = [questionnaire[i:i+max_length] for i in range(0, len(questionnaire), max_length)]
            for i, part in enumerate(parts):
                update.message.reply_text(f"📄 Часть {i+1}:\n\n{part}")
        else:
            update.message.reply_text(questionnaire)
            
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка получения анкеты: {e}")
        logger.exception(f"Ошибка получения анкеты пользователя {user_id}")

def send_to_user(update: Update, context: CallbackContext):
    """Отправляет сообщение пользователю от имени ассистента"""
    # Проверяем, что команду отправляет администратор
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    # Извлекаем ID пользователя и сообщение из команды
    if not context.args or len(context.args) < 2:
        update.message.reply_text(
            "❌ Неправильный формат команды.\n\n"
            "✅ Использование:\n"
            "<code>/send &lt;user_id&gt; Ваше сообщение</code>\n\n"
            "💡 Пример:\n"
            "<code>/send 12345678 Привет! Как твои успехи?</code>",
            parse_mode='HTML'
        )
        return
    
    user_id = context.args[0]
    message = " ".join(context.args[1:])
    
    try:
        # Сохраняем исходящее сообщение
        save_message(user_id, message, 'outgoing')
        
        # Отправляем сообщение пользователю
        context.bot.send_message(
            chat_id=user_id, 
            text=f"💌 Сообщение от вашего ассистента:\n\n{message}\n\n"
                 f"💬 Чтобы ответить, просто напишите сообщение."
        )
        update.message.reply_text("✅ Сообщение отправлено пользователю!")
        
        # Логируем действие
        logger.info(f"Администратор отправил сообщение пользователю {user_id}: {message}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка отправки: {e}"
        update.message.reply_text(error_msg)
        logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

def handle_all_messages(update: Update, context: CallbackContext):
    """Обработчик для всех входящих сообщений"""
    # Пропускаем команды
    if update.message.text and update.message.text.startswith('/'):
        return
    
    user = update.effective_user
    user_id = user.id
    
    # Обновляем активность пользователя
    update_user_activity(user_id)
    
    # Если пользователь не зарегистрирован, предлагаем начать
    if not check_user_registered(user_id):
        update.message.reply_text(
            "👋 Для начала работы с персональным ассистентом отправьте команду /start"
        )
        return
    
    message_text = update.message.text or "Сообщение без текста"
    
    # Сохраняем входящее сообщение
    save_message(user_id, message_text, 'incoming')
    
    # Формируем сообщение для администратора
    user_info = f"📩 Новое сообщение от пользователя:\n"
    user_info += f"👤 ID: {user.id}\n"
    user_info += f"📛 Имя: {user.first_name}\n"
    if user.last_name:
        user_info += f"📛 Фамилия: {user.last_name}\n"
    if user.username:
        user_info += f"🔗 Username: @{user.username}\n"
    user_info += f"💬 Текст: {message_text}\n"
    user_info += f"🕐 Время: {update.message.date.strftime('%Y-%m-%d %H:%M')}\n"
    
    # Получаем статистику пользователя
    stats = get_user_stats(user_id)
    user_info += f"\n📊 Статистика пользователя:\n"
    user_info += f"📨 Сообщений: {stats['messages_count']}\n"
    user_info += f"📅 Зарегистрирован: {stats['registration_date']}\n"
    
    # Добавляем кнопку для ответа
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Ответить пользователю", callback_data=f"reply_{user.id}")],
        [InlineKeyboardButton("👁️ Просмотреть анкету", callback_data=f"view_questionnaire_{user.id}")],
        [InlineKeyboardButton("📊 Статистика пользователя", callback_data=f"stats_{user.id}")]
    ])
    
    # Отправляем сообщение администратору
    try:
        context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=user_info,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        update.message.reply_text("✅ Ваше сообщение отправлено ассистенту! Ответим в ближайшее время.")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения администратору: {e}")
        update.message.reply_text("❌ Произошла ошибка при отправке сообщения. Попробуйте позже.")

def button_callback(update: Update, context: CallbackContext):
    """Обработчик callback кнопок"""
    query = update.callback_query
    query.answer()
    
    if query.data.startswith('reply_'):
        user_id = query.data.replace('reply_', '')
        context.user_data['reply_user_id'] = user_id
        query.edit_message_text(
            text=f"💌 Ответ пользователю\n\n"
                 f"👤 ID пользователя: {user_id}\n\n"
                 f"📝 Чтобы ответить, используйте команду:\n"
                 f"<code>/send {user_id} ваш текст сообщения</code>",
            parse_mode='HTML'
        )
    
    elif query.data.startswith('view_questionnaire_'):
        user_id = query.data.replace('view_questionnaire_', '')
        query.edit_message_text(
            text=f"📋 Просмотр анкеты пользователя {user_id}\n\n"
                 f"📝 Для просмотра анкеты используйте команду:\n"
                 f"<code>/get_questionnaire {user_id}</code>",
            parse_mode='HTML'
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
            
            query.edit_message_text(
                text=f"📊 Статистика пользователя:\n\n"
                     f"👤 Имя: {user_name}\n"
                     f"🆔 ID: {user_id}\n"
                     f"📅 Регистрация: {reg_date}\n"
                     f"📨 Сообщений: {stats['messages_count']}\n\n"
                     f"💌 Чтобы ответить:\n"
                     f"<code>/send {user_id} ваш текст</code>\n\n"
                     f"📋 Создать план:\n"
                     f"<code>/create_plan {user_id}</code>",
                parse_mode='HTML'
            )
    
    elif query.data.startswith('create_plan_'):
        user_id = query.data.replace('create_plan_', '')
        query.edit_message_text(
            text=f"📋 Создание плана для пользователя {user_id}\n\n"
                 f"Используйте команду:\n"
                 f"<code>/create_plan {user_id}</code>",
            parse_mode='HTML'
        )

def cancel(update: Update, context: CallbackContext) -> int:
    """Отмена диалога"""
    update.message.reply_text(
        '❌ Диалог прерван. Чтобы начать заново, отправьте /start',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def error_handler(update: Update, context: CallbackContext):
    """Обрабатывает ошибки в боте"""
    logger.error(msg="Исключение при обработке обновления:", exc_info=context.error)
    
    # Обрабатываем ошибку Conflict
    if "Conflict" in str(context.error):
        logger.warning("🔄 Обнаружена ошибка Conflict - другой экземпляр бота уже запущен")
        return
    
    # Для других ошибок можно отправить сообщение пользователю
    try:
        if update and update.effective_message:
            update.effective_message.reply_text(
                "❌ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

def main():
    """Основная функция запуска бота"""
    try:
        # Создание Updater (для версии 13.x)
        updater = Updater(TOKEN, use_context=True)
        
        # Получаем диспетчер для регистрации обработчиков
        dp = updater.dispatcher

        # Инициализация системы напоминаний
        global reminder_system
        reminder_system = SmartReminderSystem(updater)

        # Добавляем обработчик ошибок
        dp.add_error_handler(error_handler)

        # Обработчики для напоминаний
        reminder_conv = ConversationHandler(
            entry_points=[
                CommandHandler('reminder_settings', reminder_settings_command),
                MessageHandler(Filters.regex('^(⚙️ Настроить напоминания)$'), reminder_settings_command)
            ],
            states={
                "REMINDER_SETUP": [
                    MessageHandler(Filters.text & ~Filters.command, reminder_system.handle_reminder_setup)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel_reminder_setup)]
        )

        # Настройка обработчика диалога
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [MessageHandler(Filters.regex('^(👨 Мужской|👩 Женский|Мужской|Женский)$'), gender_choice)],
                FIRST_QUESTION: [MessageHandler(Filters.text & ~Filters.command, handle_question)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        dp.add_handler(conv_handler)
        dp.add_handler(reminder_conv)
        
        # Добавляем обработчики для команд
        dp.add_handler(CommandHandler("plan", plan_command))
        dp.add_handler(CommandHandler("progress", progress_command))
        dp.add_handler(CommandHandler("profile", profile_command))
        dp.add_handler(CommandHandler("chat", chat_command))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("stats", admin_stats))
        dp.add_handler(CommandHandler("send", send_to_user))
        dp.add_handler(CommandHandler("get_questionnaire", get_questionnaire))
        dp.add_handler(CommandHandler("questionnaire", questionnaire_command))
        dp.add_handler(CommandHandler("test_daily", test_daily))
        dp.add_handler(CommandHandler("jobinfo", job_info))
        dp.add_handler(CommandHandler("setup_jobs", setup_jobs))
        
        # Команды для пользователей
        dp.add_handler(CommandHandler("my_plan", my_plan_command))
        dp.add_handler(CommandHandler("done", done_command))
        dp.add_handler(CommandHandler("mood", mood_command))
        dp.add_handler(CommandHandler("energy", energy_command))
        
        # Новые команды для данных
        dp.add_handler(CommandHandler("water", water_command))
        dp.add_handler(CommandHandler("medication", medication_command))
        dp.add_handler(CommandHandler("habit", habit_command))
        dp.add_handler(CommandHandler("development", development_command))
        dp.add_handler(CommandHandler("progress_note", progress_note_command))
        dp.add_handler(CommandHandler("note", note_command))
        dp.add_handler(CommandHandler("balance", balance_command))
        
        # Команды для напоминаний
        dp.add_handler(CommandHandler("remind", remind_command))
        dp.add_handler(CommandHandler("reminders", reminders_command))
        
        # Команды для администратора
        dp.add_handler(CommandHandler("create_plan", create_plan_command))
        dp.add_handler(CommandHandler("set_plan", set_plan_command))
        dp.add_handler(CommandHandler("view_progress", view_progress_command))
        
        # Добавляем обработчик для callback кнопок
        dp.add_handler(CallbackQueryHandler(button_callback))
        
        # Добавляем обработчик для всех сообщений
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_all_messages))
        
        # Настройка PLANNER
        try:
            job_queue = updater.job_queue
            if job_queue:
                # Очищаем возможные старые задания
                current_jobs = job_queue.jobs()
                for job in current_jobs:
                    job.schedule_removal()
                
                # Добавляем новое задание с правильным временем
                job_queue.run_daily(
                    send_daily_plan,
                    time=dt_time(hour=6, minute=0),  # 9:00 по Москве (UTC+3)
                    days=tuple(range(7)),
                    name="daily_plan_notification"
                )
                
                # Логируем информацию о задании
                logger.info("✅ JobQueue НАСТРОЕН для ежедневных уведомлений")
                logger.info(f"🕘 Время уведомлений: 9:00 по Москве (6:00 UTC)")
                
                # Дополнительная проверка - создаем тестовое задание через 2 минуты
                job_queue.run_once(
                    lambda ctx: logger.info("🧪 Тест JobQueue: планировщик работает!"), 
                    120,
                    name="test_job_queue"
                )
                
            else:
                logger.error("❌ JobQueue не доступен - планировщик не работает!")
                
        except Exception as e:
            logger.error(f"❌ Критическая ошибка настройки JobQueue: {e}")

        logger.info("🤖 Бот запускается...")
        
        # Запускаем бота
        updater.start_polling()
        updater.idle()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
