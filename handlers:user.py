import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CallbackContext

from config import logger
from database import (
    update_user_activity, check_user_registered, save_progress_to_db,
    has_sufficient_data, get_user_activity_streak, get_user_main_goal,
    get_favorite_ritual, get_user_level_info, get_user_usage_days,
    get_db_connection
)
from services.google_sheets import (
    get_daily_plan_from_sheets, save_daily_report_to_sheets
)

# ВОССТАНОВИЛ логгер - возможно нужен для этого модуля
logger = logging.getLogger(__name__)

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий план пользователя"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    # Получаем план из Google Sheets
    today = datetime.now().strftime("%Y-%m-%d")
    plan_data = get_daily_plan_from_sheets(user_id, today)
    
    if not plan_data:
        await update.message.reply_text(
            "📋 Индивидуальный план еще не готов.\n\n"
            "Наш ассистент анализирует вашу анкету и скоро составит для вас "
            "персональный план. Обычно это занимает до 24 часов.\n\n"
            "А пока вы можете использовать общие рекомендации для продуктивного дня!"
        )
        return
    
    # Формируем сообщение с планом
    plan_text = f"📋 Ваш индивидуальный план на {today}:\n\n"
    
    if plan_data.get('strategic_tasks'):
        plan_text += "🎯 СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
        for task in plan_data['strategic_tasks']:
            plan_text += f"• {task}\n"
        plan_text += "\n"
    
    if plan_data.get('critical_tasks'):
        plan_text += "⚠️ КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
        for task in plan_data['critical_tasks']:
            plan_text += f"• {task}\n"
        plan_text += "\n"
    
    if plan_data.get('priorities'):
        plan_text += "🎯 ПРИОРИТЕТЫ ДНЯ:\n"
        for priority in plan_data['priorities']:
            plan_text += f"• {priority}\n"
        plan_text += "\n"
    
    if plan_data.get('advice'):
        plan_text += "💡 СОВЕТЫ АССИСТЕНТА:\n"
        for advice in plan_data['advice']:
            plan_text += f"• {advice}\n"
        plan_text += "\n"
    
    if plan_data.get('motivation_quote'):
        plan_text += f"💫 МОТИВАЦИЯ: {plan_data['motivation_quote']}\n"
    
    await update.message.reply_text(plan_text)

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает персонализированный прогресс"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    if not has_sufficient_data(user_id):
        # Показываем сообщение о недостатке данных
        usage_days = get_user_usage_days(user_id)
        
        await update.message.reply_text(
            f"📊 ВАШ ПРОГРЕСС ФОРМИРУЕТСЯ!\n\n"
            f"📅 День {usage_days['current_day']} • Всего дней: {usage_days['days_since_registration']} • Серия: {usage_days['current_streak']}\n\n"
            f"Пока данных недостаточно для полной статистики.\n"
            f"Отслеживаемые показатели:\n\n"
            f"✓ Выполненные задачи: 0/∞\n"
            f"✓ Настроение: пока нет оценок\n"
            f"✓ Энергия: собираем данные\n"
            f"✓ Водный баланс: отслеживается\n"
            f"✓ Активность: мониторим с {usage_days['days_since_registration']} дней\n\n"
            f"Продолжайте работать с ботом ежедневно!\n"
            f"Уже через 3 дня появится персональная статистика."
        )
    else:
        # Получаем данные за последние 7 дней
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ Ошибка подключения к базе данных")
            return
            
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_days,
                    AVG(tasks_completed) as avg_tasks,
                    AVG(mood) as avg_mood,
                    AVG(energy) as avg_energy,
                    AVG(water_intake) as avg_water,
                    COUNT(DISTINCT progress_date) as active_days
                FROM user_progress 
                WHERE user_id = %s AND progress_date >= CURRENT_DATE - INTERVAL '7 days'
            """, (user_id,))
            
            result = cursor.fetchone()
            
            total_days = result['total_days'] or 0
            avg_tasks = result['avg_tasks'] or 0
            avg_mood = result['avg_mood'] or 0
            avg_energy = result['avg_energy'] or 0
            avg_water = result['avg_water'] or 0
            active_days = result['active_days'] or 0

            # Рассчитываем проценты и динамику
            tasks_completed = f"{int(avg_tasks * 10)}/10" if avg_tasks else "0/10"
            mood_str = f"{avg_mood:.1f}/10" if avg_mood else "0/10"
            energy_str = f"{avg_energy:.1f}/10" if avg_energy else "0/10"
            water_str = f"{avg_water:.1f} стаканов/день" if avg_water else "0 стаканов/день"
            activity_str = f"{active_days}/7 дней"

            # Динамика
            mood_dynamics = "↗ улучшается" if avg_mood and avg_mood > 6 else "→ стабильно"
            energy_dynamics = "↗ растет" if avg_energy and avg_energy > 6 else "→ стабильно"
            productivity_dynamics = "↗ растет" if avg_tasks and avg_tasks > 5 else "→ стабильно"

            # Получаем дополнительную информацию для профиля
            usage_days = get_user_usage_days(user_id)
            level_info = get_user_level_info(user_id)

            # Персональный совет
            advice = "Продолжайте в том же духе! Вы на правильном пути."
            if avg_water and avg_water < 6:
                advice = "Попробуйте увеличить потребление воды до 8 стаканов - это может повысить энергию!"
            elif avg_mood and avg_mood < 6:
                advice = "Попробуйте добавить короткие перерывы для отдыха - это улучшит настроение!"

            await update.message.reply_text(
                f"📊 ВАШ ПЕРСОНАЛЬНЫЙ ПРОГРЕСС\n\n"
                f"📅 День {usage_days['current_day']} • Всего дней: {usage_days['days_since_registration']} • Серия: {usage_days['current_streak']}\n\n"
                f"✅ Выполнено задач: {tasks_completed}\n"
                f"😊 Среднее настроение: {mood_str}\n"
                f"⚡ Уровень энергии: {energy_str}\n"
                f"💧 Вода в среднем: {water_str}\n"
                f"🏃 Активность: {activity_str}\n\n"
                f"📈 ДИНАМИКА:\n"
                f"• Настроение: {mood_dynamics}\n"
                f"• Энергия: {energy_dynamics}\n"
                f"• Продуктивность: {productivity_dynamics}\n\n"
                f"🎯 СОВЕТ: {advice}"
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения прогресса для {user_id}: {e}")
            await update.message.reply_text("❌ Ошибка при получении статистики. Попробуйте позже.")
        finally:
            conn.close()

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает профиль пользователя"""
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id)
    
    if not check_user_registered(user_id):
        await update.message.reply_text("❌ Сначала заполните анкету: /start")
        return
    
    # Получаем данные для профиля
    main_goal = get_user_main_goal(user_id)
    usage_days = get_user_usage_days(user_id)
    level_info = get_user_level_info(user_id)
    favorite_ritual = get_favorite_ritual(user_id)
    
    # Получаем статистику по планам
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("❌ Ошибка подключения к базе данных")
        return
        
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_plans WHERE user_id = %s", 
            (user_id,)
        )
        total_plans_result = cursor.fetchone()
        total_plans = total_plans_result['count'] if total_plans_result else 0

        cursor.execute(
            "SELECT COUNT(*) FROM user_plans WHERE user_id = %s AND status = 'completed'", 
            (user_id,)
        )
        completed_plans_result = cursor.fetchone()
        completed_plans = completed_plans_result['count'] if completed_plans_result else 0

        # Вычисляем процент выполнения планов
        plans_percentage = (completed_plans / total_plans * 100) if total_plans > 0 else 0
        
        # Формируем профиль
        profile_text = (
            f"👤 ВАШ ПРОФИЛЬ\n\n"
            f"📅 День {usage_days['current_day']} • Всего дней: {usage_days['days_since_registration']} • Серия: {usage_days['current_streak']}\n\n"
            f"🎯 ТЕКУЩАЯ ЦЕЛЬ: {main_goal}\n"
            f"📊 ВЫПОЛНЕНО: {plans_percentage:.1f}% на пути к цели\n\n"
            f"🏆 ДОСТИЖЕНИЯ:\n"
            f"• Выполнено планов: {completed_plans} из {total_plans} ({plans_percentage:.1f}%)\n"
            f"• Максимальная регулярность: {usage_days['current_streak']} дней\n"
            f"• Любимый ритуал: {favorite_ritual}\n\n"
            f"🎮 УРОВЕНЬ: {level_info['level']}\n"
            f"⭐ ОЧКОВ: {level_info['points']} из {level_info['next_level_points']} до следующего уровня\n\n"
            f"💡 РЕКОМЕНДАЦИИ:\n"
            f"Продолжайте ежедневно отслеживать прогресс для лучших результатов!"
        )
        
        await update.message.reply_text(profile_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения профиля для {user_id}: {e}")
        await update.message.reply_text("❌ Ошибка при получении профиля. Попробуйте позже.")
    finally:
        conn.close()

async def points_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Объясняет систему очков"""
    help_text = (
        "🎮 СИСТЕМА ОЧКОВ И УРОВНЕЙ:\n\n"
        "📊 Как начисляются очки:\n"
        "• +10 очков за каждый активный день\n"
        "• +2 очка за каждую выполненную задачу\n"
        "• +5 очков за заполнение дневника прогресса\n"
        "• +15 очков за серию из 7 дней подряд\n\n"
        "🏆 Уровни:\n"
        "• Новичок (0 очков)\n"
        "• Ученик (50 очков)\n"
        "• Опытный (100 очков)\n"
        "• Профессионал (200 очков)\n"
        "• Мастер (500 очков)\n\n"
        "💡 Советы:\n"
        "• Регулярность важнее количества!\n"
        "• Даже маленькие шаги приносят очки\n"
        "• Не пропускайте дни для сохранения серии"
    )
    await update.message.reply_text(help_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает справку по командам"""
    user_id = update.effective_user.id
    update_user_activity(user_id)
    
    help_text = (
        "ℹ️ Справка по командам:\n\n"
        
        "🔹 Основные команды:\n"
        "/start - Начать работу с ботом\n"
        "/plan - План на сегодня\n"
        "/progress - Статистика прогресса\n"
        "/profile - Ваш профиль\n"
        "/points_info - Объяснение системы очков\n"
        "/help - Эта справка\n\n"
        
        "🔹 Команды для отслеживания:\n"
        "/done <1-4> - Отметить задачу выполненной\n"
        "/mood <1-10> - Оценить настроение\n"
        "/energy <1-10> - Оценить уровень энергии\n"
        "/water <стаканы> - Отслеживание воды\n\n"
        
        "🔹 Напоминания:\n"
        "/remind_me <время> <текст> - Разовое напоминание\n"
        "/regular_remind <время> <дни> <текст> - Регулярное напоминание\n"
        "/my_reminders - Показать активные напоминания\n"
        "/delete_remind <id> - Удалить напоминание\n\n"
        
        "💡 Также вы можете писать напоминания естественным языком:\n"
        "'напомни мне в 20:00 постирать купальник'\n"
        "'напоминай каждый день в 8:00 делать зарядку'\n"
        "'напомни в 11 вечера принять лекарство'\n\n"
        
        "💬 Просто напишите сообщение, чтобы связаться с ассистентом!"
    )
    
    await update.message.reply_text(help_text)

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
        
        # Сохраняем в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'mood': mood
        }
        save_daily_report_to_sheets(user_id, report_data)
        
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
        
        # Сохраняем в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'energy': energy
        }
        save_daily_report_to_sheets(user_id, report_data)
        
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
        
        # Сохраняем в Google Sheets
        report_data = {
            'date': datetime.now().strftime("%Y-%m-%d"),
            'water_intake': water
        }
        save_daily_report_to_sheets(user_id, report_data)
        
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