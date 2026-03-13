import asyncio
import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

# === НАСТРОЙКИ ===
API_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "malusko.db")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://maluska.vercel.app")
ADMIN_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003649793662"))
MY_ID = int(os.getenv("ADMIN_ID", "426795405"))
BOOKING_FEE = 300
PAYMENT_URL = os.getenv("PAYMENT_URL", "https://tips.yandex.ru/guest/payment/7290720")

print(f"✅ токен: {API_TOKEN[:20]}...")
print(f"✅ ADMIN_ID: {MY_ID}")
print(f"✅ канал: {ADMIN_CHANNEL_ID}")

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
            payment_proof TEXT,
            reminder_sent INTEGER DEFAULT 0,
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
    cursor.execute('INSERT OR IGNORE INTO users VALUES (?,?,?)', (user_id, username, first_name))
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

def get_booked_slots(date):
    """Вернёт список занятых времён на дату"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT booking_time FROM bookings WHERE booking_date = ? AND status != 'cancelled'", (date,))
    slots = [row[0] for row in cursor.fetchall()]
    conn.close()
    return slots

# === КЛАВИАТУРЫ ===
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🩸 ЗАПИСАТЬСЯ", web_app=WebAppInfo(url=WEB_APP_URL))],
    [KeyboardButton(text="🛠 ПОДДЕРЖКА / АДМИН")]
], resize_keyboard=True)

def booking_kb(booking_id):
    """Кнопки для админа: подтвердить оплату"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ОПЛАТА ПОЛУЧЕНА", callback_data=f"paid_{booking_id}")],
        [InlineKeyboardButton(text="❌ ОТМЕНИТЬ БРОНЬ", callback_data=f"cancel_{booking_id}")]
    ])

def reminder_kb(booking_id):
    """Кнопки для напоминания"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ", callback_data=f"confirm_{booking_id}")],
        [InlineKeyboardButton(text="❌ ОТМЕНИТЬ", callback_data=f"cancel_{booking_id}")]
    ])

# === ЛОГИКА ===
@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=types.MenuButtonWebApp(text="записаться", web_app=WebAppInfo(url=WEB_APP_URL))
    )
    await message.answer(
        "привет! это запись к малюске на пирсинг.\n\n"
        "🩸 жми ЗАПИСАТЬСЯ чтобы выбрать дату и время\n"
        "💰 бронь стоит 300₽ (возвращается при посещении)\n"
        "⏰ после записи отправь чек — бронь подтвердится после проверки",
        reply_markup=main_kb
    )
    logger.info(f"📩 /start от {message.from_user.id}")

@dp.message(F.text == "🛠 ПОДДЕРЖКА / АДМИН")
async def support(message: types.Message):
    await message.answer("🆘 вопросы? пиши: @shilgalvas")

@dp.message(Command("all_users"))
async def show_all_users(message: types.Message):
    if message.from_user.id != MY_ID:
        return
    users = get_users_list()
    if not users:
        await message.answer("в базе пусто")
        return
    await message.answer(f"ВСЕГО КЛИЕНТОВ: {len(users)}")
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
        status_icon = "✅" if r[6] == "paid" else "⏳"
        resp += f"{status_icon} #{r[0]} | {r[1]} | {r[2]} {r[3]} | {r[4]}\n   статус:{r[5]} оплата:{r[6]}\n\n"
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
    await message.answer(f"✅ отправлено {cnt} клиентам")

@dp.message(F.web_app_data)
async def web_app_handler(message: types.Message):
    logger.info(f"🔥 WEB_APP_DATA от {message.from_user.id}")
    try:
        data = json.loads(message.web_app_data.data)
        
        date = data.get('date')
        time = data.get('time')
        
        # Проверка занятости
        if not is_slot_available(date, time):
            await message.answer("❌ это время уже занято! выбери другое.")
            return
        
        user_name = data.get('username', message.from_user.first_name or 'клиент')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bookings (user_id, user_name, username, service, booking_date, booking_time, age_group, status, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'unpaid')
        ''', (message.from_user.id, user_name, message.from_user.username,
              data.get('service'), date, time, data.get('age')))
        booking_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # QR с информацией о брони
        payment_link = f"{PAYMENT_URL}?label=booking_{booking_id}_{date}_{time}"
        qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={payment_link}"
        
        report = (
            f"🩸 НОВАЯ ЗАЯВКА #{booking_id}\n\n"
            f"👤 Клиент: @{message.from_user.username}\n"
            f"📅 Дата: {date}\n"
            f"⏰ Время: {time}\n"
            f"💉 Услуга: {data.get('service')}\n"
            f"🎂 Возраст: {data.get('age')}\n\n"
            f"💰 Бронь: {BOOKING_FEE}₽\n"
            f"⏳ статус: ожидание оплаты"
        )
        
        sent_msg = await bot.send_message(ADMIN_CHANNEL_ID, report, reply_markup=booking_kb(booking_id))
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE bookings SET admin_msg_id = ? WHERE id = ?", (sent_msg.message_id, booking_id))
        conn.commit()
        conn.close()
        
        # Отправка QR клиенту
        qr_caption = (
            f"✅ бронь #{booking_id} оформлена!\n\n"
            f"📅 {date} в {time}\n"
            f"💉 {data.get('service')}\n\n"
            f"💰 оплати {BOOKING_FEE}₽ по QR выше\n"
            f"⏰ после оплаты ОТПРАВЬ ЧЕК СЮДА\n"
            f"❗ бронь подтвердится только после проверки чека админом"
        )
        
        await bot.send_photo(chat_id=message.from_user.id, photo=qr_api, caption=qr_caption)
        await message.answer("📲 проверь чат — там QR и инструкция!")
        logger.info(f"✅ бронь #{booking_id}")
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}", exc_info=True)
        await message.answer("❌ ошибка. напиши мастеру: @shilgalvas")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == MY_ID:
        return
    
    # Ищем последнюю неоплаченную бронь пользователя
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, booking_date, booking_time FROM bookings WHERE user_id = ? AND payment_status = 'unpaid' AND status = 'pending' ORDER BY created_at DESC LIMIT 1", (message.from_user.id,))
    booking = cursor.fetchone()
    conn.close()
    
    if booking:
        await bot.send_photo(
            MY_ID,
            message.photo[-1].file_id,
            caption=f"💳 ЧЕК от @{message.from_user.username or 'без_ника'}\n"
                    f"ID: {message.from_user.id}\n"
                    f"Бронь #{booking[0]} на {booking[1]} {booking[2]}\n\n"
                    f"✅ подтверди оплату кнопкой в канале"
        )
        await message.answer("✅ чек отправлен на проверку! жди подтверждения")
    else:
        await bot.send_photo(MY_ID, message.photo[-1].file_id,
            caption=f"💳 ЧЕК от @{message.from_user.username or 'без_ника'}\nID: {message.from_user.id}")
        await message.answer("чек отправлен! жди ответа")

@dp.callback_query(F.data.startswith("paid_"))
async def confirm_payment(callback: types.CallbackQuery):
    if callback.from_user.id != MY_ID:
        await callback.answer("❌ не твоё", show_alert=True)
        return
    
    booking_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, booking_date, booking_time, admin_msg_id FROM bookings WHERE id = ?", (booking_id,))
    booking = cursor.fetchone()
    
    if booking:
        cursor.execute("UPDATE bookings SET payment_status = 'paid', status = 'confirmed' WHERE id = ?", (booking_id,))
        conn.commit()
        
        await bot.send_message(booking[0], 
            f"✅ БРОНЬ #{booking_id} ПОДТВЕРЖДЕНА!\n\n"
            f"📅 {booking[1]} в {booking[2]}\n"
            f"💰 оплата проверена\n\n"
            f"📍 ждём тебя! Шейкмана 24\n"
            f"⚡️ напоминание придёт за 2 часа")
        
        await bot.edit_message_reply_markup(ADMIN_CHANNEL_ID, booking[3], reply_markup=None)
        await callback.answer("✅ оплата подтверждена!")
        logger.info(f"💰 оплата по брони #{booking_id} подтверждена")
    
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
        
        await bot.send_message(booking[0], 
            f"❌ БРОНЬ #{booking_id} ОТМЕНЕНА\n\n"
            f"📅 {booking[1]} в {booking[2]}\n\n"
            f"если хочешь — запишись на другое время")
        
        await bot.edit_message_reply_markup(ADMIN_CHANNEL_ID, booking[3], reply_markup=None)
        await callback.answer("❌ бронь отменена")
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
    await message.answer("отправлено мастеру! жди ответа")

async def check_reminders():
    """напоминает за 2 часа + кнопки подтвердить/отменить"""
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            now = datetime.now()
            target_time = (now + timedelta(hours=2)).strftime("%H:%M")
            target_date = now.strftime("%Y-%m-%d")
            
            cursor.execute('''
                SELECT user_id, user_name, booking_time, id FROM bookings 
                WHERE booking_date = ? AND booking_time = ? 
                AND reminder_sent = 0 AND status = 'confirmed' AND payment_status = 'paid'
            ''', (target_date, target_time))
            
            to_remind = cursor.fetchall()
            
            for user_id, name, b_time, b_id in to_remind:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"⚡️ {name}, напоминаем: запись через 2 часа ({b_time})!\n\n"
                         f"📍 Шейкмана 24\n\n"
                         f"подтверди что придёшь:",
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