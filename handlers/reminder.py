import logging
import re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, CallbackContext

from config import logger
from database import (
    update_user_activity, add_reminder_to_db, get_user_reminders, 
    delete_reminder_from_db, get_db_connection
)

logger = logging.getLogger(__name__)

async def remind_me_command(update: Update, context: CallbackContext):
    """Установка разового напоминания"""
    user_id = update.effective_user.id
    await update_user_activity(user_id)
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⏰ Установка разового напоминания:\n\n"
            "Формат:\n"
            "/remind_me <время> <текст>\n\n"
            "Примеры:\n"
            "/remind_me 20:30 принять лекарство\n"
            "/remind_me 9 утра позвонить врачу\n"
            "/remind_me 11 вечера постирать купальник\n"
            "/remind_me вечером вынести мусор\n\n"
            "⏱️ Время можно указывать в разных форматах:\n"
            "• 20:30, 09:00\n"
            "• 9 утра, 7 вечера, 11 ночи\n"
            "• 11 часов вечера, 3 часа дня\n"
            "• утром, днем, вечером, ночью"
        )
        return
    
    time_str = context.args[0]
    reminder_text = " ".join(context.args[1:])
    
    logger.info(f"🕒 Пользователь {user_id} устанавливает напоминание: {time_str} - {reminder_text}")
    
    # Парсим время
    time_data = parse_time_input(time_str)
    
    if not time_data:
        await update.message.reply_text(
            "❌ Не удалось распознать время.\n"
            "Пожалуйста, укажите время в одном из форматов:\n"
            "• 20:30 или 09:00\n"
            "• 9 утра или 7 вечера\n"
            "• 11 часов вечера\n"
            "• утром, днем, вечером"
        )
        return
    
    reminder_data = {
        'type': 'once',
        'time': time_data['time'],
        'text': reminder_text,
        'days': []
    }
    
    success = await add_reminder_to_db(user_id, reminder_data)
    
    if success:
        await update.message.reply_text(
            f"✅ Напоминание установлено на {time_data['time']}:\n"
            f"📝 {reminder_text}\n\n"
            f"Я пришлю уведомление в указанное время!"
        )
    else:
        await update.message.reply_text("❌ Не удалось установить напоминание")

async def regular_remind_command(update: Update, context: CallbackContext):
    """Установка регулярного напоминания"""
    user_id = update.effective_user.id
    await update_user_activity(user_id)
    
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "🔄 Установка регулярного напоминания:\n\n"
            "Формат:\n"
            "/regular_remind <время> <дни> <текст>\n\n"
            "Примеры:\n"
            "/regular_remind 08:00 пн,ср,пт утренняя зарядка\n"
            "/regular_remind 09:00 ежедневно принимать витамины\n"
            "/regular_remind 20:00 вт,чт йога\n\n"
            "📅 Дни недели:\n"
            "пн, вт, ср, чт, пт, сб, вс\n"
            "или 'ежедневно' для всех дней"
        )
        return
    
    time_str = context.args[0]
    days_str = context.args[1]
    reminder_text = " ".join(context.args[2:])
    
    # Парсим время
    time_data = parse_time_input(time_str)
    
    if not time_data:
        await update.message.reply_text(
            "❌ Не удалось распознать время.\n"
            "Пожалуйста, укажите время в формате ЧЧ:MM"
        )
        return
    
    # Парсим дни недели
    days_map = {
        'пн': 'пн', 'вт': 'вт', 'ср': 'ср', 'чт': 'чт',
        'пт': 'пт', 'сб': 'сб', 'вс': 'вс',
        'ежедневно': ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'],
        'понедельник': 'пн', 'вторник': 'вт', 'среда': 'ср', 'четверг': 'чт',
        'пятница': 'пт', 'суббота': 'сб', 'воскресенье': 'вс'
    }
    
    if days_str.lower() == 'ежедневно':
        days = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    else:
        days = []
        for day_part in days_str.split(','):
            day_clean = day_part.strip().lower()
            if day_clean in days_map:
                if isinstance(days_map[day_clean], list):
                    days.extend(days_map[day_clean])
                else:
                    days.append(days_map[day_clean])
    
    if not days:
        await update.message.reply_text(
            "❌ Не удалось распознать дни недели.\n"
            "Укажите дни в формате: пн,ср,пт или 'ежедневно'"
        )
        return
    
    # Убираем дубликаты
    days = list(set(days))
    
    reminder_data = {
        'type': 'regular',
        'time': time_data['time'],
        'text': reminder_text,
        'days': days
    }
    
    success = await add_reminder_to_db(user_id, reminder_data)
    
    if success:
        days_display = ', '.join(days) if days != ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'] else 'ежедневно'
        await update.message.reply_text(
            f"✅ Регулярное напоминание установлено:\n"
            f"⏰ {time_data['time']} {days_display}\n"
            f"📝 {reminder_text}\n\n"
            f"Я буду напоминать вам по установленному расписанию!"
        )
    else:
        await update.message.reply_text("❌ Не удалось установить напоминание")

async def my_reminders_command(update: Update, context: CallbackContext):
    """Показывает активные напоминания"""
    user_id = update.effective_user.id
    await update_user_activity(user_id)
    
    reminders = await get_user_reminders(user_id)
    
    if not reminders:
        await update.message.reply_text(
            "📭 У вас нет активных напоминаний\n\n"
            "💡 Чтобы установить напоминание:\n"
            "• Используйте команды /remind_me или /regular_remind\n"
            "• Или напишите естественным языком:\n"
            "  'напомни мне в 20:00 постирать купальник'\n"
            "  'напоминай каждый день в 8:00 делать зарядку'"
        )
        return
    
    reminders_text = "📋 Ваши активные напоминания:\n\n"
    
    for i, reminder in enumerate(reminders, 1):
        type_icon = "🔄" if reminder['type'] == 'regular' else "⏰"
        days_info = f" ({reminder['days']})" if reminder['type'] == 'regular' else ""
        
        reminders_text += f"{i}. {type_icon} {reminder['time']}{days_info}\n"
        reminders_text += f"   📝 {reminder['text']}\n"
        reminders_text += f"   🆔 ID: {reminder['id']}\n\n"
    
    reminders_text += "❌ Чтобы удалить напоминание:\n/delete_remind <ID>"
    
    await update.message.reply_text(reminders_text)

async def delete_remind_command(update: Update, context: CallbackContext):
    """Удаляет напоминание"""
    user_id = update.effective_user.id
    await update_user_activity(user_id)
    
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите ID напоминания для удаления:\n"
            "/delete_remind <ID>\n\n"
            "📋 Посмотреть ID ваших напоминаний:\n"
            "/my_reminders"
        )
        return
    
    try:
        reminder_id = int(context.args[0])
        success = await delete_reminder_from_db(reminder_id)
        
        if success:
            await update.message.reply_text(
                f"✅ Напоминание {reminder_id} удалено!\n\n"
                f"📋 Текущий список напоминаний:\n"
                f"/my_reminders"
            )
        else:
            await update.message.reply_text(
                "❌ Не удалось удалить напоминание.\n"
                "Проверьте правильность ID."
            )
        
    except ValueError:
        await update.message.reply_text("❌ ID напоминания должен быть числом")

async def handle_reminder_nlp(update: Update, context: CallbackContext):
    """Обрабатывает естественные запросы на напоминания"""
    user_id = update.effective_user.id
    message_text = update.message.text
    await update_user_activity(user_id)
    
    logger.info(f"🔍 Обработка естественного запроса: {message_text}")
    
    # Проверяем лимит напоминаний (максимум 20 на пользователя)
    reminders = await get_user_reminders(user_id)
    if len(reminders) >= 20:
        await update.message.reply_text(
            "❌ Достигнут лимит напоминаний (20).\n"
            "Удалите старые напоминания: /my_reminders"
        )
        return
    
    # Парсим текст напоминания
    reminder_data = parse_reminder_text(message_text)
    
    if not reminder_data:
        await update.message.reply_text(
            "❌ Не понял формат напоминания.\n\n"
            "💡 Попробуйте так:\n"
            "'напомни мне в 20:00 постирать купальник'\n"
            "'напоминай каждый день в 8:00 делать зарядку'\n"
            "'напомни завтра утром позвонить врачу'\n"
            "'напомни в 11 вечера принять лекарство'"
        )
        return
    
    # Добавляем напоминание в базу
    success = await add_reminder_to_db(user_id, reminder_data)
    
    if success:
        if reminder_data['type'] == 'regular':
            days_display = ', '.join(reminder_data['days']) if reminder_data['days'] != ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'] else 'ежедневно'
            response = (
                f"✅ Регулярное напоминание установлено!\n"
                f"⏰ {reminder_data['time']} {days_display}\n"
                f"📝 {reminder_data['text']}\n\n"
                f"Я буду напоминать вам по установленному расписанию!"
            )
        else:
            response = (
                f"✅ Напоминание установлено!\n"
                f"⏰ {reminder_data['time']}\n"
                f"📝 {reminder_data['text']}\n\n"
                f"Я пришлю уведомление в указанное время!"
            )
        
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("❌ Не удалось установить напоминание")

async def send_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет напоминания пользователям безопасно (АСИНХРОННАЯ)"""
    try:
        # Получаем текущее время и день недели
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_day_rus = now.strftime("%A").lower()
        day_translation = {
            'monday': 'пн', 'tuesday': 'вт', 'wednesday': 'ср',
            'thursday': 'чт', 'friday': 'пт', 'saturday': 'сб', 'sunday': 'вс'
        }
        current_day = day_translation.get(current_day_rus, 'пн')
        
        async with get_db_connection() as conn:
            # Ищем напоминания для текущего времени
            reminders = await conn.fetch('''
                SELECT ur.id, ur.user_id, ur.reminder_text, c.first_name, ur.reminder_type
                FROM user_reminders ur 
                JOIN clients c ON ur.user_id = c.user_id 
                WHERE ur.is_active = TRUE AND ur.reminder_time = $1 
                AND (ur.days_of_week LIKE $2 OR ur.days_of_week = 'ежедневно' OR ur.days_of_week = '')
            ''', current_time, f'%{current_day}%')
            
            for reminder in reminders:
                reminder_id = reminder['id']
                user_id = reminder['user_id']
                reminder_text = reminder['reminder_text']
                first_name = reminder['first_name']
                reminder_type = reminder['reminder_type']
                
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🔔 Напоминание: {reminder_text}"
                    )
                    logger.info(f"✅ Напоминание отправлено пользователю {user_id}")
                    
                    # Если это разовое напоминание - деактивируем его
                    if reminder_type == 'once':
                        await conn.execute(
                            'UPDATE user_reminders SET is_active = FALSE WHERE id = $1',
                            reminder_id
                        )
                        logger.info(f"📝 Разовое напоминание {reminder_id} деактивировано")
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки напоминания {user_id}: {e}")
                    
    except Exception as e:
        logger.error(f"❌ Ошибка в send_reminder_job: {e}")

def parse_time_input(time_text: str):
    """Парсит различные форматы времени"""
    time_text = time_text.lower().strip()
    
    logger.info(f"🕒 Парсим время: {time_text}")
    
    # Словарь для преобразования относительного времени
    time_mapping = {
        'утром': '08:00',
        'утро': '08:00', 
        'утра': '08:00',
        'днем': '13:00',
        'день': '13:00',
        'вечером': '20:00',
        'вечер': '20:00',
        'ночью': '22:00',
        'ночь': '22:00',
        'в обед': '13:00',
        'перед сном': '22:00',
        'после работы': '18:00',
        'в полдень': '12:00'
    }
    
    # Проверяем точное время с двоеточием (14:30, 9:00)
    exact_time_match = re.search(r'(\d{1,2}):(\d{2})', time_text)
    if exact_time_match:
        hours = int(exact_time_match.group(1))
        minutes = int(exact_time_match.group(2))
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            time_str = f"{hours:02d}:{minutes:02d}"
            logger.info(f"✅ Распознано точное время: {time_str}")
            return {'time': time_str, 'type': 'exact'}
    
    # Проверяем форматы типа "11 часов вечера", "7 утра", "3 ночи"
    hour_time_match = re.search(r'(\d{1,2})\s*(?:час\w*)?\s*(утра|вечера|ночи|дня)', time_text)
    if hour_time_match:
        hour = int(hour_time_match.group(1))
        period = hour_time_match.group(2)
        
        if period == 'утра':
            if 1 <= hour <= 12:
                time_str = f"{hour:02d}:00"
                logger.info(f"✅ Распознано время утра: {time_str}")
                return {'time': time_str, 'type': '12h'}
        elif period == 'вечера':
            if 1 <= hour <= 11:
                time_str = f"{hour + 12:02d}:00"
                logger.info(f"✅ Распознано время вечера: {time_str}")
                return {'time': time_str, 'type': '12h'}
            elif hour == 12:
                time_str = "12:00"
                logger.info(f"✅ Распознано время вечера: {time_str}")
                return {'time': time_str, 'type': '12h'}
        elif period == 'ночи':
            if 1 <= hour <= 11:
                time_str = f"{hour + 12:02d}:00"
                logger.info(f"✅ Распознано время ночи: {time_str}")
                return {'time': time_str, 'type': '12h'}
            elif hour == 12:
                time_str = "00:00"
                logger.info(f"✅ Распознано время ночи: {time_str}")
                return {'time': time_str, 'type': '12h'}
        elif period == 'дня':
            if 1 <= hour <= 11:
                time_str = f"{hour + 12:02d}:00"
                logger.info(f"✅ Распознано время дня: {time_str}")
                return {'time': time_str, 'type': '12h'}
            elif hour == 12:
                time_str = "12:00"
                logger.info(f"✅ Распознано время дня: {time_str}")
                return {'time': time_str, 'type': '12h'}
    
    # 3. Проверяем простые форматы "11 вечера", "7 утра" (без слова "час")
    simple_time_match = re.search(r'(\d{1,2})\s+(утра|вечера|ночи)', time_text)
    if simple_time_match:
        hour = int(simple_time_match.group(1))
        period = simple_time_match.group(2)
        
        if period == 'утра' and 1 <= hour <= 12:
            time_str = f"{hour:02d}:00"
            logger.info(f"✅ Распознано простое время утра: {time_str}")
            return {'time': time_str, 'type': 'simple'}
        elif period == 'вечера' and 1 <= hour <= 11:
            time_str = f"{hour + 12:02d}:00"
            logger.info(f"✅ Распознано простое время вечера: {time_str}")
            return {'time': time_str, 'type': 'simple'}
        elif period == 'ночи' and 1 <= hour <= 11:
            time_str = f"{hour + 12:02d}:00"
            logger.info(f"✅ Распознано простое время ночи: {time_str}")
            return {'time': time_str, 'type': 'simple'}
    
    # 4. Проверяем относительное время (утром, вечером и т.д.)
    if time_text in time_mapping:
        time_str = time_mapping[time_text]
        logger.info(f"✅ Распознано относительное время: {time_str}")
        return {'time': time_str, 'type': 'relative'}
    
    # 5. Обработка "через X часов/минут"
    future_match = re.search(r'через\s+(\d+)\s*(час|часа|часов|минут|минуты)', time_text)
    if future_match:
        amount = int(future_match.group(1))
        unit = future_match.group(2)
        
        now = datetime.now()
        if 'час' in unit:
            future_time = now + timedelta(hours=amount)
        else:
            future_time = now + timedelta(minutes=amount)
        
        time_str = future_time.strftime("%H:%M")
        logger.info(f"✅ Распознано будущее время: {time_str} (через {amount} {unit})")
        
        return {
            'time': time_str, 
            'type': 'future_relative',
            'delay_minutes': amount * (60 if 'час' in unit else 1),
            'original_text': time_text
        }
    
    logger.warning(f"❌ Не удалось распознать время: {time_text}")
    return None

def parse_reminder_text(text: str):
    """Парсит текст напоминания и возвращает структурированные данные"""
    original_text = text
    text_lower = text.lower()
    
    logger.info(f"🔍 Начинаем парсинг напоминания: {text}")
    
    # Определяем тип напоминания
    reminder_type = detect_reminder_type(text_lower)
    logger.info(f"📝 Тип напоминания: {reminder_type}")
    
    # Исключение: для "через X минут" всегда разовое напоминание
    if re.search(r'через\s+(\d+)\s*(минут|минуты)', text_lower):
        reminder_type = 'once'
        logger.info("🔧 Принудительно установлен тип 'once' для напоминания через минуты")
    
    # Удаляем ключевые слова из текста для извлечения времени и текста напоминания
    clean_text = text_lower
    
    # Удаляем слова для напоминаний
    reminder_words = ['напомни', 'напоминай', 'мне']
    for word in reminder_words:
        clean_text = re.sub(r'\b' + re.escape(word) + r'\b', '', clean_text)
    
    # Удаляем слова для регулярности (если это разовое напоминание)
    if reminder_type == 'once':
        regular_words = ['каждый', 'каждое', 'ежедневно', 'регулярно', 'каждую']
        for word in regular_words:
            clean_text = re.sub(r'\b' + re.escape(word) + r'\b', '', clean_text)
    
    clean_text = clean_text.strip()
    
    # Извлекаем время
    time_data = parse_time_input(clean_text)
    
    # Если время не найдено, пробуем парсить весь текст
    if not time_data:
        time_data = parse_time_input(original_text)
    
    # Если время так и не найдено, используем время по умолчанию
    if not time_data:
        time_data = {'time': '09:00', 'type': 'default'}
        logger.warning("⚠️ Время не распознано, используется время по умолчанию: 09:00")
    
    # Переносим параметры из time_data в reminder_data
    reminder_data = {
        'type': reminder_type,
        'time': time_data['time'],
        'text': '',
        'days': [],
        'original_text': original_text
    }
    
    # Добавляем дополнительные параметры из time_data
    if 'delay_minutes' in time_data:
        reminder_data['delay_minutes'] = time_data['delay_minutes']
    
    # Извлекаем дни недели для регулярных напоминаний (только если не относительное)
    if reminder_type == 'regular' and 'delay_minutes' not in time_data:
        days_map = {
            'понедельник': 'пн', 'вторник': 'вт', 'среда': 'ср', 'среду': 'ср',
            'четверг': 'чт', 'пятница': 'пт', 'пятницу': 'пт', 
            'суббота': 'сб', 'субботу': 'сб', 'воскресенье': 'вс',
            'пн': 'пн', 'вт': 'вт', 'ср': 'ср', 'чт': 'чт', 'пт': 'пт', 'сб': 'сб', 'вс': 'вс'
        }
        
        for day_full, day_short in days_map.items():
            if day_full in text_lower:
                reminder_data['days'].append(day_short)
                # Удаляем день из чистого текста
                clean_text = re.sub(r'\b' + re.escape(day_full) + r'\b', '', clean_text)
        
        # Если дни не указаны, но это регулярное напоминание - значит ежедневно
        if not reminder_data['days'] and reminder_type == 'regular':
            reminder_data['days'] = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
            logger.info("📅 Дни недели не указаны, установлено ежедневно")
    
    # Очищаем текст напоминания от лишних пробелов
    reminder_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    # Если текст пустой, используем оригинальный текст без первых слов
    if not reminder_text:
        # Удаляем первые слова напоминания
        temp_text = text_lower
        for word in ['напомни', 'напоминай', 'мне']:
            temp_text = re.sub(r'\b' + re.escape(word) + r'\b', '', temp_text)
        reminder_text = re.sub(r'\s+', ' ', temp_text).strip()
    
    reminder_data['text'] = reminder_text
    
    logger.info(f"✅ Результат парсинга: время={reminder_data['time']}, текст={reminder_text}, тип={reminder_type}, дни={reminder_data['days']}")
    
    return reminder_data

def detect_reminder_type(text: str) -> str:
    """Определяет тип напоминания по тексту"""
    text_lower = text.lower()
    
    # Ключевые слова для регулярных напоминаний (только целые слова)
    regular_keywords = [
        'каждый', 'каждое', 'ежедневно', 'регулярно', 'каждую', 
        'напоминай'  # "напоминай" - для регулярных
    ]
    
    # Дни недели
    days_keywords = [
        'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье',
        'пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'
    ]
    
    # Проверяем наличие ключевых слов для регулярных напоминаний
    for keyword in regular_keywords:
        # Ищем целые слова
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            logger.info(f"✅ Обнаружено ключевое слово для регулярного напоминания: {keyword}")
            return 'regular'
    
    # Проверяем дни недели
    for day in days_keywords:
        if day in text_lower:
            logger.info(f"✅ Обнаружен день недели: {day}")
            return 'regular'
    
    # Если нет признаков регулярности - разовое напоминание
    logger.info("✅ Определено как разовое напоминание")
    return 'once'

def schedule_reminders(application):
    """Настраивает периодическую проверку напоминаний"""
    try:
        job_queue = application.job_queue
        if job_queue:
            # Проверяем напоминания каждую минуту
            job_queue.run_repeating(
                callback=send_reminder_job,
                interval=60,  # 60 секунд
                first=10,     # начать через 10 секунд после запуска
                name="reminder_checker"
            )
            logger.info("✅ Система напоминаний запущена")
    except Exception as e:
        logger.error(f"❌ Ошибка настройки напоминаний: {e}")

# Функции для автоматических сообщений (они также относятся к напоминаниям)
async def send_morning_plan(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет утренний план пользователям (АСИНХРОННАЯ)"""
    from services.google_sheets import get_daily_plan_from_sheets
    
    try:
        async with get_db_connection() as conn:
            users = await conn.fetch(
                "SELECT user_id, first_name, username FROM clients WHERE status = 'active'"
            )
            
            for user in users:
                user_id = user['user_id']
                first_name = user['first_name']
                today = datetime.now().strftime("%Y-%m-%d")
                
                # Получаем план из Google Sheets
                plan_data = get_daily_plan_from_sheets(user_id, today)
                
                if plan_data:
                    # Формируем сообщение
                    message = f"🌅 Доброе утро, {first_name}!\n\n"
                    message += "📋 Ваш план на сегодня:\n\n"
                    
                    if plan_data.get('strategic_tasks'):
                        message += "🎯 СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
                        for task in plan_data['strategic_tasks']:
                            message += f"• {task}\n"
                        message += "\n"
                    
                    if plan_data.get('critical_tasks'):
                        message += "⚠️ КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
                        for task in plan_data['critical_tasks']:
                            message += f"• {task}\n"
                        message += "\n"
                    
                    if plan_data.get('priorities'):
                        message += "🎯 ПРИОРИТЕТЫ ДНЯ:\n"
                        for priority in plan_data['priorities']:
                            message += f"• {priority}\n"
                        message += "\n"
                    
                    if plan_data.get('advice'):
                        message += "💡 СОВЕТЫ АССИСТЕНТА:\n"
                        for advice in plan_data['advice']:
                            message += f"• {advice}\n"
                        message += "\n"
                    
                    if plan_data.get('motivation_quote'):
                        message += f"💫 МОТИВАЦИЯ: {plan_data['motivation_quote']}\n\n"
                    
                    message += "💪 Удачи в достижении ваших целей!"
                    
                    try:
                        await context.bot.send_message(chat_id=user_id, text=message)
                        logger.info(f"✅ Утренний план отправлен пользователю {user_id}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка отправки утреннего плана пользователю {user_id}: {e}")
                        
    except Exception as e:
        logger.error(f"❌ Ошибка в send_morning_plan: {e}")

async def send_evening_survey(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет вечерний опрос пользователям (АСИНХРОННАЯ)"""
    try:
        async with get_db_connection() as conn:
            users = await conn.fetch(
                "SELECT user_id, first_name FROM clients WHERE status = 'active'"
            )
            
            for user in users:
                user_id = user['user_id']
                first_name = user['first_name']
                
                message = (
                    f"🌙 Добрый вечер, {first_name}!\n\n"
                    "📊 Как прошел ваш день?\n\n"
                    "1. 🎯 Выполнили стратегические задачи? (да/нет/частично)\n"
                    "2. 🌅 Выполнили утренние ритуалы? (да/нет/частично)\n"
                    "3. 🌙 Выполнили вечерние ритуалы? (да/нет/частично)\n"
                    "4. 😊 Настроение от 1 до 10?\n"
                    "5. ⚡ Энергия от 1 до 10?\n"
                    "6. 🎯 Уровень фокуса от 1 до 10?\n"
                    "7. 🔥 Уровень мотивации от 1 до 10?\n"
                    "8. 🏆 Ключевые достижения сегодня?\n"
                    "9. 🚧 Были проблемы или препятствия?\n"
                    "10. 🌟 Что получилось хорошо?\n"
                    "11. 📈 Что можно улучшить?\n"
                    "12. 🔄 Корректировки на завтра?\n"
                    "13. 💧 Сколько воды выпили? (стаканов)\n\n"
                )
                
                try:
                    await context.bot.send_message(chat_id=user_id, text=message)
                    logger.info(f"✅ Вечерний опрос отправлен пользователю {user_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки вечернего опроса пользователю {user_id}: {e}")
                    
    except Exception as e:
        logger.error(f"❌ Ошибка в send_evening_survey: {e}")
