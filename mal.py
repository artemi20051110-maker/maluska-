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

# 🔥 загружаем переменные из .env
load_dotenv()

# === НАСТРОЙКИ ===
DB_PATH = os.getenv("DB_PATH", "malusko.db")
API_TOKEN = os.getenv("BOT_TOKEN")  # 🔥 из .env
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://maluska-webapp.vercel.app")
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 🔥 добавляем колонку last_seen если её нет
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    except sqlite3.OperationalError:
        pass  # колонка уже есть
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            service TEXT,
            booking_date TEXT,
            booking_time TEXT,
            age_group TEXT,
            status TEXT DEFAULT 'pending',
            admin_msg_id INTEGER
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
    logger.info(f"🔥🔥🔥 WEB_APP_DATA ПОЛУЧЕНЫ от {message.from_user.id}")
    logger.info(f"сырые данные: {message.web_app_data.data}")
    
    try:
        data = json.loads(message.web_app_data.data)
        logger.info(f"распарсенные данные: {data}")
        
        user_name = data.get('username', message.from_user.first_name or 'клиент')
        
        report = (
            f"🩸 НОВАЯ ЗАЯВКА\n\n"
            f"КЛИЕНТ: @{message.from_user.username or 'без_ника'}\n"
            f"ID: {message.from_user.id}\n"
            f"ИМЯ: {user_name}\n"
            f"УСЛУГА: {data.get('service', '---')}\n"
            f"ДАТА: {data.get('date', '---')} | {data.get('time', '---')}\n"
            f"ВОЗРАСТ: {data.get('age', '---')}"
        )
        
        # отправляем в канал
        sent_msg = await bot.send_message(chat_id=ADMIN_CHANNEL_ID, text=report)
        logger.info(f"✅ отправлено в канал, msg_id={sent_msg.message_id}")
        
        # сохраняем в базу
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bookings (user_id, user_name, service, booking_date, booking_time, age_group, admin_msg_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            message.from_user.id,
            user_name,
            data.get('service'),
            data.get('date'),
            data.get('time'),
            data.get('age'),
            sent_msg.message_id
        ))
        conn.commit()
        conn.close()
        logger.info(f"✅ сохранено в базу")
        
        # ответ пользователю
        await message.answer(f"✅ принято, {user_name}! заявка ушла мастеру.")
        logger.info("✅ ответ пользователю отправлен")
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА WebApp: {e}", exc_info=True)
        await message.answer(f"❌ траблы с сигналом... попробуй ещё раз или напиши мастеру.")

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