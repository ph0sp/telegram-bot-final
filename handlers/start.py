import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackContext

from config import QUESTIONS, YOUR_CHAT_ID, logger, GENDER, FIRST_QUESTION
from database import (
    save_user_info, update_user_activity, check_user_registered,
    save_questionnaire_answer, save_message, get_db_connection
)
from services.google_sheets import save_client_to_sheets

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    logger.info(f"🎯 КОМАНДА /start ВЫЗВАНА пользователем {user_id} ({user.first_name})")
    
    save_user_info(user_id, user.username, user.first_name, user.last_name)
    update_user_activity(user_id)
    
    # Очищаем предыдущие ответы (новая анкета каждый раз)
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM questionnaire_answers WHERE user_id = %s", 
                (user_id,)
            )
            conn.commit()
            logger.info(f"✅ Очищены предыдущие ответы для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка очистки ответов: {e}")
    
    # КНОПКИ С ВАШИМИ СМАЙЛИКАМИ
    keyboard = [['🧌 Мужской', '🧝🏽‍♀️ Женский']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    logger.info(f"📨 Отправляем выбор пола пользователю {user_id}")
    
    await update.message.reply_text(
        '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности.\n\n'
        'Для начала выберите пол ассистента:',
        reply_markup=reply_markup
    )
    
    # Инициализируем данные анкеты
    context.user_data['current_question'] = -1  # -1 означает этап "Готовы начать?"
    context.user_data['answers'] = {}
    
    logger.info(f"🔁 Возвращаем состояние GENDER ({GENDER}) для пользователя {user_id}")
    
    return GENDER

async def gender_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик выбора пола ассистента"""
    user_id = update.effective_user.id
    user_text = update.message.text
    
    logger.info(f"🎭 Пользователь {user_id} выбрал: {user_text}")
    
    # Обрабатываем ВАШИ смайлики
    gender = user_text.replace('🧌 ', '').replace('🧝🏽‍♀️ ', '')
    
    if gender == 'Мужской':
        assistant_name = 'Антон'
        greeting_emoji = '🧌'
    else:
        assistant_name = 'Валерия'
        greeting_emoji = '🧝🏽‍♀️'
    
    context.user_data['assistant_gender'] = gender
    context.user_data['assistant_name'] = assistant_name
    context.user_data['greeting_emoji'] = greeting_emoji
    
    logger.info(f"✅ Выбран пол: {gender}, ассистент: {assistant_name}")
    
    # Приветствие как в вашем примере
    await update.message.reply_text(
        f'{greeting_emoji} Привет! Меня зовут {assistant_name}. Я ваш персональный ассистент.\n\n'
        f'Моя задача – помочь структурировать ваш день для максимальной продуктивности и достижения целей без стресса и выгорания.\n\n'
        f'Я составлю для вас сбалансированный план на месяц, а затем мы будем ежедневно отслеживать прогресс и ваше состояние, '
        f'чтобы вы двигались к цели уверенно и эффективно и с заботой о главных ресурсах: сне, спорте и питании.\n\n'
        f'Для составления плана, который будет работать именно для вас, мне нужно понять ваш ритм жизни и цели. '
        f'Это займет около 25-30 минут. Но в результате вы получите персональную стратегию на месяц, а не шаблонный список дел.\n\n'
        f'Готовы начать?',
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Устанавливаем, что следующий шаг - подтверждение готовности
    context.user_data['current_question'] = -1
    
    logger.info(f"🔁 Возвращаем состояние FIRST_QUESTION: {FIRST_QUESTION}")
    return FIRST_QUESTION

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик ответов на вопросы анкеты"""
    user_id = update.effective_user.id
    answer_text = update.message.text
    
    current_question = context.user_data['current_question']
    logger.info(f"🔍 Обрабатываем вопрос #{current_question}: {answer_text[:50]}...")
    
    # Если это этап "Готовы начать?" (current_question = -1)
    if current_question == -1:
        # Любой ответ считается согласием - начинаем анкету
        logger.info(f"✅ Пользователь подтвердил начало анкеты: {answer_text}")
        
        # Отправляем вступительное сообщение и ПЕРВЫЙ вопрос
        await update.message.reply_text(
            "Давайте начнем!\n"
            "Последовательно отвечайте на вопросы в свободной форме, как вам удобно.\n"
            "Начнем с самого главного\n\n"
            "Блок 1: Цель и главный фокус"
        )
        
        # Отправляем ПЕРВЫЙ вопрос (индекс 0 в массиве QUESTIONS)
        await update.message.reply_text(QUESTIONS[0])
        
        # Переходим к первому вопросу
        context.user_data['current_question'] = 0
        return FIRST_QUESTION
    
    # Сохраняем ответ на текущий вопрос
    save_questionnaire_answer(user_id, current_question, QUESTIONS[current_question], answer_text)
    context.user_data['answers'][current_question] = answer_text
    
    # Переходим к следующему вопросу
    next_question = current_question + 1
    
    if next_question < len(QUESTIONS):
        # Отправляем следующий вопрос
        context.user_data['current_question'] = next_question
        await update.message.reply_text(QUESTIONS[next_question])
        return FIRST_QUESTION
    else:
        # Анкета завершена
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
        'main_goal': context.user_data['answers'].get(0, ''),
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

async def cancel(update: Update, context: CallbackContext) -> int:
    """Отменяет текущий диалог"""
    await update.message.reply_text(
        '❌ Операция отменена.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END
