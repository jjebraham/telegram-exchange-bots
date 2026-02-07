import { useState, useEffect, useCallback } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';

// ── API ──────────────────────────────────────────────────────────────────────
const API_URL = '/api';

async function api(path: string, opts: RequestInit = {}) {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...opts.headers as Record<string, string> };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, { ...opts, headers });
  return res.json();
}

// ── Types ────────────────────────────────────────────────────────────────────
interface User { id: number; first_name: string; last_name: string; phone_number: string; kyc_status: string; reference_code: string; }
interface Rates { usdt_irr: number | null; usdt_try: number | null; try_irr: number | null; }
interface ComputedRates { buy_lira?: number; sell_lira?: number; buy_tether?: number; sell_tether?: number; lira_to_tether?: number; tether_to_lira?: number; }
interface Transaction { id: number; type: string; from_currency: string; to_currency: string; amount: number; rate: number; total: number; status: string; reference_code: string; created_at: string; }
interface ChatMessage { role: 'user' | 'bot'; text: string; }

type Page = 'dashboard' | 'exchange' | 'calculator' | 'history';

// ── Formatters ───────────────────────────────────────────────────────────────
const fmt = (n: number | null | undefined) => n != null ? Math.round(n).toLocaleString('fa-IR') : '---';
const fmtDec = (n: number | null | undefined) => n != null ? n.toLocaleString('fa-IR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '---';

// ── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>('dashboard');
  const [user, setUser] = useState<User | null>(null);
  const [rates, setRates] = useState<Rates>({ usdt_irr: null, usdt_try: null, try_irr: null });
  const [computed, setComputed] = useState<ComputedRates>({});
  const [loading, setLoading] = useState(true);
  const [rateHistory, setRateHistory] = useState<{ date: string; rate: number }[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [showRegister, setShowRegister] = useState(false);
  const [showKYC, setShowKYC] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [faqs, setFaqs] = useState<{ id: number; question_fa: string; answer_fa: string }[]>([]);

  // ── Registration state ──
  const [regForm, setRegForm] = useState({ first_name: '', last_name: '', phone_number: '' });
  // ── KYC state ──
  const [kycForm, setKycForm] = useState({ national_id: '', dob: '', bank_card_number: '' });
  const [kycStep, setKycStep] = useState(0);
  // ── Chat state ──
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');

  // ── Fetch rates ──
  const fetchRates = useCallback(async () => {
    try {
      const data = await api('/rates');
      if (data.status === 'success') {
        setRates(data.raw);
        setComputed(data.computed);
        // Build mock history from current rate
        if (data.raw.usdt_irr) {
          const base = data.raw.usdt_irr / 10;
          const history = [];
          for (let i = 6; i >= 0; i--) {
            const d = new Date();
            d.setDate(d.getDate() - i);
            const variance = (Math.random() - 0.5) * base * 0.03;
            history.push({ date: d.toLocaleDateString('fa-IR', { month: 'short', day: 'numeric' }), rate: Math.round(base + variance) });
          }
          setRateHistory(history);
        }
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  // ── Telegram auth ──
  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
      const tgUser = tg.initDataUnsafe?.user;
      if (tgUser) {
        api('/auth/telegram', {
          method: 'POST',
          body: JSON.stringify({ telegram_id: tgUser.id, first_name: tgUser.first_name, last_name: tgUser.last_name || '' }),
        }).then(data => {
          if (data.status === 'success') {
            localStorage.setItem('token', data.token);
            setUser(data.user);
          }
        });
      }
    }
    // Check existing token
    const token = localStorage.getItem('token');
    if (token) {
      api('/me').then(data => {
        if (data.id) setUser(data as User);
      });
    }
    fetchRates();
    api('/faqs').then(d => { if (d.faqs) setFaqs(d.faqs); });
    const interval = setInterval(fetchRates, 60000);
    return () => clearInterval(interval);
  }, [fetchRates]);

  // ── Load transactions ──
  useEffect(() => {
    if (user && page === 'history') {
      api('/transactions').then(d => { if (d.transactions) setTransactions(d.transactions); });
    }
  }, [user, page]);

  // ── Register handler ──
  const handleRegister = async () => {
    const tg = window.Telegram?.WebApp;
    const tgId = tg?.initDataUnsafe?.user?.id || Date.now();
    const data = await api('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ telegram_id: tgId, ...regForm }),
    });
    if (data.status === 'success') {
      localStorage.setItem('token', data.token);
      setUser(data.user);
      setShowRegister(false);
    }
  };

  // ── KYC handler ──
  const handleKYCSubmit = async () => {
    const data = await api('/kyc/submit', {
      method: 'POST',
      body: JSON.stringify(kycForm),
    });
    if (data.status === 'success') {
      if (user) setUser({ ...user, kyc_status: 'Pending' });
      setShowKYC(false);
      setKycStep(0);
    }
  };

  // ── Chat handler ──
  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const q = chatInput;
    setChatMessages(prev => [...prev, { role: 'user', text: q }]);
    setChatInput('');
    try {
      const data = await api('/chatbot/ask', { method: 'POST', body: JSON.stringify({ question: q }) });
      setChatMessages(prev => [...prev, { role: 'bot', text: data.answer || 'خطا در دریافت پاسخ' }]);
    } catch {
      setChatMessages(prev => [...prev, { role: 'bot', text: 'خطا در ارتباط با سرور' }]);
    }
  };

  // ── Exchange handler ──
  const [exFrom, setExFrom] = useState('IRR');
  const [exTo, setExTo] = useState('TRY');
  const [exAmount, setExAmount] = useState('');

  const getExchangeRate = () => {
    if (exFrom === 'IRR' && exTo === 'TRY') return computed.buy_lira || 0;
    if (exFrom === 'TRY' && exTo === 'IRR') return computed.sell_lira || 0;
    if (exFrom === 'IRR' && exTo === 'USDT') return computed.buy_tether || 0;
    if (exFrom === 'USDT' && exTo === 'IRR') return computed.sell_tether || 0;
    if (exFrom === 'TRY' && exTo === 'USDT') return computed.lira_to_tether || 0;
    if (exFrom === 'USDT' && exTo === 'TRY') return computed.tether_to_lira || 0;
    return 0;
  };

  const submitExchange = async () => {
    const rate = getExchangeRate();
    const amount = parseFloat(exAmount);
    if (!amount || !rate) return;
    const total = amount * rate;
    await api('/transactions', {
      method: 'POST',
      body: JSON.stringify({ type: 'exchange', from_currency: exFrom, to_currency: exTo, amount, rate, total }),
    });
    setExAmount('');
    if (page === 'history') {
      api('/transactions').then(d => { if (d.transactions) setTransactions(d.transactions); });
    }
  };

  // ── Calculator state ──
  const [calcFrom, setCalcFrom] = useState('IRR');
  const [calcTo, setCalcTo] = useState('TRY');
  const [calcAmount, setCalcAmount] = useState('');

  const getCalcResult = () => {
    const amount = parseFloat(calcAmount);
    if (!amount) return 0;
    let rate = 0;
    if (calcFrom === 'IRR' && calcTo === 'TRY' && computed.buy_lira) rate = 1 / computed.buy_lira;
    else if (calcFrom === 'TRY' && calcTo === 'IRR' && computed.sell_lira) rate = computed.sell_lira;
    else if (calcFrom === 'IRR' && calcTo === 'USDT' && computed.buy_tether) rate = 1 / computed.buy_tether;
    else if (calcFrom === 'USDT' && calcTo === 'IRR' && computed.sell_tether) rate = computed.sell_tether;
    else if (calcFrom === 'TRY' && calcTo === 'USDT' && computed.lira_to_tether) rate = 1 / computed.lira_to_tether;
    else if (calcFrom === 'USDT' && calcTo === 'TRY' && computed.tether_to_lira) rate = computed.tether_to_lira;
    return amount * rate;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gradient-to-b from-blue-600 to-blue-800">
        <div className="text-center text-white">
          <div className="animate-spin w-12 h-12 border-4 border-white border-t-transparent rounded-full mx-auto mb-4" />
          <p className="text-lg">صرافی کیانی</p>
        </div>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50 pb-20 font-sans">
      {/* Header */}
      <header className="bg-gradient-to-l from-blue-700 to-blue-900 text-white px-4 py-3 flex items-center justify-between shadow-lg">
        <h1 className="text-lg font-bold">صرافی کیانی</h1>
        <div className="flex gap-2">
          {!user ? (
            <>
              <button onClick={() => setShowRegister(true)} className="bg-white/20 px-3 py-1 rounded-lg text-sm">ثبت نام</button>
              <button onClick={() => {
                const tg = window.Telegram?.WebApp;
                const tgUser = tg?.initDataUnsafe?.user;
                if (tgUser) {
                  api('/auth/telegram', {
                    method: 'POST',
                    body: JSON.stringify({ telegram_id: tgUser.id, first_name: tgUser.first_name, last_name: tgUser.last_name || '' }),
                  }).then(d => { if (d.status === 'success') { localStorage.setItem('token', d.token); setUser(d.user); } });
                }
              }} className="bg-white/20 px-3 py-1 rounded-lg text-sm">ورود</button>
            </>
          ) : (
            <div className="text-sm">
              {user.first_name} {user.last_name}
              <span className={`mr-2 px-2 py-0.5 rounded text-xs ${user.kyc_status === 'Approved' ? 'bg-green-500' : user.kyc_status === 'Rejected' ? 'bg-red-500' : 'bg-yellow-500'}`}>
                {user.kyc_status === 'Approved' ? 'تایید شده' : user.kyc_status === 'Rejected' ? 'رد شده' : 'در انتظار'}
              </span>
            </div>
          )}
        </div>
      </header>

      {/* Page Content */}
      <main className="px-4 py-4 max-w-lg mx-auto">
        {/* ── Dashboard ── */}
        {page === 'dashboard' && (
          <div className="space-y-4">
            {/* Welcome */}
            {user && (
              <div className="bg-white rounded-xl p-4 shadow-sm">
                <p className="text-gray-600">خوش آمدید، <span className="font-bold text-gray-800">{user.first_name}</span></p>
                {user.kyc_status !== 'Approved' && (
                  <button onClick={() => setShowKYC(true)} className="mt-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm w-full">
                    تکمیل احراز هویت
                  </button>
                )}
              </div>
            )}

            {/* Live Rates */}
            <div className="bg-white rounded-xl p-4 shadow-sm">
              <h2 className="font-bold text-gray-800 mb-3 text-base">نرخ لحظه‌ای</h2>
              <div className="grid grid-cols-1 gap-3">
                <div className="bg-blue-50 rounded-lg p-3 flex justify-between items-center">
                  <span className="text-sm text-gray-600">USDT / تومان</span>
                  <span className="font-bold text-blue-700">{fmt(rates.usdt_irr ? rates.usdt_irr / 10 : null)}</span>
                </div>
                <div className="bg-green-50 rounded-lg p-3 flex justify-between items-center">
                  <span className="text-sm text-gray-600">USDT / لیر</span>
                  <span className="font-bold text-green-700">{fmtDec(rates.usdt_try)}</span>
                </div>
                <div className="bg-purple-50 rounded-lg p-3 flex justify-between items-center">
                  <span className="text-sm text-gray-600">لیر / تومان</span>
                  <span className="font-bold text-purple-700">{fmt(rates.try_irr ? rates.try_irr / 10 : null)}</span>
                </div>
              </div>
            </div>

            {/* Quick Actions */}
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => { setPage('exchange'); setExFrom('IRR'); setExTo('TRY'); }} className="bg-green-600 text-white rounded-xl p-4 text-center shadow-sm">
                <div className="text-2xl mb-1">💰</div>
                <div className="text-sm font-medium">خرید لیر</div>
              </button>
              <button onClick={() => { setPage('exchange'); setExFrom('TRY'); setExTo('IRR'); }} className="bg-orange-600 text-white rounded-xl p-4 text-center shadow-sm">
                <div className="text-2xl mb-1">💱</div>
                <div className="text-sm font-medium">فروش لیر</div>
              </button>
              <button onClick={() => { setPage('exchange'); setExFrom('IRR'); setExTo('USDT'); }} className="bg-blue-600 text-white rounded-xl p-4 text-center shadow-sm">
                <div className="text-2xl mb-1">🪙</div>
                <div className="text-sm font-medium">خرید تتر</div>
              </button>
              <button onClick={() => { setPage('exchange'); setExFrom('USDT'); setExTo('IRR'); }} className="bg-red-600 text-white rounded-xl p-4 text-center shadow-sm">
                <div className="text-2xl mb-1">📤</div>
                <div className="text-sm font-medium">فروش تتر</div>
              </button>
            </div>

            {/* Rate Chart */}
            {rateHistory.length > 0 && (
              <div className="bg-white rounded-xl p-4 shadow-sm">
                <h2 className="font-bold text-gray-800 mb-3 text-base">نمودار USDT / تومان (۷ روز)</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={rateHistory}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} tickFormatter={v => (v / 1000).toFixed(0) + 'k'} />
                    <Tooltip formatter={(v: number) => [v.toLocaleString('fa-IR') + ' تومان', 'نرخ']} />
                    <Line type="monotone" dataKey="rate" stroke="#2563eb" strokeWidth={2} dot={{ r: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* FAQ */}
            {faqs.length > 0 && (
              <div className="bg-white rounded-xl p-4 shadow-sm">
                <h2 className="font-bold text-gray-800 mb-3 text-base">سوالات متداول</h2>
                <div className="space-y-2">
                  {faqs.map(f => (
                    <details key={f.id} className="bg-gray-50 rounded-lg">
                      <summary className="p-3 cursor-pointer text-sm font-medium text-gray-700">{f.question_fa}</summary>
                      <p className="px-3 pb-3 text-sm text-gray-600 leading-relaxed">{f.answer_fa}</p>
                    </details>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Exchange ── */}
        {page === 'exchange' && (
          <div className="space-y-4">
            <div className="bg-white rounded-xl p-4 shadow-sm">
              <h2 className="font-bold text-gray-800 mb-4 text-base">صرافی</h2>
              <div className="space-y-4">
                <div>
                  <label className="text-sm text-gray-600 block mb-1">از ارز</label>
                  <select value={exFrom} onChange={e => setExFrom(e.target.value)} className="w-full border rounded-lg p-3 text-sm bg-gray-50">
                    <option value="IRR">ریال ایران (IRR)</option>
                    <option value="TRY">لیر ترکیه (TRY)</option>
                    <option value="USDT">تتر (USDT)</option>
                  </select>
                </div>
                <div className="flex justify-center">
                  <button onClick={() => { const t = exFrom; setExFrom(exTo); setExTo(t); }} className="bg-blue-100 p-2 rounded-full">
                    <span className="text-xl">🔄</span>
                  </button>
                </div>
                <div>
                  <label className="text-sm text-gray-600 block mb-1">به ارز</label>
                  <select value={exTo} onChange={e => setExTo(e.target.value)} className="w-full border rounded-lg p-3 text-sm bg-gray-50">
                    <option value="IRR">ریال ایران (IRR)</option>
                    <option value="TRY">لیر ترکیه (TRY)</option>
                    <option value="USDT">تتر (USDT)</option>
                  </select>
                </div>
                <div>
                  <label className="text-sm text-gray-600 block mb-1">مبلغ</label>
                  <input
                    type="number"
                    value={exAmount}
                    onChange={e => setExAmount(e.target.value)}
                    placeholder="مبلغ را وارد کنید"
                    className="w-full border rounded-lg p-3 text-sm bg-gray-50"
                  />
                </div>

                {getExchangeRate() > 0 && (
                  <div className="bg-blue-50 rounded-lg p-3">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">نرخ تبدیل:</span>
                      <span className="font-bold text-blue-700">{fmt(getExchangeRate())}</span>
                    </div>
                    {exAmount && (
                      <div className="flex justify-between text-sm mt-2">
                        <span className="text-gray-600">مبلغ نهایی:</span>
                        <span className="font-bold text-green-700">{fmt(parseFloat(exAmount) * getExchangeRate())}</span>
                      </div>
                    )}
                  </div>
                )}

                <button
                  onClick={submitExchange}
                  disabled={!user || !exAmount || getExchangeRate() === 0}
                  className="w-full bg-blue-600 text-white py-3 rounded-lg text-sm font-medium disabled:opacity-50"
                >
                  {!user ? 'ابتدا وارد شوید' : 'ثبت سفارش'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Calculator ── */}
        {page === 'calculator' && (
          <div className="space-y-4">
            <div className="bg-white rounded-xl p-4 shadow-sm">
              <h2 className="font-bold text-gray-800 mb-4 text-base">ماشین حساب ارزی</h2>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">از</label>
                    <select value={calcFrom} onChange={e => setCalcFrom(e.target.value)} className="w-full border rounded-lg p-2.5 text-sm bg-gray-50">
                      <option value="IRR">تومان</option>
                      <option value="TRY">لیر</option>
                      <option value="USDT">تتر</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">به</label>
                    <select value={calcTo} onChange={e => setCalcTo(e.target.value)} className="w-full border rounded-lg p-2.5 text-sm bg-gray-50">
                      <option value="IRR">تومان</option>
                      <option value="TRY">لیر</option>
                      <option value="USDT">تتر</option>
                    </select>
                  </div>
                </div>
                <input
                  type="number"
                  value={calcAmount}
                  onChange={e => setCalcAmount(e.target.value)}
                  placeholder="مبلغ"
                  className="w-full border rounded-lg p-3 text-sm bg-gray-50"
                />
                {calcAmount && (
                  <div className="bg-gradient-to-l from-blue-50 to-green-50 rounded-lg p-4 text-center">
                    <p className="text-sm text-gray-500">نتیجه</p>
                    <p className="text-2xl font-bold text-blue-700 mt-1">{fmtDec(getCalcResult())}</p>
                    <p className="text-xs text-gray-400 mt-1">{calcTo === 'IRR' ? 'تومان' : calcTo === 'TRY' ? 'لیر' : 'تتر'}</p>
                  </div>
                )}
              </div>
            </div>

            {/* Fee info */}
            <div className="bg-white rounded-xl p-4 shadow-sm">
              <h3 className="font-bold text-gray-800 mb-2 text-sm">کارمزدها</h3>
              <div className="space-y-2 text-sm text-gray-600">
                <div className="flex justify-between"><span>خرید لیر</span><span className="text-blue-600">۲٪</span></div>
                <div className="flex justify-between"><span>فروش لیر</span><span className="text-blue-600">۳٪</span></div>
                <div className="flex justify-between"><span>خرید تتر</span><span className="text-blue-600">۱٪</span></div>
                <div className="flex justify-between"><span>فروش تتر</span><span className="text-blue-600">۱٪</span></div>
              </div>
            </div>
          </div>
        )}

        {/* ── History ── */}
        {page === 'history' && (
          <div className="space-y-4">
            <div className="bg-white rounded-xl p-4 shadow-sm">
              <h2 className="font-bold text-gray-800 mb-3 text-base">تاریخچه تراکنش‌ها</h2>
              {!user ? (
                <p className="text-sm text-gray-500 text-center py-8">ابتدا وارد حساب کاربری شوید</p>
              ) : transactions.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-8">تراکنشی یافت نشد</p>
              ) : (
                <div className="space-y-3">
                  {transactions.map(tx => (
                    <div key={tx.id} className="bg-gray-50 rounded-lg p-3">
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="text-sm font-medium text-gray-800">{tx.from_currency} → {tx.to_currency}</p>
                          <p className="text-xs text-gray-500 mt-0.5">کد: {tx.reference_code}</p>
                        </div>
                        <span className={`text-xs px-2 py-1 rounded ${tx.status === 'completed' ? 'bg-green-100 text-green-700' : tx.status === 'pending' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>
                          {tx.status === 'completed' ? 'تکمیل' : tx.status === 'pending' ? 'در انتظار' : 'لغو شده'}
                        </span>
                      </div>
                      <div className="flex justify-between mt-2 text-xs text-gray-500">
                        <span>مبلغ: {fmt(tx.amount)}</span>
                        <span>نرخ: {fmt(tx.rate)}</span>
                      </div>
                      <p className="text-xs text-gray-400 mt-1">{new Date(tx.created_at).toLocaleDateString('fa-IR')}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* ── Registration Modal ── */}
      {showRegister && (
        <div className="fixed inset-0 bg-black/50 flex items-end z-50">
          <div className="bg-white w-full rounded-t-2xl p-6 max-h-[80vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-4">
              <h2 className="font-bold text-lg">ثبت نام</h2>
              <button onClick={() => setShowRegister(false)} className="text-gray-400 text-xl">&times;</button>
            </div>
            <div className="space-y-3">
              <input value={regForm.first_name} onChange={e => setRegForm(p => ({ ...p, first_name: e.target.value }))} placeholder="نام" className="w-full border rounded-lg p-3 text-sm" />
              <input value={regForm.last_name} onChange={e => setRegForm(p => ({ ...p, last_name: e.target.value }))} placeholder="نام خانوادگی" className="w-full border rounded-lg p-3 text-sm" />
              <input value={regForm.phone_number} onChange={e => setRegForm(p => ({ ...p, phone_number: e.target.value }))} placeholder="شماره تلفن (مثال: +989121234567)" className="w-full border rounded-lg p-3 text-sm" dir="ltr" />
              <button onClick={handleRegister} className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium">ثبت نام</button>
            </div>
          </div>
        </div>
      )}

      {/* ── KYC Modal ── */}
      {showKYC && (
        <div className="fixed inset-0 bg-black/50 flex items-end z-50">
          <div className="bg-white w-full rounded-t-2xl p-6 max-h-[80vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-4">
              <h2 className="font-bold text-lg">احراز هویت</h2>
              <button onClick={() => { setShowKYC(false); setKycStep(0); }} className="text-gray-400 text-xl">&times;</button>
            </div>
            {/* Step indicator */}
            <div className="flex gap-2 mb-4">
              {[0, 1, 2].map(s => (
                <div key={s} className={`flex-1 h-1.5 rounded ${s <= kycStep ? 'bg-blue-600' : 'bg-gray-200'}`} />
              ))}
            </div>
            {kycStep === 0 && (
              <div className="space-y-3">
                <p className="text-sm text-gray-600 mb-2">کد ملی خود را وارد کنید (۱۰ رقم)</p>
                <input value={kycForm.national_id} onChange={e => setKycForm(p => ({ ...p, national_id: e.target.value }))} placeholder="کد ملی" className="w-full border rounded-lg p-3 text-sm" dir="ltr" />
                <button onClick={() => setKycStep(1)} disabled={kycForm.national_id.length < 10} className="w-full bg-blue-600 text-white py-3 rounded-lg disabled:opacity-50">مرحله بعد</button>
              </div>
            )}
            {kycStep === 1 && (
              <div className="space-y-3">
                <p className="text-sm text-gray-600 mb-2">تاریخ تولد (مثال: 13650626)</p>
                <input value={kycForm.dob} onChange={e => setKycForm(p => ({ ...p, dob: e.target.value }))} placeholder="تاریخ تولد" className="w-full border rounded-lg p-3 text-sm" dir="ltr" />
                <button onClick={() => setKycStep(2)} disabled={kycForm.dob.length < 8} className="w-full bg-blue-600 text-white py-3 rounded-lg disabled:opacity-50">مرحله بعد</button>
              </div>
            )}
            {kycStep === 2 && (
              <div className="space-y-3">
                <p className="text-sm text-gray-600 mb-2">شماره کارت بانکی (۱۶ رقم)</p>
                <input value={kycForm.bank_card_number} onChange={e => setKycForm(p => ({ ...p, bank_card_number: e.target.value }))} placeholder="شماره کارت" className="w-full border rounded-lg p-3 text-sm" dir="ltr" />
                <button onClick={handleKYCSubmit} disabled={kycForm.bank_card_number.length < 16} className="w-full bg-green-600 text-white py-3 rounded-lg disabled:opacity-50">ارسال مدارک</button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Chat Modal ── */}
      {showChat && (
        <div className="fixed inset-0 bg-black/50 flex items-end z-50">
          <div className="bg-white w-full rounded-t-2xl max-h-[80vh] flex flex-col">
            <div className="flex justify-between items-center p-4 border-b">
              <h2 className="font-bold">پشتیبانی هوشمند</h2>
              <button onClick={() => setShowChat(false)} className="text-gray-400 text-xl">&times;</button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-[200px]">
              {chatMessages.length === 0 && <p className="text-sm text-gray-400 text-center">سوال خود را بپرسید</p>}
              {chatMessages.map((m, i) => (
                <div key={i} className={`flex ${m.role === 'user' ? 'justify-start' : 'justify-end'}`}>
                  <div className={`max-w-[80%] p-3 rounded-xl text-sm ${m.role === 'user' ? 'bg-blue-100 text-blue-900' : 'bg-gray-100 text-gray-800'}`}>
                    {m.text}
                  </div>
                </div>
              ))}
            </div>
            <div className="p-4 border-t flex gap-2">
              <input
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendChat()}
                placeholder="سوال خود را بنویسید..."
                className="flex-1 border rounded-lg p-2.5 text-sm"
              />
              <button onClick={sendChat} className="bg-blue-600 text-white px-4 rounded-lg text-sm">ارسال</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Chat FAB ── */}
      <button
        onClick={() => setShowChat(true)}
        className="fixed left-4 bottom-24 w-14 h-14 bg-blue-600 text-white rounded-full shadow-lg flex items-center justify-center text-2xl z-40 hover:bg-blue-700"
      >
        💬
      </button>

      {/* ── Bottom Navigation ── */}
      <nav className="fixed bottom-0 left-0 right-0 bg-white border-t flex justify-around py-2 z-30">
        {([
          { key: 'dashboard' as Page, label: 'داشبورد', icon: '🏠' },
          { key: 'exchange' as Page, label: 'صرافی', icon: '💱' },
          { key: 'calculator' as Page, label: 'ماشین حساب', icon: '🧮' },
          { key: 'history' as Page, label: 'تاریخچه', icon: '📋' },
        ]).map(item => (
          <button
            key={item.key}
            onClick={() => setPage(item.key)}
            className={`flex flex-col items-center px-3 py-1 ${page === item.key ? 'text-blue-600' : 'text-gray-400'}`}
          >
            <span className="text-xl">{item.icon}</span>
            <span className="text-xs mt-0.5">{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
