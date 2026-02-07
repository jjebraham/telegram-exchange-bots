# Deployment Guide

## Frontend Deployment

### Prerequisites

- Node.js 20+ installed
- npm or yarn
- Supervisor installed and configured

### Setup Steps

#### 1. Install Frontend Dependencies

```bash
# Mini App
cd /home/kianirad2020/telegram_bot_repo/kiani-exchange/frontend/mini-app
npm install

# Admin Panel
cd /home/kianirad2020/telegram_bot_repo/kiani-exchange/frontend/admin-panel
npm install
```

#### 2. Configure Supervisor

```bash
# Copy configuration files
sudo cp kiani-exchange/deploy/supervisor/kiani_miniapp.conf /etc/supervisor/conf.d/
sudo cp kiani-exchange/deploy/supervisor/kiani_adminpanel.conf /etc/supervisor/conf.d/

# Create log files
sudo touch /var/log/kiani_miniapp.out.log /var/log/kiani_miniapp.err.log
sudo touch /var/log/kiani_adminpanel.out.log /var/log/kiani_adminpanel.err.log
sudo chown kianirad2020:kianirad2020 /var/log/kiani_*.log

# Update Supervisor
sudo supervisorctl reread
sudo supervisorctl update

# Start services
sudo supervisorctl start kiani_miniapp kiani_adminpanel
```

#### 3. Verify Services

```bash
# Check Supervisor status
sudo supervisorctl status

# Test endpoints
curl -I http://127.0.0.1:5173/
curl -I http://127.0.0.1:5174/

# Check logs
sudo tail -f /var/log/kiani_miniapp.out.log
```

### Production Build

For production deployment:

```bash
# Build Mini App
cd kiani-exchange/frontend/mini-app
npm run build
# Output: dist/

# Build Admin Panel
cd kiani-exchange/frontend/admin-panel
npm run build
# Output: dist/

# Serve with Nginx (see Nginx configuration section)
```

### Port Configuration Summary

| Service | Port | Supervisor Program | Purpose |
|---------|------|-------------------|---------|
| Backend API | 8000 | `kiani_api` | FastAPI server |
| Mini App | 5173 | `kiani_miniapp` | User Telegram Mini App |
| Admin Panel | 5174 | `kiani_adminpanel` | Admin dashboard |

### Troubleshooting

**Frontend not accessible:**
```bash
# Check if npm is running
ps aux | grep npm

# Check if ports are in use
sudo netstat -tulpn | grep -E '5173|5174'

# Restart services
sudo supervisorctl restart kiani_miniapp kiani_adminpanel

# Check for errors
sudo tail -100 /var/log/kiani_miniapp.err.log
```

**Build errors:**
```bash
# Clear node_modules and reinstall
cd kiani-exchange/frontend/mini-app
rm -rf node_modules package-lock.json
npm install

# Verify Node version
node --version  # Should be 20+
```
