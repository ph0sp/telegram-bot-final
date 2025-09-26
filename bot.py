import os
import logging
import sqlite3
from datetime import datetime, timedelta, time
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
load_dotenv()  # Загружает переменные из .env файла

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
    c.execute('''CREATE TABLE IF NOT EXISTS clients
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT,
                  first_name TEXT,
                  status TEXT,
                  tariff TEXT,
                  payment_date TEXT,
                  expiry_date TEXT)''')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# Вызываем инициализацию базы данных при запуске
init_db()

# Определяем состояния диалога
GENDER, FIRST_QUESTION, PAYMENT, ACTIVATION = range(4)

# Список вопросов (ПОЛНЫЙ - все 27 вопросов)
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

# Функции для работы с базой данных
def save_payment_info(user_id, tariff):
    """Сохраняет информацию об оплате в базу данных"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    payment_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expiry_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT OR REPLACE INTO clients 
                 (user_id, status, tariff, payment_date, expiry_date) 
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id, 'active', tariff, payment_date, expiry_date))
    conn.commit()
    conn.close()
    logger.info(f"Сохранена информация об оплате для пользователя {user_id}")

def check_payment_status(user_id):
    """Проверяет активна ли подписка пользователя"""
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    c.execute("SELECT expiry_date FROM clients WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return False
    
    expiry_date = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
    return datetime.now() < expiry_date

# Функция для отправки ежедневных уведомлений
async def send_daily_plan(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет ежедневный план всем активным пользователям"""
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
    # Пропускаем команды и сообщения, которые уже обрабатываются ConversationHandler
    if update.message.text and update.message.text.startswith('/'):
        return
    
    user = update.effective_user
    user_id = user.id
    
    # Проверяем статус подписки пользователя
    if not check_payment_status(user_id):
        await update.message.reply_text(
            "🔒 Для доступа к персональному ассистенту необходимо оформить подписку: /pay\n\n"
            "После оплаты вы получите полный доступ ко всем функциям ассистента."
        )
        return
    
    message_text = update.message.text or "Сообщение без текста (возможно, медиафайл)"
    
    # Формируем сообщение для администратора
    user_info = f"Сообщение от пользователя:\n"
    user_info += f"ID: {user.id}\n"
    user_info += f"Имя: {user.first_name}\n"
    if user.last_name:
        user_info += f"Фамилия: {user.last_name}\n"
    if user.username:
        user_info += f"Username: @{user.username}\n"
    user_info += f"Текст: {message_text}\n\n"
    
    # Добавляем кнопку для ответа
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Ответить пользователю", callback_data=f"reply_{user.id}")]
    ])
    
    # Отправляем сообщение администратору
    try:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=user_info,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения администратору: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    
    # Проверяем, есть ли у пользователя активная подписка
    if check_payment_status(user_id):
        await update.message.reply_text(
            "✅ У вас есть активная подписка!\n\n"
            "Доступные команды:\n"
            "/plan - Ваш план на сегодня\n"
            "/progress - Статистика прогресса\n"
            "/chat - Связь с ассистентом\n"
            "/help - Помощь"
        )
        return ConversationHandler.END
    
    keyboard = [['Мужской', 'Женский']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        'Выберите пол ассистента:',
        reply_markup=reply_markup
    )
    
    return GENDER

async def gender_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gender = update.message.text
    context.user_data['assistant_gender'] = gender
    
    if gender == 'Мужской':
        assistant_name = 'Антон'
    else:
        assistant_name = 'Валерия'
    
    context.user_data['assistant_name'] = assistant_name
    context.user_data['current_question'] = 0
    context.user_data['answers'] = {}
    
    await update.message.reply_text(
        f'Привет! Меня зовут {assistant_name}. Я ваш персональный ассистент. Моя задача – помочь структурировать ваш день для максимальной продуктивности и достижения целей без стресса и выгорания.\n\nЯ составлю для вас сбалансированный план на месяц, а затем мы будем ежедневно отслеживать прогресс и ваше состояние, чтобы вы двигались к цели уверенно и эффективно и с заботой о главных ресурсах: сне, спорте и питании.\n\nДля составления плана, который будет работать именно для вас, мне нужно понять ваш ритм жизни и цели. Это займет около 25-30 минут. Но в результате вы получите персональную стратегию на месяц, а не шаблонный список дел.\n\n'
        f'{questions[0]}',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return FIRST_QUESTION

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    current_question = context.user_data['current_question']
    context.user_data['answers'][current_question] = update.message.text
    
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
    questionnaire = f"Новая анкета от пользователя:\n"
    questionnaire += f"ID: {user.id}\n"
    questionnaire += f"Имя: {user.first_name}\n"
    if user.last_name:
        questionnaire += f"Фамилия: {user.last_name}\n"
    if user.username:
        questionnaire += f"Username: @{user.username}\n"
    questionnaire += f"Дата заполнения: {update.message.date.strftime('%Y-%m-%d %H:%M')}\n\n"
    
    # Добавляем ответы на вопросы
    for i, question in enumerate(questions):
        if i == 0:  # Пропускаем первый вопрос "Готовы начать?"
            continue
        questionnaire += f"{i}. {question}:\n{context.user_data['answers'].get(i, 'Нет ответа')}\n\n"
    
    # Разбиваем анкету на части, если она слишком длинная
    max_length = 4096  # Максимальная длина сообщения в Telegram
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
    
    # Отправляем кнопку для ответа пользователю
    try:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Ответить пользователю", callback_data=f"reply_{user.id}")]
        ])
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=f"Чтобы ответить пользователю, используйте команду:\n/send {user.id} ваш текст",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка отправки кнопки ответа: {e}")
    
    # Отправляем сообщение пользователю с предложением оплатить
    await update.message.reply_text(
        "Спасибо за ответы!\n\n"
        "Я передал всю информацию нашему специалисту. В течение часа он проанализирует ваши данные и составит для вас индивидуальный план.\n\n"
        "Чтобы получить доступ к вашему персональному плану и начать работу с ассистентом, необходимо оформить подписку: /pay"
    )
    
    return ConversationHandler.END

# Новые функции для системы оплаты и подписки
async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /pay - показывает тарифы"""
    keyboard = [
        [InlineKeyboardButton("Месяц - 5 900 руб.", callback_data="pay_month")],
        [InlineKeyboardButton("3 месяца - 15 000 руб.", callback_data="pay_3months")],
        [InlineKeyboardButton("Тестовый день за 1 руб.", callback_data="pay_test")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💰 Выберите тариф подписки:\n\n"
        "• Месяц - 5 900 руб. (полный доступ ко всем функциям)\n"
        "• 3 месяца - 15 000 руб. (экономия 2 700 руб.)\n"
        "• Тестовый день - 1 руб. (ознакомительный доступ)\n\n"
        "После оплаты вы получите:\n"
        "✅ Персональный план на основе ваших целей\n"
        "✅ Ежедневное сопровождение ассистента\n"
        "✅ Еженедельные корректировки плана\n"
        "✅ Доступ ко всем инструментам планирования",
        reply_markup=reply_markup
    )

async def handle_payment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора тарифа оплаты"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    tariff = query.data
    
    # Сохраняем информацию об оплате в базу данных
    save_payment_info(user_id, tariff)
    
    # Определяем название тарифа для сообщения пользователю
    tariff_names = {
        "pay_month": "месячная подписка",
        "pay_3months": "подписка на 3 месяца", 
        "pay_test": "тестовый день"
    }
    
    tariff_name = tariff_names.get(tariff, "подписка")
    
    await query.edit_message_text(
        text=f"✅ Оплата прошла успешно! Активна {tariff_name}.\n\n"
             f"Теперь у вас есть доступ к персональному ассистенту.\n\n"
             f"Доступные команды:\n"
             f"/plan - Ваш план на сегодня\n"
             f"/progress - Статистика прогресса\n"
             f"/chat - Связь с ассистентом\n"
             f"/help - Помощь"
    )

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий план пользователя"""
    user_id = update.effective_user.id
    
    if not check_payment_status(user_id):
        await update.message.reply_text("❌ Доступ закрыт. Оформите подписку /pay")
        return
    
    # Здесь будет логика получения плана из базы данных
    # Пока используем заглушку
    await update.message.reply_text(
        "📋 Ваш план на сегодня:\n\n"
        "1. Работа над проектом - 3 часа\n"
        "2. Спорт - 45 минут\n"
        "3. Изучение английского - 30 минут\n"
        "4. Планирование следующего дня - 20 минут\n\n"
        "Статус: 🔄 в процессе\n\n"
        "Для связи с ассистентом используйте /chat"
    )

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику прогресса"""
    user_id = update.effective_user.id
    
    if not check_payment_status(user_id):
        await update.message.reply_text("❌ Доступ закрыт. Оформите подписку /pay")
        return
    
    await update.message.reply_text(
        "📊 Ваш прогресс за неделю:\n\n"
        "✅ Выполнено задач: 18/25 (72%)\n"
        "🏃 Физическая активность: 4/5 дней\n"
        "📚 Обучение: 6/7 часов\n"
        "💤 Сон в среднем: 7.2 часа\n\n"
        "Отличные результаты! Продолжайте в том же духе!"
    )

async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает чат с ассистентом"""
    user_id = update.effective_user.id
    
    if not check_payment_status(user_id):
        await update.message.reply_text("❌ Доступ закрыт. Оформите подписку /pay")
        return
    
    await update.message.reply_text(
        "💬 Чат с ассистентом открыт. Напишите ваш вопрос или сообщение, и ассистент ответит вам в ближайшее время.\n\n"
        "Обычно ответ занимает не более 15-30 минут в рабочее время."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает справку по командам"""
    await update.message.reply_text(
        "ℹ️ Доступные команды:\n\n"
        "/start - Начать работу с ботом\n"
        "/pay - Выбрать тариф и оплатить подписку\n"
        "/plan - Посмотреть ваш план на сегодня\n"
        "/progress - Статистика вашего прогресса\n"
        "/chat - Связаться с ассистентом\n"
        "/help - Эта справка\n\n"
        "По всем вопросам обращайтесь к вашему ассистенту через команду /chat"
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика для администратора"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("У вас нет прав для этой команды.")
        return
    
    conn = sqlite3.connect('clients.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM clients WHERE status = 'active'")
    active_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM clients")
    total_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM clients WHERE tariff = 'pay_month'")
    month_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM clients WHERE tariff = 'pay_3months'")
    months3_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM clients WHERE tariff = 'pay_test'")
    test_count = c.fetchone()[0]
    
    conn.close()
    
    await update.message.reply_text(
        f"📊 Статистика бота:\n\n"
        f"Активных подписок: {active_count}\n"
        f"Всего клиентов: {total_count}\n\n"
        f"По тарифам:\n"
        f"• Месяц: {month_count}\n"
        f"• 3 месяца: {months3_count}\n"
        f"• Тестовый: {test_count}\n\n"
        f"Доход в месяц: {active_count * 5900} руб.\n"
        f"Прогнозируемый годовой доход: {active_count * 5900 * 12} руб."
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('reply_'):
        user_id = query.data.replace('reply_', '')
        context.user_data['reply_user_id'] = user_id
        await query.edit_message_text(
            text=f"Чтобы ответить пользователю {user_id}, используйте команду:\n/send {user_id} ваш текст"
        )
    elif query.data.startswith('pay_'):
        await handle_payment_choice(update, context)

async def send_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, что команду отправляет администратор
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("У вас нет прав для этой команды.")
        return
    
    # Извлекаем ID пользователя и сообщение из команды
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /send <user_id> Ваше сообщение")
        return
    
    user_id = context.args[0]
    message = " ".join(context.args[1:])
    
    try:
        # Отправляем сообщение пользователю
        await context.bot.send_message(chat_id=user_id, text=f"💌 Сообщение от вашего ассистента:\n\n{message}")
        await update.message.reply_text("✅ Сообщение отправлено пользователю!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка отправки: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        'Диалог прерван. Чтобы начать заново, отправьте /start',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END

def main():
    try:
        # Создание Application
        application = Application.builder().token(TOKEN).build()

        # Настройка обработчика диалога
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [MessageHandler(filters.Regex('^(Мужской|Женский)$'), gender_choice)],
                FIRST_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        application.add_handler(conv_handler)
        
        # Добавляем обработчики для новых команд
        application.add_handler(CommandHandler("pay", pay_command))
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("chat", chat_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("stats", admin_stats))
        application.add_handler(CommandHandler("send", send_to_user))
        
        # Добавляем обработчик для callback кнопок
        application.add_handler(CallbackQueryHandler(button_callback))
        
        # Добавляем обработчик для всех сообщений (после остальных обработчиков)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
        
        # Настраиваем планировщик для ежедневных уведомлений с помощью JobQueue
        job_queue = application.job_queue
        
        # Добавляем ежедневную задачу на 9:00 утра
        job_queue.run_daily(send_daily_plan, time=time(hour=9, minute=0), days=(0, 1, 2, 3, 4, 5, 6))

        logger.info("Бот запускается...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
