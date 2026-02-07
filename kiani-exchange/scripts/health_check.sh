#!/bin/bash
# Health check for all Kiani Exchange services

echo "Running health checks..."
echo ""

check_service() {
    local name="$1"
    local url="$2"
    if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200"; then
        echo "  [OK]     $name"
    else
        echo "  [FAIL]   $name"
    fi
}

check_service "API (8000)" "http://127.0.0.1:8000/health"
check_service "Mini App (5173)" "http://127.0.0.1:5173/"
check_service "Admin Panel (5174)" "http://127.0.0.1:5174/"

echo ""
echo "Supervisor status:"
sudo supervisorctl status | grep kiani
