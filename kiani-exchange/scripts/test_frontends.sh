#!/bin/bash

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo "Testing Kiani Exchange Production Setup..."
echo ""

# Test API backend
echo -n "Testing API (localhost:8000)... "
if curl -s -I http://127.0.0.1:8000/docs | grep -q "200"; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
fi

# Test Mini App via Nginx
echo -n "Testing miniapp.peerexo.com... "
if curl -s -I https://miniapp.peerexo.com 2>/dev/null | grep -q "200"; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED (is Nginx running?)${NC}"
fi

# Test Admin Panel via Nginx
echo -n "Testing kianiapp.peerexo.com... "
if curl -s -I https://kianiapp.peerexo.com 2>/dev/null | grep -q "200"; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED (is Nginx running?)${NC}"
fi

# Test API proxy from miniapp
echo -n "Testing /api/faqs via miniapp... "
if curl -s https://miniapp.peerexo.com/api/faqs 2>/dev/null | grep -q "\["; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
fi

# Test API proxy from admin panel
echo -n "Testing /api/faqs via kianiapp... "
if curl -s https://kianiapp.peerexo.com/api/faqs 2>/dev/null | grep -q "\["; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
fi

echo ""
echo "Supervisor Status (API only):"
sudo supervisorctl status kiani_api 2>/dev/null || echo "  supervisorctl not available"

echo ""
echo "Testing complete!"
