import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

load_dotenv()

# === НАСТРОЙКИ ===
DB_PATH = os.getenv("DB_PATH", "malusko.db")
API_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://maluska.vercel.app")  # 🔥 без пробелов!
ADMIN_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003649793662"))
MY_ID = int(os.getenv("ADMIN_ID", "426795405"))
PAYMENT_QR_PATH = "payment_qr.png"
BOOKING_FEE = 300

if not API_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env!")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
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
            status TEXT DEFAULT 'pending',
            payment_status TEXT DEFAULT 'unpaid',
            payment_receipt_id TEXT,
            admin_msg_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    conn.commit()
    conn.close()

def is_slot_available(date, time):
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

# === КЛАВИАТУРА ===
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🩸 ЗАПИСАТЬСЯ", web_app=WebAppInfo(url=WEB_APP_URL))]
    ],
    resize_keyboard=True
)

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
        logger.info(f"распарсенные данные: {data}")
        
        if not is_slot_available(data.get('date'), data.get('time')):
            await message.answer("❌ это время уже занято! выбери другое.")
            return
        
        user_name = data.get('username', message.from_user.first_name or 'клиент')
        
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
        logger.info(f"✅ сохранено в базу id={booking_id}")
        
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
            logger.error(f"QR файл не найден: {PAYMENT_QR_PATH}")
            await message.answer(
                f"✅ бронь #{booking_id} создана!\n\n"
                f"💰 оплати {BOOKING_FEE}₽ (QR не найден)\n\n"
                f"⏰ отправь чек в этот чат!"
            )
        
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
        logger.error(f"❌ ОШИБКА: {e}", exc_info=True)
        await message.answer("❌ ошибка. напиши мастеру.")

@dp.message(F.text)
async def handle_user_messages(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    
    await bot.send_message(
        MY_ID,
        f"📨 сообщение от @{message.from_user.username or 'без_ника'}\n"
        f"ID: {message.from_user.id}\n\n"
        f"{message.text}"
    )
    await message.answer("сообщение отправлено мастеру. жди ответа!")

@dp.message(F.photo)
async def handle_receipt(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    
    await bot.send_photo(
        MY_ID,
        message.photo[-1].file_id,
        caption=f"💳 чек от @{message.from_user.username or 'без_ника'}\nID: {message.from_user.id}"
    )
    await message.answer("✅ чек отправлен на проверку. жди подтверждения!")

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