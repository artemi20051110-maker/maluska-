import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOG_CHANNEL = os.getenv("LOG_CHANNEL_ID")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# 🔥 ВАЖНО: включаем подробные логи
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect("malusko.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
        (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bookings 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, service TEXT, 
        date TEXT, time TEXT, age_group TEXT, created_at TEXT)''')
    conn.commit()
    conn.close()
    logger.info("база данных инициализирована")

@dp.message(Command("start"))
async def start(message: types.Message):
    logger.info(f"команда /start от пользователя {message.from_user.id}")
    
    conn = sqlite3.connect("malusko.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?,?)",
                   (message.from_user.id, message.from_user.username, message.from_user.first_name))
    conn.commit()
    conn.close()

    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=types.MenuButtonWebApp(
            text="записаться",
            web_app=WebAppInfo(url="https://maluska.vercel.app")
        )
    )
    await message.answer("привет! нажми на кнопку в меню слева, чтобы записаться.")
    logger.info(f"меню кнопка установлена для чата {message.chat.id}")

@dp.message(F.web_app_data)
async def handle_data(message: types.Message):
    logger.info(f"🔥 ПОЛУЧЕНЫ WEB_APP_DATA от {message.from_user.id}")
    logger.info(f"сырые данные: {message.web_app_data.data}")
    
    try:
        data = json.loads(message.web_app_data.data)
        logger.info(f"распарсенные данные: {data}")
        
        # сохраняем в базу
        conn = sqlite3.connect("malusko.db")
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO bookings 
            (user_id, service, date, time, age_group, created_at) 
            VALUES (?, ?, ?, ?, ?, ?)''',
            (message.from_user.id, 
             data.get('service', 'неизвестно'),
             data.get('date', 'неизвестно'),
             data.get('time', 'неизвестно'),
             data.get('age', 'неизвестно'),
             datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        booking_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"запись сохранена в базу с id={booking_id}")
        
        report = (f"🩸 НОВАЯ ЗАЯВКА #{booking_id}\n"
                  f"Клиент: @{message.from_user.username or 'без_юзернейма'}\n"
                  f"ID: {message.from_user.id}\n"
                  f"Услуга: {data.get('service', 'неизвестно')}\n"
                  f"Дата/время: {data.get('date', '?')} в {data.get('time', '?')}\n"
                  f"Возраст: {data.get('age', '?')}")
        
        logger.info(f"отправляю отчёт админу {ADMIN_ID}")
        await bot.send_message(ADMIN_ID, report)
        logger.info("отчёт отправлен админу")
        
        if LOG_CHANNEL:
            try:
                await bot.send_message(LOG_CHANNEL, report)
                logger.info("отчёт отправлен в лог-канал")
            except Exception as e:
                logger.error(f"ошибка отправки в лог-канал: {e}")
        
        await message.answer("✅ данные отправлены мастеру. жди подтверждения!")
        logger.info("ответ пользователю отправлен")
        
    except Exception as e:
        logger.error(f"🔥 ОШИБКА обработки данных: {e}", exc_info=True)
        await message.answer(f"❌ ошибка при отправке: {str(e)}\nнапиши мастеру вручную.")

@dp.message(F.text)
async def forward_to_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        logger.info(f"сообщение от {message.from_user.id} пересылается админу")
        await bot.send_message(
            ADMIN_ID, 
            f"сообщение от @{message.from_user.username or 'без_юзернейма'}:\n\n{message.text}"
        )

async def main():
    logger.info("запуск бота...")
    init_db()
    logger.info(f"ADMIN_ID={ADMIN_ID}, LOG_CHANNEL={LOG_CHANNEL}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())