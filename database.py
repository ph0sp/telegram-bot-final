import logging
import json
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL, logger, QUESTIONS, POSTGRESQL_AVAILABLE

# ========== УНИВЕРСАЛЬНАЯ СИСТЕМА БАЗЫ ДАННЫХ ==========

@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к PostgreSQL"""
    if not DATABASE_URL or not POSTGRESQL_AVAILABLE:
        logger.error("❌ PostgreSQL не настроен или не доступен")
        raise Exception("PostgreSQL не доступен")
    
    conn = None
    try:
        # Парсим URL базы данных для PostgreSQL
        urllib.parse.uses_netloc.append("postgres")
        url = urllib.parse.urlparse(DATABASE_URL)
        
        conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port,
            cursor_factory=RealDictCursor,
            connect_timeout=10
        )
        logger.debug("✅ Подключение к PostgreSQL установлено")
        yield conn
    except psycopg2.OperationalError as e:
        logger.error(f"❌ Ошибка подключения к PostgreSQL (операционная): {e}")
        if conn:
            conn.rollback()
        raise
    except psycopg2.Error as e:
        logger.error(f"❌ Ошибка PostgreSQL: {e}")
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка подключения к БД: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
            logger.debug("🔌 Подключение к PostgreSQL закрыто")

def init_database():
    """Инициализирует таблицы в базе данных PostgreSQL"""
    if not POSTGRESQL_AVAILABLE:
        logger.error("❌ PostgreSQL не доступен для инициализации")
        return False
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица клиентов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clients (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE NOT NULL,
                    first_name TEXT,
                    username TEXT,
                    last_name TEXT,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    gender TEXT,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица ответов анкеты
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questionnaire_answers (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    question_number INTEGER NOT NULL,
                    question_text TEXT,
                    answer_text TEXT NOT NULL,
                    answer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, question_number)
                )
            ''')
            
            # Таблица прогресса
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_progress (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    progress_date DATE NOT NULL,
                    tasks_completed INTEGER DEFAULT 0,
                    mood INTEGER CHECK (mood >= 1 AND mood <= 10),
                    energy INTEGER CHECK (energy >= 1 AND energy <= 10),
                    sleep_quality INTEGER CHECK (sleep_quality >= 1 AND sleep_quality <= 10),
                    water_intake INTEGER DEFAULT 0,
                    activity_done TEXT,
                    user_comment TEXT,
                    day_rating INTEGER CHECK (day_rating >= 1 AND day_rating <= 10),
                    challenges TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, progress_date)
                )
            ''')
            
            # Таблица напоминаний
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_reminders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    reminder_text TEXT NOT NULL,
                    reminder_time TIME NOT NULL,
                    days_of_week TEXT,
                    reminder_type TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_triggered TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                )
            ''')
            
            # Таблица планов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_plans (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    plan_date DATE NOT NULL,
                    morning_ritual1 TEXT,
                    morning_ritual2 TEXT,
                    task1 TEXT,
                    task2 TEXT,
                    task3 TEXT,
                    task4 TEXT,
                    lunch_break TEXT,
                    evening_ritual1 TEXT,
                    evening_ritual2 TEXT,
                    advice TEXT,
                    sleep_time TEXT,
                    water_goal TEXT,
                    activity_goal TEXT,
                    status TEXT DEFAULT 'active',
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE,
                    UNIQUE(user_id, plan_date)
                )
            ''')
            
            # Таблица сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_messages (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    message_text TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('incoming', 'outgoing')),
                    message_type TEXT DEFAULT 'text',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                )
            ''')
            
            # Создаем индексы для улучшения производительности
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_clients_user_id ON clients(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_questionnaire_user_id ON questionnaire_answers(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_progress_user_date ON user_progress(user_id, progress_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_plans_user_date ON user_plans(user_id, plan_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_reminders_user_active ON user_reminders(user_id, is_active)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_user_created ON user_messages(user_id, created_at)')
            
            conn.commit()
            logger.info("✅ Таблицы PostgreSQL инициализированы и индексы созданы")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

# ========== ОСНОВНЫЕ ФУНКЦИИ БАЗЫ ДАННЫХ ==========

def save_user_info(user_id: int, username: str, first_name: str, last_name: Optional[str] = None):
    """Сохраняет информацию о пользователе в базу данных безопасно"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение пользователя {user_id}")
        return
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            registration_date = datetime.now()
            
            cursor.execute('''INSERT INTO clients 
                             (user_id, username, first_name, last_name, status, registration_date, last_activity) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s)
                             ON CONFLICT (user_id) DO UPDATE SET
                             username = EXCLUDED.username,
                             first_name = EXCLUDED.first_name,
                             last_name = EXCLUDED.last_name,
                             last_activity = EXCLUDED.last_activity''',
                          (user_id, username, first_name, last_name, 'active', registration_date, registration_date))
            
            conn.commit()
            logger.info(f"✅ Информация о пользователе {user_id} сохранена в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")

def update_user_activity(user_id: int):
    """Обновляет время последней активности пользователя безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            last_activity = datetime.now()
            
            cursor.execute('''UPDATE clients SET last_activity = %s WHERE user_id = %s''',
                          (last_activity, user_id))
            
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления активности {user_id}: {e}")

def check_user_registered(user_id: int) -> bool:
    """Проверяет зарегистрирован ли пользователь безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return False
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_id FROM clients WHERE user_id = %s", (user_id,))
            
            result = cursor.fetchone()
            return result is not None
            
    except Exception as e:
        logger.error(f"❌ Ошибка проверки регистрации {user_id}: {e}")
        return False

def save_questionnaire_answer(user_id: int, question_number: int, question_text: str, answer_text: str):
    """Сохраняет ответ на вопрос анкеты безопасно"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение ответа {user_id}")
        return
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            answer_date = datetime.now()
            
            # Получаем текст вопроса из конфига, если не передан
            if not question_text and question_number < len(QUESTIONS):
                question_text = QUESTIONS[question_number][:500]  # Обрезаем длинные вопросы
            
            cursor.execute('''INSERT INTO questionnaire_answers 
                             (user_id, question_number, question_text, answer_text, answer_date) 
                             VALUES (%s, %s, %s, %s, %s)
                             ON CONFLICT (user_id, question_number) 
                             DO UPDATE SET 
                                answer_text = EXCLUDED.answer_text,
                                answer_date = EXCLUDED.answer_date''',
                          (user_id, question_number, question_text, answer_text, answer_date))
            
            conn.commit()
            logger.debug(f"✅ Ответ на вопрос {question_number} сохранен для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения ответа {user_id}: {e}")

def save_message(user_id: int, message_text: str, direction: str):
    """Сохраняет сообщение в базу данных безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            created_at = datetime.now()
            
            # Определяем тип сообщения
            message_type = 'text'
            if len(message_text) > 1000:
                message_type = 'long_text'
            elif any(keyword in message_text.lower() for keyword in ['команда', '/start', '/help']):
                message_type = 'command'
            
            cursor.execute('''INSERT INTO user_messages 
                             (user_id, message_text, direction, message_type, created_at) 
                             VALUES (%s, %s, %s, %s, %s)''',
                          (user_id, message_text, direction, message_type, created_at))
            
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения {user_id}: {e}")

def save_user_plan_to_db(user_id: int, plan_data: Dict[str, Any]):
    """Сохраняет план пользователя в базу данных безопасно"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение плана {user_id}")
        return
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            created_date = datetime.now()
            
            cursor.execute('''INSERT INTO user_plans 
                             (user_id, plan_date, morning_ritual1, morning_ritual2, task1, task2, task3, task4, 
                              lunch_break, evening_ritual1, evening_ritual2, advice, sleep_time, water_goal, 
                              activity_goal, created_date) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                             ON CONFLICT (user_id, plan_date) 
                             DO UPDATE SET
                                morning_ritual1 = EXCLUDED.morning_ritual1,
                                morning_ritual2 = EXCLUDED.morning_ritual2,
                                task1 = EXCLUDED.task1,
                                task2 = EXCLUDED.task2,
                                task3 = EXCLUDED.task3,
                                task4 = EXCLUDED.task4,
                                lunch_break = EXCLUDED.lunch_break,
                                evening_ritual1 = EXCLUDED.evening_ritual1,
                                evening_ritual2 = EXCLUDED.evening_ritual2,
                                advice = EXCLUDED.advice,
                                sleep_time = EXCLUDED.sleep_time,
                                water_goal = EXCLUDED.water_goal,
                                activity_goal = EXCLUDED.activity_goal,
                                updated_date = EXCLUDED.created_date''',
                          (user_id, plan_data.get('plan_date'), plan_data.get('morning_ritual1'), 
                           plan_data.get('morning_ritual2'), plan_data.get('task1'), plan_data.get('task2'),
                           plan_data.get('task3'), plan_data.get('task4'), plan_data.get('lunch_break'),
                           plan_data.get('evening_ritual1'), plan_data.get('evening_ritual2'), 
                           plan_data.get('advice'), plan_data.get('sleep_time'), plan_data.get('water_goal'),
                           plan_data.get('activity_goal'), created_date))
            
            conn.commit()
            logger.info(f"✅ План сохранен в БД для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения плана {user_id}: {e}")

def get_user_plan_from_db(user_id: int):
    """Получает текущий план пользователя из базу данных безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return None
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''SELECT * FROM user_plans 
                             WHERE user_id = %s AND status = 'active' 
                             ORDER BY created_date DESC LIMIT 1''', (user_id,))
            
            plan = cursor.fetchone()
            return plan
    except Exception as e:
        logger.error(f"❌ Ошибка получения плана {user_id}: {e}")
        return None

def save_progress_to_db(user_id: int, progress_data: Dict[str, Any]):
    """Сохраняет прогресс пользователя в базу данных безопасно"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение прогресса {user_id}")
        return
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            progress_date = datetime.now().date()
            
            cursor.execute('''INSERT INTO user_progress 
                             (user_id, progress_date, tasks_completed, mood, energy, sleep_quality, 
                              water_intake, activity_done, user_comment, day_rating, challenges) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                             ON CONFLICT (user_id, progress_date)
                             DO UPDATE SET
                                tasks_completed = EXCLUDED.tasks_completed,
                                mood = EXCLUDED.mood,
                                energy = EXCLUDED.energy,
                                sleep_quality = EXCLUDED.sleep_quality,
                                water_intake = EXCLUDED.water_intake,
                                activity_done = EXCLUDED.activity_done,
                                user_comment = EXCLUDED.user_comment,
                                day_rating = EXCLUDED.day_rating,
                                challenges = EXCLUDED.challenges''',
                          (user_id, progress_date, progress_data.get('tasks_completed'), 
                           progress_data.get('mood'), progress_data.get('energy'), 
                           progress_data.get('sleep_quality'), progress_data.get('water_intake'),
                           progress_data.get('activity_done'), progress_data.get('user_comment'),
                           progress_data.get('day_rating'), progress_data.get('challenges')))
            
            conn.commit()
            logger.info(f"✅ Прогресс сохранен в БД для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения прогресса {user_id}: {e}")

def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Возвращает статистику пользователя безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return {'messages_count': 0, 'registration_date': 'База данных не доступна'}
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM user_messages WHERE user_id = %s AND direction = 'incoming'", (user_id,))
            messages_count_result = cursor.fetchone()
            messages_count = messages_count_result['count'] if messages_count_result else 0
            
            cursor.execute("SELECT registration_date FROM clients WHERE user_id = %s", (user_id,))
            reg_date_result = cursor.fetchone()
            reg_date = reg_date_result['registration_date'] if reg_date_result else "Неизвестно"
            
            return {
                'messages_count': messages_count,
                'registration_date': reg_date
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики {user_id}: {e}")
        return {'messages_count': 0, 'registration_date': 'Ошибка'}

def has_sufficient_data(user_id: int) -> bool:
    """Проверяет есть ли достаточно данных для статистики (минимум 3 дня) безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return False
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            count = result['count'] if result else 0
            
            return count >= 3
    except Exception as e:
        logger.error(f"❌ Ошибка проверки данных {user_id}: {e}")
        return False

def get_user_activity_streak(user_id: int) -> int:
    """Возвращает текущую серию активных дней подряд безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return 0
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT DISTINCT progress_date FROM user_progress WHERE user_id = %s ORDER BY progress_date DESC", (user_id,))
            dates_result = cursor.fetchall()
            dates = [row['progress_date'] for row in dates_result if row['progress_date']]
            
            if not dates:
                return 0
            
            # Сортируем по убыванию и проверяем последовательность
            dates.sort(reverse=True)
            streak = 0
            today = datetime.now().date()
            
            for i, date in enumerate(dates):
                expected_date = today - timedelta(days=i)
                if date == expected_date:
                    streak += 1
                else:
                    break
            
            return streak
    except Exception as e:
        logger.error(f"❌ Ошибка получения серии {user_id}: {e}")
        return 0

def get_user_main_goal(user_id: int) -> str:
    """Получает главную цель пользователя из анкеты безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return "База данных не доступна"
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT answer_text FROM questionnaire_answers WHERE user_id = %s AND question_number = 0", (user_id,))
            result = cursor.fetchone()
            return result['answer_text'] if result else "Цель не установлена"
    except Exception as e:
        logger.error(f"❌ Ошибка получения цели {user_id}: {e}")
        return "Ошибка загрузки цели"

def get_user_level_info(user_id: int) -> Dict[str, Any]:
    """Возвращает информацию об уровне пользователя безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return {'level': 'Новичок', 'points': 0, 'points_to_next': 50, 'next_level_points': 50}
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", (user_id,))
            active_days_result = cursor.fetchone()
            active_days = active_days_result['count'] if active_days_result else 0
            
            cursor.execute("SELECT SUM(tasks_completed) FROM user_progress WHERE user_id = %s", (user_id,))
            total_tasks_result = cursor.fetchone()
            total_tasks = total_tasks_result['sum'] if total_tasks_result else 0
            
            level_points = active_days * 10 + total_tasks * 2
            level_names = {
                0: "Новичок",
                50: "Ученик", 
                100: "Опытный",
                200: "Профессионал",
                500: "Мастер"
            }
            
            current_level = "Новичок"
            next_level_points = 50
            points_to_next = 50
            
            # Исправленная логика определения уровня
            sorted_points = sorted(level_names.keys())
            for i, points in enumerate(sorted_points):
                if level_points >= points:
                    current_level = level_names[points]
                    # Если есть следующий уровень
                    if i < len(sorted_points) - 1:
                        next_level_points = sorted_points[i + 1]
                        points_to_next = next_level_points - level_points
                    else:
                        # Достигнут максимальный уровень
                        next_level_points = points
                        points_to_next = 0
                else:
                    break
            
            return {
                'level': current_level,
                'points': level_points,
                'points_to_next': points_to_next,
                'next_level_points': next_level_points
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения уровня {user_id}: {e}")
        return {'level': 'Новичок', 'points': 0, 'points_to_next': 50, 'next_level_points': 50}

def get_favorite_ritual(user_id: int) -> str:
    """Определяет любимый ритуал пользователя безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return "на основе ваших предпочтений"
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Используем номер вопроса из анкеты для ритуалов
            cursor.execute("SELECT answer_text FROM questionnaire_answers WHERE user_id = %s AND question_number = 32", (user_id,))
            result = cursor.fetchone()
            
            if result:
                rituals_text = result['answer_text'].lower() if result['answer_text'] else ""
                
                if "медитация" in rituals_text:
                    return "Утренняя медитация"
                elif "зарядка" in rituals_text or "растяжка" in rituals_text:
                    return "Утренняя зарядка"
                elif "чтение" in rituals_text:
                    return "Вечернее чтение"
                elif "дневник" in rituals_text:
                    return "Ведение дневника"
                elif "планирование" in rituals_text:
                    return "Планирование задач"
            
            return "на основе ваших предпочтений"
    except Exception as e:
        logger.error(f"❌ Ошибка получения ритуала {user_id}: {e}")
        return "на основе ваших предпочтений"

def get_user_usage_days(user_id: int) -> Dict[str, int]:
    """Возвращает статистику дней использования безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT registration_date FROM clients WHERE user_id = %s", (user_id,))
            reg_result = cursor.fetchone()
            
            if not reg_result:
                return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
            
            reg_date = reg_result['registration_date'].date()
            days_since_registration = (datetime.now().date() - reg_date).days + 1
            
            cursor.execute("SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = %s", (user_id,))
            active_days_result = cursor.fetchone()
            active_days = active_days_result['count'] if active_days_result else 0
            
            current_streak = get_user_activity_streak(user_id)
            
            return {
                'days_since_registration': days_since_registration,
                'active_days': active_days,
                'current_day': active_days if active_days > 0 else 1,
                'current_streak': current_streak
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения дней использования {user_id}: {e}")
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}

# ========== ФУНКЦИИ ДЛЯ НАПОМИНАНИЙ ==========

def add_reminder_to_db(user_id: int, reminder_data: Dict[str, Any]) -> bool:
    """Добавляет напоминание в базу данных - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем добавление напоминания {user_id}")
        return False
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 🔧 ОБРАБОТКА ОТНОСИТЕЛЬНЫХ НАПОМИНАНИЙ
            if reminder_data.get('type') == 'once' and 'delay_minutes' in reminder_data:
                # Для относительных напоминаний вычисляем точное время
                reminder_time = (datetime.now() + timedelta(minutes=reminder_data['delay_minutes'])).strftime("%H:%M")
            else:
                reminder_time = reminder_data['time']
            
            days_str = ','.join(reminder_data['days']) if reminder_data['days'] else 'ежедневно'
            created_date = datetime.now()
            
            cursor.execute('''INSERT INTO user_reminders 
                             (user_id, reminder_text, reminder_time, days_of_week, reminder_type, created_date)
                             VALUES (%s, %s, %s, %s, %s, %s)''',
                          (user_id, reminder_data['text'], reminder_time, 
                           days_str, reminder_data['type'], created_date))
            
            conn.commit()
            logger.info(f"✅ Напоминание добавлено для пользователя {user_id} на {reminder_time}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка добавления напоминания: {e}")
        return False

def get_user_reminders(user_id: int) -> List[Dict]:
    """Возвращает список напоминаний пользователя безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return []
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''SELECT id, reminder_text, reminder_time, days_of_week, reminder_type 
                             FROM user_reminders 
                             WHERE user_id = %s AND is_active = TRUE 
                             ORDER BY created_date DESC''', (user_id,))
            
            reminders = []
            for row in cursor.fetchall():
                reminders.append({
                    'id': row['id'],
                    'text': row['reminder_text'],
                    'time': row['reminder_time'],
                    'days': row['days_of_week'],
                    'type': row['reminder_type']
                })
            
            return reminders
    except Exception as e:
        logger.error(f"❌ Ошибка получения напоминаний {user_id}: {e}")
        return []

def delete_reminder_from_db(reminder_id: int) -> bool:
    """Удаляет напоминание по ID безопасно"""
    if not POSTGRESQL_AVAILABLE:
        return False
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''UPDATE user_reminders SET is_active = FALSE WHERE id = %s''', (reminder_id,))
            
            conn.commit()
            logger.info(f"✅ Напоминание {reminder_id} удалено")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка удаления напоминания: {e}")
        return False

# Вызываем инициализацию при импорте модуля только если БД доступна
if POSTGRESQL_AVAILABLE:
    init_database()
else:
    logger.warning("⚠️ Пропускаем инициализацию БД - PostgreSQL не доступен")
