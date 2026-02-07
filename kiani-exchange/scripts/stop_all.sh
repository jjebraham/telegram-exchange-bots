#!/bin/bash
# Stop all Kiani Exchange services

echo "Stopping all Kiani Exchange services..."

sudo supervisorctl stop kiani_api
sudo supervisorctl stop kiani_user_bot
sudo supervisorctl stop kiani_admin_bot
sudo supervisorctl stop kiani_miniapp
sudo supervisorctl stop kiani_adminpanel

echo ""
echo "All services stopped!"
