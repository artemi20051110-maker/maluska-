import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

load_dotenv()

# === НАСТРОЙКИ ===
DB_PATH = os.getenv("DB_PATH", "malusko.db")
API_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://maluska.vercel.app")
ADMIN_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003649793662"))
MY_ID = int(os.getenv("ADMIN_ID", "426795405"))
PAYMENT_QR_PATH = "payment_qr.png"
BOOKING_FEE = 300

if not API_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден!")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === БАЗА ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        username TEXT,
        service TEXT,
        booking_date TEXT,
        booking_time TEXT,
        age_group TEXT,
        status TEXT DEFAULT 'pending',
        payment_status TEXT DEFAULT 'unpaid',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()
    logger.info("✅ БАЗА ГОТОВА")

def is_slot_available(date, time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''SELECT id FROM bookings 
        WHERE booking_date = ? AND booking_time = ? AND status != 'cancelled'
    ''', (date, time))
    result = cursor.fetchone()
    conn.close()
    return result is None

# === КЛАВИАТУРА ===
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🩸 ЗАПИСАТЬСЯ", web_app=WebAppInfo(url=WEB_APP_URL))]
], resize_keyboard=True)

# === ЛОГИКА ===
@dp.message(Command("start"))
async def start(message: types.Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,?,?)",
        (message.from_user.id, message.from_user.username, message.from_user.first_name))
    conn.commit()
    conn.close()
    
    await bot.set_chat_menu_button(chat_id=message.chat.id,
        menu_button=types.MenuButtonWebApp(text="записаться",
            web_app=WebAppInfo(url=WEB_APP_URL)))
    
    await message.answer("привет! жми 🩸 ЗАПИСАТЬСЯ", reply_markup=main_kb)
    logger.info(f"📩 /start от {message.from_user.id}")

@dp.message(F.web_app_data)
async def web_app_handler(message: types.Message):
    logger.info(f"🔥 WEB_APP_DATA от {message.from_user.id}")
    
    try:
        data = json.loads(message.web_app_data.data)
        
        if not is_slot_available(data.get('date'), data.get('time')):
            await message.answer("❌ время занято! выбери другое.")
            return
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO bookings 
            (user_id, user_name, username, service, booking_date, booking_time, age_group)
            VALUES (?,?,?,?,?,?,?)''',
            (message.from_user.id, data.get('username', 'клиент'),
             message.from_user.username, data.get('service'),
             data.get('date'), data.get('time'), data.get('age')))
        booking_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        report = (f"🩸 ЗАЯВКА #{booking_id}\n"
            f"Клиент: @{message.from_user.username}\n"
            f"Дата: {data.get('date')} {data.get('time')}\n"
            f"Услуга: {data.get('service')}\n"
            f"Возраст: {data.get('age')}")
        
        await bot.send_message(ADMIN_CHANNEL_ID, report)
        
        try:
            with open(PAYMENT_QR_PATH, 'rb') as qr:
                await bot.send_photo(message.from_user.id, photo=qr,
                    caption=f"✅ бронь #{booking_id}\n💰 оплати {BOOKING_FEE}₽ по QR\n⏰ отправь чек сюда")
        except:
            await message.answer(f"✅ бронь #{booking_id}\n💰 оплати {BOOKING_FEE}₽ (QR не найден)")
        
        await message.answer("📲 проверь чат — там QR!")
        logger.info(f"✅ бронь #{booking_id}")
        
    except Exception as e:
        logger.error(f"❌ {e}", exc_info=True)
        await message.answer("❌ ошибка. напиши мастеру.")

@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    await bot.send_message(MY_ID, f"📨 @{message.from_user.username}\n{message.text}")
    await message.answer("отправлено мастеру!")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    await bot.send_photo(MY_ID, message.photo[-1].file_id,
        caption=f"💳 чек от @{message.from_user.username}")
    await message.answer("чек отправлен на проверку!")

async def main():
    logger.info("🚀 ЗАПУСК...")
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())