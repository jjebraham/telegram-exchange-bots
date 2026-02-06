# 🏦 Kiani Exchange - Complete Crypto Exchange Platform

A comprehensive cryptocurrency exchange platform with Telegram integration, featuring a Mini App for users and a full-featured admin panel.

## 🌟 Features

### 👥 User Features (Telegram Mini App)
- ✅ **Real-time Exchange Rates** - USDT/IRR, USDT/TRY with live updates
- 📊 **Interactive Price Charts** - 7-day historical data with beautiful visualizations
- 💱 **Currency Converter** - Convert between IRR, TRY, and USDT
- 🧮 **Fee Calculator** - Calculate exact fees before transactions
- 💳 **Multi-Card Management** - Add and manage multiple bank cards
- 📜 **Transaction History** - Complete history with status tracking
- 🤖 **AI Chatbot** - Smart FAQ assistant for instant answers
- 🔔 **Price Alerts** - Get notified when prices hit your targets
- 🎨 **Modern UI/UX** - Beautiful, responsive design with dark mode
- 🔒 **Secure KYC** - ID verification with document upload
- 💸 **Multiple Transaction Types**:
  - Buy/Sell Lira (IRR ↔ TRY)
  - Buy/Sell USDT (IRR ↔ USDT)
  - Convert Lira to USDT (TRY ↔ USDT)
  - Foreign website payments

### 👨‍💼 Admin Features (Web Panel)
- 📊 **Comprehensive Dashboard** - Real-time statistics and analytics
- 👤 **User Management** - View, search, and manage all users
- ✅ **KYC Verification System** - Approve/reject with document review
- 📝 **FAQ Management** - Add, edit, delete FAQs (Persian & English)
- 📢 **Broadcast Messaging** - Send messages to user groups
- 📈 **Analytics & Reports** - Transaction volumes, user growth charts
- 🔍 **Activity Logs** - Complete audit trail of all admin actions
- ⚙️ **System Settings** - Configure rates, fees, and parameters
- 🎯 **Transaction Monitoring** - Track and manage all transactions
- 📱 **Responsive Design** - Works on desktop, tablet, and mobile

## 🏗️ Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **PostgreSQL** - Reliable relational database
- **SQLAlchemy** - ORM for database operations
- **Redis** - Caching and session management
- **Aiogram 3** - Telegram Bot framework
- **JWT** - Secure authentication
- **Bcrypt** - Password hashing

### Frontend
- **React 18** - UI library
- **TypeScript** - Type-safe JavaScript
- **Tailwind CSS** - Utility-first CSS
- **Recharts** - Data visualization
- **Vite** - Fast build tool
- **Telegram WebApp SDK** - Mini App integration

### External Services
- **Wallex API** - USDT/IRR rates
- **BTCTurk API** - USDT/TRY rates
- **Ehraz.io** - Bank card verification

## 📁 Project Structure

```
kiani-exchange/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── database.py          # Database models
│   │   ├── auth.py              # Authentication
│   │   ├── api/                 # API endpoints
│   │   └── services/            # Business logic
│   ├── bots/
│   │   ├── user_bot.py          # User Telegram bot
│   │   └── admin_bot.py         # Admin Telegram bot
│   ├── init_faqs.py             # Initialize FAQ database
│   └── requirements.txt
├── frontend/
│   ├── mini-app/                # User Mini App
│   │   ├── src/
│   │   ├── public/
│   │   ├── package.json
│   │   └── vite.config.ts
│   └── admin-panel/             # Admin Panel
│       ├── src/
│       ├── public/
│       ├── package.json
│       └── vite.config.ts
├── DEPLOYMENT.md                # Deployment guide
└── README.md                    # This file
```

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL 14+
- Redis
- Nginx

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/kiani-exchange.git
cd kiani-exchange
```

2. **Backend Setup**
```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. **Configure Environment**
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. **Initialize Database**
```bash
python -c "from database import init_db; init_db()"
python init_faqs.py
```

5. **Start Backend Services**
```bash
# Terminal 1: API Server
uvicorn main:app --reload

# Terminal 2: User Bot
python bots/user_bot.py

# Terminal 3: Admin Bot
python bots/admin_bot.py
```

6. **Frontend Setup - Mini App**
```bash
cd frontend/mini-app
npm install
npm run dev
```

7. **Frontend Setup - Admin Panel**
```bash
cd frontend/admin-panel
npm install
npm run dev
```

## 🌐 URLs

After deployment:
- **Mini App**: https://kiani.peerexo.com
- **Admin Panel**: https://admin.kiani.peerexo.com
- **API**: https://kiani.peerexo.com/api
- **API Docs**: https://kiani.peerexo.com/docs

## 📱 Telegram Bot Setup

### User Bot
1. Create bot via @BotFather
2. Get token and add to `.env`
3. Create Mini App via /newapp
4. Set menu button:
```python
await bot.set_chat_menu_button(
    menu_button=MenuButtonWebApp(
        text="🚀 داشبورد",
        web_app=WebAppInfo(url="https://kiani.peerexo.com")
    )
)
```

### Admin Bot
1. Create separate admin bot via @BotFather
2. Get token and admin chat ID
3. Add to `.env`

## 🔧 Configuration

### Environment Variables (.env)
```bash
# Database
DATABASE_URL=postgresql://user:password@localhost/kiani_exchange

# Security
JWT_SECRET_KEY=your-secret-key

# Telegram Bots
ADMIN_BOT_TOKEN=your-admin-bot-token
USER_BOT_TOKEN=your-user-bot-token
ADMIN_CHAT_ID=your-admin-telegram-id

# External APIs
WALLEX_API_KEY=your-wallex-key
EHRAZ_API_KEY=your-ehraz-key
PROXY_URL=your-proxy-url
```

## 📊 API Endpoints

### Public Endpoints
- `GET /api/rates/current` - Get current exchange rates
- `GET /api/rates/history` - Get historical rates
- `GET /api/faqs` - Get FAQ list
- `POST /api/chatbot/ask` - Ask chatbot

### User Endpoints (Auth Required)
- `POST /api/auth/telegram` - Authenticate via Telegram
- `GET /api/user/profile` - Get user profile
- `GET /api/user/transactions` - Get transaction history
- `POST /api/user/transactions` - Create transaction
- `POST /api/alerts` - Create price alert

### Admin Endpoints (Admin Auth Required)
- `POST /api/admin/login` - Admin login
- `GET /api/admin/dashboard` - Dashboard stats
- `GET /api/admin/users` - List users
- `POST /api/admin/kyc/{user_id}/approve` - Approve KYC
- `POST /api/admin/kyc/{user_id}/reject` - Reject KYC
- `POST /api/admin/faq` - Create FAQ
- `PUT /api/admin/faq/{faq_id}` - Update FAQ
- `DELETE /api/admin/faq/{faq_id}` - Delete FAQ
- `POST /api/admin/broadcast` - Send broadcast message
- `GET /api/admin/logs` - Get admin logs

## 🧪 Testing

### Backend Tests
```bash
cd backend
pytest tests/
```

### API Tests
```bash
# Test rates endpoint
curl https://kiani.peerexo.com/api/rates/current

# Test authentication
curl -X POST https://kiani.peerexo.com/api/auth/telegram \
  -H "Content-Type: application/json" \
  -d '{"telegram_id": 123456, "first_name": "Test"}'
```

## 📈 Monitoring

### Health Checks
- API: https://kiani.peerexo.com/api/health
- Database: Check connection via admin panel
- Bots: `/status` command

### Logs
```bash
# View service logs
sudo journalctl -u kiani-api -f
sudo journalctl -u kiani-user-bot -f
sudo journalctl -u kiani-admin-bot -f

# View Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

## 🔒 Security

- All passwords are hashed with bcrypt
- JWT tokens for API authentication
- SQL injection protection via ORM
- CORS configured for specific domains
- Rate limiting on all endpoints
- HTTPS only in production
- Regular security audits
- Automated backups

## 📦 Database Schema

Key tables:
- `users` - User accounts and KYC status
- `transactions` - All transaction records
- `bank_cards` - User bank cards
- `faqs` - FAQ content
- `admin_logs` - Admin activity audit trail
- `price_alerts` - User price alerts
- `support_tickets` - Support system
- `chatbot_logs` - Chatbot interactions

## 🔄 Backup & Recovery

### Automated Backups
```bash
# Daily backup at 2 AM
0 2 * * * /usr/local/bin/kiani-backup.sh
```

### Manual Backup
```bash
# Database
pg_dump -U kiani_user kiani_exchange > backup.sql

# Files
tar -czf files-backup.tar.gz /var/www/kiani-exchange/uploads
```

### Restore
```bash
# Database
psql -U kiani_user kiani_exchange < backup.sql

# Files
tar -xzf files-backup.tar.gz -C /
```

## 🐛 Troubleshooting

### Common Issues

**Bot not responding:**
```bash
sudo systemctl restart kiani-user-bot
sudo journalctl -u kiani-user-bot -n 100
```

**API errors:**
```bash
sudo systemctl restart kiani-api
sudo tail -f /var/log/nginx/error.log
```

**Database connection issues:**
```bash
sudo systemctl status postgresql
sudo -u postgres psql
```

## 📝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## 📄 License

This project is proprietary and confidential.

## 👥 Team

- **Development**: Your Team
- **Support**: @TL905411603664
- **Email**: support@kiani.com

## 📞 Support

### Contact Information
- **Telegram**: @TL905411603664
- **Phone (Iran)**: +98 912 195 82 96
- **Phone (Turkey)**: +90 541 160 36 64
- **Office**: +90 212 294 33 34
- **WhatsApp**: +90 539 290 56 86

### Office Location
Istanbul, Turkey
[Google Maps](https://maps.app.goo.gl/zEUA7XGR5XDRzG3q8)

---

**Made with ❤️ by Kiani Exchange Team**
