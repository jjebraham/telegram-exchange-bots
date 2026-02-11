#!/usr/bin/env python3
import sqlite3
import bcrypt

# Connect to database
conn = sqlite3.connect('/home/kianirad2020/telegram_bot_repo/kiani-exchange/backend/users.db')
cursor = conn.cursor()

# Reset password for test user
test_phone = "09100000001"
new_password = "Test1234"

# Generate bcrypt hash
hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Update the user's password
cursor.execute(
    "UPDATE users SET password_hash = ? WHERE phone_number = ?",
    (hashed_password, test_phone)
)

conn.commit()

# Check if update was successful
cursor.execute(
    "SELECT phone_number, first_name, last_name FROM users WHERE phone_number = ?",
    (test_phone,)
)
user = cursor.fetchone()

if user:
    print(f"✓ Password reset for user: {user[1]} {user[2]} ({user[0]})")
    print(f"  New password: {new_password}")
    print(f"  Hashed password: {hashed_password[:50]}...")
else:
    print("✗ User not found")

conn.close()