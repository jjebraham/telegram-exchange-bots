#!/bin/bash
# Check status of all Kiani Exchange services

echo "Kiani Exchange Services Status"
echo "=================================="
sudo supervisorctl status | grep kiani
echo ""
echo "Service URLs:"
echo "  API:          http://localhost:8000/docs"
echo "  Mini App:     http://localhost:5173"
echo "  Admin Panel:  http://localhost:5174"
echo ""
echo "Check logs:"
echo "  sudo tail -f /var/log/kiani_api.out.log"
echo "  sudo tail -f /var/log/kiani_miniapp.out.log"
echo "  sudo tail -f /var/log/kiani_adminpanel.out.log"
