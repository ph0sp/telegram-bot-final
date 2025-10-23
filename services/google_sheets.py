import logging
import json
import gspread
from google.oauth2.service_account import Credentials
from typing import Dict, Any, List, Optional
from datetime import datetime
import os

from config import GOOGLE_SHEETS_ID, logger

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения подключения к Google Sheets
google_sheet = None

def init_google_sheets():
    """Инициализация Google Sheets с исправленной загрузкой credentials"""
    global google_sheet
    
    try:
        # Пытаемся загрузить credentials разными способами
        creds_dict = None
        
        # Способ 1: Из переменной окружения
        from config import GOOGLE_CREDENTIALS_JSON
        if GOOGLE_CREDENTIALS_JSON:
            try:
                # Проверяем, является ли уже словарем
                if isinstance(GOOGLE_CREDENTIALS_JSON, dict):
                    creds_dict = GOOGLE_CREDENTIALS_JSON
                    logger.info("✅ Credentials загружены из переменной окружения (уже dict)")
                else:
                    # Пытаемся распарсить как JSON строку
                    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
                    logger.info("✅ Credentials загружены из переменной окружения (распарсена строка)")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"⚠️ Не удалось распарсить GOOGLE_CREDENTIALS_JSON: {e}")
        
        # Способ 2: Из файла (резервный вариант)
        if not creds_dict and os.path.exists('/home/ubuntu/telegram-bot/creds.json'):
            try:
                with open('/home/ubuntu/telegram-bot/creds.json', 'r') as f:
                    creds_dict = json.load(f)
                logger.info("✅ Credentials загружены из файла creds.json")
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки credentials из файла: {e}")
        
        if not creds_dict:
            logger.error("❌ Не удалось загрузить credentials ни из переменной окружения, ни из файла")
            return None
        
        if not GOOGLE_SHEETS_ID:
            logger.error("❌ GOOGLE_SHEETS_ID не настроен")
            return None
        
        # Настраиваем scope
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Создаем credentials
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        
        # Авторизуемся
        client = gspread.authorize(creds)
        
        # Открываем таблицу
        sheet = client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Создаем листы если их нет
        try:
            sheet.worksheet("клиенты_детали")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="клиенты_детали", rows=1000, cols=27)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "старт_работы",
                "пробуждение", "отход_ко_сну", "предпочтения_активности",
                "особенности_питания", "предпочтения_отдыха",
                "постоянные_утренние_ритуалы", "постоянные_вечерние_ритуалы",
                "индивидуальные_привычки", "лекарства_витамины",
                "цели_развиния", "главная_цель", "особые_примечания",
                "дата_последней_активности", "статус",
                "текущий_уровень", "очки_опыта", "текущая_серия_активности",
                "максимальная_серия_активности", "любимый_ритуал", 
                "дата_последнего_прогресса", "ближайшая_цель"
            ])
        
        try:
            sheet.worksheet("индивидуальные_планы_месяц")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="индивидуальные_планы_месяц", rows=1000, cols=40)
            headers = ["id_клиента", "telegram_username", "имя", "месяц"]
            for day in range(1, 32):
                headers.append(f"{day} октября")
            headers.extend(["общие_комментарии_месяца", "последнее_обновление"])
            worksheet.append_row(headers)
        
        try:
            sheet.worksheet("ежедневные_отчеты")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="ежедневные_отчеты", rows=1000, cols=28)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "дата",
                "выполнено_стратегических_задач", "утренние_ритуалы_выполнены",
                "вечерние_ритуалы_выполнены", "настроение", "энергия",
                "уровень_фокуса", "уровень_мотивации", "проблемы_препятствия",
                "вопросы_ассистенту", "что_получилось_хорошо", 
                "ключевые_достижения_дня", "что_можно_улучшить",
                "корректировки_на_завтра", "водный_баланс_факт", "статус_дня",
                "уровень_дня", "серия_активности", "любимый_ритуал_выполнен",
                "прогресс_по_цели", "рекомендации_на_день", "динамика_настроения",
                "динамика_энергии", "динамика_продуктивности"
            ])
        
        try:
            sheet.worksheet("статистика_месяца")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="статистика_месяца", rows=1000, cols=29)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "месяц",
                "среднее_настроение", "средний_уровень_мотивации",
                "процент_выполнения_планов", "прогресс_по_целям",
                "количество_активных_дней", "динамика_настроения",
                "процент_выполнения_утренних_ритуалов",
                "процент_выполнения_вечерних_ритуалов",
                "общее_количество_достижений", "основные_корректировки_месяца",
                "рекомендации_на_следующий_месяц", "итоги_месяца",
                "текущий_уровень", "серия_активности", "любимые_ритуалы",
                "динамика_регулярности", "персональные_рекомендации", 
                "уровень_в_начале_месяца", "уровень_в_конце_месяца",
                "общее_количество_очков", "средняя_продуктивность"
            ])
        
        try:
            sheet.worksheet("админ_панель")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="админ_панель", rows=1000, cols=10)
            worksheet.append_row([
                "id_клиента", "telegram_username", "имя", "текущий_статус",
                "требует_внимания", "последняя_корректировка",
                "следующий_чекап", "приоритет", "заметки_ассистента"
            ])
        
        logger.info("✅ Google Sheets инициализирован с новой структурой")
        google_sheet = sheet
        return sheet
    
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Google Sheets: {e}")
        return None

# Инициализируем Google Sheets при импорте модуля
google_sheet = init_google_sheets()

def save_client_to_sheets(user_data: Dict[str, Any]):
    """Сохраняет клиента в Google Sheets"""
    if not google_sheet:
        logger.warning("⚠️ Google Sheets не доступен")
        return False
    
    try:
        worksheet = google_sheet.worksheet("клиенты_детали")
        
        # Ищем существующего клиента
        try:
            cell = worksheet.find(str(user_data['user_id']))
            row = cell.row
            worksheet.update(f'A{row}:Y{row}', [[
                user_data['user_id'],
                user_data.get('telegram_username', ''),
                user_data.get('first_name', ''),
                user_data.get('start_date', ''),
                user_data.get('wake_time', ''),
                user_data.get('sleep_time', ''),
                user_data.get('activity_preferences', ''),
                user_data.get('diet_features', ''),
                user_data.get('rest_preferences', ''),
                user_data.get('morning_rituals', ''),
                user_data.get('evening_rituals', ''),
                user_data.get('personal_habits', ''),
                user_data.get('medications', ''),
                user_data.get('development_goals', ''),
                user_data.get('main_goal', ''),
                user_data.get('special_notes', ''),
                user_data.get('last_activity', ''),
                'active',
                user_data.get('текущий_уровень', 'Новичок'),
                user_data.get('очки_опыта', '0'),
                user_data.get('текущая_серия_активности', '0'),
                user_data.get('максимальная_серия_активности', '0'),
                user_data.get('любимый_ритуал', ''),
                user_data.get('дата_последнего_прогресса', ''),
                user_data.get('ближайшая_цель', '')
            ]])
        except Exception:
            # Создаем новую запись
            worksheet.append_row([
                user_data['user_id'],
                user_data.get('telegram_username', ''),
                user_data.get('first_name', ''),
                user_data.get('start_date', ''),
                user_data.get('wake_time', ''),
                user_data.get('sleep_time', ''),
                user_data.get('activity_preferences', ''),
                user_data.get('diet_features', ''),
                user_data.get('rest_preferences', ''),
                user_data.get('morning_rituals', ''),
                user_data.get('evening_rituals', ''),
                user_data.get('personal_habits', ''),
                user_data.get('medications', ''),
                user_data.get('development_goals', ''),
                user_data.get('main_goal', ''),
                user_data.get('special_notes', ''),
                user_data.get('last_activity', ''),
                'active',
                user_data.get('текущий_уровень', 'Новичок'),
                user_data.get('очки_опыта', '0'),
                user_data.get('текущая_серия_активности', '0'),
                user_data.get('максимальная_серия_активности', '0'),
                user_data.get('любимый_ритуал', ''),
                user_data.get('дата_последнего_прогресса', ''),
                user_data.get('ближайшая_цель', '')
            ])
        
        logger.info(f"✅ Клиент {user_data['user_id']} сохранен в Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения клиента в Google Sheets: {e}")
        return False

def format_enhanced_plan(plan_data: Dict[str, Any]) -> str:
    """Форматирует план с улучшенной структурой"""
    plan_text = f"🏁 {plan_data.get('name', 'Индивидуальный план')}\n\n"
    plan_text += f"📝 {plan_data.get('description', '')}\n\n"
    
    if plan_data.get('strategic_tasks'):
        plan_text += "🎯 СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:\n"
        for i, task in enumerate(plan_data['strategic_tasks'], 1):
            plan_text += f"{i}️⃣ {task}\n"
        plan_text += "\n"
    
    if plan_data.get('critical_tasks'):
        plan_text += "⚠️ КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:\n"
        for i, task in enumerate(plan_data['critical_tasks'], 1):
            plan_text += f"🔴 {task}\n"
        plan_text += "\n"
    
    if plan_data.get('priorities'):
        plan_text += "🎯 ПРИОРИТЕТЫ ДНЯ:\n"
        for priority in plan_data['priorities']:
            plan_text += f"⭐ {priority}\n"
        plan_text += "\n"
    
    if plan_data.get('time_blocks'):
        plan_text += "⏰ ВРЕМЕННЫЕ БЛОКИ:\n"
        for block in plan_data['time_blocks']:
            plan_text += f"🕒 {block}\n"
        plan_text += "\n"
    
    if plan_data.get('advice'):
        plan_text += "💡 СОВЕТЫ АССИСТЕНТА:\n"
        for advice in plan_data['advice']:
            plan_text += f"💫 {advice}\n"
        plan_text += "\n"
    
    if plan_data.get('motivation_quote'):
        plan_text += f"💫 МОТИВАЦИОННАЯ ЦИТАТА:\n{plan_data['motivation_quote']}\n"
    
    return plan_text.strip()

def save_daily_report_to_sheets(user_id: int, report_data: Dict[str, Any]):
    """Сохраняет ежедневный отчет в Google Sheets"""
    if not google_sheet:
        logger.warning("⚠️ Google Sheets не доступен")
        return False
    
    try:
        worksheet = google_sheet.worksheet("ежедневные_отчеты")
        
        from database import get_db_connection
        conn = get_db_connection()
        if not conn:
            return False
            
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT username, first_name FROM clients WHERE user_id = %s", (user_id,))
            user_info = cursor.fetchone()
        
            username = user_info['username'] if user_info and user_info['username'] else ""
            first_name = user_info['first_name'] if user_info and user_info['first_name'] else ""
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о пользователе {user_id}: {e}")
            return False
        finally:
            conn.close()
        
        worksheet.append_row([
            user_id,
            username,
            first_name,
            report_data.get('date', ''),
            report_data.get('strategic_tasks_done', ''),
            report_data.get('morning_rituals_done', ''),
            report_data.get('evening_rituals_done', ''),
            report_data.get('mood', ''),
            report_data.get('energy', ''),
            report_data.get('focus_level', ''),
            report_data.get('motivation_level', ''),
            report_data.get('problems', ''),
            report_data.get('questions', ''),
            report_data.get('what_went_well', ''),
            report_data.get('key_achievements', ''),
            report_data.get('what_to_improve', ''),
            report_data.get('adjustments', ''),
            report_data.get('water_intake', ''),
            report_data.get('day_status', ''),
            report_data.get('уровень_дня', ''),
            report_data.get('серия_активности', ''),
            report_data.get('любимый_ритуал_выполнен', ''),
            report_data.get('прогресс_по_цели', ''),
            report_data.get('рекомендации_на_день', ''),
            report_data.get('динамика_настроения', ''),
            report_data.get('динамика_энергии', ''),
            report_data.get('динамика_продуктивности', '')
        ])
        
        logger.info(f"✅ Отчет сохранен в Google Sheets для пользователя {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения отчета: {e}")
        return False

def get_daily_plan_from_sheets(user_id: int, date: str) -> Dict[str, Any]:
    """Получает план на день из Google Sheets"""
    if not google_sheet:
        logger.warning("⚠️ Google Sheets не доступен")
        return {}
    
    try:
        worksheet = google_sheet.worksheet("индивидуальные_планы_месяц")
        
        # Ищем пользователя
        try:
            cell = worksheet.find(str(user_id))
            row = cell.row
        except Exception:
            logger.warning(f"⚠️ Пользователь {user_id} не найден в Google Sheets")
            return {}
        
        # Получаем все данные строки
        row_data = worksheet.row_values(row)
        
        # Определяем колонку для нужной даты
        day = datetime.strptime(date, "%Y-%m-%d").day
        date_column_index = 4 + day - 1  # 4 базовые колонки + день месяца
        
        if date_column_index >= len(row_data):
            logger.warning(f"⚠️ Для даты {date} нет данных в Google Sheets")
            return {}
        
        plan_text = row_data[date_column_index]
        
        # Парсим структурированный текст плана
        plan_data = parse_structured_plan(plan_text)
        
        return plan_data
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения плана: {e}")
        return {}

def parse_structured_plan(plan_text: str) -> Dict[str, Any]:
    """Парсит структурированный текст плана на компоненты"""
    if not plan_text:
        return {}
    
    sections = {
        'strategic_tasks': [],
        'critical_tasks': [],
        'priorities': [],
        'advice': [],
        'special_rituals': [],
        'time_blocks': [],
        'resources': [],
        'expected_results': [],
        'reminders': [],
        'motivation_quote': ''
    }
    
    current_section = None
    
    for line in plan_text.split('\n'):
        line = line.strip()
        
        if not line:
            continue
            
        # Определяем секции
        if 'СТРАТЕГИЧЕСКИЕ ЗАДАЧИ:' in line:
            current_section = 'strategic_tasks'
            continue
        elif 'КРИТИЧЕСКИ ВАЖНЫЕ ЗАДАЧИ:' in line:
            current_section = 'critical_tasks'
            continue
        elif 'ПРИОРИТЕТЫ ДНЯ:' in line:
            current_section = 'priorities'
            continue
        elif 'СОВЕТЫ АССИСТЕНТА:' in line:
            current_section = 'advice'
            continue
        elif 'СПЕЦИАЛЬНЫЕ РИТУАЛЫ:' in line:
            current_section = 'special_rituals'
            continue
        elif 'ВРЕМЕННЫЕ БЛОКИ:' in line:
            current_section = 'time_blocks'
            continue
        elif 'РЕСУРСЫ И МАТЕРИАЛЫ:' in line:
            current_section = 'resources'
            continue
        elif 'ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ:' in line:
            current_section = 'expected_results'
            continue
        elif 'ДОПОЛНИТЕЛЬНЫЕ НАПОМИНАНИЯ:' in line:
            current_section = 'reminders'
            continue
        elif 'МОТИВАЦИОННАЯ ЦИТАТА:' in line:
            current_section = 'motivation_quote'
            continue
            
        # Добавляем данные в текущую секцию
        if current_section and line.startswith('- '):
            content = line[2:].strip()
            if current_section == 'motivation_quote':
                sections[current_section] = content
            else:
                sections[current_section].append(content)
    
    return sections

def save_daily_plan_to_sheets(user_id: int, date: str, plan: Dict[str, Any]) -> bool:
    """Сохраняет план в Google Sheets"""
    if not google_sheet:
        logger.warning("⚠️ Google Sheets не доступен")
        return False
    
    try:
        worksheet = google_sheet.worksheet("индивидуальные_планы_месяц")
        
        # Форматируем план в структурированный текст
        plan_text = format_enhanced_plan(plan)
        
        # Ищем пользователя
        try:
            cell = worksheet.find(str(user_id))
            row = cell.row
        except Exception:
            # Если пользователя нет, создаем новую строку
            from database import get_db_connection
            conn = get_db_connection()
            if not conn:
                return False
                
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT username, first_name FROM clients WHERE user_id = %s", (user_id,))
                user_info = cursor.fetchone()
                
                username = user_info['username'] if user_info and user_info['username'] else ""
                first_name = user_info['first_name'] if user_info and user_info['first_name'] else ""
                
                # Создаем новую строку
                current_month = datetime.now().strftime("%B %Y")
                new_row = [user_id, username, first_name, current_month]
                # Заполняем пустыми значениями для всех дней
                for _ in range(31):
                    new_row.append("")
                new_row.extend(["", datetime.now().strftime("%Y-%m-%d %H:%M")])
                
                worksheet.append_row(new_row)
                
                # Теперь находим добавленную строку
                cell = worksheet.find(str(user_id))
                row = cell.row
                
            except Exception as e:
                logger.error(f"❌ Ошибка создания строки для пользователя {user_id}: {e}")
                return False
            finally:
                conn.close()
        
        # Определяем колонку для нужной даты
        day = datetime.strptime(date, "%Y-%m-%d").day
        date_column_index = 4 + day  # 4 базовые колонки + день месяца (индексация с 1)
        
        # Обновляем ячейку с планом
        worksheet.update_cell(row, date_column_index, plan_text)
        
        logger.info(f"✅ План сохранен в Google Sheets для пользователя {user_id} на {date}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения плана: {e}")
        return False
