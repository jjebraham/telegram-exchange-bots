#!/bin/bash
# Start all Kiani Exchange services

echo "Starting all Kiani Exchange services..."

sudo supervisorctl start kiani_api
sudo supervisorctl start kiani_user_bot
sudo supervisorctl start kiani_admin_bot
sudo supervisorctl start kiani_miniapp
sudo supervisorctl start kiani_adminpanel

echo ""
echo "All services started!"
echo ""
sudo supervisorctl status | grep kiani
