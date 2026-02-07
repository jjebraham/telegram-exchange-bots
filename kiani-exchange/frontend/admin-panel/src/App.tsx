import { useState, useEffect, useCallback } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';

// ── API ──────────────────────────────────────────────────────────────────────
const API_URL = '/api';

async function api(path: string, opts: RequestInit = {}) {
  const token = localStorage.getItem('admin_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...opts.headers as Record<string, string> };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, { ...opts, headers });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem('admin_token');
    window.location.reload();
    throw new Error('Unauthorized');
  }
  return res.json();
}

type Page = 'dashboard' | 'users' | 'kyc' | 'faqs' | 'chatbot' | 'broadcast' | 'transactions' | 'settings' | 'logs';

const COLORS = ['#3b82f6', '#22c55e', '#ef4444', '#f59e0b'];

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [loggedIn, setLoggedIn] = useState(!!localStorage.getItem('admin_token'));
  const [page, setPage] = useState<Page>('dashboard');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Login
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');

  // Stats
  const [stats, setStats] = useState<Record<string, number>>({});

  // Users
  const [users, setUsers] = useState<any[]>([]);
  const [usersPage, setUsersPage] = useState(1);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersSearch, setUsersSearch] = useState('');
  const [usersKycFilter, setUsersKycFilter] = useState('');

  // KYC
  const [pendingKyc, setPendingKyc] = useState<any[]>([]);
  const [kycTab, setKycTab] = useState<'pending' | 'approved' | 'rejected'>('pending');
  const [approvedKyc, setApprovedKyc] = useState<any[]>([]);
  const [rejectedKyc, setRejectedKyc] = useState<any[]>([]);

  // FAQs
  const [faqsList, setFaqsList] = useState<any[]>([]);
  const [faqEdit, setFaqEdit] = useState<any | null>(null);
  const [faqForm, setFaqForm] = useState({ question_fa: '', answer_fa: '', question_en: '', answer_en: '', category: 'general', sort_order: 0 });

  // Chatbot logs
  const [chatLogs, setChatLogs] = useState<any[]>([]);
  const [chatLogsPage, setChatLogsPage] = useState(1);

  // Broadcast
  const [broadcastMsg, setBroadcastMsg] = useState('');
  const [broadcastTarget, setBroadcastTarget] = useState('all');
  const [broadcasts, setBroadcasts] = useState<any[]>([]);

  // Transactions
  const [txList, setTxList] = useState<any[]>([]);
  const [txPage, setTxPage] = useState(1);
  const [txTotal, setTxTotal] = useState(0);

  // Activity logs
  const [activityLogs, setActivityLogs] = useState<any[]>([]);

  // ── Login ──
  const handleLogin = async () => {
    setLoginError('');
    try {
      const data = await api('/admin/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      if (data.status === 'success') {
        localStorage.setItem('admin_token', data.token);
        setLoggedIn(true);
      } else {
        setLoginError('نام کاربری یا رمز عبور اشتباه است');
      }
    } catch {
      setLoginError('خطا در ارتباط با سرور');
    }
  };

  const logout = () => {
    localStorage.removeItem('admin_token');
    setLoggedIn(false);
  };

  // ── Data fetchers ──
  const fetchStats = useCallback(async () => {
    try { const d = await api('/admin/stats'); setStats(d); } catch { /* */ }
  }, []);

  const fetchUsers = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page: String(usersPage), limit: '20' });
      if (usersSearch) params.set('search', usersSearch);
      if (usersKycFilter) params.set('kyc_status', usersKycFilter);
      const d = await api(`/users?${params}`);
      setUsers(d.users || []);
      setUsersTotal(d.total || 0);
    } catch { /* */ }
  }, [usersPage, usersSearch, usersKycFilter]);

  const fetchKyc = useCallback(async () => {
    try {
      const [p, a, r] = await Promise.all([api('/kyc/pending'), api('/kyc/approved'), api('/kyc/rejected')]);
      setPendingKyc(p.pending || []);
      setApprovedKyc(a.approved || []);
      setRejectedKyc(r.rejected || []);
    } catch { /* */ }
  }, []);

  const fetchFaqs = useCallback(async () => {
    try { const d = await api('/faqs'); setFaqsList(d.faqs || []); } catch { /* */ }
  }, []);

  const fetchChatLogs = useCallback(async () => {
    try { const d = await api(`/admin/chatbot/logs?page=${chatLogsPage}`); setChatLogs(d.logs || []); } catch { /* */ }
  }, [chatLogsPage]);

  const fetchBroadcasts = useCallback(async () => {
    try { const d = await api('/admin/broadcasts'); setBroadcasts(d.broadcasts || []); } catch { /* */ }
  }, []);

  const fetchTransactions = useCallback(async () => {
    try { const d = await api(`/admin/transactions?page=${txPage}`); setTxList(d.transactions || []); setTxTotal(d.total || 0); } catch { /* */ }
  }, [txPage]);

  const fetchActivityLogs = useCallback(async () => {
    try { const d = await api('/admin/logs'); setActivityLogs(d.logs || []); } catch { /* */ }
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    fetchStats();
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, [loggedIn, fetchStats]);

  useEffect(() => {
    if (!loggedIn) return;
    if (page === 'users') fetchUsers();
    if (page === 'kyc') fetchKyc();
    if (page === 'faqs') fetchFaqs();
    if (page === 'chatbot') fetchChatLogs();
    if (page === 'broadcast') fetchBroadcasts();
    if (page === 'transactions') fetchTransactions();
    if (page === 'logs') fetchActivityLogs();
  }, [loggedIn, page, fetchUsers, fetchKyc, fetchFaqs, fetchChatLogs, fetchBroadcasts, fetchTransactions, fetchActivityLogs]);

  // ── Actions ──
  const approveKyc = async (userId: number) => {
    await api(`/kyc/${userId}/approve`, { method: 'POST' });
    fetchKyc();
    fetchStats();
  };

  const rejectKyc = async (userId: number) => {
    const reason = prompt('دلیل رد:') || '';
    await api(`/kyc/${userId}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
    fetchKyc();
    fetchStats();
  };

  const suspendUser = async (userId: number) => {
    await api(`/users/${userId}/suspend`, { method: 'POST' });
    fetchUsers();
  };

  const activateUser = async (userId: number) => {
    await api(`/users/${userId}/activate`, { method: 'POST' });
    fetchUsers();
  };

  const saveFaq = async () => {
    if (faqEdit) {
      await api(`/admin/faq/${faqEdit.id}`, { method: 'PUT', body: JSON.stringify(faqForm) });
    } else {
      await api('/admin/faq', { method: 'POST', body: JSON.stringify(faqForm) });
    }
    setFaqEdit(null);
    setFaqForm({ question_fa: '', answer_fa: '', question_en: '', answer_en: '', category: 'general', sort_order: 0 });
    fetchFaqs();
  };

  const deleteFaq = async (id: number) => {
    if (!confirm('آیا مطمئن هستید؟')) return;
    await api(`/admin/faq/${id}`, { method: 'DELETE' });
    fetchFaqs();
  };

  const sendBroadcast = async () => {
    if (!broadcastMsg.trim()) return;
    await api('/admin/broadcast', { method: 'POST', body: JSON.stringify({ message: broadcastMsg, target: broadcastTarget }) });
    setBroadcastMsg('');
    fetchBroadcasts();
  };

  // ── Login page ──
  if (!loggedIn) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-800 to-slate-900 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-sm">
          <div className="text-center mb-6">
            <h1 className="text-2xl font-bold text-slate-800">پنل مدیریت</h1>
            <p className="text-sm text-slate-500 mt-1">صرافی کیانی</p>
          </div>
          {loginError && <div className="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-4">{loginError}</div>}
          <div className="space-y-4">
            <input value={username} onChange={e => setUsername(e.target.value)} placeholder="نام کاربری" className="w-full border rounded-lg p-3 text-sm" dir="ltr" />
            <input value={password} onChange={e => setPassword(e.target.value)} type="password" placeholder="رمز عبور" className="w-full border rounded-lg p-3 text-sm" dir="ltr" onKeyDown={e => e.key === 'Enter' && handleLogin()} />
            <button onClick={handleLogin} className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700">ورود</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Sidebar nav items ──
  const navItems: { key: Page; label: string; icon: string }[] = [
    { key: 'dashboard', label: 'داشبورد', icon: '📊' },
    { key: 'users', label: 'کاربران', icon: '👥' },
    { key: 'kyc', label: 'احراز هویت', icon: '🪪' },
    { key: 'faqs', label: 'سوالات متداول', icon: '❓' },
    { key: 'chatbot', label: 'لاگ چت‌بات', icon: '🤖' },
    { key: 'broadcast', label: 'پیام همگانی', icon: '📢' },
    { key: 'transactions', label: 'تراکنش‌ها', icon: '💰' },
    { key: 'settings', label: 'تنظیمات', icon: '⚙️' },
    { key: 'logs', label: 'لاگ فعالیت', icon: '📋' },
  ];

  const kycPieData = [
    { name: 'تایید شده', value: stats.approved_kyc || 0 },
    { name: 'در انتظار', value: stats.pending_kyc || 0 },
    { name: 'رد شده', value: stats.rejected_kyc || 0 },
  ].filter(d => d.value > 0);

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-60' : 'w-16'} bg-slate-800 text-white transition-all duration-200 flex flex-col`}>
        <div className="p-4 border-b border-slate-700 flex items-center justify-between">
          {sidebarOpen && <span className="font-bold text-sm">صرافی کیانی</span>}
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="text-slate-400 hover:text-white">
            {sidebarOpen ? '◀' : '▶'}
          </button>
        </div>
        <nav className="flex-1 py-2">
          {navItems.map(item => (
            <button
              key={item.key}
              onClick={() => setPage(item.key)}
              className={`w-full flex items-center gap-3 px-4 py-3 text-sm hover:bg-slate-700 transition ${page === item.key ? 'bg-slate-700 text-white' : 'text-slate-300'}`}
            >
              <span className="text-lg">{item.icon}</span>
              {sidebarOpen && <span>{item.label}</span>}
            </button>
          ))}
        </nav>
        <button onClick={logout} className="p-4 border-t border-slate-700 text-slate-400 hover:text-red-400 text-sm flex items-center gap-3">
          <span>🚪</span>
          {sidebarOpen && <span>خروج</span>}
        </button>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        {/* Top bar */}
        <header className="bg-white border-b px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-800">{navItems.find(n => n.key === page)?.label}</h2>
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <span className="inline-block w-2 h-2 rounded-full bg-green-500"></span>
            API Online
          </div>
        </header>

        <div className="p-6">
          {/* ── Dashboard ── */}
          {page === 'dashboard' && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label: 'کل کاربران', value: stats.total_users, color: 'blue' },
                  { label: 'KYC در انتظار', value: stats.pending_kyc, color: 'yellow' },
                  { label: 'تراکنش‌ها', value: stats.total_transactions, color: 'green' },
                  { label: 'سوالات چت‌بات', value: stats.total_chats, color: 'purple' },
                ].map(s => (
                  <div key={s.label} className={`bg-white rounded-xl p-5 shadow-sm border-r-4 border-${s.color}-500`}>
                    <p className="text-sm text-slate-500">{s.label}</p>
                    <p className="text-3xl font-bold text-slate-800 mt-1">{s.value ?? 0}</p>
                  </div>
                ))}
              </div>

              {kycPieData.length > 0 && (
                <div className="bg-white rounded-xl p-6 shadow-sm">
                  <h3 className="font-bold text-slate-800 mb-4">وضعیت احراز هویت</h3>
                  <div className="flex items-center gap-8">
                    <ResponsiveContainer width={200} height={200}>
                      <PieChart>
                        <Pie data={kycPieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value">
                          {kycPieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="space-y-2">
                      {kycPieData.map((d, i) => (
                        <div key={d.name} className="flex items-center gap-2 text-sm">
                          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                          <span className="text-slate-600">{d.name}: {d.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div className="bg-white rounded-xl p-5 shadow-sm">
                  <p className="text-sm text-slate-500">KYC تایید شده</p>
                  <p className="text-2xl font-bold text-green-600 mt-1">{stats.approved_kyc ?? 0}</p>
                </div>
                <div className="bg-white rounded-xl p-5 shadow-sm">
                  <p className="text-sm text-slate-500">سوالات متداول</p>
                  <p className="text-2xl font-bold text-blue-600 mt-1">{stats.total_faqs ?? 0}</p>
                </div>
              </div>
            </div>
          )}

          {/* ── Users ── */}
          {page === 'users' && (
            <div className="space-y-4">
              <div className="flex gap-3 flex-wrap">
                <input value={usersSearch} onChange={e => { setUsersSearch(e.target.value); setUsersPage(1); }} placeholder="جستجو..." className="border rounded-lg px-4 py-2 text-sm flex-1 min-w-[200px]" />
                <select value={usersKycFilter} onChange={e => { setUsersKycFilter(e.target.value); setUsersPage(1); }} className="border rounded-lg px-4 py-2 text-sm">
                  <option value="">همه وضعیت‌ها</option>
                  <option value="Pending">در انتظار</option>
                  <option value="Approved">تایید شده</option>
                  <option value="Rejected">رد شده</option>
                </select>
              </div>
              <div className="bg-white rounded-xl shadow-sm overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-right p-3 font-medium text-slate-600">ID</th>
                      <th className="text-right p-3 font-medium text-slate-600">نام</th>
                      <th className="text-right p-3 font-medium text-slate-600">تلفن</th>
                      <th className="text-right p-3 font-medium text-slate-600">KYC</th>
                      <th className="text-right p-3 font-medium text-slate-600">عملیات</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map(u => (
                      <tr key={u.id} className="border-t hover:bg-slate-50">
                        <td className="p-3 font-mono text-xs">{u.id}</td>
                        <td className="p-3">{u.first_name} {u.last_name}</td>
                        <td className="p-3 font-mono text-xs" dir="ltr">{u.phone_number || '-'}</td>
                        <td className="p-3">
                          <span className={`px-2 py-1 rounded text-xs ${u.kyc_status === 'Approved' ? 'bg-green-100 text-green-700' : u.kyc_status === 'Rejected' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'}`}>
                            {u.kyc_status}
                          </span>
                        </td>
                        <td className="p-3">
                          {u.suspended ? (
                            <button onClick={() => activateUser(u.id)} className="text-green-600 text-xs hover:underline">فعال‌سازی</button>
                          ) : (
                            <button onClick={() => suspendUser(u.id)} className="text-red-600 text-xs hover:underline">تعلیق</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex justify-between items-center">
                <p className="text-sm text-slate-500">مجموع: {usersTotal} کاربر</p>
                <div className="flex gap-2">
                  <button onClick={() => setUsersPage(p => Math.max(1, p - 1))} disabled={usersPage <= 1} className="px-3 py-1 border rounded text-sm disabled:opacity-50">قبلی</button>
                  <span className="px-3 py-1 text-sm">صفحه {usersPage}</span>
                  <button onClick={() => setUsersPage(p => p + 1)} disabled={users.length < 20} className="px-3 py-1 border rounded text-sm disabled:opacity-50">بعدی</button>
                </div>
              </div>
            </div>
          )}

          {/* ── KYC ── */}
          {page === 'kyc' && (
            <div className="space-y-4">
              <div className="flex gap-2">
                {(['pending', 'approved', 'rejected'] as const).map(t => (
                  <button key={t} onClick={() => setKycTab(t)} className={`px-4 py-2 rounded-lg text-sm ${kycTab === t ? 'bg-blue-600 text-white' : 'bg-white text-slate-600 border'}`}>
                    {t === 'pending' ? `در انتظار (${pendingKyc.length})` : t === 'approved' ? `تایید شده (${approvedKyc.length})` : `رد شده (${rejectedKyc.length})`}
                  </button>
                ))}
              </div>
              <div className="space-y-3">
                {(kycTab === 'pending' ? pendingKyc : kycTab === 'approved' ? approvedKyc : rejectedKyc).map(u => (
                  <div key={u.id} className="bg-white rounded-xl p-4 shadow-sm">
                    <div className="flex justify-between items-start">
                      <div>
                        <p className="font-bold text-slate-800">{u.first_name} {u.last_name}</p>
                        <p className="text-xs text-slate-500 mt-1">ID: {u.id} | Ref: {u.reference_code}</p>
                        {u.phone_number && <p className="text-xs text-slate-500" dir="ltr">{u.phone_number}</p>}
                        {u.national_id && <p className="text-xs text-slate-500">کد ملی: {u.national_id}</p>}
                      </div>
                      {kycTab === 'pending' && (
                        <div className="flex gap-2">
                          <button onClick={() => approveKyc(u.id)} className="bg-green-600 text-white px-3 py-1.5 rounded-lg text-xs hover:bg-green-700">تایید</button>
                          <button onClick={() => rejectKyc(u.id)} className="bg-red-600 text-white px-3 py-1.5 rounded-lg text-xs hover:bg-red-700">رد</button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {(kycTab === 'pending' ? pendingKyc : kycTab === 'approved' ? approvedKyc : rejectedKyc).length === 0 && (
                  <p className="text-center text-slate-400 py-8">موردی یافت نشد</p>
                )}
              </div>
            </div>
          )}

          {/* ── FAQs ── */}
          {page === 'faqs' && (
            <div className="space-y-4">
              <div className="bg-white rounded-xl p-6 shadow-sm">
                <h3 className="font-bold text-slate-800 mb-4">{faqEdit ? 'ویرایش سوال' : 'سوال جدید'}</h3>
                <div className="space-y-3">
                  <input value={faqForm.question_fa} onChange={e => setFaqForm(p => ({ ...p, question_fa: e.target.value }))} placeholder="سوال (فارسی)" className="w-full border rounded-lg p-3 text-sm" />
                  <textarea value={faqForm.answer_fa} onChange={e => setFaqForm(p => ({ ...p, answer_fa: e.target.value }))} placeholder="پاسخ (فارسی)" className="w-full border rounded-lg p-3 text-sm h-24" />
                  <input value={faqForm.question_en} onChange={e => setFaqForm(p => ({ ...p, question_en: e.target.value }))} placeholder="Question (English)" className="w-full border rounded-lg p-3 text-sm" dir="ltr" />
                  <textarea value={faqForm.answer_en} onChange={e => setFaqForm(p => ({ ...p, answer_en: e.target.value }))} placeholder="Answer (English)" className="w-full border rounded-lg p-3 text-sm h-24" dir="ltr" />
                  <div className="flex gap-3">
                    <select value={faqForm.category} onChange={e => setFaqForm(p => ({ ...p, category: e.target.value }))} className="border rounded-lg px-3 py-2 text-sm">
                      <option value="general">عمومی</option>
                      <option value="registration">ثبت نام</option>
                      <option value="banking">بانکی</option>
                      <option value="payments">پرداخت</option>
                      <option value="tether">تتر</option>
                    </select>
                    <input type="number" value={faqForm.sort_order} onChange={e => setFaqForm(p => ({ ...p, sort_order: parseInt(e.target.value) || 0 }))} placeholder="ترتیب" className="border rounded-lg px-3 py-2 text-sm w-24" />
                    <button onClick={saveFaq} className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm hover:bg-blue-700">{faqEdit ? 'به‌روزرسانی' : 'ذخیره'}</button>
                    {faqEdit && <button onClick={() => { setFaqEdit(null); setFaqForm({ question_fa: '', answer_fa: '', question_en: '', answer_en: '', category: 'general', sort_order: 0 }); }} className="text-slate-500 text-sm hover:underline">انصراف</button>}
                  </div>
                </div>
              </div>
              <div className="space-y-3">
                {faqsList.map(f => (
                  <div key={f.id} className="bg-white rounded-xl p-4 shadow-sm">
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <p className="font-medium text-slate-800">{f.question_fa}</p>
                        <p className="text-sm text-slate-500 mt-1">{f.answer_fa}</p>
                        <div className="flex gap-2 mt-2">
                          <span className="text-xs bg-slate-100 px-2 py-0.5 rounded">{f.category}</span>
                          <span className="text-xs text-slate-400">ترتیب: {f.sort_order}</span>
                        </div>
                      </div>
                      <div className="flex gap-2 mr-4">
                        <button onClick={() => { setFaqEdit(f); setFaqForm({ question_fa: f.question_fa, answer_fa: f.answer_fa, question_en: f.question_en || '', answer_en: f.answer_en || '', category: f.category, sort_order: f.sort_order }); }} className="text-blue-600 text-xs hover:underline">ویرایش</button>
                        <button onClick={() => deleteFaq(f.id)} className="text-red-600 text-xs hover:underline">حذف</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Chatbot Logs ── */}
          {page === 'chatbot' && (
            <div className="space-y-3">
              {chatLogs.map(l => (
                <div key={l.id} className="bg-white rounded-xl p-4 shadow-sm">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-sm text-slate-800"><span className="font-medium">سوال:</span> {l.question}</p>
                      <p className="text-sm text-slate-600 mt-1"><span className="font-medium">پاسخ:</span> {l.answer}</p>
                      <div className="flex gap-3 mt-2 text-xs text-slate-400">
                        <span>کاربر: {l.first_name} {l.last_name}</span>
                        <span>اطمینان: {(l.confidence * 100).toFixed(0)}%</span>
                        <span>{l.helpful === 1 ? '👍' : l.helpful === 0 ? '👎' : '—'}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
              {chatLogs.length === 0 && <p className="text-center text-slate-400 py-8">لاگی یافت نشد</p>}
              <div className="flex justify-center gap-2">
                <button onClick={() => setChatLogsPage(p => Math.max(1, p - 1))} disabled={chatLogsPage <= 1} className="px-3 py-1 border rounded text-sm disabled:opacity-50">قبلی</button>
                <span className="px-3 py-1 text-sm">صفحه {chatLogsPage}</span>
                <button onClick={() => setChatLogsPage(p => p + 1)} className="px-3 py-1 border rounded text-sm">بعدی</button>
              </div>
            </div>
          )}

          {/* ── Broadcast ── */}
          {page === 'broadcast' && (
            <div className="space-y-4">
              <div className="bg-white rounded-xl p-6 shadow-sm">
                <h3 className="font-bold text-slate-800 mb-4">ارسال پیام همگانی</h3>
                <div className="space-y-3">
                  <textarea value={broadcastMsg} onChange={e => setBroadcastMsg(e.target.value)} placeholder="متن پیام..." className="w-full border rounded-lg p-3 text-sm h-32" />
                  <div className="flex gap-3 items-center">
                    <select value={broadcastTarget} onChange={e => setBroadcastTarget(e.target.value)} className="border rounded-lg px-4 py-2 text-sm">
                      <option value="all">همه کاربران</option>
                      <option value="verified">کاربران تایید شده</option>
                      <option value="pending">کاربران در انتظار</option>
                    </select>
                    <button onClick={sendBroadcast} className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm hover:bg-blue-700">ارسال</button>
                  </div>
                </div>
              </div>
              <div className="bg-white rounded-xl shadow-sm overflow-hidden">
                <h3 className="font-bold text-slate-800 p-4 border-b">تاریخچه پیام‌ها</h3>
                <div className="divide-y">
                  {broadcasts.map(b => (
                    <div key={b.id} className="p-4">
                      <p className="text-sm text-slate-800">{b.message}</p>
                      <div className="flex gap-3 mt-2 text-xs text-slate-400">
                        <span>هدف: {b.target}</span>
                        <span>ارسال: {b.sent_count}</span>
                        <span>{b.created_at}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── Transactions ── */}
          {page === 'transactions' && (
            <div className="space-y-4">
              <div className="bg-white rounded-xl shadow-sm overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-right p-3 font-medium text-slate-600">کد</th>
                      <th className="text-right p-3 font-medium text-slate-600">کاربر</th>
                      <th className="text-right p-3 font-medium text-slate-600">نوع</th>
                      <th className="text-right p-3 font-medium text-slate-600">مبلغ</th>
                      <th className="text-right p-3 font-medium text-slate-600">وضعیت</th>
                      <th className="text-right p-3 font-medium text-slate-600">تاریخ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {txList.map(tx => (
                      <tr key={tx.id} className="border-t hover:bg-slate-50">
                        <td className="p-3 font-mono text-xs">{tx.reference_code}</td>
                        <td className="p-3 text-xs">{tx.first_name} {tx.last_name}</td>
                        <td className="p-3 text-xs">{tx.from_currency} → {tx.to_currency}</td>
                        <td className="p-3 text-xs">{tx.amount?.toLocaleString()}</td>
                        <td className="p-3">
                          <span className={`px-2 py-0.5 rounded text-xs ${tx.status === 'completed' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}`}>{tx.status}</span>
                        </td>
                        <td className="p-3 text-xs">{tx.created_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex justify-between items-center">
                <p className="text-sm text-slate-500">مجموع: {txTotal} تراکنش</p>
                <div className="flex gap-2">
                  <button onClick={() => setTxPage(p => Math.max(1, p - 1))} disabled={txPage <= 1} className="px-3 py-1 border rounded text-sm disabled:opacity-50">قبلی</button>
                  <span className="px-3 py-1 text-sm">صفحه {txPage}</span>
                  <button onClick={() => setTxPage(p => p + 1)} disabled={txList.length < 20} className="px-3 py-1 border rounded text-sm disabled:opacity-50">بعدی</button>
                </div>
              </div>
            </div>
          )}

          {/* ── Settings ── */}
          {page === 'settings' && (
            <div className="space-y-4">
              <div className="bg-white rounded-xl p-6 shadow-sm">
                <h3 className="font-bold text-slate-800 mb-4">تنظیمات نرخ</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm text-slate-500 block mb-1">مارجین خرید لیر (%)</label>
                    <input type="number" defaultValue={2} className="w-full border rounded-lg p-2.5 text-sm" />
                  </div>
                  <div>
                    <label className="text-sm text-slate-500 block mb-1">مارجین فروش لیر (%)</label>
                    <input type="number" defaultValue={3} className="w-full border rounded-lg p-2.5 text-sm" />
                  </div>
                  <div>
                    <label className="text-sm text-slate-500 block mb-1">مارجین خرید تتر (%)</label>
                    <input type="number" defaultValue={1} className="w-full border rounded-lg p-2.5 text-sm" />
                  </div>
                  <div>
                    <label className="text-sm text-slate-500 block mb-1">مارجین فروش تتر (%)</label>
                    <input type="number" defaultValue={1} className="w-full border rounded-lg p-2.5 text-sm" />
                  </div>
                </div>
                <button className="mt-4 bg-blue-600 text-white px-6 py-2 rounded-lg text-sm hover:bg-blue-700">ذخیره تنظیمات</button>
              </div>
              <div className="bg-white rounded-xl p-6 shadow-sm">
                <h3 className="font-bold text-slate-800 mb-4">مدیریت ادمین</h3>
                <p className="text-sm text-slate-500">نام کاربری فعلی: <span className="font-mono">admin</span></p>
                <p className="text-sm text-slate-400 mt-2">برای تغییر رمز عبور، متغیر محیطی ADMIN_PASSWORD را تغییر دهید.</p>
              </div>
            </div>
          )}

          {/* ── Activity Logs ── */}
          {page === 'logs' && (
            <div className="space-y-3">
              <div className="bg-white rounded-xl shadow-sm overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-right p-3 font-medium text-slate-600">زمان</th>
                      <th className="text-right p-3 font-medium text-slate-600">ادمین</th>
                      <th className="text-right p-3 font-medium text-slate-600">عملیات</th>
                      <th className="text-right p-3 font-medium text-slate-600">جزئیات</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activityLogs.map(l => (
                      <tr key={l.id} className="border-t hover:bg-slate-50">
                        <td className="p-3 text-xs">{l.created_at}</td>
                        <td className="p-3 text-xs">{l.admin_user}</td>
                        <td className="p-3 text-xs">{l.action}</td>
                        <td className="p-3 text-xs">{l.details}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {activityLogs.length === 0 && <p className="text-center text-slate-400 py-8">لاگی یافت نشد</p>}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
