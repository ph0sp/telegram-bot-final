import os
import logging
import sqlite3
import asyncio
import time
from datetime import datetime, time
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler
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

# Инициализация Google Sheets
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
            import json
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

# Инициализация базы данных SQLite
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

# Определяем состояния диалога
GENDER, FIRST_QUESTION = range(2)

# Список вопросов (полная версия)
questions = [
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
    "Есть ли у вас ограничения по здоровью, которые нужно учитывать при планировании нагрузок?",
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

def save_user_info(user_id, username, first_name, last_name=None):
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

def update_user_activity(user_id):
    """Обновляет время последней активности пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    last_activity = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''UPDATE clients SET last_activity = ? WHERE user_id = ?''',
              (last_activity, user_id))
    conn.commit()
    conn.close()

def check_user_registered(user_id):
    """Проверяет зарегистрирован ли пользователь"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM clients WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def save_questionnaire_answer(user_id, question_number, question_text, answer_text):
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

def save_message(user_id, message_text, direction):
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

def get_user_stats(user_id):
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

# Функции для работы с планами
def save_user_plan_to_db(user_id, plan_data):
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

def get_user_plan_from_db(user_id):
    """Получает текущий план пользователя из базы данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute('''SELECT * FROM user_plans 
                 WHERE user_id = ? AND status = 'active' 
                 ORDER BY created_date DESC LIMIT 1''', (user_id,))
    plan = c.fetchone()
    conn.close()
    
    return plan

def save_progress_to_db(user_id, progress_data):
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

# Функции для работы с Google Sheets
def save_questionnaire_to_sheets(user_id, user_data, assistant_name, answers):
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
            if i < len(questions):
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

def save_plan_to_sheets(user_id, user_name, plan_data):
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

# Функция для отправки ежедневных уведомлений
async def send_daily_plan(context: ContextTypes.DEFAULT_TYPE):
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
                
                await context.bot.send_message(chat_id=user_id, text=message_text)
                success_count += 1
                await asyncio.sleep(0.1)
                
            except Exception as e:
                error_count += 1
                logger.error(f"Ошибка отправки уведомления пользователю {user[0]}: {e}")
        
        logger.info(f"✅ Рассылка завершена: {success_count} успешно, {error_count} ошибок")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в ежедневной рассылке: {e}")

# ========== НОВЫЕ КОМАНДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========

async def my_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    # Индексы полей из базы данных
    plan_text = f"📋 Ваш индивидуальный план на {plan[2]}:\n\n"
    
    plan_text += "🌅 Утренние ритуалы:\n"
    if plan[4]: plan_text += f"• {plan[4]}\n"
    if plan[5]: plan_text += f"• {plan[5]}\n"
    
    plan_text += "\n🎯 Основные задачи:\n"
    if plan[6]: plan_text += f"1. {plan[6]}\n"
    if plan[7]: plan_text += f"2. {plan[7]}\n" 
    if plan[8]: plan_text += f"3. {plan[8]}\n"
    if plan[9]: plan_text += f"4. {plan[9]}\n"
    
    if plan[10]:
        plan_text += f"\n🍽 Обеденный перерыв: {plan[10]}\n"
    
    plan_text += "\n🌙 Вечерние ритуалы:\n"
    if plan[11]: plan_text += f"• {plan[11]}\n"
    if plan[12]: plan_text += f"• {plan[12]}\n"
    
    if plan[13]:
        plan_text += f"\n💡 Совет ассистента: {plan[13]}\n"
    
    if plan[14]:
        plan_text += f"\n💤 Рекомендуемое время сна: {plan[14]}\n"
    
    if plan[15]:
        plan_text += f"💧 Цель по воде: {plan[15]}\n"
    
    if plan[16]:
        plan_text += f"🏃 Активность: {plan[16]}\n"
    
    plan_text += "\n📝 Отмечайте выполнение командой /done <номер задачи>"
    plan_text += "\n😊 Оцените настроение: /mood <1-10>"
    plan_text += "\n⚡ Оцените энергию: /energy <1-10>"
    
    await update.message.reply_text(plan_text)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмечает выполнение задачи"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите номер задачи:\n"
            "/done 1 - отметить задачу 1 выполненной\n"
            "/done 2 - отметить задачу 2 выполненной\n"
            "и т.д."
        )
        return
    
    try:
        task_number = int(context.args[0])
        if task_number < 1 or task_number > 4:
            await update.message.reply_text("❌ Номер задачи должен быть от 1 до 4")
            return
        
        # Здесь можно сохранить отметку о выполнении в базу
        task_names = {1: "первую", 2: "вторую", 3: "третью", 4: "четвертую"}
        
        await update.message.reply_text(
            f"✅ Отлично! Вы выполнили {task_names[task_number]} задачу!\n"
            f"🎉 Продолжайте в том же духе!\n\n"
            f"Оцените свое состояние:\n"
            f"/mood <1-10> - ваше настроение\n"
            f"/energy <1-10> - уровень энергии"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Номер задачи должен быть числом")

async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        # Сохраняем оценку настроения
        progress_data = {
            'mood': mood,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
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
        await update.message.reply_text(f"{response}\n\nОцените также уровень энергии: /energy <1-10>")
        
    except ValueError:
        await update.message.reply_text("❌ Оценка должна быть числом от 1 до 10")

async def energy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        # Сохраняем оценку энергии
        progress_data = {
            'energy': energy,
            'progress_date': datetime.now().strftime("%Y-%m-%d")
        }
        save_progress_to_db(user_id, progress_data)
        
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
        await update.message.reply_text(response)
        
    except ValueError:
        await update.message.reply_text("❌ Оценка должна быть числом от 1 до 10")

# ========== НОВЫЕ КОМАНДЫ ДЛЯ АДМИНИСТРАТОРА ==========

async def create_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает индивидуальный план для пользователя (только для администратора)"""
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
        # Получаем информацию о пользователе
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name, username FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_name, username = user_data
        
        # Здесь ассистент должен вручную создать план
        # Покажем инструкцию для ассистента
        await update.message.reply_text(
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
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def set_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Устанавливает план для пользователя (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
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
        await update.message.reply_text("❌ Недостаточно частей плана. Нужно 13 частей, разделенных |")
        return
    
    try:
        # Получаем информацию о пользователе
        conn = sqlite3.connect('clients.db')
        c = conn.cursor()
        c.execute("SELECT first_name FROM clients WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        conn.close()
        
        if not user_data:
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
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
            f"Пользователь получил уведомление.\n\n"
            f"Для просмотра прогресса: /view_progress {user_id}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка создания плана: {e}")

async def view_progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает прогресс пользователя (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
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
            await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден")
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
        
        await update.message.reply_text(progress_text)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ========== СУЩЕСТВУЮЩИЕ ФУНКЦИИ (с улучшениями) ==========

async def test_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для проверки рассылки (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    await update.message.reply_text("🔄 Запуск тестовой рассылки...")
    await send_daily_plan(context)
    await update.message.reply_text("✅ Тестовая рассылка завершена!")

async def job_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о запланированных заданиях (для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    try:
        application = context.application
        job_queue = application.job_queue
        
        if not job_queue:
            await update.message.reply_text("❌ JobQueue не доступен")
            return
        
        jobs = list(job_queue.jobs())
        if not jobs:
            await update.message.reply_text("📭 Нет активных заданий в JobQueue")
            return
        
        info = "📋 Активные задания JobQueue:\n\n"
        for i, job in enumerate(jobs, 1):
            info += f"{i}. {job.name or 'Без имени'}\n"
            if hasattr(job, 'next_t') and job.next_t:
                info += f"   Следующий запуск: {job.next_t}\n"
            info += f"   Интервал: {getattr(job, 'interval', 'Неизвестно')}\n\n"
        
        info += f"🕐 Текущее время сервера: {datetime.now()}"
        
        await update.message.reply_text(info)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка получения информации: {e}")

async def setup_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно настраивает JobQueue (для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    try:
        application = context.application
        job_queue = application.job_queue
        
        if not job_queue:
            await update.message.reply_text("❌ JobQueue не доступен")
            return
        
        # Очищаем старые задания
        current_jobs = list(job_queue.jobs())
        for job in current_jobs:
            job.schedule_removal()
        
        # Добавляем новое задание
        job_queue.run_daily(
            send_daily_plan,
            time=time(hour=6, minute=0),  # 9:00 по Москве (UTC+3)
            days=tuple(range(7)),
            name="daily_plan_notification"
        )
        
        # Тестовое задание через 1 минуту
        job_queue.run_once(
            lambda ctx: logger.info("🧪 Тестовое задание выполнено!"),
            60,
            name="test_job"
        )
        
        await update.message.reply_text(
            "✅ JobQueue перезапущен!\n\n"
            "📅 Ежедневные уведомления настроены на 9:00 по Москве\n"
            "🧪 Тестовое задание запланировано через 1 минуту\n\n"
            "Используйте /jobinfo для проверки"
        )
        logger.info("JobQueue принудительно перезапущен через команду /setup_jobs")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка настройки JobQueue: {e}")

# Обработчик для всех входящих сообщений
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Пропускаем команды
    if update.message.text and update.message.text.startswith('/'):
        return
    
    user = update.effective_user
    user_id = user.id
    
    # Обновляем активность пользователя
    update_user_activity(user_id)
    
    # Если пользователь не зарегистрирован, предлагаем начать
    if not check_user_registered(user_id):
        await update.message.reply_text(
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
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=user_info,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        await update.message.reply_text("✅ Ваше сообщение отправлено ассистенту! Ответим в ближайшее время.")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения администратору: {e}")
        await update.message.reply_text("❌ Произошла ошибка при отправке сообщения. Попробуйте позже.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        await update.message.reply_text(
            "✅ Вы уже зарегистрированы!\n\n"
            "📋 Доступные команды:\n"
            "/my_plan - Ваш индивидуальный план\n"
            "/plan - Общий план на сегодня\n"
            "/progress - Статистика прогресса\n"
            "/chat - Связь с ассистентом\n"
            "/help - Помощь\n"
            "/questionnaire - Заполнить анкету заново\n"
            "/profile - Ваш профиль\n\n"
            "💡 Новые команды:\n"
            "/done <номер> - отметить задачу выполненной\n"
            "/mood <1-10> - оценить настроение\n"
            "/energy <1-10> - оценить уровень энергии"
        )
        return ConversationHandler.END
    
    keyboard = [['👨 Мужской', '👩 Женский']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности.\n\n'
        'Для начала выберите пол ассистента:',
        reply_markup=reply_markup
    )
    
    return GENDER

async def gender_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        f'👋 Привет! Меня зовут {assistant_name}. Я ваш персональный ассистент. '
        f'Моя задача – помочь структурировать ваш день для максимальной продуктивности и достижения целей без стресса и выгорания.\n\n'
        f'Я составлю для вас сбалансированный план на месяц, а затем мы будем ежедневно отслеживать прогресс и ваше состояние, '
        f'чтобы вы двигались к цели уверенно и эффективно и с заботой о главных ресурсах: сне, спорте и питании.\n\n'
        f'Для составления плана, который будет работать именно для вас, мне нужно понять ваш ритм жизни и цели. '
        f'Это займет около 25-30 минут. Но в результате вы получите персональную стратегию на месяц, а не шаблонный список дел.\n\n'
        f'{questions[0]}',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return FIRST_QUESTION

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    current_question = context.user_data['current_question']
    answer_text = update.message.text
    
    # Сохраняем ответ в базу данных
    save_questionnaire_answer(user_id, current_question, questions[current_question], answer_text)
    
    # Сохраняем ответ во временные данные
    context.user_data['answers'][current_question] = answer_text
    
    context.user_data['current_question'] += 1
    
    if context.user_data['current_question'] < len(questions):
        next_question = context.user_data['current_question']
        await update.message.reply_text(questions[next_question])
        return FIRST_QUESTION
    else:
        return await finish_questionnaire(update, context)

async def finish_questionnaire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    for i, question in enumerate(questions):
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
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=part)
            except Exception as e:
                logger.error(f"Ошибка отправки части анкеты: {e}")
    else:
        try:
            await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=questionnaire)
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
        
        await context.bot.send_message(
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
    await update.message.reply_text(
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

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "✅ Статус: 🔄 в процессе выполнения\n\n"
        "💡 Для корректировки плана напишите ассистенту!\n\n"
        "🎯 Если у вас есть индивидуальный план, используйте: /my_plan"
    )

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"🎯 Отличные результаты! Продолжайте в том же духе!\n\n"
        f"💡 Советы для улучшения:\n"
        f"• Старайтесь ложиться спать до 23:00\n"
        f"• Делайте перерывы каждые 45 минут работы\n"
        f"• Пейте больше воды в течение дня\n\n"
        f"📝 Отмечайте свой прогресс:\n"
        f"/mood <1-10> - оценить настроение\n"
        f"/energy <1-10> - оценить энергию"
    )

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    await update.message.reply_text(profile_text)

async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает чат с ассистентом"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    await update.message.reply_text(
        "💬 Чат с ассистентом открыт!\n\n"
        "📝 Напишите ваш вопрос или сообщение, и ассистент ответит вам в ближайшее время.\n\n"
        "⏰ Обычно ответ занимает не более 15-30 минут в рабочее время (9:00 - 18:00).\n\n"
        "🔔 Вы также можете просто писать сообщения без команды /chat - я всегда на связи!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    await update.message.reply_text(help_text)

async def questionnaire_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает анкету заново"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    # Сбрасываем состояние анкеты
    context.user_data.clear()
    
    keyboard = [['👨 Мужской', '👩 Женский']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        '🔄 Заполнение анкеты заново\n\n'
        'Выберите пол ассистента:',
        reply_markup=reply_markup
    )
    
    return GENDER

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика для администратора"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
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
    
    await update.message.reply_text(stats_text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('reply_'):
        user_id = query.data.replace('reply_', '')
        context.user_data['reply_user_id'] = user_id
        await query.edit_message_text(
            text=f"💌 Ответ пользователю\n\n"
                 f"👤 ID пользователя: {user_id}\n\n"
                 f"📝 Чтобы ответить, используйте команду:\n"
                 f"<code>/send {user_id} ваш текст сообщения</code>",
            parse_mode='HTML'
        )
    
    elif query.data.startswith('view_questionnaire_'):
        user_id = query.data.replace('view_questionnaire_', '')
        await query.edit_message_text(
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
            
            await query.edit_message_text(
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
        await query.edit_message_text(
            text=f"📋 Создание плана для пользователя {user_id}\n\n"
                 f"Используйте команду:\n"
                 f"<code>/create_plan {user_id}</code>",
            parse_mode='HTML'
        )

async def send_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение пользователю от имени ассистента"""
    # Проверяем, что команду отправляет администратор
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    # Извлекаем ID пользователя и сообщение из команды
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
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
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"💌 Сообщение от вашего ассистента:\n\n{message}\n\n"
                 f"💬 Чтобы ответить, просто напишите сообщение."
        )
        await update.message.reply_text("✅ Сообщение отправлено пользователю!")
        
        # Логируем действие
        logger.info(f"Администратор отправил сообщение пользователю {user_id}: {message}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка отправки: {e}"
        await update.message.reply_text(error_msg)
        logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")

async def get_questionnaire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает анкету пользователя (для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
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
                await update.message.reply_text(f"❌ Пользователь с ID {user_id} не найден.")
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
            await update.message.reply_text(f"❌ Пользователь {first_name} еще не заполнял анкету или нет видимых ответов.")
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
                await update.message.reply_text(f"📄 Часть {i+1}:\n\n{part}")
        else:
            await update.message.reply_text(questionnaire)
            
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка получения анкеты: {e}")
        logger.exception(f"Ошибка получения анкеты пользователя {user_id}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        '❌ Диалог прерван. Чтобы начать заново, отправьте /start',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ошибки в боте"""
    logger.error(msg="Исключение при обработке обновления:", exc_info=context.error)
    
    # Обрабатываем ошибку Conflict
    if "Conflict" in str(context.error):
        logger.warning("🔄 Обнаружена ошибка Conflict - другой экземпляр бота уже запущен")
        return
    
    # Для других ошибок можно отправить сообщение пользователю
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")

def main():
    """Основная функция запуска бота"""
    max_retries = 5
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Создание Application
            application = Application.builder().token(TOKEN).build()

            # Добавляем обработчик ошибок
            application.add_error_handler(error_handler)

            # Настройка обработчика диалога
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('start', start)],
                states={
                    GENDER: [MessageHandler(filters.Regex('^(👨 Мужской|👩 Женский|Мужской|Женский)$'), gender_choice)],
                    FIRST_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)],
                },
                fallbacks=[CommandHandler('cancel', cancel)],
            )

            application.add_handler(conv_handler)
            
            # Добавляем обработчики для команд
            application.add_handler(CommandHandler("plan", plan_command))
            application.add_handler(CommandHandler("progress", progress_command))
            application.add_handler(CommandHandler("profile", profile_command))
            application.add_handler(CommandHandler("chat", chat_command))
            application.add_handler(CommandHandler("help", help_command))
            application.add_handler(CommandHandler("stats", admin_stats))
            application.add_handler(CommandHandler("send", send_to_user))
            application.add_handler(CommandHandler("get_questionnaire", get_questionnaire))
            application.add_handler(CommandHandler("questionnaire", questionnaire_command))
            application.add_handler(CommandHandler("test_daily", test_daily))
            application.add_handler(CommandHandler("jobinfo", job_info))
            application.add_handler(CommandHandler("setup_jobs", setup_jobs))
            
            # НОВЫЕ КОМАНДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ
            application.add_handler(CommandHandler("my_plan", my_plan_command))
            application.add_handler(CommandHandler("done", done_command))
            application.add_handler(CommandHandler("mood", mood_command))
            application.add_handler(CommandHandler("energy", energy_command))
            
            # НОВЫЕ КОМАНДЫ ДЛЯ АДМИНИСТРАТОРА
            application.add_handler(CommandHandler("create_plan", create_plan_command))
            application.add_handler(CommandHandler("set_plan", set_plan_command))
            application.add_handler(CommandHandler("view_progress", view_progress_command))
            
            # Добавляем обработчик для callback кнопок
            application.add_handler(CallbackQueryHandler(button_callback))
            
            # Добавляем обработчик для всех сообщений
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
            
            # НАСТРОЙКА PLANNER
            try:
                job_queue = application.job_queue
                if job_queue:
                    # Очищаем возможные старые задания
                    current_jobs = list(job_queue.jobs())
                    for job in current_jobs:
                        job.schedule_removal()
                    
                    # Добавляем новое задание с правильным временем
                    job_queue.run_daily(
                        send_daily_plan,
                        time=time(hour=6, minute=0),  # 9:00 по Москве (UTC+3)
                        days=tuple(range(7)),  # Все дни недели
                        name="daily_plan_notification"
                    )
                    
                    # Логируем информацию о задании
                    logger.info("✅ JobQueue НАСТРОЕН для ежедневных уведомлений")
                    logger.info(f"🕘 Время уведомлений: 9:00 по Москве (6:00 UTC)")
                    
                    # Дополнительная проверка - создаем тестовое задание через 2 минуты
                    job_queue.run_once(
                        lambda context: logger.info("🧪 Тест JobQueue: планировщик работает!"), 
                        when=120,
                        name="test_job_queue"
                    )
                    
                else:
                    logger.error("❌ JobQueue не доступен - планировщик не работает!")
                    
            except Exception as e:
                logger.error(f"❌ Критическая ошибка настройки JobQueue: {e}")

            logger.info("🤖 Бот запускается...")
            
            # Запускаем бота с обработкой ошибок Conflict
            application.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                close_loop=False
            )
            
            # Если бот завершил работу нормально, выходим из цикла
            break
            
        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Ошибка запуска бота (попытка {retry_count}/{max_retries}): {e}")
            
            # Если это ошибка Conflict, ждем и пробуем снова
            if "Conflict" in str(e):
                if retry_count < max_retries:
                    wait_time = 10 * retry_count  # Увеличиваем задержку с каждой попыткой
                    logger.info(f"🔄 Перезапуск через {wait_time} секунд...")
                    time.sleep(wait_time)
                else:
                    logger.error("❌ Достигнут лимит попыток перезапуска из-за Conflict")
                    break
            else:
                # Для других ошибок выходим из цикла
                logger.error(f"❌ Неизвестная ошибка, завершение работы: {e}")
                break

if __name__ == '__main__':
    main()
