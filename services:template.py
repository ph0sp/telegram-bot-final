import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta

from config import PLAN_TEMPLATES, WEEKLY_TEMPLATE_SCHEDULE, logger

logger = logging.getLogger(__name__)

def create_personalized_template(template_key: str, user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Создает персонализированный шаблон на основе профиля пользователя"""
    base_template = PLAN_TEMPLATES[template_key].copy()
    
    # Адаптируем под тип личности
    personality = user_profile['personality_type']
    if personality == "deep_focus":
        base_template = adapt_for_deep_focus(base_template, user_profile)
    elif personality == "dynamic":
        base_template = adapt_for_dynamic(base_template, user_profile)
    
    # Адаптируем под цели
    goal_type = user_profile.get('goal_analysis', {}).get('type', "unknown")
    if goal_type == "project":
        base_template = adapt_for_project_goal(base_template, user_profile)
    
    # Адаптируем под рабочие предпочтения
    base_template = adapt_work_blocks(base_template, user_profile)
    
    # Адаптируем под энергетические паттерны
    base_template = adapt_energy_patterns(base_template, user_profile)
    
    # Добавляем персонализированные советы
    base_template = add_personalized_advice(base_template, user_profile)
    
    return base_template

def adapt_for_deep_focus(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптация для глубоко сконцентрированного типа"""
    if 'time_blocks' in template:
        new_blocks = []
        for block in template['time_blocks']:
            if 'работа' in block.lower() or 'задач' in block.lower():
                block = block.replace('1 час', '2 часа').replace('60 минут', '120 минут')
            new_blocks.append(block)
        template['time_blocks'] = new_blocks
    
    if 'advice' in template:
        template['advice'].extend([
            "Используйте технику 'глубокой работы' - полная концентрация без отвлечений",
            "Отключайте все уведомления на время рабочих блоков"
        ])
    
    return template

def adapt_for_dynamic(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптация для динамичного типа"""
    if 'time_blocks' in template:
        new_blocks = []
        for block in template['time_blocks']:
            if 'работа' in block.lower() and '2 часа' in block:
                time_part = block.split(' - ')[0]
                task_part = block.split(' - ')[1]
                new_blocks.extend([
                    f"{time_part} - {task_part} (сессия 1)",
                    f"{add_30_min(time_part)} - {task_part} (сессия 2)",
                    f"{add_30_min(add_30_min(time_part))} - Перерыв 10 мин"
                ])
            else:
                new_blocks.append(block)
        template['time_blocks'] = new_blocks
    
    return template

def adapt_work_blocks(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптирует рабочие блоки под предпочтения пользователя"""
    work_style = profile.get('work_style', {})
    optimal_times = profile.get('optimal_times', {})
    
    if 'time_blocks' in template and optimal_times:
        new_blocks = []
        
        for block in template['time_blocks']:
            if 'глубокая работа' in block.lower():
                block = block.replace('09:00', optimal_times.get('deep_work_start', '09:00'))
            new_blocks.append(block)
        
        template['time_blocks'] = new_blocks
    
    return template

def adapt_energy_patterns(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Адаптирует план под энергетические паттерны пользователя"""
    energy_level = profile.get('energy_level', 'medium')
    
    if energy_level == 'low':
        if 'time_blocks' in template:
            enhanced_blocks = []
            for i, block in enumerate(template['time_blocks']):
                enhanced_blocks.append(block)
                if 'работа' in block.lower() and i < len(template['time_blocks']) - 1:
                    enhanced_blocks.append("Короткий перерыв 5-10 минут - размяться, попить воды")
            template['time_blocks'] = enhanced_blocks
    
    return template

def add_personalized_advice(template: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Добавляет персонализированные советы"""
    obstacles = profile.get('obstacles', [])
    motivation_triggers = profile.get('motivation_triggers', [])
    
    if 'advice' not in template:
        template['advice'] = []
    
    if 'procrastination' in obstacles:
        template['advice'].append("Начните с самой маленькой задачи - принцип '2 минут'")
    
    if 'perfectionism' in obstacles:
        template['advice'].append("Сначала сделайте, потом улучшайте - принцип 'достаточно хорошо'")
    
    if 'achievement' in motivation_triggers:
        template['advice'].append("Отмечайте каждое маленькое достижение")
    
    return template

def add_30_min(time_str: str) -> str:
    """Добавляет 30 минут к времени"""
    try:
        time_obj = datetime.strptime(time_str, "%H:%M")
        new_time = time_obj + timedelta(minutes=30)
        return new_time.strftime("%H:%M")
    except:
        return time_str

def generate_highly_personalized_plan(user_id: int, date: str, template_key: str = None) -> bool:
    """Генерирует высоко персонализированный план для пользователя"""
    try:
        # Анализируем профиль пользователя
        from services.analytics import analyze_user_profile
        user_profile = analyze_user_profile(user_id)
        
        # Определяем шаблон
        if not template_key:
            day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A").lower()
            day_translation = {
                'monday': 'понедельник', 'tuesday': 'вторник', 'wednesday': 'среда',
                'thursday': 'четверг', 'friday': 'пятница', 'saturday': 'суббота', 'sunday': 'воскресенье'
            }
            russian_day = day_translation.get(day_name, 'понедельник')
            template_key = WEEKLY_TEMPLATE_SCHEDULE.get(russian_day, "продуктивный_день")
        
        # Создаем персонализированный шаблон
        personalized_plan = create_personalized_template(template_key, user_profile)
        
        # Добавляем цель пользователя в план
        goal_text = user_profile.get('main_goal', '')
        if goal_text and goal_text != "Цель не установлена":
            if 'strategic_tasks' in personalized_plan:
                personalized_plan['strategic_tasks'].insert(0, f"Движение к цели: {goal_text}")
        
        # Сохраняем план
        from services.google_sheets import save_daily_plan_to_sheets
        success = save_daily_plan_to_sheets(user_id, date, personalized_plan)
        
        if success:
            logger.info(f"✅ Персонализированный план создан для {user_id} на {date}")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания персонализированного плана: {e}")
        return False