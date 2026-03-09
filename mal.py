import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv  # 🔥 добавлено
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import qrcode
from io import BytesIO

def generate_qr_photo(payment_url):
    """генерирует QR-код в память"""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(payment_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = BytesIO()
    img.save(bio, format='PNG')
    bio.seek(0)
    return bio

# 🔥 загружаем переменные из .env
load_dotenv()
# === ОПЛАТА ===
PAYMENT_QR_PATH = "payment_qr.png"  # 🔥 картинка с QR
PAYMENT_LINK = "https://tips.yandex.ru/guest/payment/7290720"  # 🔥 ссылка на оплату (дублирует QR)
BOOKING_FEE = 300  # сумма брони
# === НАСТРОЙКИ ===
DB_PATH = os.getenv("DB_PATH", "malusko.db")
API_TOKEN = os.getenv("BOT_TOKEN")  # 🔥 из .env
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://maluska.vercel.app")
ADMIN_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003649793662"))
MY_ID = int(os.getenv("ADMIN_ID", "426795405"))

# проверка токена
if not API_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # таблица пользователей
    cursor.execute('''
    INSERT INTO bookings (user_id, user_name, service, booking_date, booking_time, age_group, status, payment_status)
    VALUES (?, ?, ?, ?, ?, ?, 'pending', 'unpaid')
''', (
    message.from_user.id,
    user_name,
    data.get('service'),
    data.get('date'),
    data.get('time'),
    data.get('age')
))
    
    # таблица бронирований с оплатой
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            username TEXT,
            service TEXT,
            booking_date TEXT,
            booking_time TEXT,
            age_group TEXT,
            status TEXT DEFAULT 'pending',  -- pending, paid, confirmed, cancelled
            payment_status TEXT DEFAULT 'unpaid',  -- unpaid, paid, verified
            payment_receipt_id TEXT,  -- id фото чека
            admin_msg_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # таблица слотов (рабочие дни/время)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS time_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_date TEXT,
            slot_time TEXT,
            is_available INTEGER DEFAULT 1,
            UNIQUE(slot_date, slot_time)
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ БАЗА ГОТОВА")

def add_user(user_id, username, first_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
    ''', (user_id, username, first_name))
    # ❌ УДАЛИ ЭТУ СТРОКУ:
    # cursor.execute('UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
# === КЛАВИАТУРА ===
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🩸 ЗАПИСАТЬСЯ", web_app=WebAppInfo(url=WEB_APP_URL))]
    ],
    resize_keyboard=True
)
# === РАБОЧИЕ СЛОТЫ (настрой под мастера) ===
WORKING_DAYS = [0, 1, 2, 3, 4, 5, 6]  # 0=пн, 6=вс (все дни)
WORKING_HOURS = ["16:00", "17:00", "18:00", "19:00", "20:00"]  # твои окна
DAYS_AHEAD = 30  # сколько дней вперёд показывать

def generate_time_slots():
    """создаёт слоты на N дней вперёд"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    from datetime import datetime, timedelta
    today = datetime.now()
    
    for i in range(DAYS_AHEAD):
        date = (today + timedelta(days=i)).strftime('%Y-%m-%d')
        day_of_week = (today + timedelta(days=i)).weekday()
        
        if day_of_week in WORKING_DAYS:
            for time_slot in WORKING_HOURS:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO time_slots (slot_date, slot_time, is_available)
                        VALUES (?, ?, 1)
                    ''', (date, time_slot))
                except:
                    pass
    
    conn.commit()
    conn.close()

def get_available_slots(date):
    """возвращает свободные слоты на дату"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # проверяем есть ли слоты в базе
    cursor.execute('''
        SELECT slot_time FROM time_slots 
        WHERE slot_date = ? AND is_available = 1
    ''', (date,))
    available = [row[0] for row in cursor.fetchall()]
    
    # если слотов нет в базе — проверяем брони
    if not available:
        cursor.execute('''
            SELECT booking_time FROM bookings 
            WHERE booking_date = ? AND status NOT IN ('cancelled')
        ''', (date,))
        booked = [row[0] for row in cursor.fetchall()]
        available = [slot for slot in WORKING_HOURS if slot not in booked]
    
    conn.close()
    return available

def is_slot_available(date, time):
    """проверяет свободен ли конкретный слот"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM bookings 
        WHERE booking_date = ? AND booking_time = ? 
        AND status NOT IN ('cancelled')
    ''', (date, time))
    result = cursor.fetchone()
    conn.close()
    return result is None

def mark_slot_as_booked(date, time):
    """помечает слот как занятый"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE time_slots SET is_available = 0 
        WHERE slot_date = ? AND slot_time = ?
    ''', (date, time))
    conn.commit()
    conn.close()

# === ЛОГИКА ===
@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=types.MenuButtonWebApp(
            text="записаться",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    
    await message.answer(
        "привет! это запись к малюске на пирсинг.\n"
        "жми кнопку 🩸 ЗАПИСАТЬСЯ или меню слева",
        reply_markup=main_kb
    )
    logger.info(f"📩 /start от {message.from_user.id}")

@dp.message(F.web_app_data)
async def web_app_handler(message: types.Message):
    logger.info(f"🔥 WEB_APP_DATA от {message.from_user.id}")
    
    try:
        data = json.loads(message.web_app_data.data)
        
        # 🔥 ПРОВЕРКА СВОБОДНОСТИ
        if not is_slot_available(data.get('date'), data.get('time')):
            await message.answer("❌ это время уже занято! выбери другое.")
            return
        
        user_name = data.get('username', message.from_user.first_name or 'клиент')
        
        # сохраняем в базу
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bookings (user_id, user_name, username, service, booking_date, booking_time, age_group, status, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'unpaid')
        ''', (
            message.from_user.id,
            user_name,
            message.from_user.username,
            data.get('service'),
            data.get('date'),
            data.get('time'),
            data.get('age')
        ))
        booking_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # отправляем QR
        try:
            with open(PAYMENT_QR_PATH, 'rb') as qr_file:
                await bot.send_photo(
                    chat_id=message.from_user.id,
                    photo=qr_file,
                    caption=(
                        f"✅ бронь #{booking_id} создана!\n\n"
                        f"📅 {data.get('date')} в {data.get('time')}\n"
                        f"💉 {data.get('service')}\n\n"
                        f"💰 оплати бронь {BOOKING_FEE}₽ по QR выше\n\n"
                        f"⏰ после оплаты отправь чек в этот чат!"
                    )
                )
        except FileNotFoundError:
            await message.answer(
                f"✅ бронь #{booking_id} создана!\n\n"
                f"💰 оплати {BOOKING_FEE}₽ (QR не найден)\n\n"
                f"⏰ отправь чек в этот чат!"
            )
        
        # уведомление админу
        report = (
            f"🩸 НОВАЯ БРОНЬ #{booking_id}\n"
            f"Клиент: @{message.from_user.username}\n"
            f"Дата: {data.get('date')} {data.get('time')}\n"
            f"Услуга: {data.get('service')}\n"
            f"Статус: ожидание оплаты"
        )
        await bot.send_message(ADMIN_CHANNEL_ID, report)
        await message.answer("📲 проверь чат — там QR для оплаты!")
        
    except Exception as e:
        logger.error(f"ошибка: {e}", exc_info=True)
        await message.answer("❌ ошибка. напиши мастеру.")
async def main():
    logger.info("🚀 ЗАПУСК БОТА...")
    init_db()
    logger.info(f"ADMIN_CHANNEL_ID={ADMIN_CHANNEL_ID}, MY_ID={MY_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("бот остановлен")