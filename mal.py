import asyncio
import json
import logging
import sqlite3
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOG_CHANNEL = os.getenv("LOG_CHANNEL_ID")

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

def init_db():
    conn = sqlite3.connect("malusko.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
        (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bookings 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, service TEXT, 
        date TEXT, time TEXT, age_group TEXT)''')
    conn.commit()
    conn.close()

@dp.message(Command("start"))
async def start(message: types.Message):
    # сохраняем юзера в базу (как и раньше)
    conn = sqlite3.connect("malusko.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?,?)",
                   (message.from_user.id, message.from_user.username, message.from_user.first_name))
    conn.commit()
    conn.close()

    # устанавливаем кнопку меню (слева от ввода текста)
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=types.MenuButtonWebApp(
            text="записаться",
            web_app=WebAppInfo(url="https://artemi20051110-maker.github.io/maluska-/")
        )
    )
    
    await message.answer("привет! нажми на кнопку в меню слева, чтобы записаться на сеанс.")
@dp.message(F.web_app_data)
async def handle_data(message: types.Message):
    data = json.loads(message.web_app_data.data)
    
    # логика уведомления
    report = (f"новая заявка\n"
              f"клиент: @{message.from_user.username}\n"
              f"услуга: {data['service']}\n"
              f"дата/время: {data['date']} в {data['time']}\n"
              f"возраст: {data['age']}")
    
    await bot.send_message(ADMIN_ID, report)
    if LOG_CHANNEL:
        await bot.send_message(LOG_CHANNEL, report)
    await message.answer("данные отправлены мастеру.")
    
    @dp.message(F.text)
    async def forward_to_admin(message: types.Message):
    # если пишет не админ, пересылаем админу
     if message.from_user.id != ADMIN_ID:
        await bot.send_message(
            ADMIN_ID, 
            f"сообщение от @{message.from_user.username or 'без_юзернейма'}:\n\n{message.text}"
        )

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())