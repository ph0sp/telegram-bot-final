import logging
from datetime import datetime
from typing import Dict, Any, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackContext, ConversationHandler, MessageHandler, filters

from config import YOUR_CHAT_ID, logger, ADD_PLAN_USER, ADD_PLAN_DATE, ADD_PLAN_CONTENT
from database import get_connection_pool, save_user_plan_to_db, update_user_activity
from services.google_sheets import save_daily_plan_to_sheets, parse_structured_plan

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return str(user_id) == YOUR_CHAT_ID


async def admin_add_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс добавления плана (только для администратора)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END
    
    await update_user_activity(user_id)
    await update.message.reply_text(
        "📋 **ДОБАВЛЕНИЕ ПЕРСОНАЛЬНОГО ПЛАНА**\n\n"
        "Введите ID пользователя (число):"
    )
    return ADD_PLAN_USER


async def add_plan_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ID пользователя для добавления плана"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END
    
    try:
        target_user_id = int(update.message.text.strip())
        context.user_data['plan_user_id'] = target_user_id
        
        # Проверяем существование пользователя
        pool = await get_connection_pool()
        if not pool:
            await update.message.reply_text("❌ Ошибка подключения к базе данных. Попробуйте позже.")
            return ConversationHandler.END
        
        async with pool.acquire() as conn:
            user_info = await conn.fetchrow(
                "SELECT user_id, first_name, username FROM clients WHERE user_id = $1", 
                target_user_id
            )
            
            if not user_info:
                await update.message.reply_text(
                    f"❌ Пользователь с ID {target_user_id} не найден.\n\n"
                    "Проверьте ID и попробуйте снова:"
                )
                return ADD_PLAN_USER
            
            context.user_data['user_name'] = user_info['first_name']
            context.user_data['user_username'] = user_info['username'] or 'без username'
            
            await update.message.reply_text(
                f"✅ **Пользователь найден:**\n"
                f"👤 Имя: {user_info['first_name']}\n"
                f"📱 Username: {user_info['username'] or 'не указан'}\n"
                f"🆔 ID: {target_user_id}\n\n"
                f"📅 Введите дату для плана (формат: ГГГГ-ММ-ДД):"
            )
            return ADD_PLAN_DATE
            
    except ValueError:
        await update.message.reply_text(
            "❌ ID пользователя должен быть целым числом.\n\n"
            "Введите корректный ID:"
        )
        return ADD_PLAN_USER
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке пользователя: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке пользователя. Попробуйте снова:"
        )
        return ADD_PLAN_USER


async def add_plan_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает дату для добавления плана"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END
    
    date_str = update.message.text.strip()
    
    try:
        # Проверяем корректность даты
        datetime.strptime(date_str, "%Y-%m-%d")
        
        # Проверяем, что дата не в прошлом (можно закомментировать, если нужно)
        plan_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        
        if plan_date < today:
            await update.message.reply_text(
                "⚠️ **Внимание:** Вы добавляете план на прошедшую дату.\n\n"
                "Продолжить? (да/нет)"
            )
            context.user_data['waiting_date_confirmation'] = date_str
            return ADD_PLAN_DATE
        
        context.user_data['plan_date'] = date_str
        
        await update.message.reply_text(
            f"📅 **Дата:** {date_str}\n\n"
            "📝 Теперь введите содержание плана.\n\n"
            "💡 **Рекомендуемый формат:**\n"
            "СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
            "- Задача 1\n"
            "- Задача 2\n\n"
            "КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
            "- Срочная задача\n\n"
            "СОВЕТЫ АССИСТЕНТА:\n"
            "- Ваш совет\n\n"
            "💫 **Мотивационная цитата (опционально):**\n"
            "Верь в себя!"
        )
        return ADD_PLAN_CONTENT
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты.\n\n"
            "Используйте формат: **ГГГГ-ММ-ДД**\n"
            "Например: 2024-12-25\n\n"
            "Попробуйте снова:"
        )
        return ADD_PLAN_DATE
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке даты: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке даты. Попробуйте снова:"
        )
        return ADD_PLAN_DATE


async def add_plan_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает содержание плана и сохраняет его"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END
    
    plan_content = update.message.text.strip()
    target_user_id = context.user_data.get('plan_user_id')
    date_str = context.user_data.get('plan_date')
    user_name = context.user_data.get('user_name', 'Неизвестный')
    
    if not target_user_id or not date_str:
        await update.message.reply_text("❌ Ошибка: данные плана не найдены. Начните заново.")
        return ConversationHandler.END
    
    try:
        # Парсим структурированный план
        plan_data = parse_structured_plan(plan_content)
        
        # Сохраняем в Google Sheets
        success = save_daily_plan_to_sheets(target_user_id, date_str, plan_data)
        
        if not success:
            await update.message.reply_text(
                "❌ Ошибка при сохранении плана в Google Sheets.\n"
                "Проверьте подключение и попробуйте снова."
            )
            return ConversationHandler.END
        
        # Подготавливаем данные для БД
        db_plan_data = {
            'plan_date': date_str,
            'task1': plan_data.get('strategic_tasks', [''])[0] if plan_data.get('strategic_tasks') else '',
            'task2': plan_data.get('strategic_tasks', [''])[1] if len(plan_data.get('strategic_tasks', [])) > 1 else '',
            'task3': plan_data.get('strategic_tasks', [''])[2] if len(plan_data.get('strategic_tasks', [])) > 2 else '',
            'task4': plan_data.get('critical_tasks', [''])[0] if plan_data.get('critical_tasks') else '',
            'advice': plan_data.get('advice', [''])[0] if plan_data.get('advice') else '',
            'motivation_quote': plan_data.get('motivation_quote', ''),
            'priorities': plan_data.get('priorities', [''])[0] if plan_data.get('priorities') else ''
        }
        
        # Сохраняем в PostgreSQL
        await save_user_plan_to_db(target_user_id, db_plan_data)
        
        # Формируем ответ администратору
        response = (
            f"✅ **План успешно добавлен!**\n\n"
            f"👤 **Пользователь:** {user_name}\n"
            f"🆔 **ID:** {target_user_id}\n"
            f"📅 **Дата:** {date_str}\n"
            f"📊 **Сохранено в:** Google Sheets и PostgreSQL\n\n"
        )
        
        if plan_data.get('strategic_tasks'):
            response += f"🎯 **Стратегические задачи:** {len(plan_data['strategic_tasks'])}\n"
        if plan_data.get('critical_tasks'):
            response += f"⚠️ **Критические задачи:** {len(plan_data['critical_tasks'])}\n"
        if plan_data.get('advice'):
            response += f"💡 **Советы:** {len(plan_data['advice'])}\n"
        
        await update.message.reply_text(response)
        
        # Пытаемся отправить уведомление пользователю
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    f"🎉 **У вас новый персональный план!**\n\n"
                    f"📅 На дату: {date_str}\n\n"
                    f"💡 Используйте команду /plan чтобы посмотреть ваш план на сегодня.\n\n"
                    f"✨ Удачи в выполнении задач!"
                ),
                parse_mode='Markdown'
            )
            logger.info(f"✅ Уведомление отправлено пользователю {target_user_id}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось отправить уведомление пользователю {target_user_id}: {e}")
            await update.message.reply_text(
                f"ℹ️ Пользователь {user_name} не получил уведомление (возможно, заблокировал бота)."
            )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении плана: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при сохранении плана. Проверьте формат данных и попробуйте снова."
        )
    
    # Очищаем временные данные
    context.user_data.pop('plan_user_id', None)
    context.user_data.pop('plan_date', None)
    context.user_data.pop('user_name', None)
    context.user_data.pop('user_username', None)
    
    return ConversationHandler.END


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Статистика для администратора"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await update_user_activity(user_id)
    
    try:
        pool = await get_connection_pool()
        if not pool:
            await update.message.reply_text("❌ Ошибка подключения к базе данных.")
            return
        
        async with pool.acquire() as conn:
            # Получаем статистику
            total_users = await conn.fetchval("SELECT COUNT(*) FROM clients")
            active_today = await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM user_messages WHERE DATE(created_at) = CURRENT_DATE"
            )
            total_messages = await conn.fetchval("SELECT COUNT(*) FROM user_messages")
            total_answers = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM questionnaire_answers")
            total_plans = await conn.fetchval("SELECT COUNT(*) FROM user_plans")
            
            # Активные пользователи за последние 7 дней
            active_week = await conn.fetchval("""
                SELECT COUNT(DISTINCT user_id) 
                FROM user_messages 
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            """)
            
            # Новые пользователи за последние 7 дней
            new_users_week = await conn.fetchval("""
                SELECT COUNT(*) 
                FROM clients 
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            """)
        
        # Формируем статистику
        stats_text = (
            f"📊 **СТАТИСТИКА БОТА**\n\n"
            f"👥 **Пользователи:**\n"
            f"• Всего: {total_users}\n"
            f"• Активных сегодня: {active_today}\n"
            f"• Активных за неделю: {active_week}\n"
            f"• Новых за неделю: {new_users_week}\n\n"
            f"📨 **Сообщения:**\n"
            f"• Всего: {total_messages}\n\n"
            f"📝 **Анкеты:**\n"
            f"• Заполненных: {total_answers}\n\n"
            f"📋 **Планы:**\n"
            f"• Создано: {total_plans}\n\n"
        )
        
        # Проверяем Google Sheets
        try:
            from services.google_sheets import google_sheet
            if google_sheet:
                stats_text += "📊 **Google Sheets:** ✅ подключен\n"
            else:
                stats_text += "📊 **Google Sheets:** ⚠️ не доступен\n"
        except:
            stats_text += "📊 **Google Sheets:** ❌ ошибка проверки\n"
        
        stats_text += f"\n🔄 Последнее обновление: {datetime.now().strftime('%H:%M:%S')}"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при получении статистики. Попробуйте позже."
        )


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список пользователей"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await update_user_activity(user_id)
    
    try:
        pool = await get_connection_pool()
        if not pool:
            await update.message.reply_text("❌ Ошибка подключения к базе данных.")
            return
        
        async with pool.acquire() as conn:
            users = await conn.fetch("""
                SELECT user_id, username, first_name, last_name, last_activity, created_at 
                FROM clients 
                ORDER BY last_activity DESC 
                LIMIT 25
            """)
        
        if not users:
            await update.message.reply_text("📭 Пользователей не найдено.")
            return
        
        users_text = "👥 **ПОСЛЕДНИЕ ПОЛЬЗОВАТЕЛИ**\n\n"
        
        for i, user in enumerate(users, 1):
            user_id = user['user_id']
            username = f"@{user['username']}" if user['username'] else "без username"
            first_name = user['first_name'] or 'Без имени'
            last_activity = user['last_activity'].strftime('%d.%m.%Y %H:%M') if user['last_activity'] else 'никогда'
            
            users_text += f"{i}. **{first_name}** ({username})\n"
            users_text += f"   🆔 ID: `{user_id}`\n"
            users_text += f"   📅 Активен: {last_activity}\n"
            users_text += f"   📋 [Добавить план](/add_plan_{user_id})\n\n"
        
        users_text += (
            "💡 **Команды:**\n"
            "• /add_plan – добавить план\n"
            "• /admin_stats – статистика\n"
            "• /admin_users – список пользователей\n\n"
            "📊 Всего пользователей: " + str(len(users))
        )
        
        await update.message.reply_text(users_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка пользователей: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при получении списка пользователей. Попробуйте позже."
        )


async def button_callback(update: Update, context: CallbackContext) -> None:
    """Обработчик нажатий на inline-кнопки"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.answer("❌ У вас нет прав для этого действия.", show_alert=True)
        return
    
    await query.answer()
    callback_data = query.data
    
    try:
        if callback_data.startswith('reply_'):
            target_user_id = callback_data.replace('reply_', '')
            await query.edit_message_text(
                f"✍️ **Ответ пользователю**\n\n"
                f"🆔 ID: `{target_user_id}`\n\n"
                f"Используйте команду:\n"
                f"`/send {target_user_id} ваше сообщение`",
                parse_mode='Markdown'
            )
        
        elif callback_data.startswith('view_questionnaire_'):
            target_user_id = callback_data.replace('view_questionnaire_', '')
            
            pool = await get_connection_pool()
            if pool:
                async with pool.acquire() as conn:
                    answers = await conn.fetch(
                        "SELECT question_number, answer FROM questionnaire_answers WHERE user_id = $1 ORDER BY question_number",
                        int(target_user_id)
                    )
                    
                    if answers:
                        answers_text = f"📋 **Анкета пользователя {target_user_id}**\n\n"
                        for answer in answers:
                            answers_text += f"Вопрос {answer['question_number']}: {answer['answer']}\n"
                        
                        await query.edit_message_text(answers_text[:4000])
                    else:
                        await query.edit_message_text(f"📭 У пользователя {target_user_id} нет данных анкеты.")
            else:
                await query.edit_message_text("❌ Ошибка подключения к базе данных.")
        
        elif callback_data.startswith('stats_'):
            target_user_id = callback_data.replace('stats_', '')
            
            pool = await get_connection_pool()
            if pool:
                async with pool.acquire() as conn:
                    # Получаем статистику пользователя
                    user_info = await conn.fetchrow(
                        "SELECT first_name, last_activity FROM clients WHERE user_id = $1",
                        int(target_user_id)
                    )
                    
                    message_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM user_messages WHERE user_id = $1",
                        int(target_user_id)
                    )
                    
                    completed_tasks = await conn.fetchval(
                        "SELECT COUNT(*) FROM user_progress WHERE user_id = $1 AND completed = TRUE",
                        int(target_user_id)
                    )
                    
                    if user_info:
                        stats_text = (
                            f"📊 **Статистика пользователя**\n\n"
                            f"👤 Имя: {user_info['first_name']}\n"
                            f"🆔 ID: {target_user_id}\n"
                            f"📅 Последняя активность: {user_info['last_activity'].strftime('%d.%m.%Y %H:%M')}\n"
                            f"📨 Сообщений: {message_count}\n"
                            f"✅ Выполнено задач: {completed_tasks}\n"
                        )
                        
                        await query.edit_message_text(stats_text)
                    else:
                        await query.edit_message_text(f"❌ Пользователь {target_user_id} не найден.")
            else:
                await query.edit_message_text("❌ Ошибка подключения к базе данных.")
        
        elif callback_data.startswith('create_plan_'):
            target_user_id = callback_data.replace('create_plan_', '')
            await query.edit_message_text(
                f"📋 **Создание плана для пользователя**\n\n"
                f"🆔 ID: `{target_user_id}`\n\n"
                f"Используйте команду:\n"
                f"`/add_plan`\n\n"
                f"Или нажмите /add_plan и следуйте инструкциям.",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"❌ Ошибка в button_callback: {e}")
        await query.edit_message_text("❌ Произошла ошибка при обработке запроса.")


async def cancel_add_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет процесс добавления плана"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    # Очищаем временные данные
    context.user_data.pop('plan_user_id', None)
    context.user_data.pop('plan_date', None)
    context.user_data.pop('user_name', None)
    context.user_data.pop('user_username', None)
    
    await update.message.reply_text("❌ Добавление плана отменено.")
    return ConversationHandler.END
