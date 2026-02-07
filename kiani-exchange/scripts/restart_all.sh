#!/bin/bash
# Restart all Kiani Exchange services

echo "Restarting all Kiani Exchange services..."

sudo supervisorctl restart kiani_api
sudo supervisorctl restart kiani_user_bot
sudo supervisorctl restart kiani_admin_bot
sudo supervisorctl restart kiani_miniapp
sudo supervisorctl restart kiani_adminpanel

echo ""
echo "All services restarted!"
echo ""
sudo supervisorctl status | grep kiani
