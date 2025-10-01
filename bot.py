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

# Google Sheets (опционально)
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
GOOGLE_SHEETS_CREDENTIALS = os.environ.get('GOOGLE_SHEETS_CREDENTIALS')

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
    
    # Таблица сообщений
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  message_text TEXT,
                  message_date TEXT,
                  direction TEXT)''')
    
    # Таблица настроек напоминаний
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
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# ========== GOOGLE SHEETS ==========

def init_google_sheets():
    """Инициализация Google Sheets"""
    if not GOOGLE_SHEETS_AVAILABLE:
        logger.warning("⚠️ Google Sheets не доступен")
        return None
    
    try:
        if GOOGLE_SHEETS_CREDENTIALS and os.path.exists(GOOGLE_SHEETS_CREDENTIALS):
            scope = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS, scopes=scope)
        else:
            credentials_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
            if credentials_json:
                creds_dict = json.loads(credentials_json)
                scope = ['https://www.googleapis.com/auth/spreadsheets']
                creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            else:
                logger.warning("⚠️ Google Sheets credentials не найдены")
                return None
        
        client = gspread.authorize(creds)
        
        try:
            sheet = client.open("Планы_пользователей_бота")
        except gspread.SpreadsheetNotFound:
            sheet = client.create("Планы_пользователей_бота")
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
            
            worksheet2 = sheet.add_worksheet(title="Планы", rows=1000, cols=20)
            worksheet2.append_row([
                "ID", "Имя", "Дата плана", "Статус", "Утренний ритуал 1",
                "Утренний ритуал 2", "Задача 1", "Задача 2", "Задача 3",
                "Задача 4", "Обеденный перерыв", "Вечерний ритуал 1",
                "Вечерний ритуал 2", "Совет ассистента", "Время сна",
                "Вода", "Физ активность", "Примечания"
            ])
            
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
    logger.info(f"✅ Информация о пользователе {user_id} сохранена")

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

def save_questionnaire_to_sheets(user_id: int, user_data: Dict[str, Any], assistant_name: str, answers: Dict[int, str]):
    """Сохраняет анкету в Google Sheets"""
    if not google_sheet:
        return
    
    try:
        worksheet = google_sheet.worksheet("Анкеты")
        
        row_data = [
            user_id,
            user_data.get('first_name', ''),
            user_data.get('username', ''),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            assistant_name
        ]
        
        for i in range(1, 31):
            if i < len(QUESTIONS):
                answer = answers.get(i, '')
                if len(str(answer)) > 100:
                    answer = str(answer)[:100] + "..."
                row_data.append(answer)
            else:
                row_data.append('')
        
        worksheet.append_row(row_data)
        logger.info(f"✅ Анкета пользователя {user_id} сохранена в Google Sheets")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения анкеты в Google Sheets: {e}")

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
        logger.info(f"✅ План пользователя {user_id} сохранен в Google Sheets")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения плана в Google Sheets: {e}")

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
                
            credentials_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
            if not credentials_json:
                logger.warning("⚠️ GOOGLE_CREDENTIALS_JSON не найден")
                return None
            
            creds_dict = json.loads(credentials_json)
            scope = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            self.client = gspread.authorize(creds)
            
            SPREADSHEET_ID = os.environ.get('GOOGLE_SHEETS_ID')
            if not SPREADSHEET_ID:
                logger.warning("⚠️ GOOGLE_SHEETS_ID не найден")
                return None
            
            self.sheet = self.client.open_by_key(SPREADSHEET_ID)
            logger.info("✅ Google Sheets менеджер подключен")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
            return None
    
    def save_daily_data(self, user_id: int, data_type: str, value: str) -> bool:
        """Сохраняет ежедневные данные"""
        try:
            worksheet = self.sheet.worksheet("планы октябрь")
            today = datetime.now().strftime("%d.%m.%Y")
            
            records = worksheet.get_all_records()
            row_index = None
            
            for i, record in enumerate(records, start=2):
                if (str(record.get('ID клиента', '')) == str(user_id) and 
                    record.get('дата', '') == today):
                    row_index = i
                    break
            
            if not row_index:
                user_info = self.get_user_info(user_id)
                if not user_info:
                    return False
                
                new_row = [user_id, user_info['first_name'], today]
                new_row.extend([""] * 17)
                worksheet.append_row(new_row)
                
                records = worksheet.get_all_records()
                for i, record in enumerate(records, start=2):
                    if (str(record.get('ID клиента', '')) == str(user_id) and 
                        record.get('дата', '') == today):
                        row_index = i
                        break
            
            if not row_index:
                return False
            
            column_mapping = {
                'настроение': 12,
                'самочувствие': 13,
                'водный_баланс': 14,
                'привычки': 15,
                'лекарства': 16,
                'развитие': 17,
                'прогресс': 18,
                'примечание': 19,
                'баланс': 11,
                'напоминание': 20
            }
            
            if data_type in column_mapping:
                col_index = column_mapping[data_type]
                cell = worksheet.cell(row_index, col_index)
                
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
        """Получает информацию о пользователе"""
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name, username FROM clients WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        
        if result:
            return {'first_name': result[0], 'username': result[1]}
        return None

sheets_manager = GoogleSheetsManager()

# ========== СИСТЕМА НАПОМИНАНИЙ ==========

class SmartReminderSystem:
    def __init__(self, application):
        self.application = application
        self.reminder_settings = {}
        self.active_reminders = {}
    
    def load_user_settings(self, user_id: int) -> Dict[str, bool]:
        """Загружает настройки напоминаний пользователя"""
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        
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
    
    async def setup_reminders(self, update: Update, context: CallbackContext):
        """Настройка автоматических напоминаний"""
        user_id = update.effective_user.id
        
        settings = self.load_user_settings(user_id)
        context.user_data['reminder_settings'] = settings
        context.user_data['reminder_setup_step'] = 0
        
        await update.message.reply_text(
            "🔔 Давайте настроим автоматические напоминания!\n\n"
            "Я могу напоминать вам о важных вещах в течение дня.\n\n"
            "Отвечайте 'да' или 'нет' на каждый пункт.\n\n"
            "Начнем? Нужны ли вам напоминания об утренних ритуалах в 8:00?"
        )
        
        return "REMINDER_SETUP"
    
    async def handle_reminder_setup(self, update: Update, context: CallbackContext):
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
            
            if user_response in ['да', 'yes', 'нужно', 'хочу']:
                settings[current_type] = True
                response = "✅ Хорошо, буду напоминать!"
            elif user_response in ['нет', 'no', 'не нужно', 'не надо']:
                settings[current_type] = False
                response = "❌ Хорошо, не буду напоминать."
            else:
                await update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'")
                return "REMINDER_SETUP"
            
            context.user_data['reminder_setup_step'] += 1
            
            if step + 1 < len(reminder_types):
                next_type, next_text, after_text = reminder_types[step + 1]
                await update.message.reply_text(
                    f"{response}\n\nНужны ли вам напоминания о {after_text}"
                )
            else:
                self.save_user_settings(user_id, settings)
                self.schedule_reminders(user_id, settings)
                
                enabled_reminders = [rt[1] for rt in reminder_types if settings[rt[0]]]
                
                if enabled_reminders:
                    reminders_text = "\n".join([f"• {reminder}" for reminder in enabled_reminders])
                    await update.message.reply_text(
                        f"🎉 Напоминания настроены!\n\n"
                        f"Я буду напоминать вам о:\n{reminders_text}\n\n"
                        f"Вы всегда можете изменить настройки: /reminder_settings"
                    )
                else:
                    await update.message.reply_text(
                        "❌ Автоматические напоминания отключены.\n\n"
                        "Вы можете настроить их позже: /reminder_settings"
                    )
                
                return ConversationHandler.END
        
        return "REMINDER_SETUP"
    
    def schedule_reminders(self, user_id: int, settings: Dict[str, bool]):
        """Планирует автоматические напоминания"""
        reminder_times = {
            'morning_rituals': [(8, 0)],
            'evening_rituals': [(21, 0)],
            'medications': [(9, 0), (20, 0)],
            'water': [(10, 0), (13, 0), (16, 0), (19, 0)],
            'activity': [(11, 0)],
            'rest': [(15, 0)],
            'progress_check': [(19, 0)]
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
        
        for job_name in list(self.active_reminders.keys()):
            if job_name.startswith(f"auto_{user_id}_"):
                try:
                    job = self.application.job_queue.get_jobs_by_name(job_name)
                    if job:
                        job[0].schedule_removal()
                    del self.active_reminders[job_name]
                except:
                    pass
        
        for reminder_type, enabled in settings.items():
            if enabled and reminder_type in reminder_times:
                for time_tuple in reminder_times[reminder_type]:
                    hour, minute = time_tuple
                    
                    job_name = f"auto_{user_id}_{reminder_type}_{hour}_{minute}"
                    
                    try:
                        self.application.job_queue.run_daily(
                            callback=self.send_auto_reminder,
                            time=dt_time(hour=hour-3, minute=minute),
                            days=tuple(range(7)),
                            name=job_name,
                            data={'user_id': user_id, 'text': reminder_texts[reminder_type]}
                        )
                        
                        self.active_reminders[job_name] = {
                            'user_id': user_id,
                            'type': reminder_type,
                            'time': f"{hour:02d}:{minute:02d}"
                        }
                        
                        logger.info(f"✅ Автонапоминание установлено: {user_id} - {reminder_type}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка установки автонапоминания: {e}")
    
    async def send_auto_reminder(self, context: CallbackContext):
        """Отправляет автоматическое напоминание"""
        try:
            user_id = context.job.data['user_id']
            text = context.job.data['text']
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔔 НАПОМИНАНИЕ:\n\n{text}"
            )
            
            sheets_manager.save_daily_data(user_id, "напоминание", f"Авто: {text}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки автонапоминания: {e}")
    
    def set_custom_reminder(self, user_id: int, reminder_time: str, text: str) -> bool:
        """Устанавливает кастомное напоминание"""
        try:
            remind_time = datetime.strptime(reminder_time, "%H:%M").time()
            now = datetime.now().time()
            
            remind_datetime = datetime.combine(datetime.now().date(), remind_time)
            if remind_time < now:
                remind_datetime += timedelta(days=1)
            
            delay = (remind_datetime - datetime.now()).total_seconds()
            
            if delay < 0:
                return False
            
            sheets_manager.save_daily_data(user_id, "напоминание", 
                                         f"Кастом: {reminder_time} - {text}")
            
            job_name = f"custom_{user_id}_{datetime.now().timestamp()}"
            
            self.application.job_queue.run_once(
                callback=self.send_custom_reminder,
                when=delay,
                name=job_name,
                data={'user_id': user_id, 'text': text}
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
    
    async def send_custom_reminder(self, context: CallbackContext):
        """Отправляет кастомное напоминание"""
        try:
            user_id = context.job.data['user_id']
            text = context.job.data['text']
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔔 ВАШЕ НАПОМИНАНИЕ:\n\n{text}"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка отправки напоминания: {e}")

# Глобальный экземпляр системы напоминаний
reminder_system = None

# ========== ОСНОВНЫЕ КОМАНДЫ ==========

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
        keyboard = [['⚙️ Настроить напоминания', '📋 Мой план']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "✅ Вы уже зарегистрированы!\n\n"
            "🔔 Хотите настроить автоматические напоминания?",
            reply_markup=reply_markup
        )
        
        context.user_data['waiting_for_reminder_setup'] = True
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
    
    if google_sheet:
        user_data = {
            'first_name': user.first_name,
            'username': user.username
        }
        save_questionnaire_to_sheets(user.id, user_data, assistant_name, context.user_data['answers'])
    
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
    
    await update.message.reply_text(
        "🎉 Спасибо за ответы!\n\n"
        "✅ Я передал всю информацию нашему специалисту. В течение 24 часов он проанализирует ваши данные и составит для вас индивидуальный план.\n\n"
        "🔔 Теперь у вас есть доступ к персональному ассистенту!\n\n"
        "📋 Доступные команды:\n"
        "/my_plan - Ваш индивидуальный план\n"
        "/plan - Общий план на сегодня\n"
        "/progress - Статистика прогресса\n"
        "/chat - Связь с ассистентом\n"
        "/help - Помощь\n"
        "/profile - Ваш профиль"
    )
    
    return ConversationHandler.END

# ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ==========

async def plan_command(update: Update, context: CallbackContext):
    """Показывает текущий план пользователя"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    await update.message.reply_text(
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
        "💡 Для корректировки плана напишите ассистенту!"
    )

async def progress_command(update: Update, context: CallbackContext):
    """Показывает статистику прогресса"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    stats = get_user_stats(user_id)
    
    await update.message.reply_text(
        f"📊 Ваша статистика прогресса:\n\n"
        f"✅ Выполнено задач за неделю: 18/25 (72%)\n"
        f"🏃 Физическая активность: 4/5 дней\n"
        f"📚 Обучение: 6/7 часов\n"
        f"💤 Сон в среднем: 7.2 часа\n"
        f"📨 Сообщений ассистенту: {stats['messages_count']}\n"
        f"📅 С нами с: {stats['registration_date']}\n\n"
        f"🎯 Отличные результаты! Продолжайте в том же духе!"
    )

async def profile_command(update: Update, context: CallbackContext):
    """Показывает профиль пользователя"""
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
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
    profile_text += f"💎 Статус: Активный пользователь"
    
    await update.message.reply_text(profile_text)

async def chat_command(update: Update, context: CallbackContext):
    """Начинает чат с ассистентом"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    await update.message.reply_text(
        "💬 Чат с ассистентом открыт!\n\n"
        "📝 Напишите ваш вопрос или сообщение, и ассистент ответит вам в ближайшее время.\n\n"
        "⏰ Обычно ответ занимает не более 15-30 минут в рабочее время (9:00 - 18:00)."
    )

async def help_command(update: Update, context: CallbackContext):
    """Показывает справку по командам"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    help_text = "ℹ️ Справка по командам:\n\n"
    
    help_text += "🔹 Основные команды:\n"
    help_text += "/start - Начать работу с ботом\n"
    help_text += "/my_plan - Индивидуальный план\n"
    help_text += "/plan - Общий план на сегодня\n"
    help_text += "/progress - Статистика прогресса\n"
    help_text += "/profile - Ваш профиль\n"
    help_text += "/chat - Связаться с ассистентом\n"
    help_text += "/help - Эта справка\n\n"
    
    help_text += "🔹 Команды для отслеживания:\n"
    help_text += "/done <1-4> - Отметить задачу выполненной\n"
    help_text += "/mood <1-10> - Оценить настроение\n"
    help_text += "/energy <1-10> - Оценить уровень энергии\n"
    help_text += "/water <стаканы> - Отслеживание воды\n\n"
    
    help_text += "💡 Просто напишите сообщение, чтобы связаться с ассистентом!"
    
    await update.message.reply_text(help_text)

async def my_plan_command(update: Update, context: CallbackContext):
    """Показывает индивидуальный план пользователя"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    plan = get_user_plan_from_db(user_id)
    
    if not plan:
        await update.message.reply_text(
            "📋 Индивидуальный план еще не готов.\n\n"
            "Наш ассистент анализирует вашу анкету и скоро составит для вас "
            "персональный план. Обычно это занимает до 24 часов.\n\n"
            "А пока вы можете посмотреть общий план: /plan"
        )
        return
    
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
    
    await update.message.reply_text(plan_text)

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

# ========== КОМАНДЫ НАПОМИНАНИЙ ==========

async def remind_command(update: Update, context: CallbackContext):
    """Установка разового напоминания"""
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Формат команды:\n"
            "/remind ВРЕМЯ ТЕКСТ\n\n"
            "💡 Примеры:\n"
            "/remind 20:00 принять лекарство\n"
            "/remind 09:30 позвонить врачу\n\n"
            "⏰ Время в формате ЧЧ:MM (24-часовой)"
        )
        return
    
    time_str = context.args[0]
    reminder_text = " ".join(context.args[1:])
    
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "❌ Неправильный формат времени.\n"
            "Используйте: ЧЧ:MM (например, 20:00 или 09:30)"
        )
        return
    
    success = reminder_system.set_custom_reminder(user_id, time_str, reminder_text)
    
    if success:
        await update.message.reply_text(
            f"✅ Напоминание установлено на {time_str}:\n"
            f"📝 {reminder_text}\n\n"
            f"Я пришлю уведомление в указанное время!"
        )
    else:
        await update.message.reply_text("❌ Не удалось установить напоминание")

async def reminders_command(update: Update, context: CallbackContext):
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
        await update.message.reply_text(
            "📋 Ваши напоминания:\n\n" + "\n".join(user_reminders) +
            "\n\n⚙️ Изменить настройки: /reminder_settings"
        )
    else:
        await update.message.reply_text(
            "📭 У вас нет активных напоминаний\n\n"
            "⚙️ Настроить автоматические: /reminder_settings\n"
            "⏰ Установить разовое: /remind"
        )

async def reminder_settings_command(update: Update, context: CallbackContext):
    """Настройка напоминаний"""
    return await reminder_system.setup_reminders(update, context)

async def cancel_reminder_setup(update: Update, context: CallbackContext):
    """Отмена настройки напоминаний"""
    await update.message.reply_text(
        "❌ Настройка напоминаний отменена.\n\n"
        "Вы всегда можете настроить их позже: /reminder_settings"
    )
    return ConversationHandler.END

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
        save_plan_to_sheets(user_id, user_name, plan_data)
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 Ваш индивидуальный план готов!\n\n"
                     "Посмотреть его можно командой: /my_plan\n\n"
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

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

async def handle_all_messages(update: Update, context: CallbackContext):
    """Обработчик для всех входящих сообщений"""
    if update.message.text and update.message.text.startswith('/'):
        return
    
    user = update.effective_user
    user_id = user.id
    
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text(
            "👋 Для начала работы с персональным ассистентом отправьте команду /start"
        )
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
                 f"/send {user_id} ваш текст сообщения"
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
            
            await query.edit_message_text(
                text=f"📊 Статистика пользователя:\n\n"
                     f"👤 Имя: {user_name}\n"
                     f"🆔 ID: {user_id}\n"
                     f"📅 Регистрация: {reg_date}\n"
                     f"📨 Сообщений: {stats['messages_count']}\n\n"
                     f"💌 Чтобы ответить:\n"
                     f"/send {user_id} ваш текст\n\n"
                     f"📋 Создать план:\n"
                     f"/create_plan {user_id}"
            )
    
    elif query.data.startswith('create_plan_'):
        user_id = query.data.replace('create_plan_', '')
        await query.edit_message_text(
            text=f"📋 Создание плана для пользователя {user_id}\n\n"
                 f"Используйте команду:\n"
                 f"/create_plan {user_id}"
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
        
        global reminder_system
        reminder_system = SmartReminderSystem(application)

        application.add_error_handler(error_handler)

        # Обработчики для напоминаний
        reminder_conv = ConversationHandler(
            entry_points=[
                CommandHandler('reminder_settings', reminder_settings_command),
                MessageHandler(filters.Regex('^(⚙️ Настроить напоминания)$'), reminder_settings_command)
            ],
            states={
                "REMINDER_SETUP": [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_system.handle_reminder_setup)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel_reminder_setup)]
        )

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
        application.add_handler(reminder_conv)
        
        # Основные команды
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("chat", chat_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("stats", admin_stats))
        application.add_handler(CommandHandler("send", send_to_user))
        application.add_handler(CommandHandler("questionnaire", start))
        
        # Команды для пользователей
        application.add_handler(CommandHandler("my_plan", my_plan_command))
        application.add_handler(CommandHandler("done", done_command))
        application.add_handler(CommandHandler("mood", mood_command))
        application.add_handler(CommandHandler("energy", energy_command))
        application.add_handler(CommandHandler("water", water_command))
        
        # Команды для напоминаний
        application.add_handler(CommandHandler("remind", remind_command))
        application.add_handler(CommandHandler("reminders", reminders_command))
        
        # Команды для администратора
        application.add_handler(CommandHandler("create_plan", create_plan_command))
        application.add_handler(CommandHandler("set_plan", set_plan_command))
        
        # Обработчики кнопок и сообщений
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
        
        # Настройка JobQueue
        try:
            job_queue = application.job_queue
            if job_queue:
                current_jobs = job_queue.jobs()
                for job in current_jobs:
                    job.schedule_removal()
                
                job_queue.run_daily(
                    lambda ctx: logger.info("✅ Ежедневная проверка..."),
                    time=dt_time(hour=6, minute=0),
                    days=tuple(range(7)),
                    name="daily_check"
                )
                
                logger.info("✅ JobQueue настроен")
                
        except Exception as e:
            logger.error(f"❌ Ошибка настройки JobQueue: {e}")

        logger.info("🤖 Бот запускается...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
