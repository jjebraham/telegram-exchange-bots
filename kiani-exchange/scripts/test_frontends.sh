#!/bin/bash

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Testing Kiani Exchange Frontends..."
echo ""

# Test API
echo -n "Testing API (port 8000)... "
if curl -s -I http://127.0.0.1:8000/docs | grep -q "200 OK"; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
fi

# Test Mini App
echo -n "Testing Mini App (port 5173)... "
if curl -s -I http://127.0.0.1:5173/ | grep -q "200 OK"; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
fi

# Test Admin Panel
echo -n "Testing Admin Panel (port 5174)... "
if curl -s -I http://127.0.0.1:5174/ | grep -q "200 OK"; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
fi

echo ""
echo "Supervisor Status:"
sudo supervisorctl status | grep kiani

echo ""
echo "Frontend testing complete!"
