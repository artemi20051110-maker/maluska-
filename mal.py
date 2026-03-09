import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

# === НАСТРОЙКИ ===
DB_PATH = os.getenv("DB_PATH", "malusko.db")
API_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://maluska.vercel.app")
ADMIN_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003649793662"))
MY_ID = int(os.getenv("ADMIN_ID", "426795405"))
PAYMENT_QR_PATH = "payment_qr.png"
BOOKING_FEE = 300

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
            reminder_sent INTEGER DEFAULT 0,
            admin_msg_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # добавляем колонки если их нет
    columns_to_add = [
        ('phone', 'TEXT'),
        ('people', 'TEXT'),
        ('details', 'TEXT'),
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE bookings ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass
    
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
    cursor.execute('UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_users_list():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name FROM users")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"ошибка базы: {e}")
        return []

def is_slot_available(date, time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM bookings 
        WHERE booking_date = ? AND booking_time = ? AND status != 'cancelled'
    ''', (date, time))
    result = cursor.fetchone()
    conn.close()
    return result is None

# === КЛАВИАТУРА ===
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🩸 ЗАПИСАТЬСЯ", web_app=WebAppInfo(url=WEB_APP_URL))],
    [KeyboardButton(text="🛠 ПОДДЕРЖКА / АДМИН")]
], resize_keyboard=True)

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
        "жми 🩸 ЗАПИСАТЬСЯ или кнопку меню слева",
        reply_markup=main_kb
    )
    logger.info(f"📩 /start от {message.from_user.id}")

@dp.message(F.text == "🛠 ПОДДЕРЖКА / АДМИН")
async def support(message: types.Message):
    await message.answer(
        "🆘 что-то не так?\n\n"
        "если возникли вопросы по записи или оплате — пиши: @shilgalvas"
    )

@dp.message(Command("all_users"))
async def show_all_users(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    
    users = get_users_list()
    if not users:
        await message.answer("в базе пока пусто")
        return
    
    total_count = len(users)
    await message.answer(f"ВСЕГО КЛИЕНТОВ: {total_count}\n" + "— " * 25)
    
    for i in range(0, len(users), 30):
        chunk = users[i:i + 30]
        response = ""
        for user in chunk:
            u_id, u_name, f_name = user
            name = f_name if f_name else "NoName"
            nick = f"@{u_name}" if u_name else "ник скрыт"
            response += f"ID: {u_id} | {name} ({nick})\n"
        
        if response:
            await message.answer(response)

@dp.message(Command("send"))
async def broadcast(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    
    broadcast_text = message.text.replace("/send", "").strip()
    if not broadcast_text:
        await message.answer("пиши так: /send [твой текст для всех]")
        return
    
    users = get_users_list()
    count = 0
    
    for user in users:
        try:
            await bot.send_message(user[0], broadcast_text)
            count += 1
        except Exception as e:
            logger.error(f"не удалось отправить {user[0]}: {e}")
    
    await message.answer(f"✅ рассылка завершена! получили {count} клиентов")

@dp.message(Command("test_app"))
async def test_app(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="тест брони", web_app=WebAppInfo(url=f"{WEB_APP_URL}?mode=test"))]
    ])
    await message.answer("скрытый вход в систему бронирования:", reply_markup=kb)

@dp.message(Command("bookings"))
async def show_bookings(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_name, booking_date, booking_time, service, status, payment_status 
        FROM bookings WHERE status != 'cancelled' ORDER BY booking_date, booking_time
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("броней пока нет")
        return
    
    response = "📋 БРОНИ:\n\n"
    for row in rows:
        response += f"#{row[0]} | {row[1]} | {row[2]} {row[3]} | {row[4]}\n"
        response += f"   статус: {row[5]} | оплата: {row[6]}\n\n"
    
    await message.answer(response)

# === ОБРАБОТКА WEB APP ===
@dp.message(F.web_app_data)
async def web_app_handler(message: types.Message):
    logger.info(f"🔥 WEB_APP_DATA от {message.from_user.id}")
    
    try:
        data = json.loads(message.web_app_data.data)
        
        # обработка действий админа (подтвердить/отменить)
        if "action" in data and data["action"] in ["confirm_booking", "cancel_booking"]:
            b_id = data.get("booking_id")
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT admin_msg_id FROM bookings WHERE id = ?", (b_id,))
            res = cursor.fetchone()
            
            new_status = "confirmed" if data["action"] == "confirm_booking" else "cancelled"
            cursor.execute("UPDATE bookings SET status = ? WHERE id = ?", (new_status, b_id))
            conn.commit()
            conn.close()
            
            status_text = "ПОДТВЕРЖДЕНО ✅" if data["action"] == "confirm_booking" else "ОТМЕНЕНО ❌"
            
            if res and res[0]:
                try:
                    await bot.send_message(chat_id=ADMIN_CHANNEL_ID, text=status_text, reply_to_message_id=res[0])
                except Exception as e:
                    logger.error(f"не удалось ответить в канале: {e}")
            
            await message.answer(f"принято! статус брони #{b_id} обновлён")
            return
        
        # новая бронь
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
        
        report = (
            f"🩸 НОВАЯ БРОНЬ #{booking_id}\n"
            f"Клиент: @{message.from_user.username}\n"
            f"Дата: {data.get('date')} {data.get('time')}\n"
            f"Услуга: {data.get('service')}\n"
            f"Возраст: {data.get('age')}\n"
            f"Статус: ожидание оплаты"
        )
        
        sent_msg = await bot.send_message(ADMIN_CHANNEL_ID, report)
        
        # сохраняем admin_msg_id для кнопок подтверждения
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE bookings SET admin_msg_id = ? WHERE id = ?", (sent_msg.message_id, booking_id))
        conn.commit()
        conn.close()
        
        # отправляем QR
        try:
            with open(PAYMENT_QR_PATH, 'rb') as qr_file:
                await bot.send_photo(
                    chat_id=message.from_user.id,
                    photo=qr_file,
                    caption=f"✅ бронь #{booking_id}\n\n💰 оплати {BOOKING_FEE}₽ по QR выше\n⏰ после оплаты отправь чек сюда"
                )
        except FileNotFoundError:
            await message.answer(f"✅ бронь #{booking_id}\n💰 оплати {BOOKING_FEE}₽ (QR не найден)")
        
        await message.answer("📲 проверь чат — там QR для оплаты!")
        logger.info(f"✅ бронь #{booking_id}")
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}", exc_info=True)
        await message.answer("❌ ошибка. напиши мастеру.")

@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    await bot.send_message(MY_ID, f"📨 @{message.from_user.username or 'без_ника'}\n{message.text}")
    await message.answer("отправлено мастеру! жди ответа")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    await bot.send_photo(
        MY_ID,
        message.photo[-1].file_id,
        caption=f"💳 чек от @{message.from_user.username or 'без_ника'}\nID: {message.from_user.id}"
    )
    await message.answer("чек отправлен на проверку! жди подтверждения")

# === ФОНОВЫЕ ЗАДАЧИ ===
async def check_reminders():
    """напоминает за 2 часа до записи"""
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            now = datetime.now()
            target_time = (now + timedelta(hours=2)).strftime("%H:%M")
            target_date = now.strftime("%Y-%m-%d")
            
            cursor.execute('''
                SELECT user_id, user_name, booking_time FROM bookings 
                WHERE booking_date = ? AND booking_time = ? 
                AND reminder_sent = 0 AND status = 'confirmed'
            ''', (target_date, target_time))
            
            to_remind = cursor.fetchall()
            
            for user_id, name, b_time in to_remind:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"⚡️ {name}, напоминаем: запись через 2 часа ({b_time})!\n\n📍 Шейкмана 24"
                )
                cursor.execute("UPDATE bookings SET reminder_sent = 1 WHERE user_id = ? AND booking_time = ?", (user_id, b_time))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"ошибка напоминаний: {e}")
        
        await asyncio.sleep(60)

async def main():
    logger.info("🚀 ЗАПУСК...")
    init_db()
    asyncio.create_task(check_reminders())
    logger.info(f"ADMIN_CHANNEL_ID={ADMIN_CHANNEL_ID}, MY_ID={MY_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("бот остановлен")