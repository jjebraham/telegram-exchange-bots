# API Testing Guide

## Base URL
- Production: https://kianiapp.peerexo.com/api
- Local: http://localhost:8000/api

## 1. Health Check
```bash
curl https://kianiapp.peerexo.com/health
```
**Expected Response:**
```json
{"status": "ok"}
```

## 2. Get Current Rates
```bash
curl https://kianiapp.peerexo.com/api/rates/current
```
**Expected Response:**
```json
{"rates": {"USDT_IRR": 1638000.0, "USDT_TRY": 43.579}}
```

## 3. Test User Registration (Mock)
```bash
curl -X POST https://kianiapp.peerexo.com/api/users/register \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "آزمایش",
    "last_name": "کاربر",
    "national_id": "1234567890",
    "date_of_birth": "13701212",
    "bank_card_number": "6037991234567890",
    "phone_number": "09123456789",
    "password": "Test1234"
  }'
```

## 4. Test User Login
```bash
curl -X POST https://kianiapp.peerexo.com/api/users/login \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "09123456789",
    "password": "Test1234"
  }'
```

## 5. Test EHRAZ Verification (Mock)
```bash
curl -X POST https://kianiapp.peerexo.com/api/verify/ehraz \
  -H "Content-Type: application/json" \
  -d '{
    "cardNumber": "6037991234567890",
    "nationalCode": "1234567890",
    "birthDate": "13701212"
  }'
```
**Expected Response (mock mode):**
```json
{"matched": true}
```

## 6. Test Transaction Creation (requires auth token)
First, login to get token:
```bash
TOKEN=$(curl -s -X POST https://kianiapp.peerexo.com/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "09123456789", "password": "Test1234"}' | jq -r '.token')
```

Then create transaction:
```bash
curl -X POST https://kianiapp.peerexo.com/api/transactions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "user_name": "آزمایش کاربر",
    "user_phone": "09123456789",
    "verification_level": 1,
    "exchange_pair": "Toman → TL",
    "exchange_type": "buy_lira",
    "send_amount": 10000000,
    "receive_amount": 227.27,
    "reference_number": "2025020916301234",
    "timestamp": "2025-02-09T16:30:00Z",
    "status": "Pending",
    "expires_at": "2025-02-09T17:30:00Z"
  }'
```

## 7. Get User Transactions
```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://kianiapp.peerexo.com/api/user/transactions
```

## 8. Test Admin Notification
```bash
curl -X POST https://kianiapp.peerexo.com/api/admin/notify-transaction \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "آزمایش کاربر",
    "user_phone": "09123456789",
    "verification_level": 1,
    "exchange_pair": "Toman → TL",
    "send_amount": 10000000,
    "receive_amount": 227.27,
    "reference_number": "2025020916301234",
    "timestamp": "2025-02-09T16:30:00Z",
    "expires_at": "2025-02-09T17:30:00Z",
    "national_id": "1234567890",
    "date_of_birth": "13701212",
    "bank_card_number": "6037991234567890"
  }'
```

## Testing Notes:

### Frontend Testing:
1. Open https://kianiapp.peerexo.com in browser
2. Test registration form with valid Persian data
3. Test login with registered user
4. Test exchange calculator:
   - Enter amount in Toman for "خرید لیر"
   - Verify 80 TL fee shows for amounts < 15,000,000 Toman
   - Verify calculation is correct
5. Test transaction submission
6. Test history page

### Telegram Integration Testing:
1. Send test message to configured admin bot
2. Verify notifications are received for:
   - New registrations
   - Login attempts
   - Transaction requests

### Database Verification:
Check SQLite database:
```bash
sqlite3 /home/kianirad2020/telegram_bot_repo/kiani-exchange/backend/users.db
.tables
SELECT * FROM users LIMIT 5;
SELECT * FROM transactions LIMIT 5;
```

### Error Scenarios to Test:
1. Invalid national ID (not 10 digits)
2. Invalid phone number (not starting with 09)
3. Invalid date format
4. Duplicate phone number registration
5. Incorrect login credentials
6. Transaction with expired token
7. Amount below/above limits