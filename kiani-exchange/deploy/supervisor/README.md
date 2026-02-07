# Supervisor Configuration for Kiani Exchange

## Installation

1. Copy configuration files:
```bash
sudo cp kiani-exchange/deploy/supervisor/kiani_miniapp.conf /etc/supervisor/conf.d/
sudo cp kiani-exchange/deploy/supervisor/kiani_adminpanel.conf /etc/supervisor/conf.d/
```

2. Create log files:
```bash
sudo touch /var/log/kiani_miniapp.out.log /var/log/kiani_miniapp.err.log
sudo touch /var/log/kiani_adminpanel.out.log /var/log/kiani_adminpanel.err.log
sudo chown kianirad2020:kianirad2020 /var/log/kiani_*.log
```

3. Update Supervisor:
```bash
sudo supervisorctl reread
sudo supervisorctl update
```

4. Start services:
```bash
sudo supervisorctl start kiani_miniapp
sudo supervisorctl start kiani_adminpanel
```

## Management Commands

```bash
# Check status
sudo supervisorctl status

# Restart services
sudo supervisorctl restart kiani_miniapp
sudo supervisorctl restart kiani_adminpanel

# Stop services
sudo supervisorctl stop kiani_miniapp kiani_adminpanel

# View logs
sudo tail -f /var/log/kiani_miniapp.out.log
sudo tail -f /var/log/kiani_adminpanel.err.log
```

## Troubleshooting

If services fail to start:
1. Check npm is installed globally
2. Verify node_modules are installed
3. Check log files for errors
4. Ensure ports 5173 and 5174 are not in use
