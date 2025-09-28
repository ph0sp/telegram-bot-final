import os
import logging
import sqlite3
from datetime import datetime, time
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    JobQueue
)

from dotenv import load_dotenv
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

# Проверка наличия токена
if not TOKEN:
    logger.error("Токен бота не найден! Установите переменную BOT_TOKEN")
    exit(1)

if not YOUR_CHAT_ID:
    logger.error("Chat ID не найден! Установите переменную YOUR_CHAT_ID")
    exit(1)

# Инициализация базы данных
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
    
    # Таблица сообщений
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  message_text TEXT,
                  message_date TEXT,
                  direction TEXT,
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
    "Сколько времени вы обычно выделяете на приготовление еда?",
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

# Функция для отправки ежедневных уведомлений
async def send_daily_plan(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет ежедневный план всем зарегистрированным пользователям"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM clients WHERE status = 'active'")
    active_users = c.fetchall()
    conn.close()
    
    for user in active_users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text="🌅 Доброе утро! Ваш план на сегодня готов к просмотру: /plan"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {user[0]}: {e}")

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
        [InlineKeyboardButton("👁️ Просмотреть анкету", callback_data=f"view_questionnaire_{user.id}")]
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
            "/plan - Ваш план на сегодня\n"
            "/progress - Статистика прогресса\n"
            "/chat - Связь с ассистентом\n"
            "/help - Помощь\n"
            "/questionnaire - Заполнить анкету заново\n"
            "/profile - Ваш профиль"
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
            [InlineKeyboardButton("📊 Статистика пользователя", callback_data=f"stats_{user.id}")]
        ])
        
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=f"✅ Пользователь {user.first_name} завершил анкету!\n\n"
                 f"Чтобы ответить пользователю, используйте команду:\n"
                 f"<code>/send {user.id} ваш текст</code>",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Ошибка отправки кнопки ответа: {e}")
    
    # Отправляем сообщение пользователю
    await update.message.reply_text(
        "🎉 Спасибо за ответы!\n\n"
        "✅ Я передал всю информацию нашему специалисту. В течение часа он проанализирует ваши данные и составит для вас индивидуальный план.\n\n"
        "🔔 Теперь у вас есть доступ к персональному ассистенту!\n\n"
        "📋 Доступные команды:\n"
        "/plan - Ваш план на сегодня\n"
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
        "💡 Для корректировки плана напишите ассистенту!"
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
        f"• Пейте больше воды в течение дня"
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
    profile_text += f"/plan - Ваш план\n"
    profile_text += f"/progress - Статистика\n"
    profile_text += f"/questionnaire - Заполнить анкету заново\n"
    profile_text += f"/help - Помощь"
    
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
    
    await update.message.reply_text(
        "ℹ️ Справка по командам:\n\n"
        "🔹 Основные команды:\n"
        "/start - Начать работу с ботом (заполнить анкету)\n"
        "/plan - Посмотреть ваш план на сегодня\n"
        "/progress - Статистика вашего прогресса\n"
        "/profile - Ваш профиль\n"
        "/chat - Связаться с ассистентом\n"
        "/help - Эта справка\n\n"
        "🔹 Дополнительные команды:\n"
        "/questionnaire - Заполнить анкету заново\n\n"
        "💡 Просто напишите сообщение, чтобы связаться с ассистентом!\n\n"
        "📞 По всем вопросам обращайтесь к вашему ассистенту через команду /chat или просто напишите сообщение."
    )

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
    
    conn.close()
    
    stats_text = f"📊 Статистика бота:\n\n"
    stats_text += f"👥 Всего пользователей: {total_users}\n"
    stats_text += f"🟢 Активных сегодня: {active_today}\n"
    stats_text += f"📨 Всего сообщений: {total_messages}\n"
    stats_text += f"📝 Ответов в анкетах: {total_answers}\n\n"
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
        # Здесь можно добавить логику для просмотра анкеты пользователя
        await query.edit_message_text(
            text=f"📋 Просмотр анкеты пользователя {user_id}\n\n"
                 f"🔧 Функция в разработке...\n\n"
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
                     f"<code>/send {user_id} ваш текст</code>",
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

def main():
    """Основная функция запуска бота"""
    try:
        # Создание Application с JobQueue
        application = Application.builder().token(TOKEN).build()

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
        
        # Добавляем обработчик для callback кнопок
        application.add_handler(CallbackQueryHandler(button_callback))
        
        # Добавляем обработчик для всех сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
        
        # Настраиваем планировщик для ежедневных уведомлений
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_daily(send_daily_plan, time=time(hour=9, minute=0), days=(0, 1, 2, 3, 4, 5, 6))
            logger.info("✅ JobQueue настроен для ежедневных уведомлений")
        else:
            logger.warning("⚠️ JobQueue не доступен")

        logger.info("🤖 Бот запускается...")
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
