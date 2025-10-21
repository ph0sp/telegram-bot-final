import logging
import re
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta

from config import logger

def _safe_analyze_text(text: Optional[str]) -> str:
    """Безопасно обрабатывает текст для анализа"""
    return text.lower() if text else ""

def analyze_user_profile(user_id: int) -> Dict[str, Any]:
    """Анализирует профиль пользователя по новой анкете"""
    from database import get_db_connection

    # ИСПРАВЛЕНИЕ: объявляем conn заранее для безопасности в finally
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return {}
            
        cursor = conn.cursor()
        cursor.execute("SELECT question_number, answer_text FROM questionnaire_answers WHERE user_id = %s", (user_id,))
        
        rows = cursor.fetchall()
        answers = {}
        
        for row in rows:
            answers[row['question_number']] = row['answer_text']
        
        # Базовый анализ
        profile = {
            'user_id': user_id,
            'main_goal': answers.get(1, ''),
            'goal_motivation': answers.get(2, ''),
            'success_criteria': answers.get(3, ''),
            'daily_hours': extract_hours(answers.get(4, '')),
            'deadline_info': analyze_deadlines(answers.get(5, '')),
            'sleep_schedule': answers.get(6, ''),
            'daily_routine': answers.get(7, ''),
            'energy_peaks': answers.get(8, ''),
            'distraction_time': extract_hours(answers.get(9, '')),
            'burnout_frequency': answers.get(10, ''),
            'work_style': analyze_work_style(answers.get(11, '')),
            'focus_aids': analyze_focus_aids(answers.get(12, '')),
            'break_activities': analyze_break_activities(answers.get(13, '')),
            'activity_level': analyze_activity_level(answers.get(14, '')),
            'sport_preferences': answers.get(15, ''),
            'sport_schedule': answers.get(16, ''),
            'health_limitations': answers.get(17, ''),
            'eating_habits': answers.get(18, ''),
            'water_intake': analyze_water_intake(answers.get(19, '')),
            'diet_changes': answers.get(20, ''),
            'cooking_time': answers.get(21, ''),
            'sleep_quality': answers.get(22, ''),
            'motivation_triggers': analyze_motivation(answers.get(23, '')),
            'obstacles': analyze_obstacles(answers.get(24, '')),
            'stress_management': answers.get(25, ''),
            'rest_preferences': analyze_rest_preferences(answers.get(26, '')),
            'rest_frequency': answers.get(27, ''),
            'personal_rituals': answers.get(28, ''),
            'weekend_planning': answers.get(29, ''),
            'social_needs': answers.get(30, ''),
            'hobby_time': answers.get(31, ''),
            'health_rituals': answers.get(32, ''),
            'work_life_balance': answers.get(33, ''),
            'plan_obstacles': answers.get(34, ''),
            'contingency_planning': answers.get(35, ''),
            'personality_type': determine_personality_type(answers),
            'optimal_times': calculate_optimal_times(answers.get(6, ''), answers.get(8, ''))
        }
        
        return profile
        
    except Exception as e:
        logger.error(f"❌ Ошибка анализа профиля пользователя {user_id}: {e}")
        return {}
    finally:
        if conn:
            conn.close()

def analyze_work_style(answer: Optional[str]) -> Dict[str, Any]:
    """Анализирует предпочтения по стилю работы с защитой от ошибок"""
    safe_answer = _safe_analyze_text(answer)
    
    work_style = {
        'prefers_long_blocks': any(word in safe_answer for word in ['длинные', 'непрерывные', '2-4 часа']),
        'prefers_short_sessions': any(word in safe_answer for word in ['короткие', '25-50 минут', 'помодоро']),
        'prefers_variety': any(word in safe_answer for word in ['чередование', 'разные задачи']),
        'prefers_multitasking': 'многозадачность' in safe_answer,
        'focus_aids': []
    }
    
    # Безопасно добавляем focus aids
    if 'тишина' in safe_answer:
        work_style['focus_aids'].append('quiet_environment')
    if 'музыка' in safe_answer:
        work_style['focus_aids'].append('background_music')
    if 'таймеры' in safe_answer:
        work_style['focus_aids'].append('timers')
    if 'дедлайны' in safe_answer:
        work_style['focus_aids'].append('deadlines')
    
    return work_style

def analyze_focus_aids(answer: str) -> List[str]:
    """Анализирует что помогает сосредоточиться"""
    safe_answer = _safe_analyze_text(answer)
    aids = []
    if 'тишина' in safe_answer:
        aids.append('quiet')
    if 'музыка' in safe_answer:
        aids.append('music')
    if 'кафе' in safe_answer:
        aids.append('cafe')
    if 'таймеры' in safe_answer:
        aids.append('timers')
    if 'дедлайны' in safe_answer:
        aids.append('deadlines')
    return aids

def analyze_break_activities(answer: str) -> List[str]:
    """Анализирует активности во время перерывов"""
    safe_answer = _safe_analyze_text(answer)
    activities = []
    if 'соцсети' in safe_answer:
        activities.append('social_media')
    if 'прогулка' in safe_answer:
        activities.append('walk')
    if 'растяжка' in safe_answer:
        activities.append('stretch')
    if 'чтение' in safe_answer:
        activities.append('reading')
    if 'ничего' in safe_answer:
        activities.append('nothing')
    return activities

def analyze_activity_level(answer: str) -> str:
    """Анализирует уровень активности"""
    safe_answer = _safe_analyze_text(answer)
    if 'сидячий' in safe_answer:
        return 'sedentary'
    elif 'прогулки' in safe_answer:
        return 'light'
    elif '1-2 раза' in safe_answer:
        return 'moderate'
    elif '3+ раза' in safe_answer:
        return 'active'
    return 'unknown'

def analyze_water_intake(answer: Optional[str]) -> str:
    """Анализирует потребление воды с защитой от ошибок"""
    if not answer:
        return 'unknown'
        
    if '1-2' in answer:
        return 'low'
    elif '4-5' in answer:
        return 'medium'
    elif '8+' in answer:
        return 'high'
    return 'unknown'

def analyze_motivation(answer: str) -> List[str]:
    """Анализирует триггеры мотивации"""
    safe_answer = _safe_analyze_text(answer)
    triggers = []
    if 'достижения' in safe_answer:
        triggers.append('achievement')
    if 'одобрение' in safe_answer:
        triggers.append('recognition')
    if 'внутренний' in safe_answer:
        triggers.append('intrinsic')
    if 'деньги' in safe_answer or 'результаты' in safe_answer:
        triggers.append('extrinsic')
    return triggers

def analyze_obstacles(answer: str) -> List[str]:
    """Анализирует основные препятствия"""
    safe_answer = _safe_analyze_text(answer)
    obstacles = []
    if 'прокрастинация' in safe_answer:
        obstacles.append('procrastination')
    if 'перфекционизм' in safe_answer:
        obstacles.append('perfectionism')
    if 'энерги' in safe_answer:
        obstacles.append('low_energy')
    if 'организац' in safe_answer:
        obstacles.append('disorganization')
    return obstacles

def analyze_rest_preferences(answer: str) -> List[str]:
    """Анализирует предпочтения по отдыху"""
    safe_answer = _safe_analyze_text(answer)
    preferences = []
    if 'активность' in safe_answer:
        preferences.append('active_rest')
    if 'пассивный' in safe_answer:
        preferences.append('passive_rest')
    if 'общение' in safe_answer:
        preferences.append('social_rest')
    if 'уединение' in safe_answer:
        preferences.append('solitude_rest')
    return preferences

def analyze_deadlines(answer: str) -> Dict[str, Any]:
    """Анализирует дедлайны и контрольные точки"""
    safe_answer = _safe_analyze_text(answer)
    deadline_info = {
        'has_deadline': False,
        'deadline_date': None,
        'milestones': [],
        'urgency_level': 'low'
    }
    
    if any(word in safe_answer for word in ['неделя', '7 дней', 'срочно']):
        deadline_info['urgency_level'] = 'high'
    elif any(word in safe_answer for word in ['месяц', '30 дней']):
        deadline_info['urgency_level'] = 'medium'
    
    # Простой анализ наличия дедлайна
    if any(word in safe_answer for word in ['дедлайн', 'срок', 'до', 'когда']):
        deadline_info['has_deadline'] = True
    
    return deadline_info

def extract_hours(text: str) -> Optional[int]:
    """Извлекает количество часов из текста"""
    match = re.search(r'(\d+)\s*час', text)
    if match:
        return int(match.group(1))
    return None

def determine_personality_type(answers: Dict[int, str]) -> str:
    """Определяет тип личности для персонализации планов"""
    score = 0
    
    # Анализ стиля работы
    work_answer = _safe_analyze_text(answers.get(11, ""))
    if 'длинные' in work_answer:
        score += 2
    if 'многозадачность' in work_answer:
        score -= 1
    
    # Анализ мотивации
    motivation_answer = _safe_analyze_text(answers.get(23, ""))
    if 'внутренний' in motivation_answer:
        score += 1
    if 'достижения' in motivation_answer:
        score += 2
    
    if score >= 4:
        return "deep_focus"
    elif score >= 2:
        return "balanced"
    elif score >= 0:
        return "varied"
    else:
        return "dynamic"

def calculate_optimal_times(sleep_answer: str, energy_answer: str) -> Dict[str, str]:
    """Рассчитывает оптимальное время для разных активностей"""
    safe_sleep_answer = _safe_analyze_text(sleep_answer)
    safe_energy_answer = _safe_analyze_text(energy_answer)
    
    wake_time = "08:00"
    if any(word in safe_sleep_answer for word in ['5', '6']):
        wake_time = "07:00"
    elif any(word in safe_sleep_answer for word in ['9', '10']):
        wake_time = "09:00"
    
    if 'утро' in safe_energy_answer:
        deep_work_start = "09:00"
    elif 'день' in safe_energy_answer:
        deep_work_start = "13:00"
    else:
        deep_work_start = "10:00"
    
    return {
        'wake_up': wake_time,
        'deep_work_start': deep_work_start,
        'creative_work': "15:00",
        'learning_time': "11:00",
        'physical_activity': "18:00",
        'planning_time': "20:00"
    }