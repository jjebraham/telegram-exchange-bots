import logging
import sqlite3
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command

########################################
# CONFIG
########################################
ADMIN_BOT_TOKEN = "8278787504:AAGU4jeKIYq4Kw_FNcgA-7_rb3H152aKxMU"
MAIN_BOT_TOKEN = "8509657640:AAG4gNsyvG0xt5ePoFXraBlMUb6hIrWmaWE"
ADMIN_CHAT_ID = 2043363119

logging.basicConfig(level=logging.DEBUG)

admin_bot = Bot(token=ADMIN_BOT_TOKEN)
main_bot = Bot(token=MAIN_BOT_TOKEN)
adp = Dispatcher(storage=MemoryStorage())

# Create a separate router for handling logs from user bot
log_router = Router()
adp.include_router(log_router)

########################################
# DB
########################################
def get_db_connection():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS exchange_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                exchange_type TEXT,
                amount TEXT,
                rate REAL,
                details TEXT,
                status TEXT DEFAULT 'submitted',
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()

EXCHANGE_STATUS_LABELS = {
    "submitted": "ثبت شد",
    "under_process": "در حال انجام",
    "rejected": "رد شد",
    "canceled": "لغو توسط ادمین",
    "under_review": "در حال بررسی",
    "done": "انجام شد",
    "waiting_user_payment": "در انتظار پرداخت کاربر",
    "waiting_admin_payment": "در انتظار پرداخت ادمین"
}

########################################
# START
########################################
@adp.message(Command("start"))
async def admin_start(message: types.Message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    await message.answer(
        "Admin bot ready.\n"
        "Commands:\n"
        "/list\n"
        "/search <keyword>\n"
        "/downloadall"
    )

########################################
# /list
########################################
@adp.message(Command("list"))
async def admin_list_users(message: types.Message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    
    # Check if a page number was provided
    parts = message.text.strip().split()
    page = 1
    page_size = 10  # Number of users per page
    
    if len(parts) > 1 and parts[1].isdigit():
        page = int(parts[1])
    
    offset = (page - 1) * page_size
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get total count first for pagination info
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()['total']
        total_pages = (total_users + page_size - 1) // page_size
        
        # Get users for the current page
        cursor.execute("""
            SELECT id, first_name, last_name, phone_number, kyc_status, reference_code, kyc_notified
            FROM users
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (page_size, offset))
        rows = cursor.fetchall()
        
        if not rows:
            if page > 1:
                await message.answer(f"❌ No users found on page {page}. Total pages: {total_pages}")
            else:
                await message.answer("❌ No users found in the database.")
            return
            
        # Create page header
        header = f"👥 *Users List (Page {page}/{total_pages})*\n" \
                 f"Showing {len(rows)} of {total_users} total users\n\n"
        
        # Create pagination navigation buttons
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Previous", callback_data=f"page_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"page_{page+1}"))
            
        markup = InlineKeyboardMarkup(inline_keyboard=[nav_buttons]) if nav_buttons else None
        
        # Create user list with summary info
        user_list = []
        for i, r in enumerate(rows, 1):
            # Add emoji indicators for KYC status
            kyc_emoji = "✅" if r['kyc_status'] == "Approved" else "❌" if r['kyc_status'] == "Rejected" else "⏳"
            
            user_list.append(
                f"{i+offset}. *{r['first_name']} {r['last_name']}*\n" \
                f"   ID: `{r['id']}` | 📱: `{r['phone_number'] or 'N/A'}`\n" \
                f"   KYC: {kyc_emoji} {r['kyc_status']} | 🆔 Ref: `{r['reference_code']}`"
            )
        
        # Send the message with the list and navigation buttons
        await message.answer(header + "\n".join(user_list), parse_mode="Markdown", reply_markup=markup)

# Handle pagination for user list
@adp.callback_query(F.data.startswith("page_"))
async def handle_page_navigation(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_CHAT_ID:
        return
        
    page = int(callback_query.data.split("_")[1])
    await callback_query.message.delete()  # Delete the old message
    await admin_list_users(types.Message(text=f"/list {page}", from_user=callback_query.from_user, chat=callback_query.message.chat))
    await callback_query.answer()

########################################
# /search
########################################
@adp.message(Command("search"))
async def admin_search_command(message: types.Message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("ℹ️ *Usage:* `/search <keyword>`\n\nSearches across users' name, phone, reference code, and other fields.", parse_mode="Markdown")
        return
    keyword = parts[1]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, first_name, last_name, phone_number, kyc_status, reference_code, kyc_notified, 
                   bank_card_number, front_id, back_id, created_date
            FROM users
            WHERE first_name LIKE ? 
               OR last_name LIKE ? 
               OR phone_number LIKE ? 
               OR reference_code LIKE ?
               OR bank_card_number LIKE ?
               OR id LIKE ?
            """,
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))
        results = cursor.fetchall()
        
    if results:
        await message.answer(f"🔍 Found {len(results)} results for '{keyword}':")
        
        for idx, r in enumerate(results, 1):
            # Format date nicely if available
            created_date = r['created_date'] if r['created_date'] else "Unknown"
            
            # Check if user has uploaded verification documents
            docs_status = "✅" if r['front_id'] and r['back_id'] else "❌"
            
            # Format detailed user information with emoji indicators
            user_info = (
                f"👤 *User #{idx}*\n"
                f"ID: `{r['id']}`\n"
                f"Name: {r['first_name']} {r['last_name']}\n"
                f"📱 Phone: `{r['phone_number']}`\n"
                f"💳 Card: `{r['bank_card_number'] or 'Not provided'}`\n"
                f"🆔 Reference: `{r['reference_code']}`\n"
                f"📄 KYC Status: {r['kyc_status']}\n"
                f"🔔 Notified: {'Yes' if r['kyc_notified'] else 'No'}\n"
                f"📎 Documents: {docs_status}\n"
                f"📅 Created: {created_date}\n"
            )
            
            # Add approval/rejection buttons if KYC is Pending
            if r['kyc_status'] == 'Pending':
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Approve", callback_data=f"approve_{r['reference_code']}"),
                        InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_{r['reference_code']}")
                    ]
                ])
                await message.answer(user_info, reply_markup=markup, parse_mode="Markdown")
            else:
                await message.answer(user_info, parse_mode="Markdown")
    else:
        await message.answer(f"❌ No results found for '{keyword}'.")

########################################
# /downloadall
########################################
@adp.message(Command("downloadall"))
async def admin_download_all(message: types.Message):
    if message.chat.id != ADMIN_CHAT_ID:
        return

    import shutil
    import os
    from aiogram.types import FSInputFile

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT front_id, back_id FROM users")
        rows = cursor.fetchall()
    file_list = []
    for r in rows:
        front = r["front_id"]
        back = r["back_id"]
        if front and os.path.exists(front):
            file_list.append(front)
        if back and os.path.exists(back):
            file_list.append(back)
    if not file_list:
        await message.answer("No files found.")
        return

    zip_name = "user_files.zip"
    tmp_dir = "downloaded_files"
    os.makedirs(tmp_dir, exist_ok=True)
    for f in file_list:
        shutil.copy(f, os.path.join(tmp_dir, os.path.basename(f)))
    shutil.make_archive("user_files", 'zip', tmp_dir)
    await message.answer_document(FSInputFile(zip_name), caption="All user files       ")
    shutil.rmtree(tmp_dir)
    os.remove(zip_name)

########################################
# APPROVE / REJECT (Inline)
########################################
@adp.callback_query(F.data.startswith("approve_"))
async def approve_kyc_callback_adminbot(callback_query: types.CallbackQuery):
    ref_code = callback_query.data.split("_")[1]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET kyc_status='Approved', kyc_notified=0 WHERE reference_code=?", (ref_code,))
        user_id = cursor.execute("SELECT id FROM users WHERE reference_code=?",        (ref_code,)).fetchone()
        conn.commit()

    if user_id:
        await callback_query.answer("تایید شد ✅ (main bot will message user)")
    else:
        await callback_query.answer("❌ کاربر یافت نشد.")

@adp.callback_query(F.data.startswith("reject_"))
async def reject_kyc_callback_adminbot(callback_query: types.CallbackQuery):
    ref_code = callback_query.data.split("_")[1]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET kyc_status='Rejected', kyc_notified=0 WHERE reference_code=?", (ref_code,))
        user_id = cursor.execute("SELECT id FROM users WHERE reference_code=?",        (ref_code,)).fetchone()
        conn.commit()

    if user_id:
        await callback_query.answer("رد شد ❌ (main bot will message user)")
    else:
        await callback_query.answer("❌ کاربر یافت نشد.")

@adp.callback_query(F.data.startswith("exch|"))
async def exchange_status_callback(callback_query: types.CallbackQuery):
    parts = callback_query.data.split("|")
    if len(parts) != 3:
        await callback_query.answer("❌ داده نامعتبر است")
        return
    status_code = parts[1]
    request_id = parts[2]
    if status_code not in EXCHANGE_STATUS_LABELS:
        await callback_query.answer("❌ وضعیت نامعتبر است")
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, exchange_type FROM exchange_requests WHERE id=?",
            (request_id,)
        )
        row = cursor.fetchone()
        if not row:
            await callback_query.answer("❌ درخواست یافت نشد")
            return
        cursor.execute(
            "UPDATE exchange_requests SET status=?, updated_at=? WHERE id=?",
            (status_code, datetime.now().isoformat(), request_id)
        )
        conn.commit()

    status_label = EXCHANGE_STATUS_LABELS[status_code]
    try:
        await main_bot.send_message(
            row["user_id"],
            f"وضعیت درخواست شما #{request_id} به «{status_label}» تغییر کرد.\nنوع درخواست: {row['exchange_type']}"
        )
    except Exception as e:
        logging.error(f"Failed to notify user about exchange status: {e}")

    await callback_query.answer(f"✅ وضعیت به {status_label} تغییر کرد")

########################################
# USER LOGS
########################################
async def log_user_interaction(user_id, user_name, action):
    """Send log to admin chat about user interactions"""
    try:
        log_message = f"👤 User {user_id} ({user_name}) {action}"
        await admin_bot.send_message(ADMIN_CHAT_ID, log_message)
        return True
    except Exception as e:
        logging.error(f"Failed to send log to admin: {e}")
        return False

# API endpoint to receive logs from main_user_bot
@log_router.message(Command("log"))
async def receive_log(message: types.Message):
    try:
        # Format expected: /log user_id:user_name:action
        parts = message.text.split(" ", 1)
        if len(parts) != 2:
            return
            
        log_data = parts[1].split(":", 2)
        if len(log_data) != 3:
            return
            
        user_id, user_name, action = log_data
        await admin_bot.send_message(ADMIN_CHAT_ID, f"👤 User {user_id} ({user_name}) {action}")
    except Exception as e:
        logging.error(f"Error processing log: {e}")

########################################
# BOT STARTUP
########################################
async def main():
    logging.info("Starting admin bot...")
    init_db()
    await adp.start_polling(admin_bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
