import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackContext

from config import QUESTIONS, YOUR_CHAT_ID, logger, GENDER, READY_CONFIRMATION, QUESTIONNAIRE
from database import (
    save_user_info, update_user_activity, check_user_registered,
    save_questionnaire_answer, save_message
)
from services.google_sheets import save_client_to_sheets

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start - ВСЕГДА начинает анкету заново"""
    try:
        user = update.effective_user
        user_id = user.id
        
        logger.info(f"🎯 НОВАЯ АНКЕТА /start пользователем {user_id} ({user.first_name})")
        
        # ВСЕГДА начинаем новую анкету - очищаем все предыдущие данные
        context.user_data.clear()
        
        # Сохраняем пользователя с обработкой ошибок (АСИНХРОННО)
        try:
            await save_user_info(user_id, user.username, user.first_name, user.last_name)
            await update_user_activity(user_id)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")
            # Продолжаем работу, так как это не критично для анкеты
        
        # КНОПКИ С ВАШИМИ СМАЙЛИКАМИ
        keyboard = [['🧌 Мужской', '🧝🏽‍♀️ Женский']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        logger.info(f"📨 Отправляем выбор пола пользователю {user_id}")
        
        await update.message.reply_text(
            '👋 Добро пожаловать! Я ваш персональный ассистент по продуктивности.\n\n'
            'Для начала выберите пол ассистента:',
            reply_markup=reply_markup
        )
        
        # Инициализируем данные для НОВОЙ анкеты
        context.user_data['current_question'] = -1
        context.user_data['answers'] = {}
        context.user_data['questionnaire_started'] = True
        context.user_data['questionnaire_id'] = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"🔁 Начинаем новую анкету, возвращаем состояние GENDER ({GENDER})")
        
        return GENDER
    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в /start: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при запуске. Пожалуйста, попробуйте еще раз или обратитесь к администратору."
        )
        return ConversationHandler.END

async def gender_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик выбора пола ассистента"""
    try:
        user_id = update.effective_user.id
        user_text = update.message.text
        
        logger.info(f"🎭 Пользователь {user_id} выбрал: {user_text}")
        
        # НАДЕЖНАЯ обработка выбора пола
        if 'Мужской' in user_text:
            gender = 'Мужской'
            assistant_name = 'Антон'
            greeting_emoji = '🧌'
        elif 'Женский' in user_text:
            gender = 'Женский'
            assistant_name = 'Валерия' 
            greeting_emoji = '🧝🏽‍♀️'
        else:
            # Защита от неожиданного ввода
            logger.warning(f"⚠️ Неизвестный выбор пола: {user_text}, используем по умолчанию")
            gender = 'Мужской'
            assistant_name = 'Антон'
            greeting_emoji = '🧌'
        
        context.user_data['assistant_gender'] = gender
        context.user_data['assistant_name'] = assistant_name
        context.user_data['greeting_emoji'] = greeting_emoji
        
        logger.info(f"✅ Выбран пол: {gender}, ассистент: {assistant_name}")
        
        # Приветствие как в вашем примере - ОДИН РАЗ
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
        
        logger.info(f"🔁 Ждем подтверждения готовности, возвращаем состояние READY_CONFIRMATION: {READY_CONFIRMATION}")
        return READY_CONFIRMATION
    
    except Exception as e:
        logger.error(f"❌ Ошибка в gender_choice: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, начните заново с /start"
        )
        return ConversationHandler.END

async def handle_ready_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик подтверждения готовности начать анкету"""
    try:
        user_id = update.effective_user.id
        answer_text = update.message.text
        
        logger.info(f"🔍 Пользователь {user_id} подтвердил начало анкеты: {answer_text}")
        
        # ВСЕГДА начинаем анкету с ПЕРВОГО вопроса
        context.user_data['current_question'] = 0
        context.user_data['answers'] = {}
        context.user_data['questionnaire_started'] = True
        
        # Отправляем ПЕРВЫЙ вопрос
        await update.message.reply_text(QUESTIONS[0])
        
        logger.info(f"🔁 Начинаем анкету с вопроса 0, возвращаем состояние QUESTIONNAIRE: {QUESTIONNAIRE}")
        return QUESTIONNAIRE
    
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_ready_confirmation: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, начните заново с /start"
        )
        return ConversationHandler.END

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик ответов на вопросы анкеты"""
    try:
        user_id = update.effective_user.id
        answer_text = update.message.text
        
        # Проверяем что анкета действительно начата
        if 'questionnaire_started' not in context.user_data:
            logger.error(f"❌ Анкета не начата для пользователя {user_id}")
            await update.message.reply_text("❌ Что-то пошло не так. Пожалуйста, начните анкету заново с /start")
            return ConversationHandler.END
        
        current_question = context.user_data.get('current_question', 0)
        logger.info(f"🔍 Обрабатываем вопрос #{current_question}: {answer_text[:50]}...")
        
        # Сохраняем ответ на текущий вопрос с обработкой ошибок (АСИНХРОННО)
        try:
            await save_questionnaire_answer(user_id, current_question, QUESTIONS[current_question], answer_text)
            context.user_data['answers'][current_question] = answer_text
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения ответа пользователя {user_id}: {e}")
            # Продолжаем, так как ответ сохранен в context.user_data
        
        # Переходим к следующему вопросу
        next_question = current_question + 1
        
        if next_question < len(QUESTIONS):
            # Отправляем следующий вопрос
            context.user_data['current_question'] = next_question
            await update.message.reply_text(QUESTIONS[next_question])
            
            logger.info(f"🔁 Переходим к вопросу {next_question}, возвращаем состояние QUESTIONNAIRE: {QUESTIONNAIRE}")
            return QUESTIONNAIRE
        else:
            # Анкета завершена
            logger.info(f"✅ Анкета завершена для пользователя {user_id}")
            return await finish_questionnaire(update, context)
    
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_question: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке ответа. Пожалуйста, попробуйте еще раз или начните заново с /start"
        )
        return ConversationHandler.END

async def finish_questionnaire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершает анкету и отправляет данные"""
    try:
        user = update.effective_user
        user_id = user.id
        assistant_name = context.user_data.get('assistant_name', 'Ассистент')
        questionnaire_id = context.user_data.get('questionnaire_id', 'unknown')
        
        logger.info(f"🎉 Завершаем анкету {questionnaire_id} для пользователя {user_id}")
        
        # Сохраняем данные анкеты в Google Sheets с обработкой ошибок
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
            'ближайшая_цель': 'Заполнить первую неделю активности',
            'questionnaire_id': questionnaire_id,  # Уникальный ID анкеты
            'assistant_name': assistant_name
        }
        
        # Добавляем все ответы на вопросы
        for i, question in enumerate(QUESTIONS):
            answer = context.user_data['answers'].get(i, '❌ Нет ответа')
            user_data[f'question_{i+1}'] = answer
        
        try:
            save_client_to_sheets(user_data)
            logger.info(f"✅ Данные анкеты {questionnaire_id} сохранены в Google Sheets")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения в Google Sheets: {e}")
            # Не прерываем выполнение, так как это не критично для пользователя
        
        # Формируем анкету для отправки админу
        questionnaire = f"📋 Новая анкета от пользователя:\n\n"
        questionnaire += f"👤 ID: {user.id}\n"
        questionnaire += f"📛 Имя: {user.first_name}\n"
        if user.last_name:
            questionnaire += f"📛 Фамилия: {user.last_name}\n"
        if user.username:
            questionnaire += f"🔗 Username: @{user.username}\n"
        questionnaire += f"📅 Дата: {update.message.date.strftime('%Y-%m-%d %H:%M')}\n"
        questionnaire += f"👨‍💼 Ассистент: {assistant_name}\n"
        questionnaire += f"🆔 ID анкеты: {questionnaire_id}\n\n"
        
        questionnaire += "📝 Ответы на вопросы:\n\n"
        
        for i, question in enumerate(QUESTIONS):
            answer = context.user_data['answers'].get(i, '❌ Нет ответа')
            # Обрезаем длинные ответы для читабельности
            truncated_answer = answer[:500] + "..." if len(answer) > 500 else answer
            questionnaire += f"❓ {i+1}. {question}:\n"
            questionnaire += f"💬 {truncated_answer}\n\n"
        
        # Отправляем админу с обработкой ошибок
        max_length = 4096
        if len(questionnaire) > max_length:
            parts = [questionnaire[i:i+max_length] for i in range(0, len(questionnaire), max_length)]
            for part_num, part in enumerate(parts, 1):
                try:
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=part)
                    logger.info(f"✅ Отправлена часть анкеты {part_num}/{len(parts)}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки части анкеты {part_num}: {e}")
        else:
            try:
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=questionnaire)
                logger.info("✅ Анкета отправлена админу")
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
                text=f"✅ Пользователь {user.first_name} завершил анкету {questionnaire_id}!",
                reply_markup=reply_markup
            )
            logger.info("✅ Кнопки действий отправлены админу")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки кнопок админу: {e}")
        
        # Сообщение пользователю с меню
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
        
        # Очищаем только данные анкеты, сохраняем информацию об ассистенте
        keys_to_keep = ['assistant_name', 'assistant_gender', 'greeting_emoji']
        preserved_data = {k: context.user_data.get(k) for k in keys_to_keep if k in context.user_data}
        context.user_data.clear()
        context.user_data.update(preserved_data)
        
        logger.info(f"🧹 Данные анкеты очищены для пользователя {user_id}, сохранены настройки ассистента")
        return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в finish_questionnaire: {e}")
        await update.message.reply_text(
            "🎉 Спасибо за ответы! Анкета завершена, но произошла небольшая техническая ошибка. "
            "Наш специалист свяжется с вами в ближайшее время."
        )
        return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    """Отменяет текущий диалог и очищает данные"""
    try:
        user_id = update.effective_user.id
        
        # Очищаем данные анкеты, но сохраняем настройки ассистента
        keys_to_keep = ['assistant_name', 'assistant_gender', 'greeting_emoji']
        preserved_data = {k: context.user_data.get(k) for k in keys_to_keep if k in context.user_data}
        context.user_data.clear()
        context.user_data.update(preserved_data)
        
        logger.info(f"❌ Анкета отменена пользователем {user_id}")
        
        await update.message.reply_text(
            '❌ Операция отменена.',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    except Exception as e:
        logger.error(f"❌ Ошибка в cancel: {e}")
        await update.message.reply_text('❌ Операция отменена.')
        return ConversationHandler.END
