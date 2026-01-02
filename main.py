import asyncio
import sqlite3
import logging
import json
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode, ContentType
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import random
import string

# ===================== НАСТРОЙКА ЛОГГИРОВАНИЯ =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== КОНФИГУРАЦИЯ =====================
BOT_TOKEN = "8305510237:AAGXj0GEfEyxYmTayBimDTUDYZesoWdTqxA"
GROUP_ID = -5086100260
REQUIRED_CHANNEL_ID = -1003525909692

# Динамические данные (загружаются из БД)
REQUIRED_CHANNELS = []
ADMIN_IDS = []
IMAGES_DIR = "images"

# Создаем папку для изображений
if not os.path.exists(IMAGES_DIR):
    os.makedirs(IMAGES_DIR)

# ===================== ИНИЦИАЛИЗАЦИЯ БОТА =====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===================== СОСТОЯНИЯ FSM =====================
class WithdrawalStates(StatesGroup):
    waiting_for_skin_name = State()
    waiting_for_pattern = State()
    waiting_for_skin_photo = State()

class AddChannelStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_username = State()
    waiting_for_channel_name = State()
    waiting_for_invite_link = State()

class AddAdminStates(StatesGroup):
    waiting_for_admin_id = State()

class AddPromoCodeStates(StatesGroup):
    waiting_for_promo_code = State()
    waiting_for_promo_amount = State()
    waiting_for_promo_uses = State()
    waiting_for_promo_expires = State()

class AddPhotoStates(StatesGroup):
    waiting_for_photo_type = State()
    waiting_for_photo = State()

class BonusSettingsStates(StatesGroup):
    waiting_for_referral_bonus = State()
    waiting_for_welcome_bonus = State()
    waiting_for_min_withdrawal = State()

class WithdrawalRequestsStates(StatesGroup):
    waiting_withdrawal_action = State()

class AdminNotificationsStates(StatesGroup):
    waiting_notification_text = State()

# ===================== ФУНКЦИИ БАЗЫ ДАННЫХ =====================

def load_channels_from_db():
    """Загрузка каналов из БД"""
    global REQUIRED_CHANNELS
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT value FROM settings WHERE key = 'required_channels'")
    result = cursor.fetchone()
    
    REQUIRED_CHANNELS = []
    
    if result and result[0]:
        try:
            loaded_channels = json.loads(result[0])
            # Обрабатываем как список
            if isinstance(loaded_channels, list):
                for item in loaded_channels:
                    if isinstance(item, dict):
                        REQUIRED_CHANNELS.append(item)
                    elif isinstance(item, (int, str)):
                        # Конвертируем старый формат
                        channel_id = int(item)
                        REQUIRED_CHANNELS.append({
                            "id": channel_id,
                            "username": f"channel_{channel_id}",
                            "name": f"Канал {channel_id}",
                            "invite_link": f"https://t.me/c/{str(abs(channel_id))[4:]}"
                        })
            elif isinstance(loaded_channels, (int, str)):
                # Если это один канал
                channel_id = int(loaded_channels)
                REQUIRED_CHANNELS.append({
                    "id": channel_id,
                    "username": f"channel_{channel_id}",
                    "name": f"Канал {channel_id}",
                    "invite_link": f"https://t.me/c/{str(abs(channel_id))[4:]}"
                })
        except Exception as e:
            logger.error(f"Ошибка загрузки каналов: {e}")
            REQUIRED_CHANNELS = []
    
    # Если список пустой, добавляем канал по умолчанию
    if not REQUIRED_CHANNELS:
        default_channel = {
            "id": REQUIRED_CHANNEL_ID,
            "username": "k1lossez",
            "name": "K1LOSS EZ",
            "invite_link": "https://t.me/k1lossez"
        }
        REQUIRED_CHANNELS = [default_channel]
        
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                      ('required_channels', json.dumps(REQUIRED_CHANNELS)))
        conn.commit()
    
    conn.close()
    logger.info(f"Загружено каналов: {len(REQUIRED_CHANNELS)}")

def load_admins_from_db():
    """Загрузка админов из БД"""
    global ADMIN_IDS
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM admins")
    admins = cursor.fetchall()
    ADMIN_IDS = [admin[0] for admin in admins]
    
    conn.close()

def init_database():
    """Инициализация базы данных"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        balance REAL DEFAULT 0,
        referrals_count INTEGER DEFAULT 0,
        referral_from INTEGER DEFAULT 0,
        join_date TEXT,
        last_activity TEXT,
        subscribed_channels TEXT DEFAULT '[]',
        total_earned REAL DEFAULT 0,
        total_withdrawn REAL DEFAULT 0
    )
    ''')
    
    # Таблица реферальных кодов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS referral_codes (
        user_id INTEGER PRIMARY KEY,
        referral_code TEXT UNIQUE,
        created_date TEXT,
        uses_count INTEGER DEFAULT 0
    )
    ''')
    
    # Таблица транзакций
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        type TEXT,
        description TEXT,
        date TEXT,
        status TEXT DEFAULT 'completed',
        related_id INTEGER
    )
    ''')
    
    # Таблица выводов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        skin_name TEXT,
        pattern TEXT,
        photo_id TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        admin_id INTEGER,
        admin_username TEXT,
        created_date TEXT,
        processed_date TEXT,
        message_id INTEGER,
        decline_reason TEXT
    )
    ''')
    
    # Таблица админов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        is_super_admin BOOLEAN DEFAULT 0,
        added_date TEXT,
        added_by INTEGER,
        permissions TEXT DEFAULT 'all'
    )
    ''')
    
    # Таблица настроек
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')
    
    # Таблица промокодов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS promo_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        amount REAL,
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0,
        created_by INTEGER,
        created_date TEXT,
        expires_date TEXT,
        is_active BOOLEAN DEFAULT 1,
        min_balance REAL DEFAULT 0,
        for_new_users_only BOOLEAN DEFAULT 0
    )
    ''')
    
    # Таблица использованных промокодов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS used_promo_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        promo_code TEXT,
        used_date TEXT,
        amount REAL
    )
    ''')
    
    # Таблица уведомлений
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        message TEXT,
        is_read BOOLEAN DEFAULT 0,
        created_date TEXT
    )
    ''')
    
    # Таблица статистики
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS statistics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        new_users INTEGER DEFAULT 0,
        referrals_count INTEGER DEFAULT 0,
        withdrawals_count INTEGER DEFAULT 0,
        withdrawals_amount REAL DEFAULT 0,
        promo_uses INTEGER DEFAULT 0
    )
    ''')
    
    # Проверяем и добавляем недостающие столбцы
    cursor.execute("PRAGMA table_info(users)")
    users_columns = [col[1] for col in cursor.fetchall()]
    
    if 'total_earned' not in users_columns:
        cursor.execute('ALTER TABLE users ADD COLUMN total_earned REAL DEFAULT 0')
    if 'total_withdrawn' not in users_columns:
        cursor.execute('ALTER TABLE users ADD COLUMN total_withdrawn REAL DEFAULT 0')
    
    cursor.execute("PRAGMA table_info(admins)")
    admins_columns = [col[1] for col in cursor.fetchall()]
    
    if 'added_date' not in admins_columns:
        cursor.execute('ALTER TABLE admins ADD COLUMN added_date TEXT')
    if 'added_by' not in admins_columns:
        cursor.execute('ALTER TABLE admins ADD COLUMN added_by INTEGER')
    if 'permissions' not in admins_columns:
        cursor.execute('ALTER TABLE admins ADD COLUMN permissions TEXT DEFAULT "all"')
    
    cursor.execute("PRAGMA table_info(referral_codes)")
    ref_columns = [col[1] for col in cursor.fetchall()]
    
    if 'uses_count' not in ref_columns:
        cursor.execute('ALTER TABLE referral_codes ADD COLUMN uses_count INTEGER DEFAULT 0')
    
    cursor.execute("PRAGMA table_info(transactions)")
    trans_columns = [col[1] for col in cursor.fetchall()]
    
    if 'related_id' not in trans_columns:
        cursor.execute('ALTER TABLE transactions ADD COLUMN related_id INTEGER')
    
    cursor.execute("PRAGMA table_info(withdrawals)")
    wd_columns = [col[1] for col in cursor.fetchall()]
    
    if 'decline_reason' not in wd_columns:
        cursor.execute('ALTER TABLE withdrawals ADD COLUMN decline_reason TEXT')
    
    cursor.execute("PRAGMA table_info(promo_codes)")
    promo_columns = [col[1] for col in cursor.fetchall()]
    
    if 'min_balance' not in promo_columns:
        cursor.execute('ALTER TABLE promo_codes ADD COLUMN min_balance REAL DEFAULT 0')
    if 'for_new_users_only' not in promo_columns:
        cursor.execute('ALTER TABLE promo_codes ADD COLUMN for_new_users_only BOOLEAN DEFAULT 0')
    
    # Настройки по умолчанию
    default_settings = [
        ('referral_bonus', '300'),
        ('welcome_bonus', '0'),
        ('group_id', str(GROUP_ID)),
        ('bot_name', 'K1LOSSEZ Referral Bot'),
        ('min_withdrawal', '100'),
        ('referral_notifications', '1'),
        ('auto_check_subscriptions', '1'),
        ('photo_welcome', ''),
        ('photo_profile', ''),
        ('photo_referral', ''),
        ('photo_admin', ''),
        ('photo_withdrawal', ''),
        ('photo_promo', ''),
        ('photo_stats', ''),
        ('withdrawal_notify_all_admins', '1'),
        ('daily_bonus', '0'),
        ('daily_bonus_amount', '10'),
        ('referral_levels', '{"1": 300, "2": 150, "3": 75}'),
        ('multi_level_enabled', '0'),
        ('withdrawal_fee', '0'),
        ('max_withdrawal_per_day', '5000'),
        ('anti_spam_delay', '5'),
        ('maintenance_mode', '0'),
        ('maintenance_message', 'Бот на техническом обслуживании'),
        ('currency_name', 'голда'),
        ('currency_emoji', '💰'),
        ('support_username', ''),
        ('rules_message', ''),
        ('faq_message', '')
    ]
    
    for key, value in default_settings:
        cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
    
    # Добавляем начальных админов
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    initial_admins = [
        (7546928092, 1, current_time, 0),
        (6472276968, 1, current_time, 0)
    ]
    
    for admin_id, is_super, added_date, added_by in initial_admins:
        cursor.execute('SELECT * FROM admins WHERE user_id = ?', (admin_id,))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO admins (user_id, is_super_admin, added_date, added_by) VALUES (?, ?, ?, ?)', 
                          (admin_id, is_super, added_date, added_by))
    
    conn.commit()
    conn.close()

# Инициализация БД при запуске
init_database()

# Загружаем данные из БД после инициализации
load_channels_from_db()
load_admins_from_db()

# ===================== ОСНОВНЫЕ ФУНКЦИИ БД =====================

def get_user(user_id):
    """Получить информацию о пользователе"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user(user_id, **kwargs):
    """Обновить данные пользователя"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    for key, value in kwargs.items():
        cursor.execute(f'UPDATE users SET {key} = ? WHERE user_id = ?', (value, user_id))
    
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    """Получить настройку"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default

def update_setting(key, value):
    """Обновить настройку"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_referral_bonus():
    """Получить бонус за реферала"""
    return float(get_setting('referral_bonus', '300'))

def get_welcome_bonus():
    """Получить стартовый бонус"""
    return float(get_setting('welcome_bonus', '0'))

def get_photo_url(photo_type):
    """Получить URL фото из настроек"""
    return get_setting(f'photo_{photo_type}', '')

def get_currency_info():
    """Получить информацию о валюте"""
    return {
        'name': get_setting('currency_name', 'голда'),
        'emoji': get_setting('currency_emoji', '💰')
    }

def register_user(user_id, username, full_name, referral_code=None):
    """Регистрация пользователя"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    existing_user = cursor.fetchone()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if existing_user is None:
        # Новый пользователь
        referrer_id = None
        referrer_info = ""
        
        if referral_code:
            cursor.execute('SELECT user_id FROM referral_codes WHERE referral_code = ?', (referral_code,))
            result = cursor.fetchone()
            if result:
                referrer_id = result[0]
                referrer_info = f" по приглашению"
                
                # Увеличиваем счетчик использований кода
                cursor.execute('UPDATE referral_codes SET uses_count = uses_count + 1 WHERE user_id = ?', (referrer_id,))
        
        welcome_bonus = get_welcome_bonus()
        
        cursor.execute('''
        INSERT INTO users (user_id, username, full_name, referral_from, balance, join_date, 
                          last_activity, subscribed_channels, total_earned)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, referrer_id if referrer_id else 0, 
              welcome_bonus, current_time, current_time, '[]', welcome_bonus))
        
        # Начисляем бонусы по реферальной системе
        if referrer_id:
            # Бонус первому уровню
            referral_bonus = get_referral_bonus()
            cursor.execute('UPDATE users SET referrals_count = referrals_count + 1, total_earned = total_earned + ? WHERE user_id = ?', 
                          (referral_bonus, referrer_id))
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (referral_bonus, referrer_id))
            
            # Многоуровневая реферальная система
            if get_setting('multi_level_enabled', '0') == '1':
                try:
                    referral_levels = json.loads(get_setting('referral_levels', '{"1": 300, "2": 150, "3": 75}'))
                    
                    # Ищем рефереров 2 и 3 уровней
                    level = 1
                    current_referrer = referrer_id
                    
                    while level < 3:
                        cursor.execute('SELECT referral_from FROM users WHERE user_id = ?', (current_referrer,))
                        result = cursor.fetchone()
                        if not result or result[0] == 0:
                            break
                        
                        level += 1
                        current_referrer = result[0]
                        
                        if str(level) in referral_levels:
                            level_bonus = float(referral_levels[str(level)])
                            cursor.execute('UPDATE users SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?', 
                                          (level_bonus, level_bonus, current_referrer))
                            
                            cursor.execute('''
                            INSERT INTO transactions (user_id, amount, type, description, date, status)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ''', (current_referrer, level_bonus, 'referral_bonus_level', 
                                  f'Бонус {level} уровня за приглашение #{user_id}', current_time, 'completed'))
                except Exception as e:
                    logger.error(f"Ошибка в многоуровневой системе: {e}")
            
            # Транзакции для реферера
            cursor.execute('''
            INSERT INTO transactions (user_id, amount, type, description, date, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (referrer_id, referral_bonus, 'referral_bonus', 
                  f'Бонус за приглашение #{user_id}', current_time, 'completed'))
            
            # Транзакция для нового пользователя (бонус за регистрацию по ссылке)
            cursor.execute('''
            INSERT INTO transactions (user_id, amount, type, description, date, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, welcome_bonus, 'welcome_bonus_referral', 
                  'Бонус за регистрацию по реферальной ссылке', current_time, 'completed'))
            
            # Уведомление рефереру
            try:
                asyncio.create_task(notify_referrer(referrer_id, user_id, username, full_name, referral_bonus))
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления рефереру: {e}")
        
        # Транзакция для нового пользователя (основной бонус)
        cursor.execute('''
        INSERT INTO transactions (user_id, amount, type, description, date, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, welcome_bonus, 'welcome_bonus', 'Бонус за регистрацию', current_time, 'completed'))
        
        # Обновляем статистику
        cursor.execute("SELECT * FROM statistics WHERE date = ?", (current_time[:10],))
        if cursor.fetchone():
            cursor.execute("UPDATE statistics SET new_users = new_users + 1 WHERE date = ?", (current_time[:10],))
        else:
            cursor.execute('''
            INSERT INTO statistics (date, new_users, referrals_count, withdrawals_count, withdrawals_amount, promo_uses)
            VALUES (?, 1, 0, 0, 0, 0)
            ''', (current_time[:10],))
        
        # Уведомление админам
        try:
            asyncio.create_task(notify_admins_new_user(user_id, username, full_name, referrer_id, referrer_info))
        except Exception as e:
            logger.error(f"Ошибка уведомления админов: {e}")
        
        # Проверяем промокоды для новых пользователей
        try:
            asyncio.create_task(check_new_user_promos(user_id))
        except Exception as e:
            logger.error(f"Ошибка проверки промокодов: {e}")
    else:
        # Обновляем данные существующего пользователя
        cursor.execute('UPDATE users SET username = ?, full_name = ?, last_activity = ? WHERE user_id = ?', 
                      (username, full_name, current_time, user_id))
    
    conn.commit()
    conn.close()

async def notify_referrer(referrer_id, new_user_id, new_username, new_full_name, bonus_amount):
    """Уведомить реферера о новом реферале"""
    try:
        currency = get_currency_info()
        username = f"@{new_username}" if new_username else new_full_name
        
        notification_text = (
            f"🎉 <b>У вас новый реферал!</b>\n\n"
            f"👤 Пользователь: {new_full_name} ({username})\n"
            f"🆔 ID: {new_user_id}\n"
            f"{currency['emoji']} Вы получили: <b>{bonus_amount}г</b>\n\n"
            f"💎 Продолжайте приглашать друзей!"
        )
        
        await bot.send_message(referrer_id, notification_text, parse_mode=ParseMode.HTML)
        
        # Сохраняем уведомление в БД
        conn = sqlite3.connect('referral_bot.db')
        cursor = conn.cursor()
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
        INSERT INTO notifications (user_id, type, message, created_date)
        VALUES (?, ?, ?, ?)
        ''', (referrer_id, 'new_referral', f'Новый реферал: {new_full_name}', current_time))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка уведомления реферера: {e}")

async def notify_admins_new_user(user_id, username, full_name, referrer_id, referrer_info=""):
    """Уведомить админов о новом пользователе"""
    try:
        for admin_id in ADMIN_IDS:
            try:
                referrer_details = ""
                if referrer_id:
                    referrer = get_user(referrer_id)
                    if referrer:
                        referrer_name = referrer[2]
                        referrer_username = f"@{referrer[1]}" if referrer[1] else "без юзернейма"
                        referrer_details = f"\n👤 Пригласил: {referrer_name} ({referrer_username})"
                
                admin_message = (
                    f"📈 <b>НОВЫЙ ПОЛЬЗОВАТЕЛЬ{referrer_info.upper()}</b>\n\n"
                    f"👤 Имя: {full_name}\n"
                    f"📧 Юзернейм: @{username if username else 'Не указан'}\n"
                    f"🆔 ID: {user_id}{referrer_details}\n"
                    f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                await bot.send_message(admin_id, admin_message, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка уведомления админов: {e}")

async def check_new_user_promos(user_id):
    """Проверить промокоды для новых пользователей"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM promo_codes WHERE for_new_users_only = 1 AND is_active = 1')
    promos = cursor.fetchall()
    
    for promo in promos:
        promo_id, code, amount, max_uses, used_count, created_by, created_date, expires_date, is_active, min_balance, for_new_users_only = promo
        
        # Проверяем срок действия
        if expires_date and datetime.now() > datetime.strptime(expires_date, '%Y-%m-%d %H:%M:%S'):
            continue
        
        # Проверяем количество использований
        if used_count >= max_uses:
            continue
        
        # Проверяем минимальный баланс
        user = get_user(user_id)
        if user and min_balance > 0 and user[3] < min_balance:
            conn.close()
            return None, f"Для активации необходим минимальный баланс: {min_balance}"
        
        # Проверяем для новых пользователей
        if for_new_users_only == 1:
            cursor.execute('SELECT COUNT(*) FROM transactions WHERE user_id = ? AND type IN ("referral_bonus", "manual_adjustment")', (user_id,))
            trans_count = cursor.fetchone()[0] or 0
            if trans_count > 1:
                conn.close()
                return None, "Промокод только для новых пользователей"
        
        # Проверяем, использовал ли пользователь уже этот промокод
        cursor.execute('SELECT * FROM used_promo_codes WHERE user_id = ? AND promo_code = ?', (user_id, code))
        if cursor.fetchone():
            conn.close()
            return None, "Вы уже использовали этот промокод"
        
        # Начисляем баллы
        update_balance(user_id, amount, f'Автобонус для нового пользователя: {code}')
        
        # Обновляем счетчик использований
        cursor.execute('UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?', (promo_id,))
        
        # Записываем использование
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
        INSERT INTO used_promo_codes (user_id, promo_code, used_date, amount)
        VALUES (?, ?, ?, ?)
        ''', (user_id, code, current_time, amount))
        
        # Обновляем статистику
        cursor.execute("SELECT * FROM statistics WHERE date = ?", (current_time[:10],))
        if cursor.fetchone():
            cursor.execute("UPDATE statistics SET promo_uses = promo_uses + 1 WHERE date = ?", (current_time[:10],))
        else:
            cursor.execute('''
            INSERT INTO statistics (date, new_users, referrals_count, withdrawals_count, withdrawals_amount, promo_uses)
            VALUES (?, 0, 0, 0, 0, 1)
            ''', (current_time[:10],))
    
    conn.commit()
    conn.close()

def create_referral_code(user_id):
    """Создать реферальный код"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Генерируем уникальный код
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('INSERT OR REPLACE INTO referral_codes (user_id, referral_code, created_date, uses_count) VALUES (?, ?, ?, ?)', 
                  (user_id, code, current_time, 0))
    
    conn.commit()
    conn.close()
    return code

def get_referral_code(user_id):
    """Получить реферальный код пользователя"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT referral_code FROM referral_codes WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_referral_stats(user_id):
    """Получить статистику рефералов"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Прямые рефералы
    cursor.execute('SELECT COUNT(*), SUM(balance) FROM users WHERE referral_from = ?', (user_id,))
    direct_stats = cursor.fetchone()
    direct_count = direct_stats[0] or 0
    direct_balance = direct_stats[1] or 0
    
    # Вся реферальная сеть (многоуровневая)
    total_referrals = direct_count
    total_earned = get_user(user_id)[9] if get_user(user_id) else 0
    
    conn.close()
    
    return {
        'direct_count': direct_count,
        'direct_balance': direct_balance,
        'total_earned': total_earned,
        'referral_bonus': get_referral_bonus(),
        'levels': json.loads(get_setting('referral_levels', '{"1": 300, "2": 150, "3": 75}'))
    }

def get_referrals(user_id, level=1, max_level=3):
    """Получить рефералов пользователя"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    referrals = []
    
    if level == 1:
        cursor.execute('SELECT user_id, username, full_name, join_date, balance FROM users WHERE referral_from = ? ORDER BY join_date DESC', (user_id,))
        level1 = cursor.fetchall()
        
        for ref in level1:
            ref_dict = {
                'user_id': ref[0],
                'username': ref[1],
                'full_name': ref[2],
                'join_date': ref[3],
                'balance': ref[4],
                'level': 1,
                'sub_referrals': []
            }
            
            if max_level > 1:
                cursor.execute('SELECT user_id, username, full_name, join_date, balance FROM users WHERE referral_from = ? ORDER BY join_date DESC', (ref[0],))
                level2 = cursor.fetchall()
                
                for ref2 in level2:
                    ref2_dict = {
                        'user_id': ref2[0],
                        'username': ref2[1],
                        'full_name': ref2[2],
                        'join_date': ref2[3],
                        'balance': ref2[4],
                        'level': 2,
                        'sub_referrals': []
                    }
                    
                    if max_level > 2:
                        cursor.execute('SELECT user_id, username, full_name, join_date, balance FROM users WHERE referral_from = ? ORDER BY join_date DESC', (ref2[0],))
                        level3 = cursor.fetchall()
                        
                        for ref3 in level3:
                            ref3_dict = {
                                'user_id': ref3[0],
                                'username': ref3[1],
                                'full_name': ref3[2],
                                'join_date': ref3[3],
                                'balance': ref3[4],
                                'level': 3
                            }
                            ref2_dict['sub_referrals'].append(ref3_dict)
                    
                    ref_dict['sub_referrals'].append(ref2_dict)
            
            referrals.append(ref_dict)
    
    conn.close()
    return referrals

def update_balance(user_id, amount, description, transaction_type='manual_adjustment', related_id=None):
    """Обновить баланс пользователя"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Обновляем баланс
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    
    # Обновляем total_earned если пополнение
    if amount > 0 and transaction_type not in ['withdrawal', 'withdrawal_fee']:
        cursor.execute('UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?', (amount, user_id))
    
    # Обновляем total_withdrawn если вывод
    if amount < 0 and transaction_type in ['withdrawal', 'withdrawal_fee']:
        cursor.execute('UPDATE users SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?', (abs(amount), user_id))
    
    # Записываем транзакцию
    cursor.execute('''
    INSERT INTO transactions (user_id, amount, type, description, date, status, related_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, amount, transaction_type, description, current_time, 'completed', related_id))
    
    conn.commit()
    conn.close()

def create_withdrawal(user_id, skin_name, pattern, photo_id, amount):
    """Создать заявку на вывод"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Снимаем баланс с комиссией
    withdrawal_fee = float(get_setting('withdrawal_fee', '0'))
    fee_amount = amount * (withdrawal_fee / 100) if withdrawal_fee > 0 else 0
    
    try:
        # Снимаем основную сумму
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
        
        # Если есть комиссия, снимаем и ее
        if fee_amount > 0:
            cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (fee_amount, user_id))
            
            cursor.execute('''
            INSERT INTO transactions (user_id, amount, type, description, date, status, related_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, -fee_amount, 'withdrawal_fee', f'Комиссия за вывод', current_time, 'completed', None))
        
        # Создаем запись о выводе
        cursor.execute('''
        INSERT INTO withdrawals (user_id, skin_name, pattern, photo_id, amount, status, created_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, skin_name, pattern, photo_id, amount, 'pending', current_time))
        
        withdrawal_id = cursor.lastrowid
        
        # Записываем транзакцию
        cursor.execute('''
        INSERT INTO transactions (user_id, amount, type, description, date, status, related_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, -amount, 'withdrawal', f'Заявка на вывод #{withdrawal_id}', current_time, 'pending', withdrawal_id))
        
        conn.commit()
        conn.close()
        return withdrawal_id, None
        
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Ошибка создания вывода: {e}")
        return None, f"Ошибка при создании заявки: {str(e)}"

def get_withdrawals(user_id=None, status=None, limit=50):
    """Получить заявки на вывод"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    query = 'SELECT * FROM withdrawals'
    params = []
    
    if user_id or status:
        query += ' WHERE'
        conditions = []
        if user_id:
            conditions.append(' user_id = ?')
            params.append(user_id)
        if status:
            conditions.append(' status = ?')
            params.append(status)
        query += ' AND'.join(conditions)
    
    query += ' ORDER BY id DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    withdrawals = cursor.fetchall()
    conn.close()
    return withdrawals

def update_withdrawal_status(withdrawal_id, status, admin_id=None, admin_username=None, decline_reason=None):
    """Обновить статус вывода"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('SELECT user_id, amount, status FROM withdrawals WHERE id = ?', (withdrawal_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return False
    
    user_id, amount, old_status = result
    
    if status == 'completed':
        cursor.execute('''
        UPDATE withdrawals SET status = ?, admin_id = ?, admin_username = ?, processed_date = ?
        WHERE id = ?
        ''', (status, admin_id, admin_username, current_time, withdrawal_id))
        
        cursor.execute("UPDATE transactions SET status = 'completed' WHERE description = ? AND type = 'withdrawal'", 
                      (f'Заявка на вывод #{withdrawal_id}',))
        
        # Обновляем статистику
        cursor.execute("SELECT * FROM statistics WHERE date = ?", (current_time[:10],))
        if cursor.fetchone():
            cursor.execute("UPDATE statistics SET withdrawals_count = withdrawals_count + 1, withdrawals_amount = withdrawals_amount + ? WHERE date = ?", 
                          (amount, current_time[:10]))
        else:
            cursor.execute('''
            INSERT INTO statistics (date, new_users, referrals_count, withdrawals_count, withdrawals_amount, promo_uses)
            VALUES (?, 0, 0, 1, ?, 0)
            ''', (current_time[:10], amount))
        
    elif status == 'rejected':
        cursor.execute('''
        UPDATE withdrawals SET status = ?, admin_id = ?, admin_username = ?, processed_date = ?, decline_reason = ?
        WHERE id = ?
        ''', (status, admin_id, admin_username, current_time, decline_reason, withdrawal_id))
        
        # Возвращаем баланс
        withdrawal_fee = float(get_setting('withdrawal_fee', '0'))
        fee_amount = amount * (withdrawal_fee / 100) if withdrawal_fee > 0 else 0
        total_amount = amount + fee_amount
        
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (total_amount, user_id))
        cursor.execute("UPDATE transactions SET status = 'rejected' WHERE description = ? AND type = 'withdrawal'", 
                      (f'Заявка на вывод #{withdrawal_id}',))
        
        if fee_amount > 0:
            cursor.execute('DELETE FROM transactions WHERE description = ? AND type = "withdrawal_fee"', 
                          (f'Комиссия за вывод #{withdrawal_id}',))
    
    conn.commit()
    conn.close()
    return True

def get_transactions(user_id=None, transaction_type=None, limit=50):
    """Получить транзакции"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    query = 'SELECT * FROM transactions'
    params = []
    
    if user_id or transaction_type:
        query += ' WHERE'
        conditions = []
        if user_id:
            conditions.append(' user_id = ?')
            params.append(user_id)
        if transaction_type:
            conditions.append(' type = ?')
            params.append(transaction_type)
        query += ' AND'.join(conditions)
    
    query += ' ORDER BY date DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    transactions = cursor.fetchall()
    conn.close()
    return transactions

def get_detailed_transactions(user_id, days=30):
    """Получить детальные транзакции за период"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
    SELECT * FROM transactions 
    WHERE user_id = ? AND date >= ? 
    ORDER BY date DESC
    ''', (user_id, start_date))
    
    transactions = cursor.fetchall()
    
    # Группируем по дням
    daily_summary = {}
    for trans in transactions:
        date = trans[5][:10]
        if date not in daily_summary:
            daily_summary[date] = {'income': 0, 'outcome': 0, 'count': 0}
        
        if trans[2] > 0:
            daily_summary[date]['income'] += trans[2]
        else:
            daily_summary[date]['outcome'] += abs(trans[2])
        
        daily_summary[date]['count'] += 1
    
    conn.close()
    
    return {
        'transactions': transactions,
        'daily_summary': daily_summary,
        'total_income': sum([day['income'] for day in daily_summary.values()]),
        'total_outcome': sum([day['outcome'] for day in daily_summary.values()]),
        'period_days': days
    }

# ===================== ФУНКЦИИ ПРОМОКОДОВ =====================

def create_promo_code(code, amount, max_uses, created_by, expires_days=30, min_balance=0, for_new_users_only=0):
    """Создать промокод"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    expires_date = (datetime.now() + timedelta(days=expires_days)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('''
    INSERT INTO promo_codes (code, amount, max_uses, used_count, created_by, created_date, expires_date, is_active, min_balance, for_new_users_only)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (code, amount, max_uses, 0, created_by, current_time, expires_date, 1, min_balance, for_new_users_only))
    
    conn.commit()
    conn.close()
    return True

def use_promo_code(user_id, code):
    """Использовать промокод"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM promo_codes WHERE code = ? AND is_active = 1', (code,))
    promo = cursor.fetchone()
    
    if not promo:
        conn.close()
        return None, "Промокод не найден или неактивен"
    
    promo_id, _, amount, max_uses, used_count, created_by, created_date, expires_date, is_active, min_balance, for_new_users_only = promo
    
    # Проверяем срок действия
    if expires_date and datetime.now() > datetime.strptime(expires_date, '%Y-%m-%d %H:%M:%S'):
        cursor.execute('UPDATE promo_codes SET is_active = 0 WHERE id = ?', (promo_id,))
        conn.commit()
        conn.close()
        return None, "Промокод истек"
    
    # Проверяем количество использований
    if used_count >= max_uses:
        cursor.execute('UPDATE promo_codes SET is_active = 0 WHERE id = ?', (promo_id,))
        conn.commit()
        conn.close()
        return None, "Промокод уже использован максимальное количество раз"
    
    # Проверяем минимальный баланс
    user = get_user(user_id)
    if user and min_balance > 0 and user[3] < min_balance:
        conn.close()
        return None, f"Для активации необходим минимальный баланс: {min_balance}"
    
    # Проверяем для новых пользователей
    if for_new_users_only == 1:
        cursor.execute('SELECT COUNT(*) FROM transactions WHERE user_id = ? AND type IN ("referral_bonus", "manual_adjustment")', (user_id,))
        trans_count = cursor.fetchone()[0] or 0
        if trans_count > 1:
            conn.close()
            return None, "Промокод только для новых пользователей"
    
    # Проверяем, использовал ли пользователь уже этот промокод
    cursor.execute('SELECT * FROM used_promo_codes WHERE user_id = ? AND promo_code = ?', (user_id, code))
    if cursor.fetchone():
        conn.close()
        return None, "Вы уже использовали этот промокод"
    
    # Начисляем баллы
    update_balance(user_id, amount, f'Активация промокода: {code}', 'promo_code', promo_id)
    
    # Обновляем счетчик использований
    cursor.execute('UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?', (promo_id,))
    
    # Записываем использование
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    INSERT INTO used_promo_codes (user_id, promo_code, used_date, amount)
    VALUES (?, ?, ?, ?)
    ''', (user_id, code, current_time, amount))
    
    # Обновляем статистику
    cursor.execute("SELECT * FROM statistics WHERE date = ?", (current_time[:10],))
    if cursor.fetchone():
        cursor.execute("UPDATE statistics SET promo_uses = promo_uses + 1 WHERE date = ?", (current_time[:10],))
    else:
        cursor.execute('''
        INSERT INTO statistics (date, new_users, referrals_count, withdrawals_count, withdrawals_amount, promo_uses)
        VALUES (?, 0, 0, 0, 0, 1)
        ''', (current_time[:10],))
    
    conn.commit()
    conn.close()
    return amount, "Промокод успешно активирован"

def get_promo_codes(active_only=False):
    """Получить промокоды"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    if active_only:
        cursor.execute('SELECT * FROM promo_codes WHERE is_active = 1 ORDER BY created_date DESC')
    else:
        cursor.execute('SELECT * FROM promo_codes ORDER BY created_date DESC')
    
    promos = cursor.fetchall()
    conn.close()
    return promos

def delete_promo_code(code):
    """Удалить промокод"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM promo_codes WHERE code = ?', (code,))
    conn.commit()
    conn.close()
    return True

def toggle_promo_code(code, active):
    """Активировать/деактивировать промокод"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE promo_codes SET is_active = ? WHERE code = ?', (active, code))
    conn.commit()
    conn.close()
    return True

# ===================== ФУНКЦИИ АДМИНИСТРИРОВАНИЯ =====================

def is_admin(user_id):
    """Проверить, является ли пользователь админом"""
    return user_id in ADMIN_IDS

def is_super_admin(user_id):
    """Проверить, является ли пользователь суперадмином"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT is_super_admin FROM admins WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1

def get_admin_permissions(user_id):
    """Получить права админа"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT permissions FROM admins WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0]:
        try:
            return json.loads(result[0])
        except:
            return {'all': True}
    return {'all': True}

def add_admin_to_db(user_id, is_super=False, added_by=0, permissions=None):
    """Добавить администратора"""
    global ADMIN_IDS
    if user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)
        conn = sqlite3.connect('referral_bot.db')
        cursor = conn.cursor()
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if permissions is None:
            permissions = {'all': True}
        
        cursor.execute('''
        INSERT OR REPLACE INTO admins (user_id, is_super_admin, added_date, added_by, permissions)
        VALUES (?, ?, ?, ?, ?)
        ''', (user_id, 1 if is_super else 0, current_time, added_by, json.dumps(permissions)))
        
        conn.commit()
        conn.close()
        return True
    return False

def remove_admin_from_db(user_id):
    """Удалить администратора"""
    global ADMIN_IDS
    if user_id in ADMIN_IDS:
        ADMIN_IDS.remove(user_id)
        conn = sqlite3.connect('referral_bot.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        return True
    return False

def update_admin_permissions(user_id, permissions):
    """Обновить права администратора"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE admins SET permissions = ? WHERE user_id = ?', (json.dumps(permissions), user_id))
    conn.commit()
    conn.close()
    return True

def get_all_admins():
    """Получить всех администраторов"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins ORDER BY is_super_admin DESC, added_date DESC')
    admins = cursor.fetchall()
    conn.close()
    return admins

def add_channel_to_db(channel_data):
    """Добавить канал в список обязательных"""
    global REQUIRED_CHANNELS
    REQUIRED_CHANNELS.append(channel_data)
    update_setting('required_channels', json.dumps(REQUIRED_CHANNELS))
    return True

def remove_channel_from_db(channel_id):
    """Удалить канал из списка обязательных"""
    global REQUIRED_CHANNELS
    REQUIRED_CHANNELS = [ch for ch in REQUIRED_CHANNELS if isinstance(ch, dict) and ch.get('id') != channel_id]
    update_setting('required_channels', json.dumps(REQUIRED_CHANNELS))
    return True

# ===================== ФУНКЦИИ ПРОВЕРКИ ПОДПИСОК =====================

async def check_all_subscriptions(user_id):
    """Проверить подписки на все каналы"""
    not_subscribed_channels = []
    
    for channel in REQUIRED_CHANNELS:
        try:
            # Получаем ID канала
            if isinstance(channel, dict):
                channel_id = channel.get("id")
                if not channel_id:
                    continue
            elif isinstance(channel, (int, str)):
                # Если канал хранится как число
                channel_id = int(channel)
                # Создаем временный объект канала для возврата
                temp_channel = {
                    "id": channel_id,
                    "name": f"Канал {channel_id}",
                    "username": "",
                    "invite_link": f"https://t.me/c/{str(abs(channel_id))[4:]}"
                }
            else:
                logger.warning(f"Неизвестный формат канала: {type(channel)}")
                continue
            
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status in ['left', 'kicked']:
                if isinstance(channel, dict):
                    not_subscribed_channels.append(channel)
                else:
                    not_subscribed_channels.append(temp_channel)
                    
        except Exception as e:
            logger.error(f"Ошибка проверки подписки на канал {channel_id if 'channel_id' in locals() else 'неизвестный'}: {e}")
            # Если ошибка, добавляем канал как неподписанный
            if isinstance(channel, dict):
                not_subscribed_channels.append(channel)
            elif isinstance(channel, (int, str)):
                channel_id = int(channel)
                not_subscribed_channels.append({
                    "id": channel_id,
                    "name": f"Канал {channel_id}",
                    "username": "",
                    "invite_link": f"https://t.me/c/{str(abs(channel_id))[4:]}"
                })
    
    return not_subscribed_channels

async def check_subscription(user_id, channel_id):
    """Проверить подписку на конкретный канал"""
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status not in ['left', 'kicked']
    except:
        return False

# ===================== ФУНКЦИИ ОТПРАВКИ СООБЩЕНИЙ =====================

async def send_with_photo(chat_id, photo_type, caption, reply_markup=None):
    """Отправить сообщение с фото"""
    # Сначала проверяем локальный файл
    photo_path = os.path.join(IMAGES_DIR, f'{photo_type}.jpg')
    
    # Если есть локальный файл, используем его
    if os.path.exists(photo_path):
        try:
            photo = FSInputFile(photo_path)
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return message
        except Exception as e:
            logger.error(f"Ошибка отправки локального фото {photo_type}: {e}")
    
    # Затем проверяем file_id
    photo_file_id = get_setting(f'photo_{photo_type}_file_id', '')
    
    if photo_file_id:
        try:
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return message
        except Exception as e:
            logger.error(f"Ошибка отправки фото по file_id ({photo_type}): {e}")
            # Если file_id не работает, удаляем его
            update_setting(f'photo_{photo_type}_file_id', '')
    
    # Затем проверяем URL
    photo_url = get_photo_url(photo_type)
    
    if photo_url and photo_url.startswith(('http://', 'https://')):
        # Используем URL фото
        try:
            message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return message
        except Exception as e:
            logger.error(f"Ошибка отправки фото по URL ({photo_type}): {e}")
    
    # Если фото нет или ошибка - отправляем текст
    message = await bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )
    return message

async def edit_with_photo(callback, photo_type, caption, reply_markup=None):
    """Редактировать сообщение с фото"""
    try:
        # Сначала пытаемся отредактировать сообщение
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        else:
            await callback.message.edit_text(
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")
        # Если не удалось отредактировать, отправляем новое
        await send_with_photo(callback.from_user.id, photo_type, caption, reply_markup)

# ===================== КЛАВИАТУРЫ =====================

def main_keyboard():
    """Основная клавиатура"""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    keyboard.add(InlineKeyboardButton(text="👥 Мои рефералы", callback_data="my_referrals"))
    keyboard.add(InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="referral_link"))
    keyboard.add(InlineKeyboardButton(text="💰 Вывод средств", callback_data="withdrawal"))
    keyboard.add(InlineKeyboardButton(text="🎁 Промокод", callback_data="use_promo_code"))
    keyboard.add(InlineKeyboardButton(text="📦 История выводов", callback_data="withdrawal_history"))
    keyboard.adjust(2)
    return keyboard.as_markup()

def profile_keyboard():
    """Клавиатура профиля"""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="✅ Проверить подписки", callback_data="check_subscriptions"))
    keyboard.add(InlineKeyboardButton(text="💎 Детальная статистика", callback_data="detailed_stats"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="refresh_balance"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    return keyboard.as_markup()

def admin_keyboard():
    """Клавиатура админа"""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📊 Статистика бота", callback_data="bot_stats"))
    keyboard.add(InlineKeyboardButton(text="💰 Изменить баланс", callback_data="change_balance"))
    keyboard.add(InlineKeyboardButton(text="📢 Управление каналами", callback_data="manage_channels"))
    keyboard.add(InlineKeyboardButton(text="🎁 Управление промокодами", callback_data="manage_promo_codes"))
    keyboard.add(InlineKeyboardButton(text="📦 Заявки на вывод", callback_data="withdrawal_requests"))
    keyboard.add(InlineKeyboardButton(text="📊 Детальная статистика", callback_data="detailed_statistics"))
    keyboard.add(InlineKeyboardButton(text="⚡ Быстрые команды", callback_data="quick_commands"))
    keyboard.add(InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"))
    keyboard.add(InlineKeyboardButton(text="⚙️ Настройки бонусов", callback_data="bonus_settings"))
    keyboard.add(InlineKeyboardButton(text="👑 Управление админами", callback_data="manage_admins"))
    keyboard.add(InlineKeyboardButton(text="🖼 Управление фото", callback_data="manage_photos"))
    keyboard.add(InlineKeyboardButton(text="📈 Все транзакции", callback_data="all_transactions"))
    keyboard.add(InlineKeyboardButton(text="🔔 Уведомления", callback_data="admin_notifications"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    return keyboard.as_markup()

def withdrawal_confirmation_keyboard(withdrawal_id):
    """Клавиатура подтверждения вывода"""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="✅ Подтвердить вывод", callback_data=f"confirm_withdrawal_{withdrawal_id}"))
    keyboard.add(InlineKeyboardButton(text="❌ Отклонить вывод", callback_data=f"reject_withdrawal_{withdrawal_id}"))
    keyboard.add(InlineKeyboardButton(text="💬 Указать причину", callback_data=f"decline_reason_{withdrawal_id}"))
    return keyboard.as_markup()

def channels_subscription_keyboard(not_subscribed_channels):
    """Клавиатура для подписки на каналы"""
    keyboard = InlineKeyboardBuilder()
    for channel in not_subscribed_channels:
        if isinstance(channel, dict):
            keyboard.add(InlineKeyboardButton(
                text=f"📢 Подписаться на {channel.get('name', f'Канал {channel.get('id', '')}')}", 
                url=channel.get('invite_link', f"https://t.me/c/{str(abs(channel.get('id', '')))[4:]}")
            ))
    keyboard.add(InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscriptions_after"))
    keyboard.adjust(1)
    return keyboard.as_markup()

def bonus_settings_keyboard():
    """Клавиатура настроек бонусов"""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="💰 Бонус за реферала", callback_data="set_referral_bonus"))
    keyboard.add(InlineKeyboardButton(text="🎁 Стартовый бонус", callback_data="set_welcome_bonus"))
    keyboard.add(InlineKeyboardButton(text="📊 Многоуровневая система", callback_data="set_multi_level"))
    keyboard.add(InlineKeyboardButton(text="💸 Минимальный вывод", callback_data="set_min_withdrawal"))
    keyboard.add(InlineKeyboardButton(text="📈 Процент за вывод", callback_data="set_withdrawal_fee"))
    keyboard.add(InlineKeyboardButton(text="🏆 Уровни рефералов", callback_data="set_referral_levels"))
    keyboard.add(InlineKeyboardButton(text="👑 Назад в админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    return keyboard.as_markup()

def withdrawal_requests_keyboard():
    """Клавиатура заявок на вывод"""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="⏳ Ожидающие", callback_data="withdrawal_pending"))
    keyboard.add(InlineKeyboardButton(text="✅ Выполненные", callback_data="withdrawal_completed"))
    keyboard.add(InlineKeyboardButton(text="❌ Отклоненные", callback_data="withdrawal_rejected"))
    keyboard.add(InlineKeyboardButton(text="📊 Статистика выводов", callback_data="withdrawal_stats"))
    keyboard.add(InlineKeyboardButton(text="👑 Назад в админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    return keyboard.as_markup()

def quick_commands_keyboard():
    """Клавиатура быстрых команд"""
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast"))
    keyboard.add(InlineKeyboardButton(text="📊 Статистика за сегодня", callback_data="stats_today"))
    keyboard.add(InlineKeyboardButton(text="👥 Топ рефереров", callback_data="top_referrers"))
    keyboard.add(InlineKeyboardButton(text="💰 Топ по балансу", callback_data="top_balance"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить БД", callback_data="refresh_db"))
    keyboard.add(InlineKeyboardButton(text="⚙️ Настройки бота", callback_data="bot_settings"))
    keyboard.add(InlineKeyboardButton(text="👑 Назад в админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    return keyboard.as_markup()

# ===================== ОБРАБОТЧИКИ КОМАНД =====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    # Проверяем режим обслуживания
    if get_setting('maintenance_mode', '0') == '1':
        maintenance_msg = get_setting('maintenance_message', 'Бот на техническом обслуживании')
        await message.answer(f"🚧 <b>Режим обслуживания</b>\n\n{maintenance_msg}", parse_mode=ParseMode.HTML)
        return
    
    args = message.text.split()
    referral_code = args[1] if len(args) > 1 else None
    
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name
    
    # Регистрируем пользователя
    register_user(user_id, username, full_name, referral_code)
    
    # Проверяем подписки
    if get_setting('auto_check_subscriptions', '1') == '1':
        not_subscribed_channels = await check_all_subscriptions(user_id)
        
        if not_subscribed_channels:
            channels_text = "📢 <b>Для использования бота необходимо подписаться на каналы:</b>\n\n"
            for channel in not_subscribed_channels:
                if isinstance(channel, dict):
                    channels_text += f"• {channel.get('name', f'Канал {channel.get('id', '')}')}\n"
                else:
                    channels_text += f"• Канал {channel}\n"
            channels_text += "\nПосле подписки нажмите кнопку ниже:"
            
            await message.answer(
                channels_text,
                parse_mode=ParseMode.HTML,
                reply_markup=channels_subscription_keyboard(not_subscribed_channels)
            )
            return
    
    # Показываем главное меню
    user = get_user(user_id)
    balance = user[3] if user else 0
    currency = get_currency_info()
    
    referral_bonus = get_referral_bonus()
    
    caption = (
        f"👋 <b>Добро пожаловать в {get_setting('bot_name', 'K1LOSSEZ Referral Bot')}!</b>\n\n"
        f"👤 <b>Имя:</b> {full_name}\n"
        f"💰 <b>Баланс:</b> {balance} {currency['name']}\n\n"
        f"💎 <b>За каждого реферала:</b> {referral_bonus}г\n\n"
        f"<b>Используйте кнопки ниже:</b>"
    )
    
    await send_with_photo(message.chat.id, 'welcome', caption, main_keyboard())

@dp.message(Command("admin_menu"))
async def cmd_admin_menu(message: Message):
    """Панель администратора по команде /admin_menu"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    # Проверяем права
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('access_admin_panel', False):
        await message.answer("⛔ У вас нет доступа к панели администратора!")
        return
    
    admin_count = len(ADMIN_IDS)
    
    # Получаем количество пользователей
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0] or 0
    conn.close()
    
    pending_withdrawals = len(get_withdrawals(status='pending'))
    
    caption = (
        f"👑 <b>Панель администратора</b>\n\n"
        f"📊 <b>Общая статистика:</b>\n"
        f"• Администраторов: <b>{admin_count}</b>\n"
        f"• Пользователей: <b>{user_count}</b>\n"
        f"• Заявок на вывод: <b>{pending_withdrawals}</b>\n\n"
        f"<b>Выберите действие:</b>"
    )
    
    await send_with_photo(message.chat.id, 'admin', caption, admin_keyboard())
    await message.delete()

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    """Главное меню"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    balance = user[3] if user else 0
    currency = get_currency_info()
    
    caption = (
        f"🏠 <b>Главное меню {get_setting('bot_name', 'K1LOSSEZ Referral Bot')}</b>\n\n"
        f"💰 <b>Баланс:</b> {balance} {currency['name']}\n\n"
        f"👤 <b>Профиль</b> - информация о вашем аккаунте\n"
        f"👥 <b>Мои рефералы</b> - список приглашенных друзей\n"
        f"🔗 <b>Реферальная ссылка</b> - ваша персональная ссылка\n"
        f"💰 <b>Вывод средств</b> - заказать вывод голды\n"
        f"🎁 <b>Промокод</b> - активировать промокод\n"
        f"📦 <b>История выводов</b> - история ваших заявок\n"
    )
    
    await edit_with_photo(callback, 'welcome', caption, main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    """Показать профиль"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден!", show_alert=True)
        return
    
    referral_code = get_referral_code(user_id) or create_referral_code(user_id)
    currency = get_currency_info()
    
    # Получаем статистику рефералов
    ref_stats = get_referral_stats(user_id)
    
    # Получаем информацию о пригласившем
    referrer_info = ""
    if user[5] and user[5] != 0:
        referrer = get_user(user[5])
        if referrer:
            referrer_name = referrer[2]
            referrer_username = f"@{referrer[1]}" if referrer[1] else "без юзернейма"
            referrer_info = f"\n👤 <b>Пригласил:</b> {referrer_name} ({referrer_username})"
    
    join_date = user[6][:10] if user[6] else "Неизвестно"
    
    # Проверяем подписки
    not_subscribed = await check_all_subscriptions(user_id)
    subscription_status = "✅ Подписан" if not not_subscribed else "❌ Не подписан"
    
    profile_text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 <b>ID:</b> <code>{user[0]}</code>\n"
        f"👤 <b>Имя:</b> {user[2]}\n"
        f"📧 <b>Юзернейм:</b> @{user[1] if user[1] else 'Не указан'}\n"
        f"{currency['emoji']} <b>Баланс:</b> <code>{user[3]} {currency['name']}</code>\n"
        f"👥 <b>Рефералов:</b> <code>{user[4]} человек</code>\n"
        f"💰 <b>Заработано всего:</b> <code>{user[9]} {currency['name']}</code>\n"
        f"💸 <b>Выведено всего:</b> <code>{user[10]} {currency['name']}</code>"
        f"{referrer_info}\n"
        f"🔗 <b>Реферальный код:</b> <code>{referral_code}</code>\n"
        f"📅 <b>Дата регистрации:</b> {join_date}\n"
        f"✅ <b>Статус подписок:</b> {subscription_status}\n\n"
        f"💎 <b>Реферальная программа:</b>\n"
        f"• За каждого реферала: <b>{get_referral_bonus()}г</b>\n"
        f"• Всего заработано на рефералах: <b>{ref_stats['total_earned']} {currency['name']}</b>"
    )
    
    if get_setting('multi_level_enabled', '0') == '1':
        profile_text += f"\n• Многоуровневая система: <b>Включена</b>"
    
    await edit_with_photo(callback, 'profile', profile_text, profile_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "referral_link")
async def show_referral_link(callback: CallbackQuery):
    """Показать реферальную ссылку"""
    user_id = callback.from_user.id
    referral_code = get_referral_code(user_id) or create_referral_code(user_id)
    
    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    currency = get_currency_info()
    referral_bonus = get_referral_bonus()
    
    # Статистика реферального кода
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT uses_count FROM referral_codes WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    uses_count = result[0] if result else 0
    conn.close()
    
    referral_text = (
        f"🔗 <b>Ваша реферальная ссылка</b>\n\n"
        f"📝 <b>Ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"📝 <b>Код:</b>\n"
        f"<code>{referral_code}</code>\n\n"
        f"📊 <b>Статистика кода:</b>\n"
        f"• Использован раз: <b>{uses_count}</b>\n"
        f"• Заработано: <b>{uses_count * referral_bonus}г</b>\n\n"
        f"📈 <b>Бонусы:</b>\n"
        f"• За каждого реферала: <b>{referral_bonus}г</b>\n"
    )
    
    if get_setting('multi_level_enabled', '0') == '1':
        try:
            levels = json.loads(get_setting('referral_levels', '{"1": 300, "2": 150, "3": 75}'))
            for level, bonus in levels.items():
                referral_text += f"• Уровень {level}: <b>{bonus}г</b>\n"
        except Exception as e:
            logger.error(f"Ошибка загрузки уровней: {e}")
            referral_text += "• <b>Ошибка загрузки уровней</b>\n"
    else:
        referral_text += "• <b>Отключена</b>\n"
    
    referral_text += f"\n📢 <b>Просто отправьте эту ссылку друзьям!</b>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📢 Поделиться", url=f"https://t.me/share/url?url={referral_link}&text=Присоединяйся%20к%20нам!"))
    keyboard.add(InlineKeyboardButton(text="📋 Мои рефералы", callback_data="my_referrals"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(1)
    
    await edit_with_photo(callback, 'referral', referral_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "my_referrals")
async def show_my_referrals(callback: CallbackQuery):
    """Показать моих рефералов"""
    user_id = callback.from_user.id
    referrals = get_referrals(user_id, max_level=3)
    
    if referrals:
        currency = get_currency_info()
        ref_stats = get_referral_stats(user_id)
        
        referrals_text = f"👥 <b>Ваша реферальная сеть</b>\n\n"
        referrals_text += f"📊 <b>Статистика:</b>\n"
        referrals_text += f"• Прямых рефералов: <b>{ref_stats['direct_count']}</b>\n"
        referrals_text += f"• Заработано всего: <b>{ref_stats['total_earned']} {currency['name']}</b>\n\n"
        
        for ref in referrals[:15]:  # Показываем первые 15
            level_emoji = "🥇" if ref['level'] == 1 else "🥈" if ref['level'] == 2 else "🥉"
            username = f"@{ref['username']}" if ref['username'] else ref['full_name']
            
            referrals_text += (
                f"{level_emoji} <b>{ref['full_name']}</b> ({username})\n"
                f"   🆔 ID: <code>{ref['user_id']}</code>\n"
                f"   📅 Дата: {ref['join_date'][:10]}\n"
                f"   💰 Баланс: {ref['balance']} {currency['name']}\n"
            )
            
            if ref['sub_referrals']:
                referrals_text += f"   👥 Пригласил: {len(ref['sub_referrals'])} чел.\n"
            
            referrals_text += "\n"
    else:
        referrals_text = "😔 <b>У вас пока нет рефералов.</b>\n\n🔗 Приглашайте друзей по своей реферальной ссылке!"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔗 Получить ссылку", callback_data="referral_link"))
    keyboard.add(InlineKeyboardButton(text="📊 Детальная статистика", callback_data="detailed_referral_stats"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="my_referrals"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'profile', referrals_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "transaction_history")
async def show_transaction_history(callback: CallbackQuery):
    """Показать историю транзакций"""
    user_id = callback.from_user.id
    detailed = get_detailed_transactions(user_id, days=30)
    
    currency = get_currency_info()
    
    if detailed['transactions']:
        history_text = f"📋 <b>История транзакций (за {detailed['period_days']} дней)</b>\n\n"
        history_text += f"📈 <b>Итоги:</b>\n"
        history_text += f"• Всего пополнений: <b>{detailed['total_income']} {currency['name']}</b>\n"
        history_text += f"• Всего списаний: <b>{detailed['total_outcome']} {currency['name']}</b>\n"
        history_text += f"• Чистый доход: <b>{detailed['total_income'] - detailed['total_outcome']} {currency['name']}</b>\n\n"
        
        history_text += f"📅 <b>Последние операции:</b>\n\n"
        
        for trans in detailed['transactions'][:15]:  # Показываем последние 15
            trans_id, _, amount, trans_type, description, date, status, related_id = trans
            
            type_emoji = {
                'referral_bonus': '💎',
                'welcome_bonus': '🎁',
                'welcome_bonus_referral': '🎁',
                'manual_adjustment': '⚙️',
                'withdrawal': '📤',
                'withdrawal_fee': '📉',
                'promo_code': '🎫',
                'daily_bonus': '📅',
                'referral_bonus_level': '📊'
            }.get(trans_type, '💰')
            
            type_name = {
                'referral_bonus': 'Реферальный бонус',
                'welcome_bonus': 'Стартовый бонус',
                'welcome_bonus_referral': 'Бонус по ссылке',
                'manual_adjustment': 'Корректировка',
                'withdrawal': 'Вывод',
                'withdrawal_fee': 'Комиссия вывода',
                'promo_code': 'Промокод',
                'daily_bonus': 'Ежедневный бонус',
                'referral_bonus_level': 'Многоуровневый бонус'
            }.get(trans_type, trans_type)
            
            status_emoji = "✅" if status == 'completed' else "⏳" if status == 'pending' else "❌"
            date_str = date[:16] if len(date) > 10 else date
            
            history_text += (
                f"{type_emoji} <b>{amount:+.0f} {currency['name']}</b> {status_emoji}\n"
                f"📝 {type_name}: {description}\n"
                f"📅 {date_str}\n\n"
            )
    else:
        history_text = "📭 <b>У вас еще нет транзакций.</b>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📊 Детальная статистика", callback_data="detailed_stats"))
    keyboard.add(InlineKeyboardButton(text="📦 История выводов", callback_data="withdrawal_history"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="transaction_history"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'profile', history_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "use_promo_code")
async def use_promo_code_handler(callback: CallbackQuery, state: FSMContext):
    """Активация промокода"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден!", show_alert=True)
        return
    
    await callback.message.answer(
        "🎁 <b>Активация промокода</b>\n\n"
        "Введите промокод:",
        parse_mode=ParseMode.HTML
    )
    await state.set_state("waiting_for_promo_code")
    await callback.answer()

@dp.message(F.text, StateFilter("waiting_for_promo_code"))
async def process_promo_code(message: Message, state: FSMContext):
    """Обработка ввода промокода"""
    promo_code = message.text.strip().upper()
    user_id = message.from_user.id
    
    amount, result_message = use_promo_code(user_id, promo_code)
    
    if amount:
        user = get_user(user_id)
        new_balance = user[3] if user else amount
        currency = get_currency_info()
        
        success_text = (
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"🎁 Промокод: <code>{promo_code}</code>\n"
            f"💰 Получено: <b>{amount} {currency['name']}</b>\n"
            f"💰 Новый баланс: <b>{new_balance} {currency['name']}</b>\n\n"
            f"Спасибо за использование нашего бота!"
        )
        
        await message.answer(success_text, parse_mode=ParseMode.HTML)
        
        # Отправляем фото с поздравлением
        await send_with_photo(message.chat.id, 'promo', success_text)
    else:
        error_text = (
            f"❌ <b>Ошибка активации промокода</b>\n\n"
            f"Промокод: <code>{promo_code}</code>\n"
            f"Ошибка: {result_message}"
        )
        
        await message.answer(error_text, parse_mode=ParseMode.HTML)
    
    await state.clear()

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    # Проверяем права
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('access_admin_panel', False):
        await message.answer("⛔ У вас нет доступа к панели администратора!")
        return
    
    admin_count = len(ADMIN_IDS)
    
    # Получаем количество пользователей
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0] or 0
    conn.close()
    
    pending_withdrawals = len(get_withdrawals(status='pending'))
    
    caption = (
        f"👑 <b>Панель администратора {get_setting('bot_name', 'K1LOSS EZ Referral Bot')}</b>\n\n"
        f"📊 <b>Общая статистика:</b>\n"
        f"• Администраторов: <b>{admin_count}</b>\n"
        f"• Пользователей: <b>{user_count}</b>\n"
        f"• Заявок на вывод: <b>{pending_withdrawals}</b>\n\n"
        f"<b>Выберите действие:</b>"
    )
    
    await send_with_photo(message.chat.id, 'admin', caption, admin_keyboard())
    await message.delete()

# ===================== ФУНКЦИИ ДЛЯ АДМИНИСТРАТОРОВ =====================

def get_all_users(limit=1000):
    """Получить всех пользователей"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users ORDER BY join_date DESC LIMIT ?', (limit,))
    users = cursor.fetchall()
    conn.close()
    return users

def search_users(search_term):
    """Поиск пользователей"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Пробуем поиск по ID
    if search_term.isdigit():
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (int(search_term),))
        result = cursor.fetchall()
        if result:
            conn.close()
            return result
    
    # Поиск по юзернейму
    cursor.execute('SELECT * FROM users WHERE username LIKE ? OR full_name LIKE ? ORDER BY join_date DESC LIMIT 50', 
                  (f'%{search_term}%', f'%{search_term}%'))
    result = cursor.fetchall()
    
    conn.close()
    return result

def get_user_statistics():
    """Получить статистику пользователей"""
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Общая статистика
    cursor.execute('SELECT COUNT(*), SUM(balance), SUM(total_earned), SUM(total_withdrawn) FROM users')
    total_stats = cursor.fetchone()
    
    # Статистика за сегодня
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('SELECT COUNT(*), SUM(balance) FROM users WHERE date(join_date) = ?', (today,))
    today_stats = cursor.fetchone()
    
    # Активные пользователи (были сегодня)
    cursor.execute('SELECT COUNT(*) FROM users WHERE date(last_activity) = ?', (today,))
    active_today = cursor.fetchone()[0] or 0
    
    # Топ рефереров
    cursor.execute('SELECT user_id, username, full_name, referrals_count, total_earned FROM users WHERE referrals_count > 0 ORDER BY referrals_count DESC LIMIT 10')
    top_referrers = cursor.fetchall()
    
    # Топ по балансу
    cursor.execute('SELECT user_id, username, full_name, balance FROM users WHERE balance > 0 ORDER BY balance DESC LIMIT 10')
    top_balance = cursor.fetchall()
    
    conn.close()
    
    return {
        'total_users': total_stats[0] or 0,
        'total_balance': total_stats[1] or 0,
        'total_earned': total_stats[2] or 0,
        'total_withdrawn': total_stats[3] or 0,
        'new_today': today_stats[0] or 0,
        'balance_today': today_stats[1] or 0,
        'active_today': active_today,
        'top_referrers': top_referrers,
        'top_balance': top_balance
    }

# ===================== ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ =====================

@dp.callback_query(F.data == "check_subscriptions")
async def check_subscriptions_handler(callback: CallbackQuery):
    """Проверка подписок"""
    user_id = callback.from_user.id
    not_subscribed_channels = await check_all_subscriptions(user_id)
    
    if not_subscribed_channels:
        channels_text = "📢 <b>Вы не подписаны на все обязательные каналы:</b>\n\n"
        for channel in not_subscribed_channels:
            if isinstance(channel, dict):
                channels_text += f"• {channel.get('name', f'Канал {channel.get('id', '')}')}\n"
            else:
                channels_text += f"• Канал {channel}\n"
        channels_text += "\nПосле подписки нажмите кнопку ниже:"
        
        await edit_with_photo(callback, 'profile', channels_text, 
                            channels_subscription_keyboard(not_subscribed_channels))
    else:
        # Проверяем группу с обработкой ошибок
        try:
            member = await bot.get_chat_member(GROUP_ID, user_id)
            if member.status in ['left', 'kicked']:
                keyboard = InlineKeyboardBuilder()
                keyboard.add(InlineKeyboardButton(text="📢 Вступить в группу", url=f"https://t.me/c/{str(abs(GROUP_ID))[4:]}"))
                keyboard.add(InlineKeyboardButton(text="✅ Я вступил", callback_data="check_channel_subscription"))
                keyboard.adjust(1)
                
                await callback.message.edit_text(
                    "📢 Вы не подписаны на нашу группу!\n\nПосле вступления нажмите кнопку ниже:",
                    reply_markup=keyboard.as_markup()
                )
            else:
                success_text = "✅ <b>Отлично! Вы подписаны на все обязательные каналы и группу.</b>"
                await edit_with_photo(callback, 'profile', success_text, profile_keyboard())
        except Exception as e:
            logger.error(f"Ошибка проверки группы: {e}")
            success_text = "✅ <b>Отлично! Вы подписаны на все обязательные каналы.</b>"
            await edit_with_photo(callback, 'profile', success_text, profile_keyboard())
    
    await callback.answer()

@dp.callback_query(F.data == "statistics")
async def show_statistics(callback: CallbackQuery):
    """Показать общую статистику"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден!", show_alert=True)
        return
    
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Общая статистика бота
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(balance) FROM users')
    total_balance = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM withdrawals WHERE status = "completed"')
    completed_withdrawals = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT SUM(amount) FROM withdrawals WHERE status = "completed"')
    withdrawn_amount = cursor.fetchone()[0] or 0
    
    # Топ рефереров
    cursor.execute('SELECT full_name, referrals_count FROM users WHERE referrals_count > 0 ORDER BY referrals_count DESC LIMIT 10')
    top_referrers = cursor.fetchall()
    
    conn.close()
    
    currency = get_currency_info()
    ref_stats = get_referral_stats(user_id)
    
    stats_text = (
        f"📊 <b>Общая статистика {get_setting('bot_name', 'K1LOSSEZ Referral Bot')}</b>\n\n"
        f"👥 <b>Всего в системе:</b>\n"
        f"• Пользователей: <b>{total_users}</b>\n"
        f"• Общий баланс: <b>{total_balance} {currency['name']}</b>\n"
        f"• Выполнено выводов: <b>{completed_withdrawals}</b>\n"
        f"• Выведено всего: <b>{withdrawn_amount} {currency['name']}</b>\n\n"
        f"👤 <b>Ваша статистика:</b>\n"
        f"• Рефералов: <b>{user[4]} человек</b>\n"
        f"• Заработано на рефералах: <b>{ref_stats['total_earned']} {currency['name']}</b>\n"
        f"• Выведено: <b>{user[10]} {currency['name']}</b>\n\n"
        f"🏆 <b>Топ 10 рефереров:</b>\n"
    )
    
    for i, (name, count) in enumerate(top_referrers, 1):
        stats_text += f"{i}. {name}: <b>{count}</b> рефералов\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📈 Детальная статистика", callback_data="detailed_stats"))
    keyboard.add(InlineKeyboardButton(text="📋 История транзакций", callback_data="transaction_history"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="statistics"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'stats', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "withdrawal")
async def start_withdrawal(callback: CallbackQuery, state: FSMContext):
    """Начать процесс вывода"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден!", show_alert=True)
        return
    
    balance = user[3] if user else 0
    currency = get_currency_info()
    min_withdrawal = float(get_setting('min_withdrawal', '100'))
    
    if balance is None:
        balance = 0
    
    if balance < min_withdrawal:
        await callback.answer(f"❌ Минимальная сумма вывода: {min_withdrawal} {currency['name']}!", show_alert=True)
        return
    
    # Проверяем антиспам задержку
    anti_spam_delay = int(get_setting('anti_spam_delay', '5'))
    
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT created_date FROM withdrawals WHERE user_id = ? ORDER BY created_date DESC LIMIT 1', (user_id,))
    last_withdrawal = cursor.fetchone()
    conn.close()
    
    if last_withdrawal:
        last_time = datetime.strptime(last_withdrawal[0], '%Y-%m-%d %H:%M:%S')
        time_diff = (datetime.now() - last_time).seconds / 60  # в минутах
        
        if time_diff < anti_spam_delay:
            wait_time = anti_spam_delay - int(time_diff)
            await callback.answer(f"⏳ Подождите {wait_time} минут перед следующей заявкой!", show_alert=True)
            return
    
    await state.set_state(WithdrawalStates.waiting_for_skin_name)
    await state.update_data(user_id=user_id, balance=balance)
    
    withdrawal_fee = float(get_setting('withdrawal_fee', '0'))
    fee_text = f"\n📉 Комиссия за вывод: <b>{withdrawal_fee}%</b>" if withdrawal_fee > 0 else ""
    
    await callback.message.answer(
        f"💰 <b>Заявка на вывод средств</b>\n\n"
        f"{currency['emoji']} Ваш баланс: <b>{balance} {currency['name']}</b>\n"
        f"💰 Минимум для вывода: <b>{min_withdrawal} {currency['name']}</b>"
        f"{fee_text}\n\n"
        f"📝 <b>Шаг 1 из 3</b>\n"
        f"✏️ Напишите название скина с паттерном:\n\n"
        f"<i>Пример: USP | GHOSTS </i>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@dp.message(WithdrawalStates.waiting_for_skin_name)
async def process_skin_name(message: Message, state: FSMContext):
    """Обработка названия скина"""
    skin_name = message.text.strip()
    
    if len(skin_name) < 3:
        await message.answer("❌ Название скина слишком короткое. Попробуйте еще раз:")
        return
    
    await state.update_data(skin_name=skin_name)
    await state.set_state(WithdrawalStates.waiting_for_pattern)
    
    await message.answer(
        "✅ Название скина сохранено!\n\n"
        "📝 <b>Шаг 2 из 3</b>\n"
        "🔢 Напишите паттерн скина:\n\n"
        "<i>Пример: 0.123(где цифры после нуля сам паттерн скина)</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message(WithdrawalStates.waiting_for_pattern)
async def process_pattern(message: Message, state: FSMContext):
    """Обработка паттерна"""
    pattern = message.text.strip()
    
    try:
        # Проверяем, что паттерн - это число с точкой
        float(pattern)
        if not (0 <= float(pattern) <= 1):
            await message.answer("❌ Паттерн должен быть между 0 и 1. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Паттерн должен быть числом (например: 0.123(где цифры после нуля сам паттерн скина)). Попробуйте еще раз:")
        return
    
    await state.update_data(pattern=pattern)
    await state.set_state(WithdrawalStates.waiting_for_skin_photo)
    
    await message.answer(
        "✅ Паттерн сохранен!\n\n"
        "📝 <b>Шаг 3 из 3</b>\n"
        "📸 Отправьте фотографию скина:\n\n"
        "<i>Прикрепите фото в следующем сообщении</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message(WithdrawalStates.waiting_for_skin_photo, F.photo)
async def process_skin_photo(message: Message, state: FSMContext):
    """Обработка фото скина"""
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    
    user_id = data['user_id']
    skin_name = data['skin_name']
    pattern = data['pattern']
    balance = data['balance']
    
    # Создаем заявку на вывод
    withdrawal_id, error = create_withdrawal(user_id, skin_name, pattern, photo_id, balance)
    
    if error:
        await message.answer(f"❌ <b>Ошибка создания заявки:</b>\n\n{error}", parse_mode=ParseMode.HTML)
        await state.clear()
        return
    
    # Получаем информацию о пользователе
    user = get_user(user_id)
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    
    currency = get_currency_info()
    withdrawal_fee = float(get_setting('withdrawal_fee', '0'))
    fee_amount = balance * (withdrawal_fee / 100) if withdrawal_fee > 0 else 0
    
    # Формируем сообщение для группы
    withdrawal_text = (
        f"📦 <b>НОВАЯ ЗАЯВКА НА ВЫВОД #{withdrawal_id}</b>\n\n"
        f"👤 <b>Пользователь:</b> {message.from_user.full_name}\n"
        f"📧 <b>Юзернейм:</b> {username}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"💰 <b>Сумма:</b> {balance} {currency['name']}\n"
        f"📉 <b>Комиссия:</b> {fee_amount} {currency['name']} ({withdrawal_fee}%)\n"
        f"💸 <b>Итого к выплате:</b> {balance} {currency['name']}\n\n"
        f"🎮 <b>Скин:</b> {skin_name}\n"
        f"🔢 <b>Паттерн:</b> {pattern}\n\n"
        f"📅 <b>Дата:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    # Отправляем в группу с фото и кнопками
    try:
        sent_message = await bot.send_photo(
            chat_id=GROUP_ID,
            photo=photo_id,
            caption=withdrawal_text,
            parse_mode=ParseMode.HTML,
            reply_markup=withdrawal_confirmation_keyboard(withdrawal_id)
        )
        
        # Сохраняем ID сообщения
        conn = sqlite3.connect('referral_bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE withdrawals SET message_id = ? WHERE id = ?', (sent_message.message_id, withdrawal_id))
        conn.commit()
        conn.close()
        
        # Уведомляем всех админов
        if get_setting('withdrawal_notify_all_admins', '1') == '1':
            for admin_id in ADMIN_IDS:
                if admin_id != message.from_user.id:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"📦 <b>Новая заявка на вывод #{withdrawal_id}</b>\n\n"
                            f"👤 Пользователь: {message.from_user.full_name}\n"
                            f"💰 Сумма: {balance} {currency['name']}\n\n"
                            f"Перейдите в группу для обработки.",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка отправки заявки в группу: {e}")
        # Если не удалось отправить в группу, отправляем админам напрямую
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"📦 <b>НОВАЯ ЗАЯВКА НА ВЫВОД #{withdrawal_id}</b>\n\n"
                    f"👤 Пользователь: {message.from_user.full_name}\n"
                    f"📧 Юзернейм: {username}\n"
                    f"🆔 ID: {user_id}\n"
                    f"💰 Сумма: {balance} {currency['name']}\n"
                    f"🎮 Скин: {skin_name}\n"
                    f"🔢 Паттерн: {pattern}\n"
                    f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"⚠️ <b>Внимание:</b> Не удалось отправить заявку в группу!",
                    parse_mode=ParseMode.HTML
                )
            except Exception as admin_error:
                logger.error(f"Ошибка уведомления админа {admin_id}: {admin_error}")
    
    await state.clear()
    
    success_text = (
        f"✅ <b>Заявка на вывод успешно создана!</b>\n\n"
        f"📝 <b>Номер заявки:</b> #{withdrawal_id}\n"
        f"💰 <b>Сумма:</b> {balance} {currency['name']}\n"
        f"📉 <b>Комиссия:</b> {fee_amount} {currency['name']}\n"
        f"🎮 <b>Скин:</b> {skin_name}\n"
        f"🔢 <b>Паттерн:</b> {pattern}\n\n"
        f"⏳ <b>Статус:</b> Ожидание обработки администратором\n\n"
        f"Администратор свяжется с вами в ближайшее время!"
    )
    
    await message.answer(success_text, parse_mode=ParseMode.HTML)
    
    # Отправляем фото подтверждения
    await send_with_photo(user_id, 'withdrawal', success_text, main_keyboard())

@dp.callback_query(F.data == "withdrawal_history")
async def show_withdrawal_history(callback: CallbackQuery):
    """Показать историю выводов"""
    user_id = callback.from_user.id
    withdrawals = get_withdrawals(user_id=user_id, limit=20)
    
    currency = get_currency_info()
    
    if withdrawals:
        history_text = f"📦 <b>История ваших выводов</b>\n\n"
        
        total_withdrawn = 0
        pending_count = 0
        completed_count = 0
        rejected_count = 0
        
        for wd in withdrawals:
            wd_id, _, skin_name, pattern, photo_id, amount, status, admin_id, admin_username, created_date, processed_date, message_id, decline_reason = wd
            
            status_emoji = {
                'pending': '⏳',
                'completed': '✅',
                'rejected': '❌'
            }.get(status, '❓')
            
            status_text = {
                'pending': 'В обработке',
                'completed': 'Выполнено',
                'rejected': 'Отклонено'
            }.get(status, status)
            
            history_text += (
                f"{status_emoji} <b>Заявка #{wd_id}</b>\n"
                f"💰 Сумма: {amount} {currency['name']}\n"
                f"🎮 Скин: {skin_name}\n"
                f"🔢 Паттерн: {pattern}\n"
                f"📅 Дата: {created_date[:10] if created_date else 'Неизвестно'}\n"
                f"📊 Статус: {status_text}\n"
            )
            
            if status == 'completed' and admin_username:
                history_text += f"👤 Админ: {admin_username}\n"
            elif status == 'rejected' and decline_reason:
                history_text += f"📝 Причина: {decline_reason}\n"
            
            history_text += "\n"
            
            # Статистика
            if status == 'pending':
                pending_count += 1
            elif status == 'completed':
                completed_count += 1
                total_withdrawn += amount
            elif status == 'rejected':
                rejected_count += 1
        
        # Добавляем общую статистику
        history_text += f"📊 <b>Общая статистика:</b>\n"
        history_text += f"• Всего заявок: <b>{len(withdrawals)}</b>\n"
        history_text += f"• В обработке: <b>{pending_count}</b>\n"
        history_text += f"• Выполнено: <b>{completed_count}</b>\n"
        history_text += f"• Отклонено: <b>{rejected_count}</b>\n"
        history_text += f"• Выведено всего: <b>{total_withdrawn} {currency['name']}</b>\n"
    else:
        history_text = "📭 <b>У вас еще не было заявок на вывод.</b>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="💰 Новый вывод", callback_data="withdrawal"))
    keyboard.add(InlineKeyboardButton(text="📋 История транзакций", callback_data="transaction_history"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="withdrawal_history"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'profile', history_text, keyboard.as_markup())
    await callback.answer()

# ===================== ОБРАБОТЧИКИ ДЛЯ АДМИНИСТРАТОРОВ =====================

@dp.callback_query(F.data.startswith("confirm_withdrawal_"))
async def confirm_withdrawal_handler(callback: CallbackQuery):
    """Подтвердить вывод"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split("_")[-1])
    admin_username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
    
    success = update_withdrawal_status(withdrawal_id, 'completed', user_id, admin_username)
    
    if success:
        # Получаем информацию о выводе
        conn = sqlite3.connect('referral_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM withdrawals WHERE id = ?', (withdrawal_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            wd_user_id, amount = result
            currency = get_currency_info()
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    wd_user_id,
                    f"✅ <b>Ваша заявка на вывод #{withdrawal_id} одобрена!</b>\n\n"
                    f"💰 Сумма: {amount} {currency['name']}\n"
                    f"👤 Администратор: {admin_username}\n"
                    f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"Совсем скоро ваш скин купят!",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления пользователя: {e}")
            
            # Обновляем сообщение в группе
            try:
                conn = sqlite3.connect('referral_bot.db')
                cursor = conn.cursor()
                cursor.execute('SELECT message_id FROM withdrawals WHERE id = ?', (withdrawal_id,))
                msg_result = cursor.fetchone()
                conn.close()
                
                if msg_result and msg_result[0]:
                    try:
                        await bot.edit_message_caption(
                            chat_id=GROUP_ID,
                            message_id=msg_result[0],
                            caption=f"✅ <b>ВЫВОД #{withdrawal_id} ВЫПОЛНЕН</b>\n\n"
                                   f"👤 Администратор: {admin_username}\n"
                                   f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Ошибка редактирования сообщения в группе: {e}")
            except Exception as e:
                logger.error(f"Ошибка получения message_id: {e}")
        
        await callback.answer(f"✅ Вывод #{withdrawal_id} подтвержден!")
        
        # Обновляем клавиатуру в сообщении
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e:
            logger.error(f"Ошибка обновления клавиатуры: {e}")
    else:
        await callback.answer("❌ Ошибка подтверждения вывода!", show_alert=True)

@dp.callback_query(F.data.startswith("reject_withdrawal_"))
async def reject_withdrawal_handler(callback: CallbackQuery, state: FSMContext):
    """Отклонить вывод"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    withdrawal_id = int(callback.data.split("_")[-1])
    
    await callback.message.answer(
        f"📝 <b>Отклонение вывода #{withdrawal_id}</b>\n\n"
        f"Укажите причину отклонения:",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state("waiting_decline_reason")
    await state.update_data(withdrawal_id=withdrawal_id)
    await callback.answer()

@dp.message(StateFilter("waiting_decline_reason"))
async def process_decline_reason(message: Message, state: FSMContext):
    """Обработка причины отклонения"""
    data = await state.get_data()
    withdrawal_id = data['withdrawal_id']
    decline_reason = message.text.strip()
    
    if not decline_reason:
        await message.answer("❌ Причина отклонения не может быть пустой. Попробуйте еще раз:")
        return
    
    admin_username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    
    success = update_withdrawal_status(withdrawal_id, 'rejected', message.from_user.id, admin_username, decline_reason)
    
    if success:
        # Получаем информацию о выводе
        conn = sqlite3.connect('referral_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM withdrawals WHERE id = ?', (withdrawal_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            wd_user_id, amount = result
            currency = get_currency_info()
            user = get_user(wd_user_id)
            new_balance = user[3] if user else amount
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    wd_user_id,
                    f"❌ <b>Ваша заявка на вывод #{withdrawal_id} отклонена!</b>\n\n"
                    f"💰 Сумма: {amount} {currency['name']} возвращена на баланс\n"
                    f"📝 Причина: {decline_reason}\n"
                    f"👤 Администратор: {admin_username}\n"
                    f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"💰 Текущий баланс: {new_balance} {currency['name']}",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления пользователя: {e}")
        
        await message.answer(f"✅ Вывод #{withdrawal_id} отклонен!")
        
        # Обновляем сообщение в группе
        try:
            conn = sqlite3.connect('referral_bot.db')
            cursor = conn.cursor()
            cursor.execute('SELECT message_id FROM withdrawals WHERE id = ?', (withdrawal_id,))
            msg_result = cursor.fetchone()
            conn.close()
            
            if msg_result and msg_result[0]:
                try:
                    await bot.edit_message_caption(
                        chat_id=GROUP_ID,
                        message_id=msg_result[0],
                        caption=f"❌ <b>ВЫВОД #{withdrawal_id} ОТКЛОНЕН</b>\n\n"
                               f"📝 Причина: {decline_reason}\n"
                               f"👤 Администратор: {admin_username}\n"
                               f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Ошибка редактирования сообщения в группе: {e}")
        except Exception as e:
            logger.error(f"Ошибка получения message_id: {e}")
    else:
        await message.answer("❌ Ошибка отклонения вывода!")
    
    await state.clear()

# ===================== АДМИН КОМАНДЫ =====================

@dp.message(Command("add_balance"))
async def add_balance_command(message: Message):
    """Добавить баланс пользователю"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Проверяем права
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_balance', False):
        await message.answer("⛔ У вас нет прав на изменение баланса!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 4:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/add_balance user_id сумма описание</code>\n\n"
                "Пример:\n"
                "<code>/add_balance 123456789 100 Бонус за активность</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user_id = int(parts[1])
        amount = float(parts[2])
        description = ' '.join(parts[3:])
        
        user = get_user(target_user_id)
        if not user:
            await message.answer("❌ Пользователь не найден!")
            return
        
        old_balance = user[3] or 0
        update_balance(target_user_id, amount, description, 'manual_adjustment')
        new_user = get_user(target_user_id)
        new_balance = new_user[3] if new_user and new_user[3] is not None else old_balance + amount
        
        currency = get_currency_info()
        
        result_text = (
            f"✅ <b>Баланс обновлен!</b>\n\n"
            f"👤 Пользователь: {user[2]}\n"
            f"🆔 ID: {target_user_id}\n"
            f"📊 Изменение: {amount:+} {currency['name']}\n"
            f"📝 Причина: {description}\n"
            f"💰 Старый баланс: {old_balance} {currency['name']}\n"
            f"💰 Новый баланс: {new_balance} {currency['name']}"
        )
        
        await message.answer(result_text, parse_mode=ParseMode.HTML)
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_user_id,
                f"💰 <b>Ваш баланс изменен!</b>\n\n"
                f"📊 Изменение: {amount:+} {currency['name']}\n"
                f"📝 Причина: {description}\n"
                f"💰 Новый баланс: {new_balance} {currency['name']}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя: {e}")
            await message.answer("⚠️ Не удалось отправить уведомление пользователю")
            
    except ValueError as e:
        await message.answer(f"❌ Ошибка в формате данных: {e}")
    except Exception as e:
        logger.error(f"Ошибка в команде add_balance: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_referral_bonus"))
async def set_referral_bonus_command(message: Message):
    """Установить бонус за реферала"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Проверяем права
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await message.answer("⛔ У вас нет прав на изменение настроек!")
        return
    
    try:
        amount = float(message.text.split()[1])
        if amount < 0:
            await message.answer("❌ Сумма должна быть положительной!")
            return
        
        update_setting('referral_bonus', str(amount))
        
        await message.answer(f"✅ Бонус за реферала изменен на {amount}г!")
        
        # Уведомляем всех админов
        for admin_id in ADMIN_IDS:
            if admin_id != user_id:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚙️ <b>Изменение настройки</b>\n\n"
                        f"👤 Админ: @{message.from_user.username if message.from_user.username else message.from_user.full_name}\n"
                        f"🎯 Настройка: Бонус за реферала\n"
                        f"💰 Новое значение: {amount}г",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
    except IndexError:
        await message.answer("❌ Ошибка формата. Используйте: /set_referral_bonus 500")
    except ValueError:
        await message.answer("❌ Ошибка формата. Сумма должна быть числом!")
    except Exception as e:
        logger.error(f"Ошибка в команде set_referral_bonus: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_welcome_bonus"))
async def set_welcome_bonus_command(message: Message):
    """Установить стартовый бонус"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await message.answer("⛔ У вас нет прав на изменение настроек!")
        return
    
    try:
        amount = float(message.text.split()[1])
        if amount < 0:
            await message.answer("❌ Сумма должна быть положительной!")
            return
        
        update_setting('welcome_bonus', str(amount))
        currency = get_currency_info()
        
        await message.answer(f"✅ Стартовый бонус изменен на {amount} {currency['name']}!")
        
        for admin_id in ADMIN_IDS:
            if admin_id != user_id:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚙️ <b>Изменение настройки</b>\n\n"
                        f"👤 Админ: @{message.from_user.username if message.from_user.username else message.from_user.full_name}\n"
                        f"🎯 Настройка: Стартовый бонус\n"
                        f"💰 Новое значение: {amount} {currency['name']}",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления админа {admin_id}: {e}")
    except IndexError:
        await message.answer("❌ Ошибка формата. Используйте: /set_welcome_bonus 100")
    except ValueError:
        await message.answer("❌ Ошибка формата. Сумма должна быть числом!")
    except Exception as e:
        logger.error(f"Ошибка в команде set_welcome_bonus: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# ===================== КОМАНДЫ ДЛЯ РАБОТЫ С ФОТО =====================

@dp.message(Command("set_photo"))
async def set_photo_command(message: Message, state: FSMContext):
    """Установить фото для раздела бота"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_photos', False):
        await message.answer("⛔ У вас нет прав на управление фото!")
        return
    
    # Список доступных типов фото
    photo_types = [
        "welcome - фото для приветствия",
        "profile - фото для профиля",
        "referral - фото для реферальной системы",
        "admin - фото для админ-панели",
        "withdrawal - фото для вывода",
        "promo - фото для промокодов",
        "stats - фото для статистики"
    ]
    
    await message.answer(
        "📸 <b>Установка фото для раздела бота</b>\n\n"
        "<b>Доступные типы фото:</b>\n" + "\n".join([f"• {pt}" for pt in photo_types]) + "\n\n"
        "Введите тип фото (например: <code>welcome</code>):",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AddPhotoStates.waiting_for_photo_type)

@dp.message(AddPhotoStates.waiting_for_photo_type)
async def process_photo_type(message: Message, state: FSMContext):
    """Обработка типа фото"""
    photo_type = message.text.strip().lower()
    
    valid_types = ['welcome', 'profile', 'referral', 'admin', 'withdrawal', 'promo', 'stats']
    
    if photo_type not in valid_types:
        await message.answer(
            f"❌ Неверный тип фото. Доступные типы:\n"
            f"{', '.join(valid_types)}\n\n"
            f"Попробуйте еще раз:"
        )
        return
    
    await state.update_data(photo_type=photo_type)
    await state.set_state(AddPhotoStates.waiting_for_photo)
    
    await message.answer(
        f"📸 <b>Установка фото для {photo_type}</b>\n\n"
        f"Отправьте URL фото (ссылку) или прикрепите фото.\n\n"
        f"<i>Поддерживаются ссылки на Яндекс.Диск, Google Drive или любые прямые ссылки на изображения.</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message(AddPhotoStates.waiting_for_photo)
async def process_photo_url(message: Message, state: FSMContext):
    """Обработка URL фото"""
    data = await state.get_data()
    photo_type = data['photo_type']
    
    # Проверяем, отправлена ли ссылка или фото
    if message.text:
        # Это URL
        photo_url = message.text.strip()
        
        # Проверяем, что это валидный URL
        if not (photo_url.startswith('http://') or photo_url.startswith('https://')):
            await message.answer("❌ Неверный формат ссылки. Ссылка должна начинаться с http:// или https://")
            return
        
        # Сохраняем URL в настройках
        update_setting(f'photo_{photo_type}', photo_url)
        
        await message.answer(
            f"✅ <b>Фото для {photo_type} успешно установлено!</b>\n\n"
            f"📎 Ссылка: {photo_url}\n\n"
            f"Фото будет использоваться в соответствующем разделе бота.",
            parse_mode=ParseMode.HTML
        )
        
    elif message.photo:
        # Это загруженное фото
        photo_id = message.photo[-1].file_id
        
        # Сохраняем file_id
        update_setting(f'photo_{photo_type}_file_id', photo_id)
        
        # Также сохраняем file_id в обычное поле для совместимости
        update_setting(f'photo_{photo_type}', f'file_id:{photo_id}')
        
        await message.answer(
            f"✅ <b>Фото для {photo_type} успешно установлено!</b>\n\n"
            f"📸 Фото сохранено как file_id.\n\n"
            f"<i>Фото будет использоваться в соответствующем разделе бота.</i>",
            parse_mode=ParseMode.HTML
        )
        
        # Также предлагаем скачать фото для локального хранения
        try:
            file = await bot.get_file(photo_id)
            file_path = file.file_path
            downloaded_file = await bot.download_file(file_path)
            
            # Сохраняем локально
            local_path = os.path.join(IMAGES_DIR, f'{photo_type}.jpg')
            with open(local_path, 'wb') as f:
                f.write(downloaded_file.read())
            
            await message.answer(
                f"📁 Фото также сохранено локально: {local_path}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения фото локально: {e}")
            await message.answer(
                f"⚠️ Не удалось сохранить фото локально. Ошибка: {e}",
                parse_mode=ParseMode.HTML
            )
    
    else:
        await message.answer("❌ Пожалуйста, отправьте URL ссылку или прикрепите фото.")
        return
    
    await state.clear()

# ===================== ДОБАВЛЕННЫЕ ОБРАБОТЧИКИ ДЛЯ КНОПОК =====================

@dp.callback_query(F.data == "refresh_balance")
async def refresh_balance(callback: CallbackQuery):
    """Обновить баланс"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден!", show_alert=True)
        return
    
    balance = user[3] or 0
    currency = get_currency_info()
    
    await callback.answer(f"💰 Ваш баланс: {balance} {currency['name']}")

@dp.callback_query(F.data == "detailed_stats")
async def detailed_stats(callback: CallbackQuery):
    """Детальная статистика"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден!", show_alert=True)
        return
    
    # Получаем детальную статистику
    transactions = get_detailed_transactions(user_id, days=30)
    referrals = get_referrals(user_id)
    ref_stats = get_referral_stats(user_id)
    
    currency = get_currency_info()
    
    # Формируем текст
    stats_text = (
        f"📊 <b>Детальная статистика</b>\n\n"
        f"💰 <b>Баланс:</b> {user[3] or 0} {currency['name']}\n"
        f"💎 <b>Заработано всего:</b> {user[9] or 0} {currency['name']}\n"
        f"💸 <b>Выведено всего:</b> {user[10] or 0} {currency['name']}\n\n"
        f"👥 <b>Реферальная статистика:</b>\n"
        f"• Прямых рефералов: {ref_stats['direct_count']}\n"
        f"• Заработано на рефералах: {ref_stats['total_earned']} {currency['name']}\n\n"
        f"📈 <b>Транзакции за 30 дней:</b>\n"
        f"• Пополнений: {transactions['total_income']} {currency['name']}\n"
        f"• Списаний: {transactions['total_outcome']} {currency['name']}\n"
        f"• Чистый доход: {transactions['total_income'] - transactions['total_outcome']} {currency['name']}\n\n"
        f"📅 <b>Дата регистрации:</b> {user[6][:10] if user[6] else 'Неизвестно'}\n"
        f"📱 <b>Последняя активность:</b> {user[7][:16] if user[7] else 'Неизвестно'}"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📋 История транзакций", callback_data="transaction_history"))
    keyboard.add(InlineKeyboardButton(text="📦 История выводов", callback_data="withdrawal_history"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="detailed_stats"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'stats', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "detailed_referral_stats")
async def detailed_referral_stats(callback: CallbackQuery):
    """Детальная статистика рефералов"""
    user_id = callback.from_user.id
    referrals = get_referrals(user_id, max_level=3)
    ref_stats = get_referral_stats(user_id)
    
    currency = get_currency_info()
    
    if referrals:
        stats_text = f"📊 <b>Детальная реферальная статистика</b>\n\n"
        
        # Считаем по уровням
        level_counts = {1: 0, 2: 0, 3: 0}
        level_earnings = {1: 0, 2: 0, 3: 0}
        
        def count_levels(ref_list):
            for ref in ref_list:
                level_counts[ref['level']] += 1
                if ref['level'] == 1:
                    level_earnings[1] += get_referral_bonus()
                
                if 'sub_referrals' in ref and ref['sub_referrals']:
                    count_levels(ref['sub_referrals'])
        
        count_levels(referrals)
        
        # Многоуровневая система
        if get_setting('multi_level_enabled', '0') == '1':
            try:
                levels = json.loads(get_setting('referral_levels', '{"1": 300, "2": 150, "3": 75}'))
                for level, bonus in levels.items():
                    lvl = int(level)
                    if lvl > 1:
                        level_earnings[lvl] = level_counts[lvl] * float(bonus)
            except Exception as e:
                logger.error(f"Ошибка расчета многоуровневой системы: {e}")
        
        stats_text += f"📈 <b>По уровням:</b>\n"
        for level in [1, 2, 3]:
            stats_text += f"• Уровень {level}: {level_counts[level]} чел. = {level_earnings[level]}г\n"
        
        stats_text += f"\n💰 <b>Итого заработано:</b> {ref_stats['total_earned']} {currency['name']}\n"
        
        # Список рефералов
        stats_text += f"\n👥 <b>Список рефералов (первые 10):</b>\n"
        for i, ref in enumerate(referrals[:10], 1):
            level_emoji = "🥇" if ref['level'] == 1 else "🥈" if ref['level'] == 2 else "🥉"
            username = f"@{ref['username']}" if ref['username'] else ref['full_name']
            stats_text += f"{i}. {level_emoji} {ref['full_name']} ({username})\n"
        
    else:
        stats_text = "😔 <b>У вас пока нет рефералов.</b>\n\n🔗 Приглашайте друзей по своей реферальной ссылке!"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="referral_link"))
    keyboard.add(InlineKeyboardButton(text="📊 Общая статистика", callback_data="statistics"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="detailed_referral_stats"))
    keyboard.add(InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'profile', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "check_subscriptions_after")
async def check_subscriptions_after(callback: CallbackQuery):
    """Проверка подписок после нажатия кнопки"""
    user_id = callback.from_user.id
    not_subscribed_channels = await check_all_subscriptions(user_id)
    
    if not_subscribed_channels:
        await callback.answer("❌ Вы все еще не подписаны на все каналы!", show_alert=True)
        return
    
    # Проверяем группу (с обработкой ошибок)
    try:
        member = await bot.get_chat_member(GROUP_ID, user_id)
        if member.status in ['left', 'kicked']:
            await callback.answer("❌ Вы не подписаны на группу!", show_alert=True)
            return
    except Exception as e:
        logger.error(f"Ошибка проверки группы: {e}")
        # Если ошибка, пропускаем проверку группы
    
    user = get_user(user_id)
    balance = user[3] if user else 0
    currency = get_currency_info()
    
    caption = (
        f"✅ <b>Отлично! Вы подписаны на все каналы!</b>\n\n"
        f"👤 <b>Имя:</b> {callback.from_user.full_name}\n"
        f"💰 <b>Баланс:</b> {balance} {currency['name']}\n\n"
        f"Теперь вы можете использовать все функции бота!"
    )
    
    await edit_with_photo(callback, 'welcome', caption, main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "check_channel_subscription")
async def check_group_subscription(callback: CallbackQuery):
    """Проверка подписки на группу"""
    user_id = callback.from_user.id
    
    try:
        member = await bot.get_chat_member(GROUP_ID, user_id)
        if member.status in ['left', 'kicked']:
            await callback.answer("❌ Вы все еще не вступили в группу!", show_alert=True)
            return
    except Exception as e:
        logger.error(f"Ошибка проверки группы: {e}")
        await callback.answer("❌ Ошибка проверки группы!", show_alert=True)
        return
    
    user = get_user(user_id)
    balance = user[3] if user else 0
    currency = get_currency_info()
    
    caption = (
        f"✅ <b>Отлично! Вы вступили в группу!</b>\n\n"
        f"👤 <b>Имя:</b> {callback.from_user.full_name}\n"
        f"💰 <b>Баланс:</b> {balance} {currency['name']}\n\n"
        f"Теперь вы можете использовать все функции бота!"
    )
    
    await edit_with_photo(callback, 'welcome', caption, main_keyboard())
    await callback.answer()

# ===================== ОБРАБОТЧИКИ АДМИН-МЕНЮ =====================

@dp.callback_query(F.data == "bot_stats")
async def bot_stats_handler(callback: CallbackQuery):
    """Статистика бота для админа"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    stats = get_user_statistics()
    pending_withdrawals = len(get_withdrawals(status='pending'))
    total_promos = len(get_promo_codes(active_only=False))
    active_promos = len(get_promo_codes(active_only=True))
    
    currency = get_currency_info()
    
    stats_text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"• Всего: <b>{stats['total_users']}</b>\n"
        f"• Сегодня новых: <b>{stats['new_today']}</b>\n"
        f"• Активных сегодня: <b>{stats['active_today']}</b>\n\n"
        f"💰 <b>Финансы:</b>\n"
        f"• Общий баланс: <b>{stats['total_balance']} {currency['name']}</b>\n"
        f"• Заработано всего: <b>{stats['total_earned']} {currency['name']}</b>\n"
        f"• Выведено всего: <b>{stats['total_withdrawn']} {currency['name']}</b>\n\n"
        f"📦 <b>Заявки:</b>\n"
        f"• Ожидают обработки: <b>{pending_withdrawals}</b>\n\n"
        f"🎁 <b>Промокоды:</b>\n"
        f"• Всего: <b>{total_promos}</b>\n"
        f"• Активных: <b>{active_promos}</b>\n\n"
        f"👑 <b>Администраторы:</b> <b>{len(ADMIN_IDS)}</b>"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📈 Детальная статистика", callback_data="detailed_statistics"))
    keyboard.add(InlineKeyboardButton(text="📊 Топ пользователей", callback_data="top_users"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="bot_stats"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_menu_back")
async def admin_menu_back(callback: CallbackQuery):
    """Возврат в админ-меню"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    admin_count = len(ADMIN_IDS)
    
    # Получаем количество пользователей
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0] or 0
    conn.close()
    
    pending_withdrawals = len(get_withdrawals(status='pending'))
    
    caption = (
        f"👑 <b>Панель администратора</b>\n\n"
        f"📊 <b>Общая статистика:</b>\n"
        f"• Администраторов: <b>{admin_count}</b>\n"
        f"• Пользователей: <b>{user_count}</b>\n"
        f"• Заявок на вывод: <b>{pending_withdrawals}</b>\n\n"
        f"<b>Выберите действие:</b>"
    )
    
    await edit_with_photo(callback, 'admin', caption, admin_keyboard())
    await callback.answer()

# ===================== ОБРАБОТЧИКИ ДЛЯ ВСЕХ КНОПОК АДМИН-ПАНЕЛИ =====================

@dp.callback_query(F.data == "admin_users")
async def admin_users_handler(callback: CallbackQuery):
    """Управление пользователями"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_users', False):
        await callback.answer("⛔ У вас нет прав на управление пользователями!", show_alert=True)
        return
    
    stats = get_user_statistics()
    
    stats_text = (
        f"👥 <b>Управление пользователей</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"• Новых сегодня: <b>{stats['new_today']}</b>\n"
        f"• Активных сегодня: <b>{stats['active_today']}</b>\n"
        f"• Общий баланс: <b>{stats['total_balance']}г</b>\n\n"
        f"🏆 <b>Топ 5 рефереров:</b>\n"
    )
    
    for i, (uid, username, name, ref_count, earned) in enumerate(stats['top_referrers'][:5], 1):
        stats_text += f"{i}. {name}: <b>{ref_count}</b> рефералов (<b>{earned}г</b>)\n"
    
    stats_text += f"\n💰 <b>Топ 5 по балансу:</b>\n"
    for i, (uid, username, name, balance) in enumerate(stats['top_balance'][:5], 1):
        stats_text += f"{i}. {name}: <b>{balance}г</b>\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔍 Поиск пользователя", callback_data="search_user"))
    keyboard.add(InlineKeyboardButton(text="📋 Список пользователей", callback_data="user_list"))
    keyboard.add(InlineKeyboardButton(text="📊 Детальная статистика", callback_data="detailed_user_stats"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_users"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "change_balance")
async def change_balance_handler(callback: CallbackQuery):
    """Изменение баланса"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_balance', False):
        await callback.answer("⛔ У вас нет прав на изменение баланса!", show_alert=True)
        return
    
    stats_text = (
        f"💰 <b>Изменение баланса пользователя</b>\n\n"
        f"Для изменения баланса используйте команду:\n"
        f"<code>/add_balance ID_пользователя сумма описание</code>\n\n"
        f"Примеры:\n"
        f"• Добавить баланс:\n"
        f"<code>/add_balance 123456789 100 Бонус за активность</code>\n\n"
        f"• Снять баланс:\n"
        f"<code>/add_balance 123456789 -50 Штраф за нарушение</code>\n\n"
        f"Или нажмите кнопку ниже для быстрого изменения:"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="search_user"))
    keyboard.add(InlineKeyboardButton(text="📋 Список пользователей", callback_data="user_list"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "bonus_settings")
async def bonus_settings_handler(callback: CallbackQuery):
    """Настройки бонусов"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await callback.answer("⛔ У вас нет прав на изменение настроек!", show_alert=True)
        return
    
    referral_bonus = get_referral_bonus()
    welcome_bonus = get_welcome_bonus()
    min_withdrawal = float(get_setting('min_withdrawal', '100'))
    withdrawal_fee = float(get_setting('withdrawal_fee', '0'))
    multi_level_enabled = get_setting('multi_level_enabled', '0') == '1'
    
    stats_text = (
        f"⚙️ <b>Настройки бонусов</b>\n\n"
        f"📊 <b>Текущие настройки:</b>\n"
        f"• Бонус за реферала: <b>{referral_bonus}г</b>\n"
        f"• Стартовый бонус: <b>{welcome_bonus}г</b>\n"
        f"• Минимальный вывод: <b>{min_withdrawal}г</b>\n"
        f"• Комиссия за вывод: <b>{withdrawal_fee}%</b>\n"
        f"• Многоуровневая система: <b>{'✅ Включена' if multi_level_enabled else '❌ Выключена'}</b>\n\n"
        f"Выберите параметр для изменения:"
    )
    
    await edit_with_photo(callback, 'admin', stats_text, bonus_settings_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "manage_channels")
async def manage_channels_handler(callback: CallbackQuery):
    """Управление каналами"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_channels', False):
        await callback.answer("⛔ У вас нет прав на управление каналами!", show_alert=True)
        return
    
    channels_text = "📢 <b>Управление обязательными каналами</b>\n\n"
    
    if not REQUIRED_CHANNELS:
        channels_text += "❌ Нет обязательных каналов\n"
    else:
        channels_text += f"📊 Всего каналов: <b>{len(REQUIRED_CHANNELS)}</b>\n\n"
        
        for i, channel in enumerate(REQUIRED_CHANNELS, 1):
            if isinstance(channel, dict):
                channels_text += (
                    f"{i}. <b>{channel.get('name', 'Без имени')}</b>\n"
                    f"   🆔 ID: <code>{channel.get('id', 'Не указан')}</code>\n"
                    f"   📧 Юзернейм: @{channel.get('username', 'Не указан')}\n"
                    f"   🔗 Ссылка: {channel.get('invite_link', 'Не указана')}\n\n"
                )
            else:
                channels_text += f"{i}. Канал {channel}\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel"))
    keyboard.add(InlineKeyboardButton(text="➖ Удалить канал", callback_data="remove_channel"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить список", callback_data="manage_channels"))
    keyboard.add(InlineKeyboardButton(text="📊 Статистика подписок", callback_data="subscription_stats"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', channels_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "manage_admins")
async def manage_admins_handler(callback: CallbackQuery):
    """Управление админами"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    if not is_super_admin(user_id):
        await callback.answer("⛔ Только суперадмин может управлять админами!", show_alert=True)
        return
    
    admins = get_all_admins()
    
    admins_text = "👑 <b>Управление администраторами</b>\n\n"
    
    if not admins:
        admins_text += "❌ Нет администраторов\n"
    else:
        admins_text += f"📊 Всего администраторов: <b>{len(admins)}</b>\n\n"
        
        for admin in admins:
            admin_id, is_super, added_date, added_by, permissions_json = admin
            
            # Получаем информацию об администраторе
            user_info = get_user(admin_id)
            if user_info:
                name = user_info[2]
                username = f"@{user_info[1]}" if user_info[1] else "без юзернейма"
            else:
                name = "Неизвестно"
                username = "без юзернейма"
            
            status = "🟢 Суперадмин" if is_super == 1 else "🔵 Админ"
            
            admins_text += (
                f"• <b>{name}</b> {status}\n"
                f"  📧 {username}\n"
                f"  🆔 ID: <code>{admin_id}</code>\n"
                f"  📅 Добавлен: {added_date[:10] if added_date else 'Неизвестно'}\n\n"
            )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="➕ Добавить админа", callback_data="add_admin"))
    keyboard.add(InlineKeyboardButton(text="➖ Удалить админа", callback_data="remove_admin"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить список", callback_data="manage_admins"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', admins_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "manage_promo_codes")
async def manage_promo_codes_handler(callback: CallbackQuery):
    """Управление промокодами"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_promo_codes', False):
        await callback.answer("⛔ У вас нет прав на управление промокодами!", show_alert=True)
        return
    
    promos = get_promo_codes(active_only=False)
    
    promos_text = "🎁 <b>Управление промокодами</b>\n\n"
    
    if not promos:
        promos_text += "❌ Нет промокодов\n"
    else:
        active_count = len([p for p in promos if p[8] == 1])
        used_count = sum([p[4] for p in promos])
        
        promos_text += f"📊 Всего промокодов: <b>{len(promos)}</b>\n"
        promos_text += f"✅ Активных: <b>{active_count}</b>\n"
        promos_text += f"🔄 Использовано раз: <b>{used_count}</b>\n\n"
        
        for promo in promos[:10]:  # Показываем первые 10
            promo_id, code, amount, max_uses, used_count, created_by, created_date, expires_date, is_active, min_balance, for_new_users_only = promo
            
            status = "🟢 Активен" if is_active == 1 else "🔴 Неактивен"
            expires_info = f"до {expires_date[:10]}" if expires_date else "без срока"
            
            promos_text += (
                f"• <b>{code}</b> {status}\n"
                f"  💰 Сумма: {amount}г\n"
                f"  🎯 Использовано: {used_count}/{max_uses}\n"
                f"  📅 {expires_info}\n\n"
            )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="➕ Создать промокод", callback_data="create_promo_code"))
    keyboard.add(InlineKeyboardButton(text="📋 Список промокодов", callback_data="promo_codes_list"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="manage_promo_codes"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', promos_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "manage_photos")
async def manage_photos_handler(callback: CallbackQuery):
    """Управление фото"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_photos', False):
        await callback.answer("⛔ У вас нет прав на управление фото!", show_alert=True)
        return
    
    photo_types = [
        ('welcome', 'Приветствие'),
        ('profile', 'Профиль'),
        ('referral', 'Реферальная система'),
        ('admin', 'Админ-панель'),
        ('withdrawal', 'Вывод средств'),
        ('promo', 'Промокоды'),
        ('stats', 'Статистика')
    ]
    
    photos_text = "🖼 <b>Управление фотографиями</b>\n\n"
    
    for photo_type, photo_name in photo_types:
        photo_url = get_photo_url(photo_type)
        photo_file_id = get_setting(f'photo_{photo_type}_file_id', '')
        photo_path = os.path.join(IMAGES_DIR, f'{photo_type}.jpg')
        
        if photo_file_id or photo_url or os.path.exists(photo_path):
            photos_text += f"✅ <b>{photo_name}:</b> Установлено\n"
        else:
            photos_text += f"❌ <b>{photo_name}:</b> Не установлено\n"
    
    photos_text += "\nДля установки фото используйте команду:\n"
    photos_text += "<code>/set_photo</code>\n\n"
    photos_text += "Или выберите тип фото для быстрой установки:"
    
    keyboard = InlineKeyboardBuilder()
    for photo_type, photo_name in photo_types:
        keyboard.add(InlineKeyboardButton(text=f"📸 {photo_name}", callback_data=f"set_photo_{photo_type}"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', photos_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "withdrawal_requests")
async def withdrawal_requests_handler(callback: CallbackQuery):
    """Заявки на вывод"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_withdrawals', False):
        await callback.answer("⛔ У вас нет прав на управление заявками на вывод!", show_alert=True)
        return
    
    pending_withdrawals = get_withdrawals(status='pending', limit=10)
    
    stats_text = "📦 <b>Заявки на вывод</b>\n\n"
    
    if not pending_withdrawals:
        stats_text += "✅ <b>Нет ожидающих заявок</b>\n\n"
    else:
        stats_text += f"⏳ <b>Ожидают обработки:</b> <b>{len(pending_withdrawals)}</b>\n\n"
        
        total_amount = sum([wd[5] for wd in pending_withdrawals])
        stats_text += f"💰 <b>Общая сумма:</b> <b>{total_amount}г</b>\n\n"
        
        for wd in pending_withdrawals[:5]:
            wd_id, wd_user_id, skin_name, pattern, _, amount, status, _, _, created_date, _, _, _ = wd
            
            # Получаем информацию о пользователе
            user = get_user(wd_user_id)
            if user:
                user_name = user[2]
                user_username = f"@{user[1]}" if user[1] else "без юзернейма"
            else:
                user_name = "Неизвестно"
                user_username = "без юзернейма"
            
            stats_text += (
                f"• <b>Заявка #{wd_id}</b>\n"
                f"  👤 {user_name} ({user_username})\n"
                f"  💰 {amount}г | 🎮 {skin_name[:20]}...\n"
                f"  📅 {created_date[:16]}\n\n"
            )
    
    # Статистика за сегодня
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status = "completed" AND date(processed_date) = ?', (today,))
    today_stats = cursor.fetchone()
    today_count = today_stats[0] or 0
    today_amount = today_stats[1] or 0
    conn.close()
    
    stats_text += f"📊 <b>Статистика за сегодня:</b>\n"
    stats_text += f"• Выполнено: <b>{today_count}</b> заявок\n"
    stats_text += f"• Выплачено: <b>{today_amount}г</b>\n\n"
    
    stats_text += "Выберите действие:"
    
    await edit_with_photo(callback, 'admin', stats_text, withdrawal_requests_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "all_transactions")
async def all_transactions_handler(callback: CallbackQuery):
    """Все транзакции"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('view_transactions', False):
        await callback.answer("⛔ У вас нет прав на просмотр транзакций!", show_alert=True)
        return
    
    transactions = get_transactions(limit=20)
    
    stats_text = "📈 <b>Все транзакции</b>\n\n"
    
    if not transactions:
        stats_text += "📭 <b>Нет транзакций</b>\n\n"
    else:
        stats_text += f"📊 <b>Последние 20 транзакций:</b>\n\n"
        
        total_income = 0
        total_outcome = 0
        
        for trans in transactions:
            trans_id, user_id_trans, amount, trans_type, description, date, status, related_id = trans
            
            type_emoji = {
                'referral_bonus': '💎',
                'welcome_bonus': '🎁',
                'manual_adjustment': '⚙️',
                'withdrawal': '📤',
                'promo_code': '🎫'
            }.get(trans_type, '💰')
            
            if amount > 0:
                total_income += amount
                amount_text = f"+{amount}г"
            else:
                total_outcome += abs(amount)
                amount_text = f"{amount}г"
            
            # Получаем информацию о пользователе
            user = get_user(user_id_trans)
            if user:
                user_name = user[2][:15]
            else:
                user_name = f"ID:{user_id_trans}"
            
            stats_text += (
                f"{type_emoji} <b>{amount_text}</b>\n"
                f"👤 {user_name} | {trans_type}\n"
                f"📝 {description[:30]}...\n"
                f"📅 {date[:16]}\n\n"
            )
    
    stats_text += f"📊 <b>Итоги:</b>\n"
    stats_text += f"• Пополнений: <b>{total_income}г</b>\n"
    stats_text += f"• Списаний: <b>{total_outcome}г</b>\n"
    stats_text += f"• Чистый доход: <b>{total_income - total_outcome}г</b>\n\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📋 Детальная статистика", callback_data="detailed_statistics"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="all_transactions"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "detailed_statistics")
async def detailed_statistics_handler(callback: CallbackQuery):
    """Детальная статистика"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    # Получаем статистику за последние 7 дней
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    stats_7_days = []
    total_new_users = 0
    total_referrals = 0
    total_withdrawals = 0
    total_withdrawn = 0
    
    for i in range(7):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        cursor.execute("SELECT new_users, referrals_count, withdrawals_count, withdrawals_amount FROM statistics WHERE date = ?", (date,))
        result = cursor.fetchone()
        
        if result:
            new_users, referrals, withdrawals, withdrawn = result
            stats_7_days.append({
                'date': date[5:],  # Берем только месяц-день
                'new_users': new_users or 0,
                'referrals': referrals or 0,
                'withdrawals': withdrawals or 0,
                'withdrawn': withdrawn or 0
            })
            
            total_new_users += new_users or 0
            total_referrals += referrals or 0
            total_withdrawals += withdrawals or 0
            total_withdrawn += withdrawn or 0
        else:
            stats_7_days.append({
                'date': date[5:],
                'new_users': 0,
                'referrals': 0,
                'withdrawals': 0,
                'withdrawn': 0
            })
    
    conn.close()
    
    # Формируем текст
    stats_text = (
        f"📊 <b>Детальная статистика (за 7 дней)</b>\n\n"
        f"📈 <b>Итоги за период:</b>\n"
        f"• Новых пользователей: <b>{total_new_users}</b>\n"
        f"• Реферальных переходов: <b>{total_referrals}</b>\n"
        f"• Выполнено выводов: <b>{total_withdrawals}</b>\n"
        f"• Выведено всего: <b>{total_withdrawn}г</b>\n\n"
        f"📅 <b>Детали по дням:</b>\n"
    )
    
    for day in reversed(stats_7_days):
        stats_text += (
            f"• {day['date']}: "
            f"👤{day['new_users']} "
            f"👥{day['referrals']} "
            f"💰{day['withdrawals']}({day['withdrawn']}г)\n"
        )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📊 Статистика бота", callback_data="bot_stats"))
    keyboard.add(InlineKeyboardButton(text="📈 Все транзакции", callback_data="all_transactions"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="detailed_statistics"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_notifications")
async def admin_notifications_handler(callback: CallbackQuery):
    """Уведомления"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('send_notifications', False):
        await callback.answer("⛔ У вас нет прав на отправку уведомлений!", show_alert=True)
        return
    
    stats_text = (
        f"🔔 <b>Уведомления</b>\n\n"
        f"Здесь вы можете отправлять уведомления пользователям.\n\n"
        f"<b>Доступные действия:</b>\n"
        f"• Отправить всем пользователям\n"
        f"• Отправить по фильтру\n"
        f"• Просмотреть историю уведомлений\n\n"
        f"Выберите действие:"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📢 Рассылка всем", callback_data="broadcast_all"))
    keyboard.add(InlineKeyboardButton(text="🎯 Рассылка по фильтру", callback_data="broadcast_filter"))
    keyboard.add(InlineKeyboardButton(text="📋 История уведомлений", callback_data="notifications_history"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "quick_commands")
async def quick_commands_handler(callback: CallbackQuery):
    """Быстрые команды"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    stats_text = (
        f"⚡ <b>Быстрые команды</b>\n\n"
        f"<b>Доступные команды:</b>\n"
        f"• /add_balance - изменить баланс\n"
        f"• /set_referral_bonus - изменить бонус за реферала\n"
        f"• /set_welcome_bonus - изменить стартовый бонус\n"
        f"• /set_photo - установить фото\n"
        f"• /admin_menu - панель администратора\n\n"
        f"<b>Быстрые действия:</b>\n"
        f"Выберите действие ниже:"
    )
    
    await edit_with_photo(callback, 'admin', stats_text, quick_commands_keyboard())
    await callback.answer()

# ===================== ОБРАБОТЧИКИ ДЛЯ БЫСТРЫХ КОМАНД =====================

@dp.callback_query(F.data == "broadcast")
async def broadcast_handler(callback: CallbackQuery, state: FSMContext):
    """Рассылка"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('send_notifications', False):
        await callback.answer("⛔ У вас нет прав на рассылку!", show_alert=True)
        return
    
    await callback.message.answer(
        "📢 <b>Рассылка сообщения</b>\n\n"
        "Введите текст сообщения для рассылки всем пользователям:",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AdminNotificationsStates.waiting_notification_text)
    await callback.answer()

@dp.message(AdminNotificationsStates.waiting_notification_text)
async def process_broadcast_text(message: Message, state: FSMContext):
    """Обработка текста рассылки"""
    broadcast_text = message.text.strip()
    
    if not broadcast_text:
        await message.answer("❌ Текст рассылки не может быть пустым!")
        return
    
    # Получаем всех пользователей
    users = get_all_users()
    
    if not users:
        await message.answer("❌ В базе данных нет пользователей!")
        await state.clear()
        return
    
    await message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")
    
    success_count = 0
    fail_count = 0
    
    for user in users:
        user_id = user[0]
        
        try:
            await bot.send_message(
                user_id,
                f"📢 <b>Официальное уведомление от администрации:</b>\n\n"
                f"{broadcast_text}\n\n"
                f"<i>Это автоматическое сообщение, не отвечайте на него.</i>",
                parse_mode=ParseMode.HTML
            )
            success_count += 1
            await asyncio.sleep(0.1)  # Небольшая задержка, чтобы не превысить лимиты Telegram
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
            fail_count += 1
    
    result_text = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 <b>Результаты:</b>\n"
        f"• Всего пользователей: {len(users)}\n"
        f"• Успешно отправлено: {success_count}\n"
        f"• Не удалось отправить: {fail_count}\n\n"
        f"📝 <b>Текст сообщения:</b>\n"
        f"{broadcast_text[:100]}..."
    )
    
    await message.answer(result_text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "stats_today")
async def stats_today_handler(callback: CallbackQuery):
    """Статистика за сегодня"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Статистика за сегодня
    cursor.execute('SELECT new_users, referrals_count, withdrawals_count, withdrawals_amount, promo_uses FROM statistics WHERE date = ?', (today,))
    stats = cursor.fetchone()
    
    if stats:
        new_users, referrals, withdrawals, withdrawn, promo_uses = stats
        new_users = new_users or 0
        referrals = referrals or 0
        withdrawals = withdrawals or 0
        withdrawn = withdrawn or 0
        promo_uses = promo_uses or 0
    else:
        new_users = referrals = withdrawals = withdrawn = promo_uses = 0
    
    # Активные пользователи сегодня
    cursor.execute('SELECT COUNT(*) FROM users WHERE date(last_activity) = ?', (today,))
    active_users = cursor.fetchone()[0] or 0
    
    # Новые заявки на вывод
    cursor.execute('SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status = "pending" AND date(created_date) = ?', (today,))
    new_withdrawals = cursor.fetchone()
    new_withdrawals_count = new_withdrawals[0] or 0
    new_withdrawals_amount = new_withdrawals[1] or 0
    
    conn.close()
    
    stats_text = (
        f"📊 <b>Статистика за сегодня ({today})</b>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"• Новых: <b>{new_users}</b>\n"
        f"• Активных: <b>{active_users}</b>\n"
        f"• Реферальных переходов: <b>{referrals}</b>\n\n"
        f"💰 <b>Финансы:</b>\n"
        f"• Новых заявок на вывод: <b>{new_withdrawals_count}</b>\n"
        f"• Сумма новых заявок: <b>{new_withdrawals_amount}г</b>\n"
        f"• Выполнено выводов: <b>{withdrawals}</b>\n"
        f"• Выведено сегодня: <b>{withdrawn}г</b>\n\n"
        f"🎁 <b>Промокоды:</b>\n"
        f"• Активировано: <b>{promo_uses}</b>\n\n"
        f"📈 <b>Общая активность:</b> <b>{new_users + referrals + withdrawals + promo_uses}</b> действий"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="stats_today"))
    keyboard.add(InlineKeyboardButton(text="📊 Детальная статистика", callback_data="detailed_statistics"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "top_referrers")
async def top_referrers_handler(callback: CallbackQuery):
    """Топ рефереров"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    stats = get_user_statistics()
    
    stats_text = "🏆 <b>Топ 10 рефереров</b>\n\n"
    
    if not stats['top_referrers']:
        stats_text += "📭 <b>Нет данных о реферерах</b>\n\n"
    else:
        for i, (uid, username, name, ref_count, earned) in enumerate(stats['top_referrers'], 1):
            username_display = f"@{username}" if username else "без юзернейма"
            stats_text += (
                f"{i}. <b>{name}</b> ({username_display})\n"
                f"   🆔 ID: <code>{uid}</code>\n"
                f"   👥 Рефералов: <b>{ref_count}</b>\n"
                f"   💰 Заработано: <b>{earned}г</b>\n\n"
            )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="💰 Топ по балансу", callback_data="top_balance"))
    keyboard.add(InlineKeyboardButton(text="👥 Все пользователи", callback_data="user_list"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="top_referrers"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "top_balance")
async def top_balance_handler(callback: CallbackQuery):
    """Топ по балансу"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    stats = get_user_statistics()
    
    stats_text = "💰 <b>Топ 10 по балансу</b>\n\n"
    
    if not stats['top_balance']:
        stats_text += "📭 <b>Нет данных</b>\n\n"
    else:
        for i, (uid, username, name, balance) in enumerate(stats['top_balance'], 1):
            username_display = f"@{username}" if username else "без юзернейма"
            stats_text += (
                f"{i}. <b>{name}</b> ({username_display})\n"
                f"   🆔 ID: <code>{uid}</code>\n"
                f"   💰 Баланс: <b>{balance}г</b>\n\n"
            )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🏆 Топ рефереров", callback_data="top_referrers"))
    keyboard.add(InlineKeyboardButton(text="👥 Все пользователи", callback_data="user_list"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="top_balance"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

# ===================== ОБРАБОТЧИКИ ДЛЯ УПРАВЛЕНИЯ ПРОМОКОДАМИ =====================

@dp.callback_query(F.data == "create_promo_code")
async def create_promo_code_handler(callback: CallbackQuery, state: FSMContext):
    """Создание промокода"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_promo_codes', False):
        await callback.answer("⛔ У вас нет прав на создание промокодов!", show_alert=True)
        return
    
    await callback.message.answer(
        "🎁 <b>Создание промокода</b>\n\n"
        "Введите код промокода (только латинские буквы и цифры):",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AddPromoCodeStates.waiting_for_promo_code)
    await callback.answer()

@dp.message(AddPromoCodeStates.waiting_for_promo_code)
async def process_promo_code_name(message: Message, state: FSMContext):
    """Обработка названия промокода"""
    promo_code = message.text.strip().upper()
    
    # Проверяем формат промокода
    if not promo_code.isalnum():
        await message.answer(
            "❌ Промокод должен содержать только латинские буквы и цифры.\n"
            "Попробуйте еще раз:"
        )
        return
    
    # Проверяем уникальность
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM promo_codes WHERE code = ?', (promo_code,))
    if cursor.fetchone():
        conn.close()
        await message.answer(
            "❌ Промокод уже существует. Введите другой код:"
        )
        return
    conn.close()
    
    await state.update_data(promo_code=promo_code)
    await state.set_state(AddPromoCodeStates.waiting_for_promo_amount)
    
    await message.answer(
        f"✅ Код промокода: <b>{promo_code}</b>\n\n"
        f"Введите сумму бонуса (например: 100):",
        parse_mode=ParseMode.HTML
    )

@dp.message(AddPromoCodeStates.waiting_for_promo_amount)
async def process_promo_amount(message: Message, state: FSMContext):
    """Обработка суммы промокода"""
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Неверный формат суммы. Введите число (например: 100):")
        return
    
    await state.update_data(amount=amount)
    await state.set_state(AddPromoCodeStates.waiting_for_promo_uses)
    
    await message.answer(
        f"✅ Сумма бонуса: <b>{amount}г</b>\n\n"
        f"Введите максимальное количество использований (например: 10):",
        parse_mode=ParseMode.HTML
    )

@dp.message(AddPromoCodeStates.waiting_for_promo_uses)
async def process_promo_uses(message: Message, state: FSMContext):
    """Обработка количества использований"""
    try:
        max_uses = int(message.text.strip())
        if max_uses <= 0:
            await message.answer("❌ Количество должно быть больше 0. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Неверный формат. Введите целое число (например: 10):")
        return
    
    await state.update_data(max_uses=max_uses)
    await state.set_state(AddPromoCodeStates.waiting_for_promo_expires)
    
    await message.answer(
        f"✅ Максимальное использование: <b>{max_uses} раз</b>\n\n"
        f"Введите срок действия в днях (например: 30):",
        parse_mode=ParseMode.HTML
    )

@dp.message(AddPromoCodeStates.waiting_for_promo_expires)
async def process_promo_expires(message: Message, state: FSMContext):
    """Обработка срока действия"""
    try:
        expires_days = int(message.text.strip())
        if expires_days <= 0:
            await message.answer("❌ Срок должен быть больше 0 дней. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число дней (например: 30):")
        return
    
    data = await state.get_data()
    promo_code = data.get('promo_code')
    amount = data.get('amount')
    max_uses = data.get('max_uses')
    
    # Создаем промокод
    success = create_promo_code(
        code=promo_code,
        amount=amount,
        max_uses=max_uses,
        created_by=message.from_user.id,
        expires_days=expires_days,
        min_balance=0,
        for_new_users_only=0
    )
    
    if success:
        result_text = (
            f"✅ <b>Промокод успешно создан!</b>\n\n"
            f"🎁 <b>Код:</b> <code>{promo_code}</code>\n"
            f"💰 <b>Сумма:</b> {amount}г\n"
            f"🔄 <b>Использований:</b> {max_uses} раз\n"
            f"📅 <b>Срок действия:</b> {expires_days} дней\n\n"
            f"Промокод активен и готов к использованию!"
        )
    else:
        result_text = "❌ Ошибка создания промокода!"
    
    await message.answer(result_text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "promo_codes_list")
async def promo_codes_list_handler(callback: CallbackQuery):
    """Список промокодов"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_promo_codes', False):
        await callback.answer("⛔ У вас нет прав на просмотр промокодов!", show_alert=True)
        return
    
    promos = get_promo_codes(active_only=False)
    
    if not promos:
        promos_text = "📭 <b>Нет созданных промокодов</b>"
    else:
        promos_text = "🎁 <b>Список всех промокодов</b>\n\n"
        
        for promo in promos:
            promo_id, code, amount, max_uses, used_count, created_by, created_date, expires_date, is_active, min_balance, for_new_users_only = promo
            
            status = "🟢" if is_active == 1 else "🔴"
            expires_info = f"до {expires_date[:10]}" if expires_date else "без срока"
            
            # Получаем информацию о создателе
            creator = get_user(created_by)
            creator_name = creator[2] if creator else "Неизвестно"
            
            promos_text += (
                f"{status} <b>{code}</b>\n"
                f"   💰 Сумма: {amount}г\n"
                f"   🎯 Использовано: {used_count}/{max_uses}\n"
                f"   📅 {expires_info}\n"
                f"   👤 Создал: {creator_name}\n\n"
            )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="➕ Создать промокод", callback_data="create_promo_code"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить список", callback_data="promo_codes_list"))
    keyboard.add(InlineKeyboardButton(text="🗑 Удалить промокод", callback_data="delete_promo_code_menu"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', promos_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "delete_promo_code_menu")
async def delete_promo_code_menu_handler(callback: CallbackQuery):
    """Меню удаления промокода"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_promo_codes', False):
        await callback.answer("⛔ У вас нет прав на удаление промокодов!", show_alert=True)
        return
    
    promos = get_promo_codes(active_only=False)
    
    if not promos:
        await callback.answer("❌ Нет промокодов для удаления!", show_alert=True)
        return
    
    promos_text = "🗑 <b>Удаление промокода</b>\n\n"
    promos_text += "Введите код промокода для удаления:\n\n"
    promos_text += "<b>Доступные промокоды:</b>\n"
    
    for promo in promos[:10]:  # Показываем первые 10
        code = promo[1]
        amount = promo[2]
        used_count = promo[4]
        max_uses = promo[3]
        promos_text += f"• <code>{code}</code> - {amount}г ({used_count}/{max_uses})\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="↩️ Назад к списку", callback_data="promo_codes_list"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await callback.message.answer(promos_text, parse_mode=ParseMode.HTML, reply_markup=keyboard.as_markup())
    await callback.answer()

@dp.message(Command("delete_promo"))
async def delete_promo_command(message: Message):
    """Команда удаления промокода"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_promo_codes', False):
        await message.answer("⛔ У вас нет прав на удаление промокодов!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/delete_promo КОД_ПРОМОКОДА</code>\n\n"
                "Пример:\n"
                "<code>/delete_promo SUMMER2024</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        promo_code = parts[1].upper()
        success = delete_promo_code(promo_code)
        
        if success:
            await message.answer(f"✅ Промокод <code>{promo_code}</code> удален!", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ Промокод <code>{promo_code}</code> не найден!", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка удаления промокода: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data.startswith("set_photo_"))
async def quick_set_photo_handler(callback: CallbackQuery, state: FSMContext):
    """Быстрая установка фото по типу"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_photos', False):
        await callback.answer("⛔ У вас нет прав на управление фото!", show_alert=True)
        return
    
    photo_type = callback.data.split("_")[2]  # Получаем тип фото из callback_data
    
    photo_names = {
        'welcome': 'Приветствие',
        'profile': 'Профиль',
        'referral': 'Реферальная система',
        'admin': 'Админ-панель',
        'withdrawal': 'Вывод средств',
        'promo': 'Промокоды',
        'stats': 'Статистика'
    }
    
    photo_name = photo_names.get(photo_type, photo_type)
    
    await callback.message.answer(
        f"📸 <b>Установка фото для {photo_name}</b>\n\n"
        f"Отправьте URL фото (ссылку) или прикрепите фото.\n\n"
        f"<i>Поддерживаются ссылки на изображения.</i>",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AddPhotoStates.waiting_for_photo)
    await state.update_data(photo_type=photo_type)
    await callback.answer()

# ===================== ОБРАБОТЧИКИ ДЛЯ ДРУГИХ КНОПОК =====================

@dp.callback_query(F.data == "add_channel")
async def add_channel_handler(callback: CallbackQuery, state: FSMContext):
    """Добавление канала"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_channels', False):
        await callback.answer("⛔ У вас нет прав на управление каналами!", show_alert=True)
        return
    
    await callback.message.answer(
        "📢 <b>Добавление обязательного канала</b>\n\n"
        "Введите ID канала (например: -1001234567890):",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AddChannelStates.waiting_for_channel_id)
    await callback.answer()

@dp.message(AddChannelStates.waiting_for_channel_id)
async def process_channel_id(message: Message, state: FSMContext):
    """Обработка ID канала"""
    try:
        channel_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число (например: -1001234567890):")
        return
    
    await state.update_data(channel_id=channel_id)
    await state.set_state(AddChannelStates.waiting_for_channel_username)
    
    await message.answer(
        f"✅ ID канала: <code>{channel_id}</code>\n\n"
        f"Введите юзернейм канала (без @, например: k1lossez):",
        parse_mode=ParseMode.HTML
    )

@dp.message(AddChannelStates.waiting_for_channel_username)
async def process_channel_username(message: Message, state: FSMContext):
    """Обработка юзернейма канала"""
    username = message.text.strip().replace('@', '')
    
    if not username:
        await message.answer("❌ Юзернейм не может быть пустым. Попробуйте еще раз:")
        return
    
    await state.update_data(channel_username=username)
    await state.set_state(AddChannelStates.waiting_for_channel_name)
    
    await message.answer(
        f"✅ Юзернейм: @{username}\n\n"
        f"Введите название канала (например: K1LOSS EZ):",
        parse_mode=ParseMode.HTML
    )

@dp.message(AddChannelStates.waiting_for_channel_name)
async def process_channel_name(message: Message, state: FSMContext):
    """Обработка названия канала"""
    channel_name = message.text.strip()
    
    if not channel_name:
        await message.answer("❌ Название не может быть пустым. Попробуйте еще раз:")
        return
    
    await state.update_data(channel_name=channel_name)
    await state.set_state(AddChannelStates.waiting_for_invite_link)
    
    await message.answer(
        f"✅ Название: {channel_name}\n\n"
        f"Введите ссылку-приглашение (например: https://t.me/k1lossez):",
        parse_mode=ParseMode.HTML
    )

@dp.message(AddChannelStates.waiting_for_invite_link)
async def process_channel_invite_link(message: Message, state: FSMContext):
    """Обработка ссылки-приглашения"""
    invite_link = message.text.strip()
    
    if not (invite_link.startswith('https://t.me/') or invite_link.startswith('t.me/')):
        await message.answer("❌ Неверный формат ссылки. Должна начинаться с https://t.me/ или t.me/\nПопробуйте еще раз:")
        return
    
    data = await state.get_data()
    channel_id = data.get('channel_id')
    channel_username = data.get('channel_username')
    channel_name = data.get('channel_name')
    
    # Создаем объект канала
    channel_data = {
        "id": channel_id,
        "username": channel_username,
        "name": channel_name,
        "invite_link": invite_link if invite_link.startswith('https://') else f"https://{invite_link}"
    }
    
    # Добавляем канал
    success = add_channel_to_db(channel_data)
    
    if success:
        result_text = (
            f"✅ <b>Канал успешно добавлен!</b>\n\n"
            f"📢 <b>Название:</b> {channel_name}\n"
            f"🆔 <b>ID:</b> <code>{channel_id}</code>\n"
            f"📧 <b>Юзернейм:</b> @{channel_username}\n"
            f"🔗 <b>Ссылка:</b> {invite_link}\n\n"
            f"Теперь пользователи должны подписаться на этот канал."
        )
    else:
        result_text = "❌ Ошибка добавления канала!"
    
    await message.answer(result_text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "remove_channel")
async def remove_channel_handler(callback: CallbackQuery):
    """Удаление канала"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_channels', False):
        await callback.answer("⛔ У вас нет прав на управление каналами!", show_alert=True)
        return
    
    if not REQUIRED_CHANNELS:
        await callback.answer("❌ Нет каналов для удаления!", show_alert=True)
        return
    
    channels_text = "🗑 <b>Удаление канала</b>\n\n"
    channels_text += "Введите ID канала для удаления:\n\n"
    channels_text += "<b>Текущие каналы:</b>\n"
    
    for channel in REQUIRED_CHANNELS:
        if isinstance(channel, dict):
            channels_text += f"• <code>{channel.get('id')}</code> - {channel.get('name', 'Без имени')}\n"
        else:
            channels_text += f"• <code>{channel}</code>\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="↩️ Назад к списку", callback_data="manage_channels"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await callback.message.answer(channels_text, parse_mode=ParseMode.HTML, reply_markup=keyboard.as_markup())
    await callback.answer()

@dp.message(Command("remove_channel"))
async def remove_channel_command(message: Message):
    """Команда удаления канала"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_channels', False):
        await message.answer("⛔ У вас нет прав на управление каналами!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/remove_channel ID_КАНАЛА</code>\n\n"
                "Пример:\n"
                "<code>/remove_channel -1003525909692</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        channel_id = int(parts[1])
        success = remove_channel_from_db(channel_id)
        
        if success:
            await message.answer(f"✅ Канал <code>{channel_id}</code> удален!", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ Канал <code>{channel_id}</code> не найден!", parse_mode=ParseMode.HTML)
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")
    except Exception as e:
        logger.error(f"Ошибка удаления канала: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "add_admin")
async def add_admin_handler(callback: CallbackQuery, state: FSMContext):
    """Добавление администратора"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    if not is_super_admin(user_id):
        await callback.answer("⛔ Только суперадмин может добавлять админов!", show_alert=True)
        return
    
    await callback.message.answer(
        "👑 <b>Добавление администратора</b>\n\n"
        "Введите ID пользователя (например: 1234567890):",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(AddAdminStates.waiting_for_admin_id)
    await callback.answer()

@dp.message(AddAdminStates.waiting_for_admin_id)
async def process_admin_id(message: Message, state: FSMContext):
    """Обработка ID администратора"""
    try:
        admin_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число (например: 1234567890):")
        return
    
    # Проверяем, существует ли пользователь
    user = get_user(admin_id)
    if not user:
        await message.answer(f"❌ Пользователь с ID <code>{admin_id}</code> не найден в базе данных!", parse_mode=ParseMode.HTML)
        await state.clear()
        return
    
    # Добавляем админа
    success = add_admin_to_db(admin_id, is_super=False, added_by=message.from_user.id)
    
    if success:
        user_name = user[2]
        result_text = (
            f"✅ <b>Администратор успешно добавлен!</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_name}\n"
            f"🆔 <b>ID:</b> <code>{admin_id}</code>\n"
            f"👑 <b>Статус:</b> Администратор\n\n"
            f"Теперь пользователь имеет доступ к панели администратора."
        )
        
        # Уведомляем нового админа
        try:
            await bot.send_message(
                admin_id,
                f"👑 <b>Вас назначили администратором!</b>\n\n"
                f"Теперь у вас есть доступ к панели администратора.\n"
                f"Для входа используйте команду /admin_menu",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления нового админа: {e}")
            result_text += "\n\n⚠️ Не удалось отправить уведомление новому администратору."
    else:
        result_text = f"❌ Пользователь <code>{admin_id}</code> уже является администратором!"
    
    await message.answer(result_text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "remove_admin")
async def remove_admin_handler(callback: CallbackQuery):
    """Удаление администратора"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    if not is_super_admin(user_id):
        await callback.answer("⛔ Только суперадмин может удалять админов!", show_alert=True)
        return
    
    admins = get_all_admins()
    
    if len(admins) <= 1:
        await callback.answer("❌ Нельзя удалить последнего администратора!", show_alert=True)
        return
    
    admins_text = "🗑 <b>Удаление администратора</b>\n\n"
    admins_text += "Введите ID администратора для удаления:\n\n"
    admins_text += "<b>Текущие администраторы:</b>\n"
    
    for admin in admins:
        admin_id, is_super, added_date, added_by, permissions_json = admin
        
        # Получаем информацию об администраторе
        user_info = get_user(admin_id)
        if user_info:
            name = user_info[2]
            username = f"@{user_info[1]}" if user_info[1] else "без юзернейма"
        else:
            name = "Неизвестно"
            username = "без юзернейма"
        
        status = "🟢 Суперадмин" if is_super == 1 else "🔵 Админ"
        admins_text += f"• <code>{admin_id}</code> - {name} {status}\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="↩️ Назад к списку", callback_data="manage_admins"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await callback.message.answer(admins_text, parse_mode=ParseMode.HTML, reply_markup=keyboard.as_markup())
    await callback.answer()

@dp.message(Command("remove_admin"))
async def remove_admin_command(message: Message):
    """Команда удаления администратора"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    if not is_super_admin(user_id):
        await message.answer("⛔ Только суперадмин может удалять админов!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/remove_admin ID_АДМИНИСТРАТОРА</code>\n\n"
                "Пример:\n"
                "<code>/remove_admin 1234567890</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        admin_id = int(parts[1])
        
        # Нельзя удалить себя
        if admin_id == user_id:
            await message.answer("❌ Нельзя удалить самого себя!")
            return
        
        # Нельзя удалить суперадмина (если вы не суперадмин)
        if is_super_admin(admin_id) and not is_super_admin(user_id):
            await message.answer("❌ Нельзя удалить суперадмина!")
            return
        
        success = remove_admin_from_db(admin_id)
        
        if success:
            await message.answer(f"✅ Администратор <code>{admin_id}</code> удален!", parse_mode=ParseMode.HTML)
            
            # Уведомляем удаленного админа
            try:
                await bot.send_message(
                    admin_id,
                    f"👑 <b>Ваши права администратора были отозваны!</b>\n\n"
                    f"Теперь у вас нет доступа к панели администратора.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления удаленного админа: {e}")
        else:
            await message.answer(f"❌ Администратор <code>{admin_id}</code> не найден!", parse_mode=ParseMode.HTML)
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")
    except Exception as e:
        logger.error(f"Ошибка удаления администратора: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "withdrawal_pending")
async def withdrawal_pending_handler(callback: CallbackQuery):
    """Ожидающие заявки на вывод"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_withdrawals', False):
        await callback.answer("⛔ У вас нет прав на управление заявками на вывод!", show_alert=True)
        return
    
    withdrawals = get_withdrawals(status='pending', limit=20)
    
    if not withdrawals:
        stats_text = "✅ <b>Нет ожидающих заявок на вывод</b>"
    else:
        stats_text = f"⏳ <b>Ожидающие заявки на вывод ({len(withdrawals)})</b>\n\n"
        
        total_amount = 0
        for wd in withdrawals:
            wd_id, wd_user_id, skin_name, pattern, _, amount, status, _, _, created_date, _, _, _ = wd
            
            # Получаем информацию о пользователе
            user = get_user(wd_user_id)
            if user:
                user_name = user[2]
                user_username = f"@{user[1]}" if user[1] else "без юзернейма"
            else:
                user_name = "Неизвестно"
                user_username = "без юзернейма"
            
            total_amount += amount
            
            stats_text += (
                f"📦 <b>Заявка #{wd_id}</b>\n"
                f"👤 {user_name} ({user_username})\n"
                f"🆔 ID: <code>{wd_user_id}</code>\n"
                f"💰 Сумма: {amount}г\n"
                f"🎮 Скин: {skin_name[:20]}...\n"
                f"🔢 Паттерн: {pattern}\n"
                f"📅 Дата: {created_date[:16]}\n\n"
            )
        
        stats_text += f"💰 <b>Общая сумма:</b> <b>{total_amount}г</b>\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="withdrawal_pending"))
    keyboard.add(InlineKeyboardButton(text="📦 Все заявки", callback_data="withdrawal_requests"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "withdrawal_completed")
async def withdrawal_completed_handler(callback: CallbackQuery):
    """Выполненные заявки на вывод"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_withdrawals', False):
        await callback.answer("⛔ У вас нет прав на управление заявками на вывод!", show_alert=True)
        return
    
    withdrawals = get_withdrawals(status='completed', limit=20)
    
    if not withdrawals:
        stats_text = "📭 <b>Нет выполненных заявок на вывод</b>"
    else:
        stats_text = f"✅ <b>Выполненные заявки на вывод ({len(withdrawals)})</b>\n\n"
        
        total_amount = 0
        for wd in withdrawals[:10]:  # Показываем первые 10
            wd_id, wd_user_id, skin_name, _, _, amount, status, admin_id, admin_username, _, processed_date, _, _ = wd
            
            # Получаем информацию о пользователе
            user = get_user(wd_user_id)
            if user:
                user_name = user[2]
            else:
                user_name = "Неизвестно"
            
            total_amount += amount
            
            stats_text += (
                f"✅ <b>#{wd_id}</b> - {amount}г\n"
                f"👤 {user_name} | 👷 {admin_username or 'Неизвестно'}\n"
                f"📅 {processed_date[:10] if processed_date else 'Неизвестно'}\n\n"
            )
        
        stats_text += f"💰 <b>Всего выплачено:</b> <b>{total_amount}г</b>\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="withdrawal_completed"))
    keyboard.add(InlineKeyboardButton(text="📦 Все заявки", callback_data="withdrawal_requests"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "withdrawal_rejected")
async def withdrawal_rejected_handler(callback: CallbackQuery):
    """Отклоненные заявки на вывод"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_withdrawals', False):
        await callback.answer("⛔ У вас нет прав на управление заявками на вывод!", show_alert=True)
        return
    
    withdrawals = get_withdrawals(status='rejected', limit=20)
    
    if not withdrawals:
        stats_text = "📭 <b>Нет отклоненных заявок на вывод</b>"
    else:
        stats_text = f"❌ <b>Отклоненные заявки на вывод ({len(withdrawals)})</b>\n\n"
        
        for wd in withdrawals[:10]:  # Показываем первые 10
            wd_id, wd_user_id, skin_name, _, _, amount, status, admin_id, admin_username, _, processed_date, _, decline_reason = wd
            
            # Получаем информацию о пользователе
            user = get_user(wd_user_id)
            if user:
                user_name = user[2]
            else:
                user_name = "Неизвестно"
            
            stats_text += (
                f"❌ <b>#{wd_id}</b> - {amount}г\n"
                f"👤 {user_name} | 👷 {admin_username or 'Неизвестно'}\n"
                f"📝 Причина: {decline_reason[:30]}...\n"
                f"📅 {processed_date[:10] if processed_date else 'Неизвестно'}\n\n"
            )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="withdrawal_rejected"))
    keyboard.add(InlineKeyboardButton(text="📦 Все заявки", callback_data="withdrawal_requests"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "withdrawal_stats")
async def withdrawal_stats_handler(callback: CallbackQuery):
    """Статистика выводов"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    # Статистика за последние 30 дней
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Общая статистика
    cursor.execute('SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status = "completed"')
    total_stats = cursor.fetchone()
    total_count = total_stats[0] or 0
    total_amount = total_stats[1] or 0
    
    cursor.execute('SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status = "pending"')
    pending_stats = cursor.fetchone()
    pending_count = pending_stats[0] or 0
    pending_amount = pending_stats[1] or 0
    
    cursor.execute('SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status = "rejected"')
    rejected_stats = cursor.fetchone()
    rejected_count = rejected_stats[0] or 0
    rejected_amount = rejected_stats[1] or 0
    
    # Статистика за сегодня
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status = "completed" AND date(processed_date) = ?', (today,))
    today_stats = cursor.fetchone()
    today_count = today_stats[0] or 0
    today_amount = today_stats[1] or 0
    
    conn.close()
    
    stats_text = (
        f"📊 <b>Статистика выводов</b>\n\n"
        f"📈 <b>Общая статистика:</b>\n"
        f"• Всего выполнено: <b>{total_count}</b> заявок\n"
        f"• Выплачено всего: <b>{total_amount}г</b>\n"
        f"• Ожидают обработки: <b>{pending_count}</b> заявок\n"
        f"• На сумму: <b>{pending_amount}г</b>\n"
        f"• Отклонено: <b>{rejected_count}</b> заявок\n"
        f"• На сумму: <b>{rejected_amount}г</b>\n\n"
        f"📅 <b>Сегодня ({today}):</b>\n"
        f"• Выполнено: <b>{today_count}</b> заявок\n"
        f"• Выплачено: <b>{today_amount}г</b>"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="withdrawal_stats"))
    keyboard.add(InlineKeyboardButton(text="📦 Все заявки", callback_data="withdrawal_requests"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

# ===================== ОБРАБОТЧИКИ ДЛЯ НАСТРОЕК БОНУСОВ =====================

@dp.callback_query(F.data == "set_referral_bonus")
async def set_referral_bonus_handler(callback: CallbackQuery, state: FSMContext):
    """Установка бонуса за реферала"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await callback.answer("⛔ У вас нет прав на изменение настроек!", show_alert=True)
        return
    
    current_bonus = get_referral_bonus()
    
    await callback.message.answer(
        f"💰 <b>Изменение бонуса за реферала</b>\n\n"
        f"Текущее значение: <b>{current_bonus}г</b>\n\n"
        f"Введите новое значение (например: 500):",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(BonusSettingsStates.waiting_for_referral_bonus)
    await callback.answer()

@dp.message(BonusSettingsStates.waiting_for_referral_bonus)
async def process_referral_bonus(message: Message, state: FSMContext):
    """Обработка нового бонуса за реферала"""
    try:
        new_bonus = float(message.text.strip())
        if new_bonus < 0:
            await message.answer("❌ Сумма должна быть положительной. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 500):")
        return
    
    old_bonus = get_referral_bonus()
    update_setting('referral_bonus', str(new_bonus))
    
    result_text = (
        f"✅ <b>Бонус за реферала изменен!</b>\n\n"
        f"💰 <b>Старое значение:</b> {old_bonus}г\n"
        f"💰 <b>Новое значение:</b> {new_bonus}г\n\n"
        f"Изменение вступит в силу для новых рефералов."
    )
    
    await message.answer(result_text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "set_welcome_bonus")
async def set_welcome_bonus_handler(callback: CallbackQuery, state: FSMContext):
    """Установка стартового бонуса"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await callback.answer("⛔ У вас нет прав на изменение настроек!", show_alert=True)
        return
    
    current_bonus = get_welcome_bonus()
    
    await callback.message.answer(
        f"🎁 <b>Изменение стартового бонуса</b>\n\n"
        f"Текущее значение: <b>{current_bonus}г</b>\n\n"
        f"Введите новое значение (например: 100):",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(BonusSettingsStates.waiting_for_welcome_bonus)
    await callback.answer()

@dp.message(BonusSettingsStates.waiting_for_welcome_bonus)
async def process_welcome_bonus(message: Message, state: FSMContext):
    """Обработка нового стартового бонуса"""
    try:
        new_bonus = float(message.text.strip())
        if new_bonus < 0:
            await message.answer("❌ Сумма должна быть положительной. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 100):")
        return
    
    old_bonus = get_welcome_bonus()
    update_setting('welcome_bonus', str(new_bonus))
    
    result_text = (
        f"✅ <b>Стартовый бонус изменен!</b>\n\n"
        f"🎁 <b>Старое значение:</b> {old_bonus}г\n"
        f"🎁 <b>Новое значение:</b> {new_bonus}г\n\n"
        f"Изменение вступит в силу для новых пользователей."
    )
    
    await message.answer(result_text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "set_min_withdrawal")
async def set_min_withdrawal_handler(callback: CallbackQuery, state: FSMContext):
    """Установка минимального вывода"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await callback.answer("⛔ У вас нет прав на изменение настроек!", show_alert=True)
        return
    
    current_min = float(get_setting('min_withdrawal', '100'))
    
    await callback.message.answer(
        f"💸 <b>Изменение минимального вывода</b>\n\n"
        f"Текущее значение: <b>{current_min}г</b>\n\n"
        f"Введите новое значение (например: 50):",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(BonusSettingsStates.waiting_for_min_withdrawal)
    await callback.answer()

@dp.message(BonusSettingsStates.waiting_for_min_withdrawal)
async def process_min_withdrawal(message: Message, state: FSMContext):
    """Обработка нового минимального вывода"""
    try:
        new_min = float(message.text.strip())
        if new_min < 0:
            await message.answer("❌ Сумма должна быть положительной. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: 50):")
        return
    
    old_min = float(get_setting('min_withdrawal', '100'))
    update_setting('min_withdrawal', str(new_min))
    
    result_text = (
        f"✅ <b>Минимальный вывод изменен!</b>\n\n"
        f"💸 <b>Старое значение:</b> {old_min}г\n"
        f"💸 <b>Новое значение:</b> {new_min}г\n\n"
        f"Пользователи смогут выводить средства от {new_min}г."
    )
    
    await message.answer(result_text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data == "set_withdrawal_fee")
async def set_withdrawal_fee_handler(callback: CallbackQuery, state: FSMContext):
    """Установка комиссии за вывод"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await callback.answer("⛔ У вас нет прав на изменение настроек!", show_alert=True)
        return
    
    current_fee = float(get_setting('withdrawal_fee', '0'))
    
    await callback.message.answer(
        f"📉 <b>Изменение комиссии за вывод</b>\n\n"
        f"Текущее значение: <b>{current_fee}%</b>\n\n"
        f"Введите новое значение (например: 5):",
        parse_mode=ParseMode.HTML
    )
    
    await state.update_data(setting_type='withdrawal_fee')
    await callback.answer()

@dp.message(F.text, lambda message: message.from_user.id in ADMIN_IDS)
async def process_settings_update(message: Message, state: FSMContext):
    """Обработка обновления настроек"""
    try:
        # Проверяем, не является ли это командой
        if message.text.startswith('/'):
            return
            
        data = await state.get_data()
        setting_type = data.get('setting_type')
        
        if not setting_type:
            return
            
        try:
            new_value = float(message.text.strip())
            if new_value < 0:
                await message.answer("❌ Сумма должна быть положительной.")
                return
                
            if setting_type == 'withdrawal_fee':
                old_value = float(get_setting('withdrawal_fee', '0'))
                update_setting('withdrawal_fee', str(new_value))
                result_text = (
                    f"✅ <b>Комиссия за вывод изменена!</b>\n\n"
                    f"📉 <b>Старое значение:</b> {old_value}%\n"
                    f"📉 <b>Новое значение:</b> {new_value}%\n\n"
                    f"Комиссия будет применяться ко всем новым выводам."
                )
            elif setting_type == 'multi_level':
                old_value = get_setting('multi_level_enabled', '0')
                new_bool = '1' if new_value > 0 else '0'
                update_setting('multi_level_enabled', new_bool)
                status = "включена" if new_bool == '1' else "выключена"
                result_text = f"✅ <b>Многоуровневая система {status}!</b>"
                
        except ValueError:
            await message.answer("❌ Неверный формат. Введите число.")
            return
            
        await message.answer(result_text, parse_mode=ParseMode.HTML)
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка обновления настроек: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "subscription_stats")
async def subscription_stats_handler(callback: CallbackQuery):
    """Статистика подписок"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    # Получаем всех пользователей
    users = get_all_users()
    
    if not users:
        stats_text = "📭 <b>Нет пользователей для проверки</b>"
    else:
        stats_text = "📊 <b>Статистика подписок</b>\n\n"
        
        checked_users = 0
        subscribed_users = 0
        
        # Проверяем подписки для первых 50 пользователей (чтобы не перегружать бота)
        for user in users[:50]:
            user_id_to_check = user[0]
            not_subscribed = await check_all_subscriptions(user_id_to_check)
            
            checked_users += 1
            if not not_subscribed:
                subscribed_users += 1
        
        percent = (subscribed_users / checked_users * 100) if checked_users > 0 else 0
        
        stats_text += (
            f"👥 <b>Проверено пользователей:</b> {checked_users}\n"
            f"✅ <b>Подписаны на все каналы:</b> {subscribed_users}\n"
            f"📈 <b>Процент подписок:</b> {percent:.1f}%\n\n"
            f"<i>Проверено только первые {min(50, len(users))} пользователей.</i>"
        )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="subscription_stats"))
    keyboard.add(InlineKeyboardButton(text="📢 Управление каналами", callback_data="manage_channels"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "refresh_db")
async def refresh_db_handler(callback: CallbackQuery):
    """Обновление базы данных"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    # Перезагружаем данные из БД
    load_channels_from_db()
    load_admins_from_db()
    
    await callback.answer("✅ Данные из БД обновлены!", show_alert=True)

@dp.callback_query(F.data == "bot_settings")
async def bot_settings_handler(callback: CallbackQuery):
    """Настройки бота"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await callback.answer("⛔ У вас нет прав на изменение настроек!", show_alert=True)
        return
    
    # Получаем текущие настройки
    bot_name = get_setting('bot_name', 'K1LOSS EZ Referral Bot')
    currency_name = get_setting('currency_name', 'голда')
    currency_emoji = get_setting('currency_emoji', '💰')
    support_username = get_setting('support_username', 'не указан')
    maintenance_mode = get_setting('maintenance_mode', '0') == '1'
    auto_check = get_setting('auto_check_subscriptions', '1') == '1'
    
    settings_text = (
        f"⚙️ <b>Настройки бота</b>\n\n"
        f"🤖 <b>Имя бота:</b> {bot_name}\n"
        f"💰 <b>Валюта:</b> {currency_name} {currency_emoji}\n"
        f"👤 <b>Поддержка:</b> @{support_username}\n"
        f"🛠 <b>Режим обслуживания:</b> {'✅ Включен' if maintenance_mode else '❌ Выключен'}\n"
        f"✅ <b>Автопроверка подписок:</b> {'✅ Включена' if auto_check else '❌ Выключена'}\n\n"
        f"<b>Для изменения используйте команды:</b>\n"
        f"• /set_bot_name - изменить имя бота\n"
        f"• /set_currency - изменить валюту\n"
        f"• /set_support - изменить поддержку\n"
        f"• /toggle_maintenance - включить/выключить режим обслуживания\n"
        f"• /toggle_auto_check - включить/выключить автопроверку подписок"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="bot_settings"))
    keyboard.add(InlineKeyboardButton(text="⚙️ Настройки бонусов", callback_data="bonus_settings"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', settings_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "search_user")
async def search_user_handler(callback: CallbackQuery):
    """Поиск пользователя"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    await callback.message.answer(
        "🔍 <b>Поиск пользователя</b>\n\n"
        "Введите ID пользователя, юзернейм или имя:",
        parse_mode=ParseMode.HTML
    )
    
    await callback.answer()

@dp.message(Command("find_user"))
async def find_user_command(message: Message):
    """Команда поиска пользователя"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/find_user поисковый_запрос</code>\n\n"
                "Примеры:\n"
                "<code>/find_user 1234567890</code>\n"
                "<code>/find_user username</code>\n"
                "<code>/find_user Имя Фамилия</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        search_term = ' '.join(parts[1:])
        results = search_users(search_term)
        
        if not results:
            await message.answer(f"❌ Пользователи по запросу '{search_term}' не найдены!")
            return
        
        results_text = f"🔍 <b>Результаты поиска '{search_term}'</b>\n\n"
        
        for user in results[:10]:  # Показываем первые 10 результатов
            user_id, username, full_name, balance, referrals_count, _, join_date, _, _, total_earned, total_withdrawn = user
            
            username_display = f"@{username}" if username else "без юзернейма"
            join_date_formatted = join_date[:10] if join_date else "Неизвестно"
            
            results_text += (
                f"👤 <b>{full_name}</b> ({username_display})\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"💰 Баланс: {balance}г\n"
                f"👥 Рефералов: {referrals_count}\n"
                f"📅 Регистрация: {join_date_formatted}\n\n"
            )
        
        if len(results) > 10:
            results_text += f"<i>Показано 10 из {len(results)} результатов</i>"
        
        keyboard = InlineKeyboardBuilder()
        if len(results) == 1:
            # Если найден только один пользователь, добавляем кнопки быстрых действий
            single_user_id = results[0][0]
            keyboard.add(InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"change_user_balance_{single_user_id}"))
            keyboard.add(InlineKeyboardButton(text="👁 Просмотр профиля", callback_data=f"view_user_{single_user_id}"))
        
        keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
        keyboard.adjust(2)
        
        await message.answer(results_text, parse_mode=ParseMode.HTML, reply_markup=keyboard.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка поиска пользователя: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "user_list")
async def user_list_handler(callback: CallbackQuery):
    """Список пользователей"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    users = get_all_users(limit=50)
    
    if not users:
        stats_text = "📭 <b>Нет пользователей в базе данных</b>"
    else:
        stats_text = f"👥 <b>Последние 50 пользователей</b>\n\n"
        
        for i, user in enumerate(users[:20], 1):  # Показываем первые 20
            user_id, username, full_name, balance, referrals_count, _, join_date, _, _, total_earned, total_withdrawn = user
            
            username_display = f"@{username}" if username else "без юзернейма"
            join_date_formatted = join_date[:10] if join_date else "Неизвестно"
            
            stats_text += (
                f"{i}. <b>{full_name}</b> ({username_display})\n"
                f"   🆔 <code>{user_id}</code> | 💰 {balance}г\n"
                f"   👥 {referrals_count} реф. | 📅 {join_date_formatted}\n\n"
            )
        
        if len(users) > 20:
            stats_text += f"<i>Показано 20 из {len(users)} пользователей</i>\n\n"
        
        # Общая статистика
        total_balance = sum([user[3] for user in users])
        total_referrals = sum([user[4] for user in users])
        
        stats_text += (
            f"📊 <b>Статистика по списку:</b>\n"
            f"• Всего: {len(users)} пользователей\n"
            f"• Общий баланс: {total_balance}г\n"
            f"• Всего рефералов: {total_referrals}"
        )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔍 Поиск пользователя", callback_data="search_user"))
    keyboard.add(InlineKeyboardButton(text="🏆 Топ рефереров", callback_data="top_referrers"))
    keyboard.add(InlineKeyboardButton(text="💰 Топ по балансу", callback_data="top_balance"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="user_list"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "detailed_user_stats")
async def detailed_user_stats_handler(callback: CallbackQuery):
    """Детальная статистика пользователей"""
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    
    # Получаем статистику за последние 30 дней
    conn = sqlite3.connect('referral_bot.db')
    cursor = conn.cursor()
    
    # Статистика регистраций
    cursor.execute('''
    SELECT date, COUNT(*) as count 
    FROM users 
    WHERE date(join_date) >= date('now', '-30 days') 
    GROUP BY date(join_date) 
    ORDER BY date(join_date) DESC
    LIMIT 15
    ''')
    registrations = cursor.fetchall()
    
    # Статистика активности
    cursor.execute('''
    SELECT date(last_activity) as date, COUNT(*) as count 
    FROM users 
    WHERE date(last_activity) >= date('now', '-30 days') 
    GROUP BY date(last_activity) 
    ORDER BY date(last_activity) DESC
    LIMIT 15
    ''')
    activity = cursor.fetchall()
    
    # Группировка по дням недели
    cursor.execute('''
    SELECT strftime('%w', join_date) as weekday, COUNT(*) as count 
    FROM users 
    WHERE date(join_date) >= date('now', '-90 days') 
    GROUP BY strftime('%w', join_date)
    ''')
    weekday_stats = cursor.fetchall()
    
    conn.close()
    
    days_of_week = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
    
    stats_text = (
        f"📊 <b>Детальная статистика пользователей</b>\n\n"
        f"📅 <b>Регистрации за 30 дней:</b>\n"
    )
    
    if registrations:
        for date_str, count in registrations[:10]:  # Показываем последние 10 дней
            if date_str:
                stats_text += f"• {date_str}: {count} регистраций\n"
    else:
        stats_text += "Нет данных о регистрациях\n"
    
    stats_text += f"\n📱 <b>Активность за 30 дней:</b>\n"
    
    if activity:
        for date_str, count in activity[:10]:  # Показываем последние 10 дней
            if date_str:
                stats_text += f"• {date_str}: {count} активных\n"
    else:
        stats_text += "Нет данных об активности\n"
    
    stats_text += f"\n🗓 <b>Регистрации по дням недели (90 дней):</b>\n"
    
    if weekday_stats:
        for weekday_num, count in weekday_stats:
            weekday_name = days_of_week[int(weekday_num)]
            stats_text += f"• {weekday_name}: {count} регистраций\n"
    else:
        stats_text += "Нет данных\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📈 Графики активности", callback_data="activity_charts"))
    keyboard.add(InlineKeyboardButton(text="👥 Все пользователи", callback_data="user_list"))
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="detailed_user_stats"))
    keyboard.add(InlineKeyboardButton(text="👑 В админ-меню", callback_data="admin_menu_back"))
    keyboard.adjust(2)
    
    await edit_with_photo(callback, 'admin', stats_text, keyboard.as_markup())
    await callback.answer()

# ===================== ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ =====================

@dp.message(Command("set_bot_name"))
async def set_bot_name_command(message: Message):
    """Изменение имени бота"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await message.answer("⛔ У вас нет прав на изменение настроек!")
        return
    
    try:
        new_name = message.text.replace('/set_bot_name', '').strip()
        if not new_name:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/set_bot_name Новое имя бота</code>\n\n"
                "Пример:\n"
                "<code>/set_bot_name K1LOSSEZ Referral Bot</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        old_name = get_setting('bot_name', 'K1LOSSEZ Referral Bot')
        update_setting('bot_name', new_name)
        
        await message.answer(
            f"✅ <b>Имя бота изменено!</b>\n\n"
            f"🤖 <b>Старое имя:</b> {old_name}\n"
            f"🤖 <b>Новое имя:</b> {new_name}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка изменения имени бота: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_currency"))
async def set_currency_command(message: Message):
    """Изменение валюты"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await message.answer("⛔ У вас нет прав на изменение настроек!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/set_currency название эмодзи</code>\n\n"
                "Пример:\n"
                "<code>/set_currency голда 💰</code>\n"
                "<code>/set_currency coins 🪙</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        currency_name = parts[1]
        currency_emoji = parts[2]
        
        old_name = get_setting('currency_name', 'голда')
        old_emoji = get_setting('currency_emoji', '💰')
        
        update_setting('currency_name', currency_name)
        update_setting('currency_emoji', currency_emoji)
        
        await message.answer(
            f"✅ <b>Валюта изменена!</b>\n\n"
            f"💰 <b>Старая:</b> {old_name} {old_emoji}\n"
            f"💰 <b>Новая:</b> {currency_name} {currency_emoji}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка изменения валюты: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("set_support"))
async def set_support_command(message: Message):
    """Изменение поддержки"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await message.answer("⛔ У вас нет прав на изменение настроек!")
        return
    
    try:
        support_username = message.text.replace('/set_support', '').strip().replace('@', '')
        if not support_username:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "<code>/set_support юзернейм</code>\n\n"
                "Пример:\n"
                "<code>/set_support support_username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        old_support = get_setting('support_username', '')
        update_setting('support_username', support_username)
        
        await message.answer(
            f"✅ <b>Поддержка изменена!</b>\n\n"
            f"👤 <b>Старая:</b> @{old_support if old_support else 'не указана'}\n"
            f"👤 <b>Новая:</b> @{support_username}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка изменения поддержки: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("toggle_maintenance"))
async def toggle_maintenance_command(message: Message):
    """Включение/выключение режима обслуживания"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await message.answer("⛔ У вас нет прав на изменение настроек!")
        return
    
    try:
        current_mode = get_setting('maintenance_mode', '0')
        new_mode = '1' if current_mode == '0' else '0'
        
        update_setting('maintenance_mode', new_mode)
        
        if new_mode == '1':
            # Запрашиваем сообщение для режима обслуживания
            await message.answer(
                "🛠 <b>Режим обслуживания включен!</b>\n\n"
                "Введите сообщение, которое будут видеть пользователи:",
                parse_mode=ParseMode.HTML
            )
            
            # Ждем сообщение
            @dp.message(F.from_user.id == user_id)
            async def process_maintenance_message(msg: Message):
                maintenance_message = msg.text
                update_setting('maintenance_message', maintenance_message)
                
                await msg.answer(
                    f"✅ <b>Режим обслуживания настроен!</b>\n\n"
                    f"📝 <b>Сообщение:</b>\n{maintenance_message}",
                    parse_mode=ParseMode.HTML
                )
        else:
            await message.answer("✅ <b>Режим обслуживания выключен!</b>", parse_mode=ParseMode.HTML)
            
    except Exception as e:
        logger.error(f"Ошибка переключения режима обслуживания: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("toggle_auto_check"))
async def toggle_auto_check_command(message: Message):
    """Включение/выключение автопроверки подписок"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    permissions = get_admin_permissions(user_id)
    if not permissions.get('all', False) and not permissions.get('manage_settings', False):
        await message.answer("⛔ У вас нет прав на изменение настроек!")
        return
    
    try:
        current_mode = get_setting('auto_check_subscriptions', '1')
        new_mode = '0' if current_mode == '1' else '1'
        
        update_setting('auto_check_subscriptions', new_mode)
        
        status = "включена" if new_mode == '1' else "выключена"
        await message.answer(f"✅ <b>Автопроверка подписок {status}!</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка переключения автопроверки: {e}")
        await message.answer(f"❌ Ошибка: {e}")

# ===================== ГЛАВНАЯ ФУНКЦИЯ =====================

async def main():
    """Главная функция запуска бота"""
    print("=" * 70)
    print(f"🤖 {get_setting('bot_name', 'K1LOSS EZ Referral Bot')} запущен!")
    print(f"🔑 Администраторов: {len(ADMIN_IDS)}")
    print(f"📢 Каналов для подписки: {len(REQUIRED_CHANNELS)}")
    print(f"👥 Группа ID: {GROUP_ID}")
    print("=" * 70)
    
    try:
        bot_info = await bot.get_me()
        print(f"🤖 Бот: @{bot_info.username}")
        print(f"🆔 ID бота: {bot_info.id}")
        print(f"👤 Имя бота: {bot_info.first_name}")
    except Exception as e:
        print(f"❌ Ошибка получения информации о боте: {e}")
    
    print("=" * 70)
    
    # Проверяем наличие фото
    print("📸 Проверка фото:")
    
    photo_types = ['welcome', 'profile', 'referral', 'admin', 'withdrawal', 'promo', 'stats']
    for photo_type in photo_types:
        photo_url = get_photo_url(photo_type)
        photo_file_id = get_setting(f'photo_{photo_type}_file_id', '')
        photo_path = os.path.join(IMAGES_DIR, f'{photo_type}.jpg')
        
        if photo_file_id:
            print(f"  ✅ {photo_type} - file_id установлен")
        elif photo_url:
            print(f"  ✅ {photo_type} - URL установлен")
        elif os.path.exists(photo_path):
            print(f"  ✅ {photo_type}.jpg - локальный файл")
        else:
            print(f"  ⚠️ {photo_type} - не установлено")
    
    print("=" * 70)
    print("🚀 Бот готов к работе!")
    print("=" * 70)
    print("👑 Команда админ-меню: /admin_menu")
    print("📸 Команда для установки фото: /set_photo")
    print("💰 Команда для изменения баланса: /add_balance")
    print("⚙️ Команда для изменения бонуса: /set_referral_bonus /set_welcome_bonus")
    print("🎁 Команда для управления промокодами: /delete_promo")
    print("📢 Команда для управления каналами: /remove_channel")
    print("👑 Команда для управления админами: /remove_admin")
    print("=" * 70)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Проверяем, существует ли БД, если нет - создаем
    if not os.path.exists('referral_bot.db'):
        print("📁 Создаю новую базу данных...")
        init_database()
    else:
        print("📁 Загружаю существующую базу данных...")
        # Проверяем структуру БД и добавляем недостающие таблицы/столбцы
        conn = sqlite3.connect('referral_bot.db')
        cursor = conn.cursor()
        
        # Проверяем все таблицы
        tables_to_check = [
            ('users', '''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    balance REAL DEFAULT 0,
                    referrals_count INTEGER DEFAULT 0,
                    referral_from INTEGER DEFAULT 0,
                    join_date TEXT,
                    last_activity TEXT,
                    subscribed_channels TEXT DEFAULT '[]',
                    total_earned REAL DEFAULT 0,
                    total_withdrawn REAL DEFAULT 0
                )
            '''),
            ('referral_codes', '''
                CREATE TABLE IF NOT EXISTS referral_codes (
                    user_id INTEGER PRIMARY KEY,
                    referral_code TEXT UNIQUE,
                    created_date TEXT,
                    uses_count INTEGER DEFAULT 0
                )
            '''),
            # Добавьте все остальные таблицы здесь...
        ]
        
        for table_name, create_query in tables_to_check:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if not cursor.fetchone():
                print(f"  ➕ Создаю таблицу: {table_name}")
                cursor.execute(create_query)
        
        conn.commit()
        conn.close()
    
    # Загружаем данные из БД
    load_channels_from_db()
    load_admins_from_db()
    
    # Запускаем бота
    asyncio.run(main())
