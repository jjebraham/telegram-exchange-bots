# Testing Checklist

## Mini App
- [ ] Opens in browser at http://localhost:5173
- [ ] Shows real-time rates (USDT/IRR, USDT/TRY, TRY/IRR)
- [ ] Registration form works
- [ ] Login via Telegram WebApp works
- [ ] KYC submission (3-step) works
- [ ] 7-day rate chart displays correctly
- [ ] Calculator converts between all currency pairs
- [ ] Transaction history loads for logged-in users
- [ ] AI chatbot responds to questions
- [ ] Bottom navigation switches between pages
- [ ] Quick action buttons navigate to exchange page

## Admin Panel
- [ ] Login page shows at http://localhost:5174
- [ ] Login with admin/admin123 works
- [ ] Dashboard shows stats (users, KYC, transactions)
- [ ] KYC pie chart displays correctly
- [ ] User list loads with pagination
- [ ] User search works
- [ ] KYC filter works
- [ ] KYC approve/reject works
- [ ] FAQ create/edit/delete works
- [ ] Chatbot logs visible
- [ ] Broadcast send works
- [ ] Transaction list loads
- [ ] Activity logs visible
- [ ] Settings page renders
- [ ] Sidebar collapse/expand works
- [ ] Logout works

## Backend API
- [ ] GET /health returns ok
- [ ] GET /api/rates returns current rates
- [ ] POST /api/auth/telegram authenticates users
- [ ] POST /api/auth/register creates new users
- [ ] POST /api/admin/login authenticates admin
- [ ] GET /api/users returns user list (admin only)
- [ ] GET /api/kyc/pending returns pending KYC
- [ ] POST /api/kyc/{id}/approve works
- [ ] POST /api/kyc/{id}/reject works
- [ ] GET /api/faqs returns FAQ list
- [ ] POST /api/admin/faq creates FAQ
- [ ] PUT /api/admin/faq/{id} updates FAQ
- [ ] DELETE /api/admin/faq/{id} deletes FAQ
- [ ] POST /api/chatbot/ask returns answer
- [ ] POST /api/admin/broadcast creates broadcast
- [ ] GET /api/admin/stats returns statistics
- [ ] GET /api/admin/logs returns activity logs

## Supervisor
- [ ] setup_supervisor.sh copies configs
- [ ] start_all.sh starts all services
- [ ] stop_all.sh stops all services
- [ ] restart_all.sh restarts all services
- [ ] status.sh shows running status
- [ ] health_check.sh validates all endpoints
