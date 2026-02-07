# Kiani Exchange - Complete Deployment Guide

## 📋 System Architecture

```
┌─────────────────────────────────────────────────────┐
│                  TELEGRAM USERS                      │
│              ↓                    ↓                  │
│    [Mini App Interface]    [Bot Commands]           │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│              FastAPI Backend Server                  │
│   ┌──────────────────────────────────────────┐     │
│   │ • REST API Endpoints                      │     │
│   │ • Authentication (JWT)                    │     │
│   │ • Rate Management                         │     │
│   │ • Transaction Processing                  │     │
│   │ • KYC Verification                        │     │
│   │ • AI Chatbot Service                      │     │
│   └──────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│                   PostgreSQL DB                      │
│   • Users & Authentication                           │
│   • Transactions History                             │
│   • KYC Documents                                    │
│   • FAQs & Admin Logs                               │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│               External Services                      │
│   • Wallex API (USDT/IRR)                           │
│   • BTCTurk API (USDT/TRY)                          │
│   • Ehraz.io (Bank Card Verification)               │
└─────────────────────────────────────────────────────┘
```

## 🚀 Deployment Steps

### 1. Server Setup (Ubuntu 22.04 LTS)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip -y

# Install PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# Install Nginx
sudo apt install nginx -y

# Install Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install nodejs -y

# Install Redis (for caching)
sudo apt install redis-server -y
```

### 2. Database Setup

```bash
# Switch to postgres user
sudo -u postgres psql

# In PostgreSQL console:
CREATE DATABASE kiani_exchange;
CREATE USER kiani_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE kiani_exchange TO kiani_user;
\q
```

### 3. Backend Deployment

```bash
# Create project directory
mkdir -p /var/www/kiani-exchange
cd /var/www/kiani-exchange

# Clone or upload your code
git clone https://github.com/yourusername/kiani-exchange.git .
# OR upload files via scp/sftp

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
DATABASE_URL=postgresql://kiani_user:your_secure_password@localhost/kiani_exchange
JWT_SECRET_KEY=$(openssl rand -hex 32)
ADMIN_BOT_TOKEN=8278787504:AAGU4jeKIYq4Kw_FNcgA-7_rb3H152aKxMU
USER_BOT_TOKEN=8509657640:AAG4gNsyvG0xt5ePoFXraBlMUb6hIrWmaWE
ADMIN_CHAT_ID=2043363119
WALLEX_API_KEY=15064|7tVDd4NDBYmATAe4lWTUQSTzj0v7ceTELEv6u6zG
PROXY_URL=http://jjebraham-25:Amir1234@p.webshare.io:80
EHRAZ_API_KEY=5942b9d62abc20405dadfb2c0f546b669cf1471c
EOF

# Initialize database
python -c "from database import init_db; init_db()"

# Create first admin user
python -c "
from database import SessionLocal, Admin
from main import hash_password
db = SessionLocal()
admin = Admin(
    telegram_id=ADMIN_CHAT_ID,
    username='admin',
    email='admin@kiani.com',
    password_hash=hash_password('your_admin_password'),
    full_name='Main Admin',
    role='super_admin'
)
db.add(admin)
db.commit()
print('Admin created successfully')
"
```

### 4. Create Systemd Services

```bash
# FastAPI service
sudo nano /etc/systemd/system/kiani-api.service
```

```ini
[Unit]
Description=Kiani Exchange FastAPI
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/kiani-exchange/backend
Environment="PATH=/var/www/kiani-exchange/backend/venv/bin"
ExecStart=/var/www/kiani-exchange/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# User Bot service
sudo nano /etc/systemd/system/kiani-user-bot.service
```

```ini
[Unit]
Description=Kiani User Telegram Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/kiani-exchange/backend/bots
Environment="PATH=/var/www/kiani-exchange/backend/venv/bin"
ExecStart=/var/www/kiani-exchange/backend/venv/bin/python user_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# Admin Bot service
sudo nano /etc/systemd/system/kiani-admin-bot.service
```

```ini
[Unit]
Description=Kiani Admin Telegram Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/kiani-exchange/backend/bots
Environment="PATH=/var/www/kiani-exchange/backend/venv/bin"
ExecStart=/var/www/kiani-exchange/backend/venv/bin/python admin_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable kiani-api kiani-user-bot kiani-admin-bot
sudo systemctl start kiani-api kiani-user-bot kiani-admin-bot

# Check status
sudo systemctl status kiani-api
sudo systemctl status kiani-user-bot
sudo systemctl status kiani-admin-bot
```

### 5. Frontend Deployment (Mini App)

```bash
cd /var/www/kiani-exchange/frontend/mini-app

# Install dependencies
npm install

# Build for production
npm run build

# Output will be in dist/ folder
```

### 6. Frontend Deployment (Admin Panel)

```bash
cd /var/www/kiani-exchange/frontend/admin-panel

# Install dependencies
npm install

# Build for production
npm run build

# Output will be in dist/ folder
```

### 7. Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/kiani-exchange
```

```nginx
# API Backend
server {
    listen 80;
    server_name kiani.peerexo.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name kiani.peerexo.com;

    # SSL Configuration (obtain via certbot)
    ssl_certificate /etc/letsencrypt/live/kiani.peerexo.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kiani.peerexo.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # API endpoints
    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Mini App
    location / {
        root /var/www/kiani-exchange/frontend/mini-app/dist;
        try_files $uri $uri/ /index.html;

        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
}

# Admin Panel
server {
    listen 80;
    server_name admin.kiani.peerexo.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name admin.kiani.peerexo.com;

    ssl_certificate /etc/letsencrypt/live/admin.kiani.peerexo.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/admin.kiani.peerexo.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Admin Panel
    location / {
        root /var/www/kiani-exchange/frontend/admin-panel/dist;
        try_files $uri $uri/ /index.html;

        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/kiani-exchange /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Obtain SSL certificates
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d kiani.peerexo.com -d admin.kiani.peerexo.com

# Reload Nginx
sudo systemctl reload nginx
```

### 8. Configure Telegram Bot Webhooks (Alternative to Polling)

```python
# In your bot files, add webhook setup:
import requests

WEBHOOK_URL = "https://kiani.peerexo.com"

# For user bot
requests.post(
    f"https://api.telegram.org/bot{USER_BOT_TOKEN}/setWebhook",
    json={"url": f"{WEBHOOK_URL}/webhook/user"}
)

# For admin bot
requests.post(
    f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/setWebhook",
    json={"url": f"{WEBHOOK_URL}/webhook/admin"}
)
```

### 9. Setup Monitoring & Logging

```bash
# Install monitoring tools
sudo apt install prometheus node-exporter grafana -y

# Configure log rotation
sudo nano /etc/logrotate.d/kiani-exchange
```

```
/var/log/kiani-exchange/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload kiani-api kiani-user-bot kiani-admin-bot
    endscript
}
```

### 10. Backup Configuration

```bash
# Create backup script
sudo nano /usr/local/bin/kiani-backup.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/kiani-exchange"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
pg_dump -U kiani_user kiani_exchange | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Backup uploaded files
tar -czf $BACKUP_DIR/files_$DATE.tar.gz /var/www/kiani-exchange/uploads

# Keep only last 30 days
find $BACKUP_DIR -type f -mtime +30 -delete

echo "Backup completed: $DATE"
```

```bash
# Make executable
sudo chmod +x /usr/local/bin/kiani-backup.sh

# Add to crontab (daily at 2 AM)
sudo crontab -e
0 2 * * * /usr/local/bin/kiani-backup.sh >> /var/log/kiani-backup.log 2>&1
```

## 📱 Telegram Mini App Setup

### 1. Register Mini App with BotFather

```
/newapp
Select your bot: @YourUserBot
App name: Kiani Exchange
Short description: صرافی آنلاین کیانی
Photo: (upload app icon)
GIF: (optional)
Web App URL: https://kiani.peerexo.com
```

### 2. Add Menu Button to Bot

```python
# In user_bot.py
from aiogram.types import MenuButtonWebApp, WebAppInfo

async def set_menu_button():
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="🚀 داشبورد",
            web_app=WebAppInfo(url="https://kiani.peerexo.com")
        )
    )

# Call on startup
await set_menu_button()
```

## 🔒 Security Checklist

- [ ] Change all default passwords
- [ ] Set up firewall (ufw)
- [ ] Configure fail2ban
- [ ] Enable SSL/TLS
- [ ] Restrict database access
- [ ] Set up regular backups
- [ ] Configure log monitoring
- [ ] Enable rate limiting
- [ ] Set up intrusion detection
- [ ] Configure CORS properly

## 📊 Performance Optimization

### Redis Caching

```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

async def get_cached_rate(currency_pair):
    cached = redis_client.get(f"rate:{currency_pair}")
    if cached:
        return json.loads(cached)

    # Fetch fresh data
    rate = await fetch_rate(currency_pair)
    redis_client.setex(f"rate:{currency_pair}", 300, json.dumps(rate))
    return rate
```

### Database Indexing

```sql
-- Add indexes for frequently queried columns
CREATE INDEX idx_users_telegram_id ON users(telegram_id);
CREATE INDEX idx_users_kyc_status ON users(kyc_status);
CREATE INDEX idx_transactions_user_id ON transactions(user_id);
CREATE INDEX idx_transactions_status ON transactions(status);
CREATE INDEX idx_transactions_created_at ON transactions(created_at DESC);
```

## 🧪 Testing

```bash
# Run backend tests
cd backend
pytest tests/

# Test API endpoints
curl https://kiani.peerexo.com/api/rates/current

# Test bot responses
# Send /start to your bot
```

## 📈 Monitoring URLs

- Admin Panel: https://admin.kiani.peerexo.com
- Mini App: https://kiani.peerexo.com
- API Health: https://kiani.peerexo.com/api/health
- API Docs: https://kiani.peerexo.com/docs

## 🆘 Troubleshooting

### Bot not responding
```bash
sudo systemctl status kiani-user-bot
sudo journalctl -u kiani-user-bot -f
```

### API errors
```bash
sudo systemctl status kiani-api
sudo tail -f /var/log/nginx/error.log
```

### Database connection issues
```bash
sudo -u postgres psql kiani_exchange
\conninfo
```

## 📝 Maintenance Commands

```bash
# Restart all services
sudo systemctl restart kiani-api kiani-user-bot kiani-admin-bot

# View logs
sudo journalctl -u kiani-api -f
sudo journalctl -u kiani-user-bot -f

# Database backup
sudo -u postgres pg_dump kiani_exchange > backup.sql

# Clear Redis cache
redis-cli FLUSHALL
```

## 🎯 Post-Deployment Checklist

- [ ] Test user registration flow
- [ ] Test KYC approval/rejection
- [ ] Test transaction creation
- [ ] Test admin login
- [ ] Test FAQ management
- [ ] Test broadcast messaging
- [ ] Test price updates
- [ ] Test chatbot responses
- [ ] Test mini app on mobile
- [ ] Test all payment flows
- [ ] Verify SSL certificates
- [ ] Check backup automation
- [ ] Monitor error rates
- [ ] Test emergency procedures

## 📞 Support

For issues or questions:
- Telegram: @TL905411603664
- Email: support@kiani.com
