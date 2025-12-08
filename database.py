import logging
import json
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from contextlib import asynccontextmanager

import asyncpg
from asyncpg import Connection, Record

from config import DATABASE_URL, logger, QUESTIONS, POSTGRESQL_AVAILABLE

# Глобальный пул подключений для эффективности
_connection_pool = None

async def get_connection_pool():
    """Создает и возвращает пул подключений к PostgreSQL"""
    global _connection_pool
    if _connection_pool is None:
        try:
            _connection_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=10,
                command_timeout=60,
                server_settings={
                    'application_name': 'telegram_bot',
                    'timezone': 'UTC'
                }
            )
            logger.info("✅ Пул подключений к PostgreSQL создан")
        except Exception as e:
            logger.error(f"❌ Ошибка создания пула подключений: {e}")
            raise
    return _connection_pool

@asynccontextmanager
async def get_db_connection():
    """Асинхронный контекстный менеджер для подключения к PostgreSQL"""
    if not DATABASE_URL or not POSTGRESQL_AVAILABLE:
        logger.error("❌ PostgreSQL не настроен или не доступен")
        raise Exception("PostgreSQL не доступен")
    
    pool = await get_connection_pool()
    conn = None
    try:
        conn = await pool.acquire()
        logger.debug("✅ Подключение к PostgreSQL установлено")
        yield conn
    except asyncpg.PostgresError as e:
        logger.error(f"❌ Ошибка PostgreSQL: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка подключения к БД: {e}")
        raise
    finally:
        if conn:
            await pool.release(conn)
            logger.debug("🔌 Подключение к PostgreSQL возвращено в пул")

async def init_database():
    """Асинхронно инициализирует таблицы в базе данных PostgreSQL"""
    if not POSTGRESQL_AVAILABLE:
        logger.error("❌ PostgreSQL не доступен для инициализации")
        return False
    
    try:
        async with get_db_connection() as conn:
            # Таблица клиентов
            await conn.execute('''
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
            await conn.execute('''
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
            await conn.execute('''
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
            await conn.execute('''
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
            await conn.execute('''
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
            await conn.execute('''
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
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_clients_user_id ON clients(user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_questionnaire_user_id ON questionnaire_answers(user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_progress_user_date ON user_progress(user_id, progress_date)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_plans_user_date ON user_plans(user_id, plan_date)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_reminders_user_active ON user_reminders(user_id, is_active)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_user_created ON user_messages(user_id, created_at)')
            
            logger.info("✅ Таблицы PostgreSQL инициализированы и индексы созданы")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

async def save_user_info(user_id: int, username: str, first_name: str, last_name: Optional[str] = None):
    """Асинхронно сохраняет информацию о пользователе в базу данных"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение пользователя {user_id}")
        return
    
    try:
        async with get_db_connection() as conn:
            registration_date = datetime.now()
            
            await conn.execute('''INSERT INTO clients 
                             (user_id, username, first_name, last_name, status, registration_date, last_activity) 
                             VALUES ($1, $2, $3, $4, $5, $6, $7)
                             ON CONFLICT (user_id) DO UPDATE SET
                             username = EXCLUDED.username,
                             first_name = EXCLUDED.first_name,
                             last_name = EXCLUDED.last_name,
                             last_activity = EXCLUDED.last_activity''',
                          user_id, username, first_name, last_name, 'active', registration_date, registration_date)
            
            logger.info(f"✅ Информация о пользователе {user_id} сохранена в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")

async def update_user_activity(user_id: int):
    """Асинхронно обновляет время последней активности пользователя"""
    if not POSTGRESQL_AVAILABLE:
        return
    
    try:
        async with get_db_connection() as conn:
            last_activity = datetime.now()
            
            await conn.execute('''UPDATE clients SET last_activity = $1 WHERE user_id = $2''',
                          last_activity, user_id)
            
    except Exception as e:
        logger.error(f"❌ Ошибка обновления активности {user_id}: {e}")

async def check_user_registered(user_id: int) -> bool:
    """Асинхронно проверяет зарегистрирован ли пользователь"""
    if not POSTGRESQL_AVAILABLE:
        return False
    
    try:
        async with get_db_connection() as conn:
            result = await conn.fetchrow("SELECT user_id FROM clients WHERE user_id = $1", user_id)
            return result is not None
            
    except Exception as e:
        logger.error(f"❌ Ошибка проверки регистрации {user_id}: {e}")
        return False

async def save_questionnaire_answer(user_id: int, question_number: int, question_text: str, answer_text: str):
    """Асинхронно сохраняет ответ на вопрос анкеты"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение ответа {user_id}")
        return
    
    try:
        async with get_db_connection() as conn:
            answer_date = datetime.now()
            
            # Получаем текст вопроса из конфига, если не передан
            if not question_text and question_number < len(QUESTIONS):
                question_text = QUESTIONS[question_number]["text"][:500] if question_number < len(QUESTIONS) else ""
            
            await conn.execute('''INSERT INTO questionnaire_answers 
                             (user_id, question_number, question_text, answer_text, answer_date) 
                             VALUES ($1, $2, $3, $4, $5)
                             ON CONFLICT (user_id, question_number) 
                             DO UPDATE SET 
                                answer_text = EXCLUDED.answer_text,
                                answer_date = EXCLUDED.answer_date''',
                          user_id, question_number, question_text, answer_text, answer_date)
            
            logger.debug(f"✅ Ответ на вопрос {question_number} сохранен для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения ответа {user_id}: {e}")

async def save_message(user_id: int, message_text: str, direction: str):
    """Асинхронно сохраняет сообщение в базу данных"""
    if not POSTGRESQL_AVAILABLE:
        return
    
    try:
        async with get_db_connection() as conn:
            created_at = datetime.now()
            
            # Определяем тип сообщения
            message_type = 'text'
            if len(message_text) > 1000:
                message_type = 'long_text'
            elif any(keyword in message_text.lower() for keyword in ['команда', '/start', '/help']):
                message_type = 'command'
            
            await conn.execute('''INSERT INTO user_messages 
                             (user_id, message_text, direction, message_type, created_at) 
                             VALUES ($1, $2, $3, $4, $5)''',
                          user_id, message_text, direction, message_type, created_at)
            
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения {user_id}: {e}")

async def save_user_plan_to_db(user_id: int, plan_data: Dict[str, Any]):
    """Асинхронно сохраняет план пользователя в базу данных"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение плана {user_id}")
        return
    
    try:
        async with get_db_connection() as conn:
            created_date = datetime.now()
            
            await conn.execute('''INSERT INTO user_plans 
                             (user_id, plan_date, morning_ritual1, morning_ritual2, task1, task2, task3, task4, 
                              lunch_break, evening_ritual1, evening_ritual2, advice, sleep_time, water_goal, 
                              activity_goal, created_date) 
                             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
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
                          user_id, plan_data.get('plan_date'), plan_data.get('morning_ritual1'), 
                          plan_data.get('morning_ritual2'), plan_data.get('task1'), plan_data.get('task2'),
                          plan_data.get('task3'), plan_data.get('task4'), plan_data.get('lunch_break'),
                          plan_data.get('evening_ritual1'), plan_data.get('evening_ritual2'), 
                          plan_data.get('advice'), plan_data.get('sleep_time'), plan_data.get('water_goal'),
                          plan_data.get('activity_goal'), created_date)
            
            logger.info(f"✅ План сохранен в БД для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения плана {user_id}: {e}")

async def get_user_plan_from_db(user_id: int):
    """Асинхронно получает текущий план пользователя из базы данных"""
    if not POSTGRESQL_AVAILABLE:
        return None
    
    try:
        async with get_db_connection() as conn:
            plan = await conn.fetchrow('''SELECT * FROM user_plans 
                             WHERE user_id = $1 AND status = 'active' 
                             ORDER BY created_date DESC LIMIT 1''', user_id)
            
            return dict(plan) if plan else None
    except Exception as e:
        logger.error(f"❌ Ошибка получения плана {user_id}: {e}")
        return None

async def save_progress_to_db(user_id: int, progress_data: Dict[str, Any]):
    """Асинхронно сохраняет прогресс пользователя в базу данных"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем сохранение прогресса {user_id}")
        return
    
    try:
        async with get_db_connection() as conn:
            progress_date = datetime.now().date()
            
            await conn.execute('''INSERT INTO user_progress 
                             (user_id, progress_date, tasks_completed, mood, energy, sleep_quality, 
                              water_intake, activity_done, user_comment, day_rating, challenges) 
                             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
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
                          user_id, progress_date, progress_data.get('tasks_completed'), 
                          progress_data.get('mood'), progress_data.get('energy'), 
                          progress_data.get('sleep_quality'), progress_data.get('water_intake'),
                          progress_data.get('activity_done'), progress_data.get('user_comment'),
                          progress_data.get('day_rating'), progress_data.get('challenges'))
            
            logger.info(f"✅ Прогресс сохранен в БД для пользователя {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения прогресса {user_id}: {e}")

async def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Асинхронно возвращает статистику пользователя"""
    if not POSTGRESQL_AVAILABLE:
        return {'messages_count': 0, 'registration_date': 'База данных не доступна'}
    
    try:
        async with get_db_connection() as conn:
            messages_count_result = await conn.fetchval(
                "SELECT COUNT(*) FROM user_messages WHERE user_id = $1 AND direction = 'incoming'", 
                user_id
            )
            messages_count = messages_count_result if messages_count_result else 0
            
            reg_date_result = await conn.fetchrow(
                "SELECT registration_date FROM clients WHERE user_id = $1", 
                user_id
            )
            reg_date = reg_date_result['registration_date'] if reg_date_result else "Неизвестно"
            
            return {
                'messages_count': messages_count,
                'registration_date': reg_date
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики {user_id}: {e}")
        return {'messages_count': 0, 'registration_date': 'Ошибка'}

async def has_sufficient_data(user_id: int) -> bool:
    """Асинхронно проверяет есть ли достаточно данных для статистики (минимум 3 дня)"""
    if not POSTGRESQL_AVAILABLE:
        return False
    
    try:
        async with get_db_connection() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = $1", 
                user_id
            )
            return count >= 3 if count else False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки данных {user_id}: {e}")
        return False

async def get_user_activity_streak(user_id: int) -> int:
    """Асинхронно возвращает текущую серию активных дней подряд"""
    if not POSTGRESQL_AVAILABLE:
        return 0
    
    try:
        async with get_db_connection() as conn:
            dates_result = await conn.fetch(
                "SELECT DISTINCT progress_date FROM user_progress WHERE user_id = $1 ORDER BY progress_date DESC", 
                user_id
            )
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

async def get_user_main_goal(user_id: int) -> str:
    """Асинхронно получает главную цель пользователя из анкеты"""
    if not POSTGRESQL_AVAILABLE:
        return "База данных не доступна"
    
    try:
        async with get_db_connection() as conn:
            result = await conn.fetchrow(
                "SELECT answer_text FROM questionnaire_answers WHERE user_id = $1 AND question_number = 0", 
                user_id
            )
            return result['answer_text'] if result else "Цель не установлена"
    except Exception as e:
        logger.error(f"❌ Ошибка получения цели {user_id}: {e}")
        return "Ошибка загрузки цели"

async def get_user_level_info(user_id: int) -> Dict[str, Any]:
    """Асинхронно возвращает информацию об уровне пользователя"""
    if not POSTGRESQL_AVAILABLE:
        return {'level': 'Новичок', 'points': 0, 'points_to_next': 50, 'next_level_points': 50}
    
    try:
        async with get_db_connection() as conn:
            active_days = await conn.fetchval(
                "SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = $1", 
                user_id
            ) or 0
            
            total_tasks = await conn.fetchval(
                "SELECT SUM(tasks_completed) FROM user_progress WHERE user_id = $1", 
                user_id
            ) or 0
            
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

async def get_favorite_ritual(user_id: int) -> str:
    """Асинхронно определяет любимый ритуал пользователя"""
    if not POSTGRESQL_AVAILABLE:
        return "на основе ваших предпочтений"
    
    try:
        async with get_db_connection() as conn:
            # Используем номер вопроса из анкеты для ритуалов
            result = await conn.fetchrow(
                "SELECT answer_text FROM questionnaire_answers WHERE user_id = $1 AND question_number = 32", 
                user_id
            )
            
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

async def get_user_usage_days(user_id: int) -> Dict[str, int]:
    """Асинхронно возвращает статистику дней использования"""
    if not POSTGRESQL_AVAILABLE:
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
    
    try:
        async with get_db_connection() as conn:
            reg_result = await conn.fetchrow(
                "SELECT registration_date FROM clients WHERE user_id = $1", 
                user_id
            )
            
            if not reg_result:
                return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}
            
            reg_date = reg_result['registration_date'].date()
            days_since_registration = (datetime.now().date() - reg_date).days + 1
            
            active_days = await conn.fetchval(
                "SELECT COUNT(DISTINCT progress_date) FROM user_progress WHERE user_id = $1", 
                user_id
            ) or 0
            
            current_streak = await get_user_activity_streak(user_id)
            
            return {
                'days_since_registration': days_since_registration,
                'active_days': active_days,
                'current_day': active_days if active_days > 0 else 1,
                'current_streak': current_streak
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения дней использования {user_id}: {e}")
        return {'days_since_registration': 0, 'active_days': 0, 'current_day': 0, 'current_streak': 0}

async def add_reminder_to_db(user_id: int, reminder_data: Dict[str, Any]) -> bool:
    """Асинхронно добавляет напоминание в базу данных"""
    if not POSTGRESQL_AVAILABLE:
        logger.warning(f"⚠️ PostgreSQL не доступен, пропускаем добавление напоминания {user_id}")
        return False
    
    try:
        async with get_db_connection() as conn:
            # 🔧 ОБРАБОТКА ОТНОСИТЕЛЬНЫХ НАПОМИНАНИЙ
            if reminder_data.get('type') == 'once' and 'delay_minutes' in reminder_data:
                # Для относительных напоминаний вычисляем точное время
                reminder_time = (datetime.now() + timedelta(minutes=reminder_data['delay_minutes'])).strftime("%H:%M")
            else:
                reminder_time = reminder_data['time']
            
            days_str = ','.join(reminder_data['days']) if reminder_data['days'] else 'ежедневно'
            created_date = datetime.now()
            
            await conn.execute('''INSERT INTO user_reminders 
                             (user_id, reminder_text, reminder_time, days_of_week, reminder_type, created_date)
                             VALUES ($1, $2, $3, $4, $5, $6)''',
                          user_id, reminder_data['text'], reminder_time, 
                          days_str, reminder_data['type'], created_date)
            
            logger.info(f"✅ Напоминание добавлено для пользователя {user_id} на {reminder_time}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка добавления напоминания: {e}")
        return False

async def get_user_reminders(user_id: int) -> List[Dict]:
    """Асинхронно возвращает список напоминаний пользователя"""
    if not POSTGRESQL_AVAILABLE:
        return []
    
    try:
        async with get_db_connection() as conn:
            reminders_result = await conn.fetch(
                '''SELECT id, reminder_text, reminder_time, days_of_week, reminder_type 
                 FROM user_reminders 
                 WHERE user_id = $1 AND is_active = TRUE 
                 ORDER BY created_date DESC''', 
                user_id
            )
            
            reminders = []
            for row in reminders_result:
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

async def delete_reminder_from_db(reminder_id: int) -> bool:
    """Асинхронно удаляет напоминание по ID"""
    if not POSTGRESQL_AVAILABLE:
        return False
    
    try:
        async with get_db_connection() as conn:
            await conn.execute('''UPDATE user_reminders SET is_active = FALSE WHERE id = $1''', reminder_id)
            
            logger.info(f"✅ Напоминание {reminder_id} удалено")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка удаления напоминания: {e}")
        return False

# Асинхронная инициализация БД при старте
async def initialize_database():
    """Асинхронно инициализирует базу данных при старте приложения"""
    if POSTGRESQL_AVAILABLE:
        success = await init_database()
        if success:
            logger.info("✅ База данных успешно инициализирована")
        else:
            logger.error("❌ Ошибка инициализации базы данных")
    else:
        logger.warning("⚠️ Пропускаем инициализацию БД - PostgreSQL не доступен")
