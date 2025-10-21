import logging
import psycopg2
from contextlib import contextmanager
from psycopg2.extras import RealDictCursor
from datetime import datetime
from config import DATABASE_URL, logger

@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к PostgreSQL"""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        yield conn
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        raise
    finally:
        if conn:
            conn.close()

def init_database():
    """Инициализирует таблицы в базе данных"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                
                # Таблица пользователей
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS clients (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT UNIQUE NOT NULL,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'active',
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                        FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                    )
                ''')
                
                # Таблица прогресса
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_progress (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        progress_date DATE NOT NULL,
                        tasks_completed INTEGER DEFAULT 0,
                        mood INTEGER,
                        energy INTEGER,
                        sleep_quality INTEGER,
                        water_intake INTEGER,
                        activity_done TEXT,
                        user_comment TEXT,
                        day_rating INTEGER,
                        challenges TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
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
                        FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                    )
                ''')
                
                # Таблица сообщений
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_messages (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        message_text TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES clients(user_id) ON DELETE CASCADE
                    )
                ''')
                
            conn.commit()
            logger.info("✅ Таблицы базы данных инициализированы")
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# Функции для работы с пользователями
def save_user_info(user_id: int, username: str, first_name: str, last_name: str = None):
    """Сохраняет информацию о пользователе"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO clients (user_id, username, first_name, last_name, last_activity)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        last_activity = EXCLUDED.last_activity
                ''', (user_id, username, first_name, last_name, datetime.now()))
                conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")

def update_user_activity(user_id: int):
    """Обновляет время последней активности пользователя"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE clients SET last_activity = %s WHERE user_id = %s',
                    (datetime.now(), user_id)
                )
                conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления активности {user_id}: {e}")

def check_user_registered(user_id: int) -> bool:
    """Проверяет зарегистрирован ли пользователь"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT 1 FROM clients WHERE user_id = %s',
                    (user_id,)
                )
                return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"❌ Ошибка проверки регистрации {user_id}: {e}")
        return False

# Функции для работы с анкетой
def save_questionnaire_answer(user_id: int, question_number: int, question_text: str, answer_text: str):
    """Сохраняет ответ на вопрос анкеты"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO questionnaire_answers 
                    (user_id, question_number, question_text, answer_text, answer_date)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, question_number) DO UPDATE SET
                        answer_text = EXCLUDED.answer_text,
                        answer_date = EXCLUDED.answer_date
                ''', (user_id, question_number, question_text, answer_text, datetime.now()))
                conn.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения ответа {user_id}: {e}")

# ... добавьте остальные функции из вашего кода

def get_user_answers(user_id: int) -> dict:
    """Получает все ответы пользователя на анкету"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT question_number, answer_text FROM questionnaire_answers WHERE user_id = %s',
                    (user_id,)
                )
                return {row['question_number']: row['answer_text'] for row in cursor.fetchall()}
    except Exception as e:
        logger.error(f"❌ Ошибка получения ответов {user_id}: {e}")
        return {}

# Инициализируем БД при импорте модуля
init_database()