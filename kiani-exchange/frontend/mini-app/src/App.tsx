import { useState, useEffect, useCallback } from 'react';

const API_URL = import.meta.env.VITE_API_URL || '/api';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Rates {
  buy_lira: number;
  sell_lira: number;
  buy_usdt: number;
  sell_usdt: number;
  usdt_to_lira: number;
  lira_to_usdt: number;
  foreign_payment: number;
}

interface User {
  id: number;
  first_name: string;
  last_name: string;
  phone_number: string;
  kyc_status: string;
  verification_level: number;
}

interface Transaction {
  id: number;
  exchange_pair: string;
  reference_number: string;
  send_amount: number;
  receive_amount: number;
  status: string;
  timestamp: string;
}

type TabType = 'dashboard' | 'exchange' | 'register' | 'login' | 'history';

type ExchangeType =
  | 'buy_lira'
  | 'sell_lira'
  | 'buy_usdt'
  | 'sell_usdt'
  | 'convert_usdt_to_lira'
  | 'convert_lira_to_usdt';

// ─── Helper Components ──────────────────────────────────────────────────────

const RateBox = ({
  label,
  rate,
  loading,
}: {
  label: string;
  rate: number | string;
  loading: boolean;
}) => (
  <div className="bg-white rounded-xl p-4 shadow-md mb-3">
    <div className="flex justify-between items-center">
      <span className="text-gray-700 font-semibold text-sm">{label}</span>
      <span className="text-blue-600 font-bold text-lg">
        {loading
          ? '...'
          : typeof rate === 'number'
            ? `${rate.toLocaleString('fa-IR')} تومان`
            : `${rate} لیر`}
      </span>
    </div>
  </div>
);

const ExchangeButton = ({
  label,
  icon,
  color,
  onClick,
  type,
}: {
  label: string;
  icon: string;
  color: string;
  onClick: (type: ExchangeType) => void;
  type: ExchangeType;
}) => (
  <button
    onClick={() => onClick(type)}
    className={`${color} text-white p-6 rounded-2xl shadow-lg hover:shadow-xl transition-all flex flex-col items-center justify-center`}
  >
    <span className="text-3xl mb-2">{icon}</span>
    <span className="font-bold text-lg">{label}</span>
  </button>
);

const InfoRow = ({ label, value }: { label: string; value: string }) => (
  <div className="flex justify-between items-center py-2 border-b border-gray-100">
    <span className="text-sm text-gray-600">{label}:</span>
    <span className="font-semibold text-gray-800">{value}</span>
  </div>
);

// ─── Exchange Pair Labels ───────────────────────────────────────────────────

const EXCHANGE_LABELS: Record<ExchangeType, string> = {
  buy_lira: 'IRR \u2192 TRY',
  sell_lira: 'TRY \u2192 IRR',
  buy_usdt: 'IRR \u2192 USDT',
  sell_usdt: 'USDT \u2192 IRR',
  convert_usdt_to_lira: 'USDT \u2192 TRY',
  convert_lira_to_usdt: 'TRY \u2192 USDT',
};

const EXCHANGE_PERSIAN_LABELS: Record<ExchangeType, string> = {
  buy_lira: '\u062e\u0631\u06cc\u062f \u0644\u06cc\u0631',
  sell_lira: '\u0641\u0631\u0648\u0634 \u0644\u06cc\u0631',
  buy_usdt: '\u062e\u0631\u06cc\u062f \u062a\u062a\u0631',
  sell_usdt: '\u0641\u0631\u0648\u0634 \u062a\u062a\u0631',
  convert_usdt_to_lira: '\u062a\u0628\u062f\u06cc\u0644 \u062a\u062a\u0631 \u0628\u0647 \u0644\u06cc\u0631',
  convert_lira_to_usdt: '\u062a\u0628\u062f\u06cc\u0644 \u0644\u06cc\u0631 \u0628\u0647 \u062a\u062a\u0631',
};

// ─── Main App ───────────────────────────────────────────────────────────────

function App() {
  const [activeTab, setActiveTab] = useState<TabType>('dashboard');
  const [user, setUser] = useState<User | null>(null);
  const [rates, setRates] = useState<Rates>({
    buy_lira: 0,
    sell_lira: 0,
    buy_usdt: 0,
    sell_usdt: 0,
    usdt_to_lira: 0,
    lira_to_usdt: 0,
    foreign_payment: 0,
  });
  const [loading, setLoading] = useState(true);
  const [selectedExchange, setSelectedExchange] = useState<ExchangeType | null>(null);

  // Check for existing session on mount
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      fetchUserProfile(token);
    }
    fetchRates();
    const interval = setInterval(fetchRates, 600000); // refresh every 10 min
    return () => clearInterval(interval);
  }, []);

  const fetchUserProfile = async (token: string) => {
    try {
      const response = await fetch(`${API_URL}/users/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        const data = await response.json();
        setUser(data.user);
      } else {
        localStorage.removeItem('token');
      }
    } catch {
      // silently fail - user just won't be logged in
    }
  };

  const fetchRates = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/rates/current`);
      const data = await response.json();

      const usdt_irr = data.rates.USDT_IRR;
      const usdt_try = data.rates.USDT_TRY;
      const eff_toman = usdt_irr / 10;

      setRates({
        buy_lira: Math.round(((eff_toman / usdt_try) * 1.02) / 10) * 10,
        sell_lira: Math.round(((eff_toman / usdt_try) * 0.97) / 10) * 10,
        buy_usdt: Math.round((eff_toman * 1.01) / 10) * 10,
        sell_usdt: Math.round((eff_toman * 0.99) / 10) * 10,
        usdt_to_lira: parseFloat((usdt_try * 1.02).toFixed(2)),
        lira_to_usdt: parseFloat((usdt_try * 0.98).toFixed(2)),
        foreign_payment: Math.round((eff_toman * 1.05) / 10) * 10,
      });
    } catch (error) {
      console.error('Rate fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleExchangeClick = (exchangeType: ExchangeType) => {
    if (!user || user.kyc_status !== 'Approved') {
      setActiveTab('login');
      return;
    }
    setSelectedExchange(exchangeType);
    setActiveTab('exchange');
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setUser(null);
    setActiveTab('dashboard');
  };

  return (
    <div className="min-h-screen bg-gray-100 pb-20">
      {/* Header */}
      <header className="bg-gradient-to-r from-blue-700 to-purple-700 text-white p-4 shadow-lg">
        <div className="flex justify-between items-center">
          <h1 className="text-xl font-bold">صرافی کیانی</h1>
          {user ? (
            <div className="flex items-center gap-3">
              <span className="text-sm">{user.first_name}</span>
              <button
                onClick={handleLogout}
                className="text-xs bg-white/20 px-3 py-1 rounded-full"
              >
                خروج
              </button>
            </div>
          ) : (
            <button
              onClick={() => setActiveTab('login')}
              className="text-sm bg-white/20 px-4 py-1.5 rounded-full"
            >
              ورود / ثبت نام
            </button>
          )}
        </div>
      </header>

      {/* Main Content */}
      <main>
        {activeTab === 'dashboard' && (
          <DashboardPage
            rates={rates}
            loading={loading}
            onExchangeClick={handleExchangeClick}
            onRefresh={fetchRates}
          />
        )}
        {activeTab === 'exchange' && selectedExchange && (
          <ExchangePage
            rates={rates}
            user={user}
            selectedExchange={selectedExchange}
            onBack={() => setActiveTab('dashboard')}
          />
        )}
        {activeTab === 'register' && (
          <RegistrationPage
            onLoginRedirect={() => setActiveTab('login')}
          />
        )}
        {activeTab === 'login' && (
          <LoginPage
            onSuccess={(loggedUser) => {
              setUser(loggedUser);
              setActiveTab('dashboard');
            }}
            onRegisterRedirect={() => setActiveTab('register')}
          />
        )}
        {activeTab === 'history' && <HistoryPage />}
      </main>

      {/* Bottom Navigation */}
      <nav className="fixed bottom-0 left-0 right-0 bg-white shadow-[0_-2px_10px_rgba(0,0,0,0.1)] border-t border-gray-200">
        <div className="flex justify-around items-center py-2">
          <NavButton
            label="خانه"
            icon="🏠"
            active={activeTab === 'dashboard'}
            onClick={() => setActiveTab('dashboard')}
          />
          <NavButton
            label="تاریخچه"
            icon="📋"
            active={activeTab === 'history'}
            onClick={() => {
              if (!user) {
                setActiveTab('login');
              } else {
                setActiveTab('history');
              }
            }}
          />
          <NavButton
            label={user ? 'پروفایل' : 'ورود'}
            icon={user ? '👤' : '🔑'}
            active={activeTab === 'login' || activeTab === 'register'}
            onClick={() => setActiveTab(user ? 'dashboard' : 'login')}
          />
        </div>
      </nav>
    </div>
  );
}

// ─── Navigation Button ──────────────────────────────────────────────────────

function NavButton({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center px-4 py-1 ${
        active ? 'text-blue-600' : 'text-gray-500'
      }`}
    >
      <span className="text-xl">{icon}</span>
      <span className="text-xs mt-1 font-medium">{label}</span>
    </button>
  );
}

// ─── PART 1 & 2: Dashboard Page ─────────────────────────────────────────────

function DashboardPage({
  rates,
  loading,
  onExchangeClick,
  onRefresh,
}: {
  rates: Rates;
  loading: boolean;
  onExchangeClick: (type: ExchangeType) => void;
  onRefresh: () => void;
}) {
  return (
    <div>
      {/* Rates Section */}
      <div className="p-4">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold text-gray-800">نرخ لحظه‌ای</h2>
          <button
            onClick={onRefresh}
            className="text-sm text-blue-600 bg-blue-50 px-3 py-1 rounded-full"
          >
            بروزرسانی
          </button>
        </div>

        <RateBox label="نرخ خرید لیر از ما" rate={rates.buy_lira} loading={loading} />
        <RateBox label="نرخ فروش لیر به ما" rate={rates.sell_lira} loading={loading} />
        <RateBox label="نرخ خرید تتر از ما" rate={rates.buy_usdt} loading={loading} />
        <RateBox label="نرخ فروش تتر به ما" rate={rates.sell_usdt} loading={loading} />
        <RateBox label="تبدیل تتر به لیر" rate={rates.usdt_to_lira} loading={loading} />
        <RateBox label="تبدیل لیر به تتر" rate={rates.lira_to_usdt} loading={loading} />
        <RateBox
          label="نرخ دلار خرید از سایت‌های خارجی"
          rate={rates.foreign_payment}
          loading={loading}
        />
      </div>

      {/* Action Buttons */}
      <div className="grid grid-cols-2 gap-4 p-4">
        <ExchangeButton
          label="خرید لیر"
          icon="💰"
          color="bg-gradient-to-br from-green-500 to-emerald-600"
          onClick={onExchangeClick}
          type="buy_lira"
        />
        <ExchangeButton
          label="فروش لیر"
          icon="💸"
          color="bg-gradient-to-br from-red-500 to-pink-600"
          onClick={onExchangeClick}
          type="sell_lira"
        />
        <ExchangeButton
          label="خرید تتر"
          icon="🪙"
          color="bg-gradient-to-br from-blue-500 to-indigo-600"
          onClick={onExchangeClick}
          type="buy_usdt"
        />
        <ExchangeButton
          label="فروش تتر"
          icon="💵"
          color="bg-gradient-to-br from-orange-500 to-amber-600"
          onClick={onExchangeClick}
          type="sell_usdt"
        />
        <ExchangeButton
          label="تبدیل تتر به لیر"
          icon="🔄"
          color="bg-gradient-to-br from-purple-500 to-violet-600"
          onClick={onExchangeClick}
          type="convert_usdt_to_lira"
        />
        <ExchangeButton
          label="تبدیل لیر به تتر"
          icon="🔁"
          color="bg-gradient-to-br from-teal-500 to-cyan-600"
          onClick={onExchangeClick}
          type="convert_lira_to_usdt"
        />
      </div>
    </div>
  );
}

// ─── PART 3: Exchange Page ──────────────────────────────────────────────────

function ExchangePage({
  rates,
  user,
  selectedExchange,
  onBack,
}: {
  rates: Rates;
  user: User | null;
  selectedExchange: ExchangeType;
  onBack: () => void;
}) {
  const [amount, setAmount] = useState('');
  const [receiveAmount, setReceiveAmount] = useState(0);
  const [countdown, setCountdown] = useState(3600);
  const [requestSubmitted, setRequestSubmitted] = useState(false);
  const [transactionRef, setTransactionRef] = useState('');

  useEffect(() => {
    if (!amount || !selectedExchange) return;

    const amt = parseFloat(amount);
    if (isNaN(amt) || amt <= 0) {
      setReceiveAmount(0);
      return;
    }

    let received = 0;
    switch (selectedExchange) {
      case 'buy_lira':
        received = amt / rates.buy_lira;
        break;
      case 'sell_lira':
        received = amt * rates.sell_lira;
        break;
      case 'buy_usdt':
        received = amt / rates.buy_usdt;
        break;
      case 'sell_usdt':
        received = amt * rates.sell_usdt;
        break;
      case 'convert_usdt_to_lira':
        received = amt * rates.usdt_to_lira;
        break;
      case 'convert_lira_to_usdt':
        received = amt / rates.lira_to_usdt;
        break;
    }

    setReceiveAmount(parseFloat(received.toFixed(4)));
  }, [amount, selectedExchange, rates]);

  const generateRefNumber = () => {
    const now = new Date();
    const dateStr =
      now.getFullYear().toString() +
      (now.getMonth() + 1).toString().padStart(2, '0') +
      now.getDate().toString().padStart(2, '0') +
      now.getHours().toString().padStart(2, '0') +
      now.getMinutes().toString().padStart(2, '0');
    const random4 = Math.floor(1000 + Math.random() * 9000);
    return `${dateStr}${random4}`;
  };

  const handleSubmit = async () => {
    if (!user || user.kyc_status !== 'Approved') {
      alert('لطفاً ابتدا وارد شوید و احراز هویت کنید');
      return;
    }

    if (!amount || parseFloat(amount) <= 0) {
      alert('لطفاً مبلغ معتبر وارد کنید');
      return;
    }

    const refNumber = generateRefNumber();
    setTransactionRef(refNumber);

    const transactionData = {
      user_name: `${user.first_name} ${user.last_name}`,
      user_phone: user.phone_number,
      verification_level: user.verification_level || 1,
      exchange_pair: EXCHANGE_LABELS[selectedExchange],
      exchange_type: selectedExchange,
      send_amount: parseFloat(amount),
      receive_amount: receiveAmount,
      reference_number: refNumber,
      timestamp: new Date().toISOString(),
      status: 'Pending',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
    };

    try {
      const response = await fetch(`${API_URL}/transactions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify(transactionData),
      });

      if (response.ok) {
        setRequestSubmitted(true);

        // Notify admin
        fetch(`${API_URL}/admin/notify-transaction`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(transactionData),
        }).catch(() => {
          // admin notification failure is non-critical
        });

        // Start countdown
        const interval = setInterval(() => {
          setCountdown((prev) => {
            if (prev <= 1) {
              clearInterval(interval);
              return 0;
            }
            return prev - 1;
          });
        }, 1000);
      } else {
        alert('خطا در ارسال درخواست');
      }
    } catch {
      alert('خطا در ارتباط با سرور');
    }
  };

  const formatCountdown = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="p-4">
      {/* Back Button */}
      <button
        onClick={onBack}
        className="mb-4 text-blue-600 font-semibold flex items-center gap-1"
      >
        <span>→</span> بازگشت
      </button>

      {!requestSubmitted ? (
        <div className="bg-white rounded-2xl p-6 shadow-lg">
          <h2 className="text-2xl font-bold text-gray-800 mb-6">درخواست معامله</h2>

          {/* User Info */}
          {user && (
            <div className="bg-blue-50 rounded-xl p-4 mb-6">
              <p className="text-sm text-gray-700 mb-2">
                <strong>نام:</strong> {user.first_name} {user.last_name}
              </p>
              <p className="text-sm text-gray-700 mb-2">
                <strong>شماره تماس:</strong> {user.phone_number}
              </p>
              <p className="text-sm text-gray-700">
                <strong>وضعیت احراز:</strong>
                <span
                  className={`mr-2 px-3 py-1 rounded-full text-xs ${
                    user.verification_level === 2
                      ? 'bg-green-100 text-green-700'
                      : 'bg-yellow-100 text-yellow-700'
                  }`}
                >
                  {user.verification_level === 2
                    ? 'سطح 2 تایید شده'
                    : 'سطح 1 تایید شده'}
                </span>
              </p>
            </div>
          )}

          {/* Exchange Type */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              نوع معامله
            </label>
            <div className="bg-gray-100 rounded-xl p-4 text-center">
              <span className="text-lg font-bold text-blue-600">
                {EXCHANGE_PERSIAN_LABELS[selectedExchange]} ({EXCHANGE_LABELS[selectedExchange]})
              </span>
            </div>
          </div>

          {/* Amount Input */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              مبلغ ارسالی
            </label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="مبلغ را وارد کنید"
              className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none text-lg"
            />
          </div>

          {/* Receive Amount */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              مبلغ دریافتی
            </label>
            <div className="bg-green-50 border-2 border-green-200 rounded-xl p-4">
              <p className="text-2xl font-bold text-green-600 text-center">
                {receiveAmount.toLocaleString('fa-IR')}
              </p>
            </div>
          </div>

          {/* Submit Button */}
          <button
            onClick={handleSubmit}
            disabled={!user || user.kyc_status !== 'Approved' || !amount}
            className={`w-full py-4 rounded-xl font-bold text-lg ${
              !user || user.kyc_status !== 'Approved'
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-gradient-to-r from-blue-600 to-purple-600 text-white hover:shadow-xl'
            }`}
          >
            {!user || user.kyc_status !== 'Approved'
              ? 'لطفاً ابتدا وارد شوید'
              : 'ارسال درخواست'}
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-2xl p-6 shadow-lg">
          <h2 className="text-2xl font-bold text-green-600 mb-6 text-center">
            درخواست ثبت شد
          </h2>

          <div className="space-y-4">
            <InfoRow label="شماره پیگیری" value={transactionRef} />
            <InfoRow
              label="نام"
              value={`${user?.first_name} ${user?.last_name}`}
            />
            <InfoRow label="شماره تماس" value={user?.phone_number || ''} />
            <InfoRow
              label="نوع معامله"
              value={EXCHANGE_LABELS[selectedExchange]}
            />
            <InfoRow
              label="مبلغ ارسالی"
              value={parseFloat(amount).toLocaleString('fa-IR')}
            />
            <InfoRow
              label="مبلغ دریافتی"
              value={receiveAmount.toLocaleString('fa-IR')}
            />
            <InfoRow
              label="تاریخ و زمان"
              value={new Date().toLocaleString('fa-IR')}
            />

            {/* Countdown Timer */}
            <div className="bg-yellow-50 border-2 border-yellow-200 rounded-xl p-4">
              <p className="text-sm text-gray-700 mb-2">زمان باقیمانده:</p>
              <p className="text-3xl font-bold text-yellow-600 text-center font-mono">
                {formatCountdown(countdown)}
              </p>
            </div>

            {/* Status */}
            <div className="bg-blue-50 rounded-xl p-4">
              <p className="text-sm text-gray-700 mb-2">وضعیت:</p>
              <span className="px-4 py-2 bg-yellow-100 text-yellow-700 rounded-full font-semibold">
                در انتظار تایید
              </span>
            </div>

            {/* Cancel Button */}
            <button
              onClick={() => {
                setRequestSubmitted(false);
                setAmount('');
                setReceiveAmount(0);
                setCountdown(3600);
              }}
              className="w-full py-3 bg-red-100 text-red-600 rounded-xl font-semibold hover:bg-red-200"
            >
              لغو درخواست
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── PART 4: Registration Page ──────────────────────────────────────────────

interface RegistrationFormData {
  firstName: string;
  lastName: string;
  nationalId: string;
  dateOfBirth: string;
  bankCardNumber: string;
  phoneNumber: string;
  password: string;
  confirmPassword: string;
  acceptedTerms: boolean;
}

function RegistrationPage({
  onLoginRedirect,
}: {
  onLoginRedirect: () => void;
}) {
  const [attempts, setAttempts] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [formData, setFormData] = useState<RegistrationFormData>({
    firstName: '',
    lastName: '',
    nationalId: '',
    dateOfBirth: '',
    bankCardNumber: '',
    phoneNumber: '',
    password: '',
    confirmPassword: '',
    acceptedTerms: false,
  });
  const [errors, setErrors] = useState<Partial<Record<keyof RegistrationFormData, string>>>({});

  useEffect(() => {
    checkAttemptLimit();
  }, []);

  const isPersian = (text: string) => /^[\u0600-\u06FF\s]+$/.test(text);

  const isValidNationalId = (nid: string) =>
    /^\d{10}$/.test(nid) && new Set(nid).size > 1;

  const isValidJalaliDate = (date: string) => {
    const cleaned = date.replace(/\//g, '');
    if (!/^\d{8}$/.test(cleaned)) return false;
    if (!cleaned.startsWith('13')) return false;
    const month = parseInt(cleaned.substring(4, 6));
    const day = parseInt(cleaned.substring(6, 8));
    return month >= 1 && month <= 12 && day >= 1 && day <= 31;
  };

  const isValidBankCard = (card: string) => {
    const cleaned = card.replace(/\s/g, '');
    return /^\d{16}$/.test(cleaned);
  };

  const isValidPhone = (phone: string) => /^09\d{9}$/.test(phone);

  const isValidPassword = (password: string) => {
    const hasLetter = /[a-zA-Z]/.test(password);
    const hasNumber = /\d/.test(password);
    return hasLetter && hasNumber && password.length >= 8;
  };

  const validateForm = () => {
    const newErrors: Partial<Record<keyof RegistrationFormData, string>> = {};

    if (!formData.firstName || !isPersian(formData.firstName)) {
      newErrors.firstName = 'نام باید فقط با حروف فارسی باشد';
    }
    if (!formData.lastName || !isPersian(formData.lastName)) {
      newErrors.lastName = 'نام خانوادگی باید فقط با حروف فارسی باشد';
    }
    if (!isValidNationalId(formData.nationalId)) {
      newErrors.nationalId = 'کد ملی نامعتبر است';
    }
    if (!isValidJalaliDate(formData.dateOfBirth)) {
      newErrors.dateOfBirth = 'تاریخ تولد نامعتبر است (مثال: 1370/05/15)';
    }
    if (!isValidBankCard(formData.bankCardNumber)) {
      newErrors.bankCardNumber = 'شماره کارت باید 16 رقم باشد';
    }
    if (!isValidPhone(formData.phoneNumber)) {
      newErrors.phoneNumber = 'شماره موبایل نامعتبر است';
    }
    if (!isValidPassword(formData.password)) {
      newErrors.password = 'رمز عبور باید حداقل 8 کاراکتر و شامل حروف و اعداد باشد';
    }
    if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'رمز عبور و تکرار آن یکسان نیستند';
    }
    if (!formData.acceptedTerms) {
      newErrors.acceptedTerms = 'باید قوانین و مقررات را بپذیرید';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const checkAttemptLimit = () => {
    const today = new Date().toDateString();
    const stored = localStorage.getItem('reg_attempts');
    if (stored) {
      const { date, count } = JSON.parse(stored);
      if (date === today) {
        setAttempts(count);
        return count < 5;
      }
    }
    return true;
  };

  const incrementAttempts = () => {
    const today = new Date().toDateString();
    const newCount = attempts + 1;
    localStorage.setItem(
      'reg_attempts',
      JSON.stringify({ date: today, count: newCount })
    );
    setAttempts(newCount);
  };

  const updateField = useCallback(
    (field: keyof RegistrationFormData, value: string | boolean) => {
      setFormData((prev) => ({ ...prev, [field]: value }));
    },
    []
  );

  const formatCardNumber = (value: string) => {
    const cleaned = value.replace(/\s/g, '').replace(/\D/g, '');
    const groups = cleaned.match(/.{1,4}/g);
    return groups ? groups.join(' ') : cleaned;
  };

  const handleSubmit = async () => {
    if (!validateForm()) return;

    if (attempts >= 5) {
      alert('شما بیش از 5 بار امروز تلاش کرده‌اید. لطفاً فردا دوباره تلاش کنید.');
      return;
    }

    setSubmitting(true);

    try {
      // Verify with EHRAZ.IO
      const ehrazResponse = await fetch(`${API_URL}/verify/ehraz`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cardNumber: formData.bankCardNumber.replace(/\s/g, ''),
          nationalCode: formData.nationalId,
          birthDate: formData.dateOfBirth.replace(/\//g, ''),
        }),
      });

      const ehrazData = await ehrazResponse.json();

      if (!ehrazData.matched) {
        incrementAttempts();
        alert('اطلاعات وارد شده صحیح نیست. لطفاً دوباره بررسی کنید.');
        setSubmitting(false);
        return;
      }

      // Register user
      const registerResponse = await fetch(`${API_URL}/users/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          first_name: formData.firstName,
          last_name: formData.lastName,
          national_id: formData.nationalId,
          date_of_birth: formData.dateOfBirth.replace(/\//g, ''),
          bank_card_number: formData.bankCardNumber.replace(/\s/g, ''),
          phone_number: formData.phoneNumber,
          password: formData.password,
        }),
      });

      if (registerResponse.ok) {
        alert('ثبت نام با موفقیت انجام شد! اکنون می‌توانید وارد شوید.');
        onLoginRedirect();
      } else {
        const errorData = await registerResponse.json().catch(() => null);
        incrementAttempts();
        alert(errorData?.detail || 'خطا در ثبت نام. لطفاً دوباره تلاش کنید.');
      }
    } catch {
      incrementAttempts();
      alert('خطا در ارتباط با سرور');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-4">
      <div className="bg-white rounded-2xl p-6 shadow-lg max-w-md mx-auto">
        <h2 className="text-2xl font-bold text-gray-800 mb-6 text-center">
          ثبت نام
        </h2>

        {attempts >= 5 ? (
          <div className="bg-red-50 border-2 border-red-200 rounded-xl p-6 text-center">
            <p className="text-red-600 font-semibold mb-2">محدودیت تلاش</p>
            <p className="text-sm text-red-500">
              شما امروز 5 بار تلاش کرده‌اید. لطفاً فردا دوباره تلاش کنید.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* First Name */}
            <FormField
              label="نام (فارسی)"
              error={errors.firstName}
              placeholder="نام خود را وارد کنید"
              value={formData.firstName}
              onChange={(v) => updateField('firstName', v)}
            />

            {/* Last Name */}
            <FormField
              label="نام خانوادگی (فارسی)"
              error={errors.lastName}
              placeholder="نام خانوادگی خود را وارد کنید"
              value={formData.lastName}
              onChange={(v) => updateField('lastName', v)}
            />

            {/* National ID */}
            <FormField
              label="کد ملی (10 رقم)"
              error={errors.nationalId}
              placeholder="کد ملی 10 رقمی"
              value={formData.nationalId}
              onChange={(v) => updateField('nationalId', v)}
              maxLength={10}
            />

            {/* Date of Birth */}
            <FormField
              label="تاریخ تولد (شمسی)"
              error={errors.dateOfBirth}
              placeholder="1370/05/15"
              value={formData.dateOfBirth}
              onChange={(v) => updateField('dateOfBirth', v)}
            />

            {/* Bank Card */}
            <FormField
              label="شماره کارت بانکی (16 رقم)"
              error={errors.bankCardNumber}
              placeholder="1234 5678 9012 3456"
              value={formData.bankCardNumber}
              onChange={(v) => updateField('bankCardNumber', formatCardNumber(v))}
              maxLength={19}
            />

            {/* Phone Number */}
            <FormField
              label="شماره موبایل"
              error={errors.phoneNumber}
              placeholder="09123456789"
              value={formData.phoneNumber}
              onChange={(v) => updateField('phoneNumber', v)}
              type="tel"
              maxLength={11}
            />

            {/* Password */}
            <FormField
              label="رمز عبور"
              error={errors.password}
              placeholder="حداقل 8 کاراکتر با حروف و اعداد"
              value={formData.password}
              onChange={(v) => updateField('password', v)}
              type="password"
            />

            {/* Confirm Password */}
            <FormField
              label="تکرار رمز عبور"
              error={errors.confirmPassword}
              placeholder="رمز عبور را دوباره وارد کنید"
              value={formData.confirmPassword}
              onChange={(v) => updateField('confirmPassword', v)}
              type="password"
            />

            {/* Terms and Conditions */}
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={formData.acceptedTerms}
                onChange={(e) => updateField('acceptedTerms', e.target.checked)}
                className="mt-1 w-5 h-5 text-blue-600"
              />
              <label className="text-sm text-gray-700">
                <span className="text-blue-600 underline cursor-pointer">
                  قوانین و مقررات
                </span>{' '}
                را مطالعه کرده و می‌پذیرم
              </label>
            </div>
            {errors.acceptedTerms && (
              <p className="text-red-500 text-xs">{errors.acceptedTerms}</p>
            )}

            {/* Attempt Counter */}
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-3">
              <p className="text-xs text-yellow-700">
                تلاش‌های امروز: {attempts} / 5
              </p>
            </div>

            {/* Submit Button */}
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="w-full bg-gradient-to-r from-blue-600 to-purple-600 text-white py-4 rounded-xl font-bold text-lg hover:shadow-xl transition-all disabled:opacity-50"
            >
              {submitting ? 'در حال ثبت نام...' : 'ثبت نام'}
            </button>

            {/* Login Link */}
            <p className="text-center text-sm text-gray-600">
              قبلاً ثبت نام کرده‌اید؟{' '}
              <button
                onClick={onLoginRedirect}
                className="text-blue-600 font-semibold"
              >
                وارد شوید
              </button>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Form Field Component ───────────────────────────────────────────────────

function FormField({
  label,
  error,
  placeholder,
  value,
  onChange,
  type = 'text',
  maxLength,
}: {
  label: string;
  error?: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  maxLength?: number;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full px-4 py-3 border-2 rounded-xl focus:outline-none ${
          error
            ? 'border-red-500'
            : 'border-gray-200 focus:border-blue-500'
        }`}
        placeholder={placeholder}
        maxLength={maxLength}
      />
      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
    </div>
  );
}

// ─── PART 5: Login Page ─────────────────────────────────────────────────────

function LoginPage({
  onSuccess,
  onRegisterRedirect,
}: {
  onSuccess: (user: User) => void;
  onRegisterRedirect: () => void;
}) {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleLogin = async () => {
    setError('');

    if (!phoneNumber || !password) {
      setError('لطفاً تمام فیلدها را پر کنید');
      return;
    }

    setSubmitting(true);

    try {
      const response = await fetch(`${API_URL}/users/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phone_number: phoneNumber,
          password: password,
        }),
      });

      const data = await response.json();

      if (response.ok && data.token) {
        localStorage.setItem('token', data.token);
        onSuccess(data.user);
      } else {
        setError('شماره موبایل یا رمز عبور اشتباه است');
      }
    } catch {
      setError('خطا در ارتباط با سرور');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-4">
      <div className="bg-white rounded-2xl p-6 shadow-lg max-w-md mx-auto">
        <h2 className="text-2xl font-bold text-gray-800 mb-6 text-center">
          ورود
        </h2>

        <div className="space-y-4">
          {/* Phone Number */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              شماره موبایل
            </label>
            <input
              type="tel"
              maxLength={11}
              value={phoneNumber}
              onChange={(e) => setPhoneNumber(e.target.value)}
              className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none"
              placeholder="09123456789"
            />
          </div>

          {/* Password */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              رمز عبور
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none"
              placeholder="رمز عبور خود را وارد کنید"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleLogin();
              }}
            />
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-3">
              <p className="text-red-600 text-sm">{error}</p>
            </div>
          )}

          {/* Login Button */}
          <button
            onClick={handleLogin}
            disabled={submitting}
            className="w-full bg-gradient-to-r from-green-600 to-emerald-600 text-white py-4 rounded-xl font-bold text-lg hover:shadow-xl transition-all disabled:opacity-50"
          >
            {submitting ? 'در حال ورود...' : 'ورود'}
          </button>

          {/* Register Link */}
          <p className="text-center text-sm text-gray-600">
            حساب کاربری ندارید؟{' '}
            <button
              onClick={onRegisterRedirect}
              className="text-blue-600 font-semibold"
            >
              ثبت نام کنید
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── PART 6: History Page ───────────────────────────────────────────────────

function HistoryPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTransactions();
  }, []);

  const fetchTransactions = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`${API_URL}/user/transactions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      setTransactions(data.transactions || []);
    } catch (error) {
      console.error('Error fetching transactions:', error);
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      Pending: 'bg-yellow-100 text-yellow-700',
      Approved: 'bg-green-100 text-green-700',
      Expired: 'bg-gray-100 text-gray-700',
      Canceled: 'bg-red-100 text-red-700',
      'Under Review': 'bg-blue-100 text-blue-700',
    };
    return colors[status] || 'bg-gray-100 text-gray-700';
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      Pending: 'در انتظار',
      Approved: 'تایید شده',
      Expired: 'منقضی شده',
      Canceled: 'لغو شده',
      'Under Review': 'در حال بررسی',
    };
    return labels[status] || status;
  };

  return (
    <div className="p-4">
      <h2 className="text-2xl font-bold text-gray-800 mb-4">
        تاریخچه تراکنش‌ها
      </h2>

      {loading ? (
        <div className="text-center py-10">
          <div className="animate-spin w-12 h-12 border-4 border-blue-600 border-t-transparent rounded-full mx-auto"></div>
        </div>
      ) : transactions.length === 0 ? (
        <div className="bg-white rounded-2xl p-8 text-center shadow-lg">
          <p className="text-gray-500">هنوز تراکنشی ثبت نشده است</p>
        </div>
      ) : (
        <div className="space-y-3">
          {transactions.map((tx) => (
            <div key={tx.id} className="bg-white rounded-xl p-4 shadow-md">
              <div className="flex justify-between items-start mb-3">
                <div>
                  <p className="font-semibold text-gray-800">
                    {tx.exchange_pair}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    شماره پیگیری: {tx.reference_number}
                  </p>
                </div>
                <span
                  className={`px-3 py-1 rounded-full text-xs font-semibold ${getStatusColor(
                    tx.status
                  )}`}
                >
                  {getStatusLabel(tx.status)}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-gray-600">مبلغ ارسال:</span>
                  <p className="font-semibold">
                    {tx.send_amount.toLocaleString('fa-IR')}
                  </p>
                </div>
                <div>
                  <span className="text-gray-600">مبلغ دریافت:</span>
                  <p className="font-semibold">
                    {tx.receive_amount.toLocaleString('fa-IR')}
                  </p>
                </div>
              </div>

              <div className="mt-3 pt-3 border-t border-gray-100">
                <p className="text-xs text-gray-500">
                  {new Date(tx.timestamp).toLocaleString('fa-IR')}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
