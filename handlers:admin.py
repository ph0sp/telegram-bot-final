import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackContext, ConversationHandler, MessageHandler, filters

from config import YOUR_CHAT_ID, logger
from database import get_db_connection
from services.google_sheets import save_daily_plan_to_sheets, parse_structured_plan

# Оставляем логгер на всякий случай, если он используется
logger = logging.getLogger(__name__)

async def admin_add_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс добавления плана (только для администратора)"""
    if str(update.effective_user.id) != YOUR_CHAT_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📋 ДОБАВЛЕНИЕ ПЕРСОНАЛЬНОГО ПЛАНА\n\n"
        "Введите ID пользователя:"
    )
    return 3  # ADD_PLAN_USER

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
            return 3  # ADD_PLAN_USER
            
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
                return 3  # ADD_PLAN_USER
            
            context.user_data['user_name'] = user_info['first_name']
        except Exception as e:
            logger.error(f"❌ Ошибка проверки пользователя {user_id}: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при проверке пользователя. Попробуйте снова:"
            )
            return 3  # ADD_PLAN_USER
        finally:
            conn.close()
        
        await update.message.reply_text(
            f"👤 Пользователь: {user_info['first_name']} (ID: {user_id})\n\n"
            "Введите дату для плана (формат: ГГГГ-ММ-ДД):"
        )
        return 4  # ADD_PLAN_DATE
        
    except ValueError:
        await update.message.reply_text(
            "❌ ID пользователя должен быть числом.\n"
            "Введите корректный ID:"
        )
        return 3  # ADD_PLAN_USER

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
        return 5  # ADD_PLAN_CONTENT
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты.\n"
            "Используйте формат: ГГГГ-ММ-ДД\n"
            "Попробуйте снова:"
        )
        return 4  # ADD_PLAN_DATE

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
            "SELECT COUNT(*) FROM user_messages WHERE direction = 'incoming'"
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
    
    # Проверяем Google Sheets
    from services.google_sheets import google_sheet
    if google_sheet:
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

def save_user_plan_to_db(user_id: int, plan_data: dict):
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