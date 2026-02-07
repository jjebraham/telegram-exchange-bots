# Kiani Exchange

A Telegram-based currency exchange platform for trading Iranian Rial, Turkish Lira, and USDT/Tether.

## Quick Start

1. Clone the repository
2. Install dependencies for each service
3. Configure environment variables
4. Start services via Supervisor

## Development Servers & Ports

The Kiani Exchange platform runs on the following ports:

- **Backend API**: `http://localhost:8000`
  - API Docs: `http://localhost:8000/docs`
  - Managed by Supervisor: `kiani_api`

- **Mini App (User Interface)**: `http://localhost:5173`
  - React + Vite development server
  - Managed by Supervisor: `kiani_miniapp`

- **Admin Panel**: `http://localhost:5174`
  - React + Vite development server
  - Managed by Supervisor: `kiani_adminpanel`

## Frontend Setup

### Initial Setup

1. **Install Mini App dependencies:**
```bash
cd kiani-exchange/frontend/mini-app
npm install
```

2. **Install Admin Panel dependencies:**
```bash
cd kiani-exchange/frontend/admin-panel
npm install
```

### Running in Development

**Option 1: Manual (for development)**
```bash
# Terminal 1 - Mini App
cd kiani-exchange/frontend/mini-app
npm run dev

# Terminal 2 - Admin Panel
cd kiani-exchange/frontend/admin-panel
npm run dev
```

**Option 2: Supervisor (for production-like environment)**

See [deploy/supervisor/README.md](deploy/supervisor/README.md) for Supervisor setup.

### Health Checks

```bash
# Check API
curl -I http://127.0.0.1:8000/docs

# Check Mini App
curl -I http://127.0.0.1:5173/

# Check Admin Panel
curl -I http://127.0.0.1:5174/

# Check Supervisor status
sudo supervisorctl status
```

Expected output:
```
kiani_api                        RUNNING   pid 12345, uptime 1:23:45
kiani_miniapp                    RUNNING   pid 12346, uptime 1:23:45
kiani_adminpanel                 RUNNING   pid 12347, uptime 1:23:45
```
