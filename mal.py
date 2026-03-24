import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

load_dotenv()

# === НАСТРОЙКИ ===
API_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "malusko.db")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://maluska.vercel.app")
ADMIN_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003649793662"))
MY_ID = int(os.getenv("ADMIN_ID", "426795405"))
BOOKING_FEE = 300
PAYMENT_PHONE = os.getenv("PAYMENT_PHONE", "+7 (999) 123-45-67")
STUDIO_ADDRESS = os.getenv("STUDIO_ADDRESS", "г. Екатеринбург, ул. Шейкмана 24")
MASTER_USERNAME = os.getenv("MASTER_USERNAME", "@shilgalvas")

ANATOMY_PIERCINGS = ["пупок", "индастриал", "дейс", "антибровь", "язык", "губа", "бридж"]

print(f"✅ токен: {API_TOKEN[:20]}...")
print(f"✅ ADMIN_ID: {MY_ID}")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
            comment TEXT,
            status TEXT DEFAULT 'pending',
            payment_status TEXT DEFAULT 'unpaid',
            reminder_sent INTEGER DEFAULT 0,
            admin_msg_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    columns = [
        ("comment", "TEXT"),
        ("status", "TEXT"),
        ("payment_status", "TEXT"),
        ("reminder_sent", "INTEGER"),
        ("admin_msg_id", "INTEGER")
    ]
    
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE bookings ADD COLUMN {col_name} {col_type}")
        except:
            pass
    
    conn.commit()
    conn.close()
    logger.info("✅ БАЗА ГОТОВА")

def add_user(user_id, username, first_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)', (user_id, username, first_name))
    cursor.execute('UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_users_list():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows

def is_slot_available(date, time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM bookings WHERE booking_date = ? AND booking_time = ? AND status != 'cancelled'", (date, time))
    result = cursor.fetchone()
    conn.close()
    return result is None

def get_user_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, service, booking_date, booking_time, status, payment_status FROM bookings WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# === КЛАВИАТУРЫ ===
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📋 мои брони", web_app=WebAppInfo(url=WEB_APP_URL))],
    [KeyboardButton(text="🛠 поддержка / админ")]
], resize_keyboard=True)

def booking_kb(booking_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ оплата получена", callback_data=f"paid_{booking_id}")],
        [InlineKeyboardButton(text="❌ отменить", callback_data=f"cancel_{booking_id}")]
    ])

def reminder_kb(booking_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ подтвердить", callback_data=f"confirm_{booking_id}")],
        [InlineKeyboardButton(text="❌ отменить", callback_data=f"cancel_{booking_id}")]
    ])

# === ЛОГИКА ===
@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await bot.set_chat_menu_button(chat_id=message.chat.id, menu_button=types.MenuButtonCommands())
    
    text = (
        f"привет! это запись к малюске на пирсинг.\n\n"
        f"🩸 жми внизу чтобы записаться\n"
        f"💰 бронь 300₽ (возвращается)\n"
        f"📱 оплата: {PAYMENT_PHONE}\n"
        f"⏰ после записи отправь чек"
    )
    
    await message.answer(text, reply_markup=main_kb)
    logger.info(f"📩 /start от {message.from_user.id}")

@dp.message(F.text == "🛠 поддержка / админ")
async def support(message: types.Message):
    await message.answer(f"🆘 пиши: {MASTER_USERNAME}")

@dp.message(Command("all_users"))
async def show_all_users(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    users = get_users_list()
    if not users:
        await message.answer("в базе пусто")
        return
    await message.answer(f"ВСЕГО: {len(users)}")
    for u in users[:30]:
        await message.answer(f"ID: {u[0]} | {u[2] or 'NoName'} (@{u[1] or 'скрыт'})")

@dp.message(Command("bookings"))
async def show_bookings(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id,user_name,booking_date,booking_time,service,status,payment_status FROM bookings WHERE status!='cancelled' ORDER BY booking_date")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await message.answer("броней нет")
        return
    resp = "📋 БРОНИ:\n\n"
    for r in rows:
        icon = "✅" if r[6] == "paid" else "⏳"
        resp += f"{icon} #{r[0]} | {r[1]} | {r[2]} {r[3]} | {r[4]}\n"
    await message.answer(resp)

@dp.message(Command("history"))
async def show_history(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("пиши: /history <user_id>")
        return
    user_id = int(args[1])
    history = get_user_history(user_id)
    if not history:
        await message.answer(f"у {user_id} нет броней")
        return
    resp = f"📋 ИСТОРИЯ {user_id}:\n\n"
    for h in history:
        resp += f"#{h[0]} | {h[1]} | {h[2]} {h[3]} | {h[4]} | {h[5]}\n"
    await message.answer(resp)

@dp.message(Command("send"))
async def broadcast(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    text = message.text.replace("/send", "").strip()
    if not text:
        await message.answer("пиши: /send [текст]")
        return
    users = get_users_list()
    cnt = 0
    for u in users:
        try:
            await bot.send_message(u[0], text)
            cnt += 1
        except:
            pass
    await message.answer(f"✅ отправлено {cnt}")

@dp.message(Command("reply"))
async def reply_to_user(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("пиши: /reply <user_id> <текст>")
        return
    
    user_id = int(args[1])
    text = args[2]
    
    try:
        await bot.send_message(user_id, text)
        await message.answer(f"✅ отправлено {user_id}")
    except Exception as e:
        await message.answer(f"❌ ошибка: {e}")

@dp.message(F.web_app_data)
async def web_app_handler(message: types.Message):
    logger.info(f"🔥 WEB_APP_DATA от {message.from_user.id}")
    
    try:
        data = json.loads(message.web_app_data.data)
        date = data.get('date')
        time = data.get('time')
        
        if not is_slot_available(date, time):
            await message.answer("❌ время занято!")
            return
        
        user_name = data.get('username', message.from_user.first_name or 'клиент')
        comment = data.get('comment', '')
        service = data.get('service', '')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bookings (user_id, user_name, username, service, booking_date, booking_time, age_group, comment, status, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'unpaid')
        ''', (message.from_user.id, user_name, message.from_user.username,
              service, date, time, data.get('age'), comment))
        booking_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"✅ бронь #{booking_id} создана")
        
        report = f"🩸 ЗАЯВКА #{booking_id}\n\n👤 @{message.from_user.username}\n📅 {date} {time}\n💉 {service}\n🎂 {data.get('age')}"
        if comment:
            report += f"\n💬 {comment}"
        
        sent_msg = await bot.send_message(ADMIN_CHANNEL_ID, report, reply_markup=booking_kb(booking_id))
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE bookings SET admin_msg_id = ? WHERE id = ?", (sent_msg.message_id, booking_id))
        conn.commit()
        conn.close()
        
        needs_consultation = any(p in service.lower() for p in ANATOMY_PIERCINGS)
        
        msg = f"✅ бронь #{booking_id}\n\n📅 {date} в {time}\n💉 {service}\n\n💰 300₽ на {PAYMENT_PHONE}"
        
        if needs_consultation:
            msg += f"\n\n⚠️ {service} — нужна консультация\n📲 напиши: {MASTER_USERNAME}"
        
        msg += "\n\n📍 после оплаты отправь чек в этот чат"
        
        await message.answer(msg)
        logger.info(f"✅ клиент получил подтверждение #{booking_id}")
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}", exc_info=True)
        await message.answer(f"❌ ошибка. пиши: {MASTER_USERNAME}")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    logger.info(f"📸 ФОТО от {message.from_user.id}")
    
    if message.from_user.id == MY_ID:
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, booking_date, booking_time, service 
        FROM bookings 
        WHERE user_id = ? AND payment_status = 'unpaid' AND status = 'pending' 
        ORDER BY created_at DESC LIMIT 1
    """, (message.from_user.id,))
    booking = cursor.fetchone()
    conn.close()
    
    if booking:
        await bot.send_photo(
            MY_ID,
            message.photo[-1].file_id,
            caption=f"💳 ЧЕК\n👤 @{message.from_user.username or 'без_ника'}\nID: {message.from_user.id}\nБронь #{booking[0]}\n📅 {booking[1]} {booking[2]}\n💉 {booking[3]}"
        )
        
        await bot.send_message(ADMIN_CHANNEL_ID, f"📨 чек по брони #{booking[0]} получен")
        await message.answer("✅ чек отправлен! жди подтверждения")
        logger.info(f"✅ чек по брони #{booking[0]} отправлен")
    else:
        await bot.send_photo(MY_ID, message.photo[-1].file_id, caption=f"💳 ЧЕК от @{message.from_user.username or 'без_ника'}")
        await message.answer("чек отправлен!")

@dp.callback_query(F.data.startswith("paid_"))
async def confirm_payment(callback: types.CallbackQuery):
    if callback.from_user.id != MY_ID:
        await callback.answer("❌ не твоё", show_alert=True)
        return
    
    booking_id = int(callback.data.split("_")[1])
    logger.info(f"💰 подтверждение оплаты #{booking_id}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, booking_date, booking_time, service, admin_msg_id FROM bookings WHERE id = ?", (booking_id,))
    booking = cursor.fetchone()
    
    if booking:
        cursor.execute("UPDATE bookings SET payment_status = 'paid', status = 'confirmed' WHERE id = ?", (booking_id,))
        conn.commit()
        
        guide_path = "guide.jpg"
        if os.path.exists(guide_path):
            await bot.send_photo(
                booking[0],
                photo=FSInputFile(guide_path),
                caption=f"✅ БРОНЬ #{booking_id} ПОДТВЕРЖДЕНА!\n\n📅 {booking[1]} в {booking[2]}\n💉 {booking[3]}\n\n📍 {STUDIO_ADDRESS}\n🗺 вход со стороны Попова\n\n⚡️ напоминание за 2 часа"
            )
        else:
            await bot.send_message(booking[0], 
                f"✅ БРОНЬ #{booking_id} ПОДТВЕРЖДЕНА!\n\n📅 {booking[1]} в {booking[2]}\n💉 {booking[3]}\n\n📍 {STUDIO_ADDRESS}\n🗺 вход со стороны Попова\n\n⚡️ напоминание за 2 часа"
            )
        
        try:
            await bot.edit_message_reply_markup(ADMIN_CHANNEL_ID, booking[4], reply_markup=None)
        except:
            pass
        
        await callback.answer("✅ подтверждено!")
        logger.info(f"💰 оплата #{booking_id} подтверждена")
    
    conn.close()

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_booking(callback: types.CallbackQuery):
    if callback.from_user.id != MY_ID:
        await callback.answer("❌ не твоё", show_alert=True)
        return
    
    booking_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, booking_date, booking_time, admin_msg_id FROM bookings WHERE id = ?", (booking_id,))
    booking = cursor.fetchone()
    
    if booking:
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
        
        await bot.send_message(booking[0], f"❌ бронь #{booking_id} отменена\n\n📅 {booking[1]} в {booking[2]}\n\nзапишись на другое время")
        
        try:
            await bot.edit_message_reply_markup(ADMIN_CHANNEL_ID, booking[3], reply_markup=None)
        except:
            pass
        
        await callback.answer("❌ отменено")
        logger.info(f"❌ бронь #{booking_id} отменена")
    
    conn.close()

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_reminder(callback: types.CallbackQuery):
    booking_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE bookings SET status = 'confirmed' WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    
    await callback.answer("✅ подтверждено!")
    await callback.message.edit_text(f"{callback.message.text}\n\n✅ ПОДТВЕРЖДЕНО")

@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    await bot.send_message(MY_ID, f"📨 @{message.from_user.username or 'без_ника'}\n{message.text}")
    await message.answer("отправлено! жди ответа")

async def check_reminders():
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            now = datetime.now()
            target_time = (now + timedelta(hours=2)).strftime("%H:%M")
            target_date = now.strftime("%Y-%m-%d")
            
            cursor.execute("""
                SELECT user_id, user_name, booking_time, id FROM bookings 
                WHERE booking_date = ? AND booking_time = ? 
                AND reminder_sent = 0 AND status = 'confirmed' AND payment_status = 'paid'
            """, (target_date, target_time))
            
            to_remind = cursor.fetchall()
            
            for user_id, name, b_time, b_id in to_remind:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"⚡️ {name}, напоминаем: запись через 2 часа ({b_time})!\n\n📍 {STUDIO_ADDRESS}\n\nподтверди:",
                    reply_markup=reminder_kb(b_id)
                )
                cursor.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (b_id,))
            
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