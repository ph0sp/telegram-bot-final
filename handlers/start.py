import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackContext

from config import QUESTIONS, YOUR_CHAT_ID, logger
from database import (
    save_user_info, update_user_activity,
    save_questionnaire_answer, get_db_connection
)
from services.google_sheets import save_client_to_sheets

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start с восстановлением состояния"""
    user = update.effective_user
    user_id = user.id
    
    logger.info(f"🔍 Пользователь {user_id} запустил /start")
    
    save_user_info(user_id, user.username, user.first_name, user.last_name)
    update_user_activity(user_id)
    
    # Восстанавливаем состояние анкеты
    questionnaire_state = restore_questionnaire_state(user_id)
    
    logger.info(f"📋 Состояние анкеты для {user_id}: "
               f"current_question={questionnaire_state['current_question']}, "
               f"has_answers={questionnaire_state['has_previous_answers']}")
    
    # Если анкета полностью заполнена
    if questionnaire_state['current_question'] >= len(QUESTIONS):
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
        
    # Если анкета заполнена частично
    elif questionnaire_state['has_previous_answers']:
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
        return 2  # RESTORE_CHOICE
        
    else:
        # Новая анкета
        keyboard = [['👨 Мужской', '👩 Женский']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности.\n\n'
            'Для начала выберите пол ассистента:',
            reply_markup=reply_markup
        )
        
        return 0  # GENDER

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
    
    # Отправляем приветствие одним сообщением
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
    
    # Отправляем ПЕРВЫЙ вопрос отдельным сообщением
    await update.message.reply_text(QUESTIONS[0])
    return 1  # FIRST_QUESTION

async def handle_restore_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор продолжения анкеты (продолжить или начать заново)"""
    choice = update.message.text
    user_id = update.effective_user.id
    questionnaire_state = context.user_data.get('questionnaire_state', {})
    
    if choice == '✅ Продолжить анкету':
        # Восстанавливаем данные из базы
        context.user_data['current_question'] = questionnaire_state['current_question']
        context.user_data['answers'] = questionnaire_state['answers']
        context.user_data['assistant_name'] = 'Антон'  # По умолчанию
        
        # Отправляем ТОЛЬКО текущий вопрос
        await update.message.reply_text(
            QUESTIONS[questionnaire_state['current_question']],
            reply_markup=ReplyKeyboardRemove()
        )
        
        return 1  # FIRST_QUESTION
        
    elif choice == '🔄 Начать заново':
        # Очищаем старые ответы
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM questionnaire_answers WHERE user_id = %s", 
                    (user_id,)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка удаления ответов: {e}")
        
        # Начинаем заново
        context.user_data['current_question'] = 0
        context.user_data['answers'] = {}
        
        # Отправляем ПЕРВЫЙ вопрос
        await update.message.reply_text(
            QUESTIONS[0],
            reply_markup=ReplyKeyboardRemove()
        )
        
        return 1  # FIRST_QUESTION
        
    else:
        await update.message.reply_text("❌ Операция отменена.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

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
    
    # Проверяем, есть ли еще вопросы
    if context.user_data['current_question'] < len(QUESTIONS):
        # Отправляем СЛЕДУЮЩИЙ вопрос
        await update.message.reply_text(QUESTIONS[context.user_data['current_question']])
        return 1  # FIRST_QUESTION
    else:
        # Анкета завершена
        return await finish_questionnaire(update, context)

async def finish_questionnaire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает анкету и отправляет данные"""
    user = update.effective_user
    assistant_name = context.user_data.get('assistant_name', 'Ассистент')
    
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
    
    for i in range(len(QUESTIONS)):
        answer = context.user_data['answers'].get(i, '❌ Нет ответа')
        short_question = QUESTIONS[i][:100] + "..." if len(QUESTIONS[i]) > 100 else QUESTIONS[i]
        questionnaire += f"❓ {i+1}. {short_question}:\n"
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

def restore_questionnaire_state(user_id: int) -> dict:
    """Восстанавливает состояние анкеты пользователя из PostgreSQL"""
    try:
        with get_db_connection() as conn:
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
                answers[row[0]] = row[1]  # row[0] - question_number, row[1] - answer_text
            
            if answers:
                # Находим ПЕРВЫЙ неотвеченный вопрос
                current_question = 0
                for i in range(len(QUESTIONS)):
                    if i not in answers:
                        current_question = i
                        break
                else:
                    # Все вопросы отвечены
                    current_question = len(QUESTIONS)
                
                logger.info(f"📊 Восстановлено состояние анкеты для {user_id}: "
                           f"отвечено {len(answers)} вопросов, текущий вопрос: {current_question}")
                
                return {
                    'current_question': current_question,
                    'answers': answers,
                    'has_previous_answers': True
                }
            
            return {'current_question': 0, 'answers': {}, 'has_previous_answers': False}
            
    except Exception as e:
        logger.error(f"❌ Ошибка БД при восстановлении анкеты {user_id}: {e}")
        return {'current_question': 0, 'answers': {}, 'has_previous_answers': False}
