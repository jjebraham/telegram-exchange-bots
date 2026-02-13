import { useState, useEffect, useCallback, useRef } from 'react';
import { calculateFee, calculateReceiveAmount, deriveRates } from './exchangeMath';
import type { ExchangeType, Rates } from './exchangeMath';

const API_URL = import.meta.env.VITE_API_URL || '/api';

const notifyMessage = (message: string, title = 'KIANI Exchange') => {
  const tg = (window as any)?.Telegram?.WebApp;
  if (tg?.showPopup) {
    tg.showPopup({ title, message, buttons: [{ type: 'ok', text: 'باشه' }] });
    return;
  }
  window.alert(message);
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface User {
  id: number;
  first_name: string;
  last_name: string;
  phone_number: string;
  kyc_status: string;
  verification_level: number;
  national_id?: string;
  dob?: string;
  bank_card_number?: string;
}

interface Transaction {
  id: number;
  exchange_pair: string;
  reference_number: string;
  send_amount: number;
  receive_amount: number;
  status: string;
  timestamp: string;
  receipt_photo_url?: string;
  receipt_description?: string;
  payment_link?: string;
}

type TabType = 'dashboard' | 'exchange' | 'register' | 'login' | 'history' | 'faq' | 'admin';

// ─── Helper Components ──────────────────────────────────────────────────────

const RateBox = ({
  label,
  rate,
  loading,
}: {
  label: string;
  rate: number | string;
  loading: boolean;
}) => {
  // Check if this is a conversion rate (تبدیل لیر به تتر or تبدیل تتر به لیر)
  const isConversionRate = label.includes('تبدیل لیر به تتر') || label.includes('تبدیل تتر به لیر');
  
  return (
    <div className="bg-white rounded-xl p-4 shadow-md mb-3">
      <div className="flex justify-between items-center">
        <span className="text-gray-700 font-semibold text-sm">{label}</span>
        <span className="text-blue-600 font-bold text-lg">
          {loading
            ? '...'
            : isConversionRate
              ? `${rate.toLocaleString('fa-IR')} لیر`
              : `${rate.toLocaleString('fa-IR')} تومان`}
        </span>
      </div>
    </div>
  );
};

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

// Helper functions for formatting and validation
const formatNumberWithCommas = (num: string): string => {
  // Remove non-digits
  const cleaned = num.replace(/\D/g, '');
  // Add commas for every 3 digits
  return cleaned.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
};

const removeCommas = (num: string): string => {
  return num.replace(/,/g, '');
};

const isPersianText = (text: string): boolean => /^[\u0600-\u06FF\s]+$/.test(text.trim());

const isValidLuhn = (cardNumber: string): boolean => {
  const cleaned = cardNumber.replace(/\D/g, '');
  if (cleaned.length !== 16) return false;
  let sum = 0;
  let shouldDouble = false;
  for (let i = cleaned.length - 1; i >= 0; i--) {
    let digit = parseInt(cleaned.charAt(i), 10);
    if (shouldDouble) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    sum += digit;
    shouldDouble = !shouldDouble;
  }
  return sum % 10 === 0;
};

// Format receive amount based on currency
const formatReceiveAmount = (amount: number, exchangeType: ExchangeType, type: 'send' | 'receive'): string => {
  const unit = getCurrencyUnit(exchangeType, type);
  
  if (unit === 'تومان') {
    // Toman: no decimals, Persian digits
    return Math.round(amount).toLocaleString('fa-IR');
  } else if (unit === 'TL') {
    // TL: 2 decimal places, English digits
    return amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  } else if (unit === 'USDT') {
    // USDT: 2 decimal places, English digits with $ sign
    return `$${amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;
  }
  
  // Default: 2 decimal places, English digits
  return amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
};

// Helper function to get currency unit (need to declare this earlier)
const getCurrencyUnit = (exchangeType: ExchangeType, type: 'send' | 'receive'): string => {
  switch (exchangeType) {
    case 'buy_lira':
      return type === 'send' ? 'تومان' : 'TL';
    case 'sell_lira':
      return type === 'send' ? 'TL' : 'تومان';
    case 'buy_usdt':
      return type === 'send' ? 'تومان' : 'USDT';
    case 'sell_usdt':
      return type === 'send' ? 'USDT' : 'تومان';
    case 'convert_usdt_to_lira':
      return type === 'send' ? 'USDT' : 'TL';
    case 'convert_lira_to_usdt':
      return type === 'send' ? 'TL' : 'USDT';
    default:
      return '';
  }
};

// Minimum and maximum limits for each exchange type
const EXCHANGE_LIMITS: Record<ExchangeType, { min: number; max: number; fee: number }> = {
  buy_lira: { min: 5000000, max: 200000000, fee: 0 }, // Toman to TL
  sell_lira: { min: 2000, max: 200000, fee: 0 }, // TL to Toman
  buy_usdt: { min: 10000000, max: 200000000, fee: 0 }, // Toman to USDT
  sell_usdt: { min: 100, max: 50000, fee: 0 }, // USDT to Toman
  convert_usdt_to_lira: { min: 100, max: 50000, fee: 0 }, // USDT to TL
  convert_lira_to_usdt: { min: 5000, max: 200000, fee: 0 }, // TL to USDT
};

// ─── Exchange Pair Labels ───────────────────────────────────────────────────

const EXCHANGE_LABELS: Record<ExchangeType, string> = {
  buy_lira: 'Toman \u2192 TL',
  sell_lira: 'TL \u2192 Toman',
  buy_usdt: 'Toman \u2192 USDT',
  sell_usdt: 'USDT \u2192 Toman',
  convert_usdt_to_lira: 'USDT \u2192 TL',
  convert_lira_to_usdt: 'TL \u2192 USDT',
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
  const isAdminHost = typeof window !== 'undefined' && window.location.hostname.includes('kianiapp');
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
    if (!rates.buy_lira) setLoading(true);
    try {
      const response = await fetch(`${API_URL}/rates/current`);
      const data = await response.json();

      const usdt_irr = data.rates.USDT_IRR;
      const usdt_try = data.rates.USDT_TRY;
      if (data.derived_rates) {
        // Ensure all rate properties are present, defaulting to 0 for missing ones
        const defaultRates = {
          buy_lira: 0,
          sell_lira: 0,
          buy_usdt: 0,
          sell_usdt: 0,
          usdt_to_lira: 0,
          lira_to_usdt: 0,
          foreign_payment: 0,
        };
        setRates({ ...defaultRates, ...data.derived_rates });
      } else {
        setRates(deriveRates(usdt_irr, usdt_try));
      }
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

  if (isAdminHost) {
    return <AdminPanelPage />;
  }

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
        {activeTab === 'faq' && <FaqPage />}
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
            label="FAQ"
            icon="❓"
            active={activeTab === 'faq'}
            onClick={() => setActiveTab('faq')}
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
  const [formattedAmount, setFormattedAmount] = useState('');
  const [receiveAmount, setReceiveAmount] = useState(0);
  const [fee, setFee] = useState(0);
  const [totalAmount, setTotalAmount] = useState(0);
  const [countdown, setCountdown] = useState(3600);
  const [requestSubmitted, setRequestSubmitted] = useState(false);
  const [transactionRef, setTransactionRef] = useState('');
  const [error, setError] = useState('');
  const [numericAmount, setNumericAmount] = useState(0);
  const countdownIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (countdownIntervalRef.current) {
        clearInterval(countdownIntervalRef.current);
        countdownIntervalRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!amount || !selectedExchange) return;

    const amt = parseFloat(removeCommas(amount));
    setNumericAmount(amt);
    
    if (isNaN(amt) || amt <= 0) {
      setReceiveAmount(0);
      setFee(0);
      setTotalAmount(0);
      setError('');
      return;
    }

    // Validate against limits
    const limits = EXCHANGE_LIMITS[selectedExchange];
    if (amt < limits.min) {
      setError(`حداقل مبلغ ${limits.min.toLocaleString('fa-IR')} ${getCurrencyUnit(selectedExchange, 'send')}`);
      setReceiveAmount(0);
      setFee(0);
      setTotalAmount(0);
      return;
    }
    if (amt > limits.max) {
      setError(`حداکثر مبلغ ${limits.max.toLocaleString('fa-IR')} ${getCurrencyUnit(selectedExchange, 'send')}`);
      setReceiveAmount(0);
      setFee(0);
      setTotalAmount(0);
      return;
    }
    
    setError('');

    const calculation = calculateReceiveAmount(selectedExchange, amt, rates);
    setFee(calculation.fee);
    setTotalAmount(amt);
    setReceiveAmount(parseFloat(calculation.receiveAmount.toFixed(4)));

    if (
      (selectedExchange === 'convert_usdt_to_lira' || selectedExchange === 'sell_usdt') &&
      calculation.netSendAmount <= 0
    ) {
      setError('مبلغ ارسال باید بیشتر از کارمزد باشد');
    }
  }, [amount, selectedExchange, rates]);

  // Helper function to get currency unit

  const handleAmountChange = (value: string) => {
    // Format with commas as user types
    const formatted = formatNumberWithCommas(value);
    setFormattedAmount(formatted);
    setAmount(formatted);
  };

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
      notifyMessage('لطفاً ابتدا وارد شوید و احراز هویت کنید');
      return;
    }

    const amt = parseFloat(removeCommas(amount));
    if (!amount || amt <= 0) {
      notifyMessage('لطفاً مبلغ معتبر وارد کنید');
      return;
    }

    // Validate against limits
    const limits = EXCHANGE_LIMITS[selectedExchange];
    if (amt < limits.min) {
      notifyMessage(`حداقل مبلغ ${limits.min.toLocaleString('fa-IR')} ${getCurrencyUnit(selectedExchange, 'send')}`);
      return;
    }
    if (amt > limits.max) {
      notifyMessage(`حداکثر مبلغ ${limits.max.toLocaleString('fa-IR')} ${getCurrencyUnit(selectedExchange, 'send')}`);
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
      send_amount: amt,
      receive_amount: receiveAmount,
      fee: fee,
      total_amount: totalAmount,
      reference_number: refNumber,
      timestamp: new Date().toISOString(),
      status: 'Pending',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
    };

    // For admin notification (with user's 3 factors)
    const adminNotificationData = {
      user_name: `${user.first_name} ${user.last_name}`,
      user_phone: user.phone_number,
      verification_level: user.verification_level || 1,
      exchange_pair: EXCHANGE_LABELS[selectedExchange],
      send_amount: amt,
      receive_amount: receiveAmount,
      reference_number: refNumber,
      timestamp: new Date().toISOString(),
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      national_id: user.national_id,
      date_of_birth: user.dob,
      bank_card_number: user.bank_card_number,
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

        // Notify admin with user's 3 factors
        fetch(`${API_URL}/admin/notify-transaction`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(adminNotificationData),
        }).catch(() => {
          // admin notification failure is non-critical
        });

        // Clear any existing interval
        if (countdownIntervalRef.current) {
          clearInterval(countdownIntervalRef.current);
        }
        
        // Start countdown
        countdownIntervalRef.current = setInterval(() => {
          setCountdown((prev) => {
            if (prev <= 1) {
              if (countdownIntervalRef.current) {
                clearInterval(countdownIntervalRef.current);
                countdownIntervalRef.current = null;
              }
              return 0;
            }
            return prev - 1;
          });
        }, 1000);
      } else {
        notifyMessage('خطا در ارسال درخواست');
      }
    } catch {
      notifyMessage('خطا در ارتباط با سرور');
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
              مبلغ ارسالی ({getCurrencyUnit(selectedExchange, 'send')})
            </label>
            <input
              type="text"
              inputMode="numeric"
              value={formattedAmount}
              onChange={(e) => handleAmountChange(e.target.value)}
              placeholder="مبلغ را وارد کنید"
              className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none text-lg text-left direction-ltr"
              dir="ltr"
            />
            {error && (
              <p className="text-red-500 text-sm mt-2">{error}</p>
            )}
            {/* Show limits */}
            <div className="text-xs text-gray-500 mt-2">
              <span>حداقل: {EXCHANGE_LIMITS[selectedExchange].min.toLocaleString('fa-IR')}</span>
              <span className="mx-2">•</span>
              <span>حداکثر: {EXCHANGE_LIMITS[selectedExchange].max.toLocaleString('fa-IR')}</span>
            </div>
          </div>

          {/* Fee Display */}
          {fee > 0 && (
            <div className="mb-3">
              <div className="flex justify-between items-center text-sm">
                <span className="text-gray-600">کارمزد:</span>
                <span className="font-semibold text-red-600">
                  {fee.toLocaleString('fa-IR')} {getCurrencyUnit(selectedExchange, 'receive')}
                </span>
              </div>
              {selectedExchange === 'sell_lira' && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-2 mt-2 text-xs text-yellow-700">
                  <p>✅ برای تراکنش های زیر 5000 لیر کارمزد ثابت ۸۰ TL از مبلغ دریافتی کسر می‌شود.</p>
                </div>
              )}
              {selectedExchange === 'buy_lira' && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-2 mt-2 text-xs text-yellow-700">
                  <p>✅ برای تراکنش های زیر 15,000,000 تومان کارمزد ثابت ۸۰ TL از مبلغ دریافتی کسر می‌شود.</p>
                </div>
              )}
              {(selectedExchange === 'convert_usdt_to_lira' || selectedExchange === 'sell_usdt') && (
                <div className="flex justify-between items-center text-sm mt-1">
                  <span className="text-gray-600">مبلغ خالص پس از کارمزد:</span>
                  <span className="font-semibold text-purple-600">
                    {(Math.max(numericAmount - fee, 0)).toLocaleString('fa-IR')} USDT
                  </span>
                </div>
              )}
              <div className="flex justify-between items-center text-sm mt-1">
                <span className="text-gray-600">کل مبلغ قابل پرداخت:</span>
                <span className="font-semibold text-blue-600">
                  {totalAmount.toLocaleString('fa-IR')} {getCurrencyUnit(selectedExchange, 'send')}
                </span>
              </div>
            </div>
          )}

          {/* Receive Amount */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              مبلغ دریافتی ({getCurrencyUnit(selectedExchange, 'receive')})
            </label>
            <div className="bg-green-50 border-2 border-green-200 rounded-xl p-4">
              <p className="text-2xl font-bold text-green-600 text-center" dir="ltr">
                {formatReceiveAmount(receiveAmount, selectedExchange, 'receive')}
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
              value={`${parseFloat(removeCommas(amount)).toLocaleString('fa-IR')} ${getCurrencyUnit(selectedExchange, 'send')}`}
            />
            {fee > 0 && (
              <InfoRow
                label="کارمزد"
                value={`${fee.toLocaleString('fa-IR')} ${getCurrencyUnit(selectedExchange, 'receive')}`}
              />
            )}
            <InfoRow
              label="مبلغ دریافتی"
              value={formatReceiveAmount(receiveAmount, selectedExchange, 'receive')}
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
              onClick={async () => {
                if (!confirm('آیا مطمئن هستید که می‌خواهید این درخواست را لغو کنید؟')) {
                  return;
                }
                
                try {
                  // Call backend to cancel transaction
                  const response = await fetch(`${API_URL}/transactions/${transactionRef}/cancel`, {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                      Authorization: `Bearer ${localStorage.getItem('token')}`,
                    },
                  });
                  
                  if (response.ok) {
                    // Clear countdown interval
                    if (countdownIntervalRef.current) {
                      clearInterval(countdownIntervalRef.current);
                      countdownIntervalRef.current = null;
                    }
                    
                    // Reset form
                    setRequestSubmitted(false);
                    setAmount('');
                    setFormattedAmount('');
                    setNumericAmount(0);
                    setReceiveAmount(0);
                    setFee(0);
                    setTotalAmount(0);
                    setError('');
                    setCountdown(3600);
                    setTransactionRef('');
                    notifyMessage('درخواست با موفقیت لغو شد');
                  } else {
                    // Try to get error details from response
                    try {
                      const errorData = await response.json();
                      notifyMessage(`خطا در لغو درخواست: ${errorData.detail || 'خطای ناشناخته'}`);
                    } catch {
                      notifyMessage(`خطا در لغو درخواست (کد: ${response.status})`);
                    }
                    
                    // Even if cancel fails, reset the form so user can try again
                    // Clear countdown interval
                    if (countdownIntervalRef.current) {
                      clearInterval(countdownIntervalRef.current);
                      countdownIntervalRef.current = null;
                    }
                    
                    setRequestSubmitted(false);
                    setAmount('');
                    setFormattedAmount('');
                    setNumericAmount(0);
                    setReceiveAmount(0);
                    setFee(0);
                    setTotalAmount(0);
                    setError('');
                    setCountdown(3600);
                  }
                } catch (error) {
                  console.error('Cancel error:', error);
                  notifyMessage('خطا در ارتباط با سرور. لطفاً اتصال اینترنت خود را بررسی کنید.');
                  
                  // Reset form even on network error
                  // Clear countdown interval
                  if (countdownIntervalRef.current) {
                    clearInterval(countdownIntervalRef.current);
                    countdownIntervalRef.current = null;
                  }
                  
                  setRequestSubmitted(false);
                  setAmount('');
                  setFormattedAmount('');
                  setNumericAmount(0);
                  setReceiveAmount(0);
                  setFee(0);
                  setTotalAmount(0);
                  setError('');
                  setCountdown(3600);
                }
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
  const [progress, setProgress] = useState(0);
  const [showTerms, setShowTerms] = useState(false);
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

  const isValidNationalId = (nid: string) => {
    // Exactly 10 digits and not all same digits
    const cleaned = nid.replace(/\D/g, '');
    return /^\d{10}$/.test(cleaned) && new Set(cleaned).size > 1;
  };

  const isValidJalaliDate = (date: string) => {
    const cleaned = date.replace(/\//g, '');
    // Must be exactly 8 digits
    if (!/^\d{8}$/.test(cleaned)) return false;
    
    const year = parseInt(cleaned.substring(0, 4));
    const month = parseInt(cleaned.substring(4, 6));
    const day = parseInt(cleaned.substring(6, 8));
    
    // Year: 1300 to 1399, but 1387+ are under 18 and rejected later
    if (year < 1300 || year > 1399) return false;
    
    // Month: 01 to 12
    if (month < 1 || month > 12) return false;
    
    // Day: 01 to 31 (simple validation)
    if (day < 1 || day > 31) return false;
    
    return true;
  };

  const isValidBankCard = (card: string) => {
    const cleaned = card.replace(/\s/g, '').replace(/\D/g, '');
    return /^\d{16}$/.test(cleaned) && isValidLuhn(cleaned);
  };

  const isValidPhone = (phone: string) => {
    const cleaned = phone.replace(/\D/g, '');
    return /^09\d{9}$/.test(cleaned);
  };

  const isValidPassword = (password: string) => {
    const hasLetter = /[a-zA-Z]/.test(password);
    const hasNumber = /\d/.test(password);
    return hasLetter && hasNumber && password.length >= 8;
  };

  const validateForm = () => {
    const newErrors: Partial<Record<keyof RegistrationFormData, string>> = {};

    if (!formData.firstName || !isPersianText(formData.firstName)) {
      newErrors.firstName = 'لطفا نام را با حروف فارسی وارد کنید';
    }
    if (!formData.lastName || !isPersianText(formData.lastName)) {
      newErrors.lastName = 'لطفا نام خانوادگی را با حروف فارسی وارد کنید';
    }
    if (!isValidNationalId(formData.nationalId)) {
      newErrors.nationalId = 'کد ملی نامعتبر است';
    }
    if (!isValidJalaliDate(formData.dateOfBirth)) {
      newErrors.dateOfBirth = 'تاریخ تولد نامعتبر است (مثال: 1370/05/15)';
    } else {
      const year = parseInt(formData.dateOfBirth.replace(/\//g, '').slice(0, 4), 10);
      if (year >= 1387) {
        newErrors.dateOfBirth = 'برای ثبت نام باید حداقل 18 سال داشته باشید';
      }
    }
    if (!isValidBankCard(formData.bankCardNumber)) {
      newErrors.bankCardNumber = 'شماره کارت نامعتبر است';
    }
    if (!isValidPhone(formData.phoneNumber)) {
      newErrors.phoneNumber = 'لطفا شماره موبایل ایران به نام خودتان مطابق مثال وارد کنید 09121111111';
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

  const validateSingleField = (field: keyof RegistrationFormData, value: string | boolean) => {
    const nextErrors = { ...errors };
    const strValue = String(value);
    delete nextErrors[field];

    if (field === 'firstName' && strValue && !isPersianText(strValue)) {
      nextErrors.firstName = 'لطفا نام را با حروف فارسی وارد کنید';
    }
    if (field === 'lastName' && strValue && !isPersianText(strValue)) {
      nextErrors.lastName = 'لطفا نام خانوادگی را با حروف فارسی وارد کنید';
    }
    if (field === 'nationalId' && strValue && !isValidNationalId(strValue)) {
      nextErrors.nationalId = 'کد ملی نامعتبر است';
    }
    if (field === 'phoneNumber' && strValue && !/^09\d{9}$/.test(strValue.replace(/\D/g, ''))) {
      nextErrors.phoneNumber = 'لطفا شماره موبایل ایران به نام خودتان مطابق مثال وارد کنید 09121111111';
    }
    if (field === 'bankCardNumber' && strValue.replace(/\D/g, '').length === 16 && !isValidLuhn(strValue)) {
      nextErrors.bankCardNumber = 'شماره کارت نامعتبر است';
    }
    if (field === 'dateOfBirth' && strValue.replace(/\D/g, '').length >= 4) {
      const year = parseInt(strValue.replace(/\D/g, '').slice(0, 4), 10);
      if (!String(year).startsWith('13')) {
        nextErrors.dateOfBirth = 'سال تولد باید با 13 شروع شود';
      } else if (year >= 1387) {
        nextErrors.dateOfBirth = 'برای ثبت نام باید حداقل 18 سال داشته باشید';
      }
    }
    if (field === 'password' && strValue && !isValidPassword(strValue)) {
      nextErrors.password = 'رمز عبور باید حداقل 8 کاراکتر و شامل حروف و اعداد باشد';
    }
    if (field === 'confirmPassword' && strValue && strValue !== formData.password) {
      nextErrors.confirmPassword = 'رمز عبور و تکرار آن یکسان نیستند';
    }
    setErrors(nextErrors);
  };


   const handleSubmit = async () => {
    if (!validateForm()) return;

    if (attempts >= 5) {
      notifyMessage('شما بیش از 5 بار امروز تلاش کرده‌اید. لطفاً فردا دوباره تلاش کنید.');
      return;
    }

    setSubmitting(true);
    setProgress(0);
    const progressTimer = window.setInterval(() => {
      setProgress((prev) => (prev >= 95 ? prev : prev + 5));
    }, 1000);

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
        notifyMessage('اطلاعات وارد شده صحیح نیست. لطفاً دوباره بررسی کنید.\n\n' +
              'اطلاعات کارت بانکی شما با کد ملی و تاریخ تولدتان همخوانی ندارد.\n' +
              'لطفا اطلاعات وارد شده رو بررسی و دوباره تلاش کنید.');
        setSubmitting(false);
        clearInterval(progressTimer);
        setProgress(0);
        return;
      }

      // Verify national ID with phone ownership
      const mobileMatchResponse = await fetch(`${API_URL}/verify/ehraz-mobile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nationalCode: formData.nationalId,
          mobileNumber: formData.phoneNumber,
        }),
      });
      const mobileMatchData = await mobileMatchResponse.json();
      if (!mobileMatchData.matched) {
        incrementAttempts();
        setErrors((prev) => ({ ...prev, phoneNumber: 'اطلاعات شماره موبایل با کد ملی شما همخوانی ندارد لطفا فقط شماره موبایل ثبت شده به نام خودتان را وارد کنید' }));
        notifyMessage('اطلاعات شماره موبایل با کد ملی شما همخوانی ندارد لطفا فقط شماره موبایل ثبت شده به نام خودتان را وارد کنید');
        setSubmitting(false);
        clearInterval(progressTimer);
        setProgress(0);
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
        notifyMessage('ثبت نام با موفقیت انجام شد! اکنون می‌توانید وارد شوید.');
        onLoginRedirect();
      } else {
        const errorData = await registerResponse.json().catch(() => null);
        incrementAttempts();
        
        // Show specific error messages based on backend response
        let errorMessage = 'خطا در ثبت نام. لطفاً دوباره تلاش کنید.';
        
        if (errorData?.detail) {
          if (errorData.detail === 'already_registered_phone') {
            errorMessage = 'شما قبلاً در سیستم ثبت‌نام کرده‌اید. لطفاً وارد شوید.';
          } else if (errorData.detail === 'already_registered_national_id') {
            errorMessage = 'این کد ملی قبلاً ثبت شده است. لطفاً وارد شوید یا با پشتیبانی تماس بگیرید.';
          } else if (errorData.detail === 'already_registered_card') {
            errorMessage = 'این شماره کارت قبلاً ثبت شده است.';
          } else {
            errorMessage = 'خطا در ثبت نام، لطفاً مجدد تلاش کنید.';
          }
        }
        
        notifyMessage(errorMessage);
      }
    } catch (error) {
      incrementAttempts();
      console.error('Registration error:', error);
      notifyMessage('خطا در ارتباط با سرور. لطفاً اتصال اینترنت خود را بررسی کنید و دوباره تلاش کنید.');
    } finally {
      clearInterval(progressTimer);
      setProgress(100);
      setTimeout(() => setProgress(0), 400);
      setSubmitting(false);
    }
  };

  // Terms and Conditions Popup Component
  const TermsPopup = () => (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl p-6 max-w-md w-full max-h-[80vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-xl font-bold text-gray-800">قوانین و مقررات</h3>
          <button
            onClick={() => setShowTerms(false)}
            className="text-gray-500 hover:text-gray-700 text-2xl"
          >
            ×
          </button>
        </div>
        <div className="space-y-4 text-sm text-gray-700">
          <p>
            با ثبت نام در این سامانه، شما قوانین و مقررات زیر را می‌پذیرید:
          </p>
          <ul className="list-disc pr-4 space-y-2">
            <li>اطلاعات وارد شده باید واقعی و متعلق به خودتان باشد.</li>
            <li>هرگونه سوءاستفاده از سامانه پیگرد قانونی خواهد داشت.</li>
            <li>کاربر مسئول حفظ امنیت حساب کاربری خود است.</li>
            <li>سامانه در صورت مشاهده فعالیت مشکوک حق لغو حساب را دارد.</li>
            <li>نرخ‌ها بر اساس بازار تعیین و ممکن است تغییر کند.</li>
            <li>تراکنش‌ها پس از تایید نهایی قابل اجرا هستند.</li>
            <li>کارمزد تراکنش‌ها مطابق با تعرفه‌های اعلامی محاسبه می‌شود.</li>
            <li>شماره کارت باید متعلق به خود کاربر باشد.</li>
            <li>حداقل سن برای استفاده از سامانه 18 سال است.</li>
            <li>کاربر موظف است اطلاعات تماس خود را به روز نگه دارد.</li>
          </ul>
          <p className="text-xs text-gray-500 mt-4">
            تاریخ آخرین بروزرسانی: ۱۴۰۳/۱۱/۱۸
          </p>
        </div>
        <div className="mt-6">
          <button
            onClick={() => setShowTerms(false)}
            className="w-full bg-blue-600 text-white py-3 rounded-xl font-semibold hover:bg-blue-700"
          >
            فهمیدم
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="p-4">
      {showTerms && <TermsPopup />}
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
              onBlur={(v) => validateSingleField('firstName', v)}
              type="text"
              inputMode="text"
              dir="rtl"
            />

            {/* Last Name */}
            <FormField
              label="نام خانوادگی (فارسی)"
              error={errors.lastName}
              placeholder="نام خانوادگی خود را وارد کنید"
              value={formData.lastName}
              onChange={(v) => updateField('lastName', v)}
              onBlur={(v) => validateSingleField('lastName', v)}
              type="text"
              inputMode="text"
              dir="rtl"
            />

            {/* National ID */}
            <FormField
              label="کد ملی (10 رقم)"
              error={errors.nationalId}
              placeholder="کد ملی 10 رقمی"
              value={formData.nationalId}
              onChange={(v) => updateField('nationalId', v)}
              onBlur={(v) => validateSingleField('nationalId', v)}
              type="nationalId"
              inputMode="numeric"
              dir="ltr"
              maxLength={10}
            />

            {/* Date of Birth */}
            <FormField
              label="تاریخ تولد (شمسی)"
              error={errors.dateOfBirth}
              placeholder="1370/05/15"
              value={formData.dateOfBirth}
              onChange={(v) => updateField('dateOfBirth', v)}
              onBlur={(v) => validateSingleField('dateOfBirth', v)}
              type="date"
              inputMode="numeric"
              dir="ltr"
              maxLength={10}
            />

            {/* Bank Card */}
            <FormField
              label="شماره کارت بانکی (16 رقم)"
              error={errors.bankCardNumber}
              placeholder="1234 5678 9012 3456"
              value={formData.bankCardNumber}
              onChange={(v) => updateField('bankCardNumber', v)}
              onBlur={(v) => validateSingleField('bankCardNumber', v)}
              type="card"
              inputMode="numeric"
              dir="ltr"
              maxLength={19}
            />

            {/* Phone Number */}
            <FormField
              label="شماره موبایل"
              error={errors.phoneNumber}
              placeholder="09123456789"
              value={formData.phoneNumber}
              onChange={(v) => updateField('phoneNumber', v)}
              onBlur={(v) => validateSingleField('phoneNumber', v)}
              type="tel"
              inputMode="numeric"
              dir="ltr"
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
                <span 
                  className="text-blue-600 underline cursor-pointer"
                  onClick={() => setShowTerms(true)}
                >
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
            {submitting && (
              <div className="w-full mt-2">
                <div className="text-xs text-gray-600 mb-1">در حال بررسی اطلاعات... {progress}%</div>
                <div className="w-full bg-gray-200 h-2 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}

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

interface FormFieldProps {
  label: string;
  error?: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: (value: string) => void;
  type?: 'text' | 'tel' | 'password' | 'nationalId' | 'date' | 'card';
  maxLength?: number;
  inputMode?: 'text' | 'numeric' | 'tel' | 'email';
  dir?: 'ltr' | 'rtl';
}

function FormField({
  label,
  error,
  placeholder,
  value,
  onChange,
  onBlur,
  type = 'text',
  maxLength,
  inputMode = 'text',
  dir = 'rtl',
}: FormFieldProps) {
  // Handle different input types
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let newValue = e.target.value;
    
    // Apply formatting based on type
    switch (type) {
      case 'nationalId':
        // Only allow digits, max 10
        newValue = newValue.replace(/\D/g, '').slice(0, 10);
        break;
      case 'date':
        // Format as xxxx/yy/zz - allow up to 8 digits
        newValue = newValue.replace(/\D/g, '');
        // Allow up to 8 digits
        newValue = newValue.slice(0, 8);
        // Format with slashes after 4 digits and after 6 digits
        if (newValue.length > 4) {
          newValue = newValue.slice(0, 4) + '/' + newValue.slice(4);
        }
        if (newValue.length > 7) {
          newValue = newValue.slice(0, 7) + '/' + newValue.slice(7);
        }
        break;
      case 'card':
        // Format as 1234 5678 9012 3456
        newValue = newValue.replace(/\D/g, '');
        // Allow up to 16 digits
        newValue = newValue.slice(0, 16);
        // Format with spaces every 4 digits
        if (newValue.length > 4) {
          newValue = newValue.slice(0, 4) + ' ' + newValue.slice(4);
        }
        if (newValue.length > 9) {
          newValue = newValue.slice(0, 9) + ' ' + newValue.slice(9);
        }
        if (newValue.length > 14) {
          newValue = newValue.slice(0, 14) + ' ' + newValue.slice(14);
        }
        break;
      case 'tel':
        // Only allow digits for phone
        newValue = newValue.replace(/\D/g, '').slice(0, 11);
        break;
    }
    
    onChange(newValue);
  };

  // Determine input type for HTML
  const htmlType = type === 'password' ? 'password' : 
                   type === 'tel' ? 'tel' : 'text';
  
  // Determine input mode based on type
  let htmlInputMode: 'text' | 'numeric' | 'tel' | 'email' = 'text';
  
  if (inputMode) {
    htmlInputMode = inputMode;
  } else if (type === 'nationalId' || type === 'date' || type === 'card' || type === 'tel') {
    htmlInputMode = 'numeric';
  } else if (type === 'password') {
    htmlInputMode = 'text'; // Show full keyboard for password
  } else {
    htmlInputMode = 'text';
  }

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        {label}
      </label>
      <input
        type={htmlType}
        inputMode={htmlInputMode}
        value={value}
        onChange={handleChange}
        onBlur={() => onBlur?.(value)}
        className={`w-full px-4 py-3 border-2 rounded-xl focus:outline-none ${
          error
            ? 'border-red-500'
            : 'border-gray-200 focus:border-blue-500'
        } ${dir === 'ltr' ? 'text-left direction-ltr' : ''}`}
        placeholder={placeholder}
        // Don't set maxLength for formatted fields (date, card) as we handle formatting internally
        maxLength={type === 'date' || type === 'card' ? undefined : maxLength}
        dir={dir}
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
  const [resetMode, setResetMode] = useState<'' | 'bot' | 'sms'>('');
  const [resetCode, setResetCode] = useState('');
  const [newPassword, setNewPassword] = useState('');

  const startReset = async (channel: 'bot' | 'sms') => {
    if (!phoneNumber) {
      setError('ابتدا شماره موبایل را وارد کنید');
      return;
    }

    if (channel === 'bot') {
      notifyMessage('در تلگرام به ربات پیام /resetpassword بدهید و شماره خود را با Share Contact ارسال کنید.');
      return;
    }

    const response = await fetch(`${API_URL}/users/password-reset/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone_number: phoneNumber, channel }),
    });

    if (response.ok) {
      setResetMode(channel);
      notifyMessage('در صورت معتبر بودن شماره، کد بازیابی پیامک شد.');
    } else {
      setError('در ارسال درخواست بازیابی خطا رخ داد');
    }
  };

  const completeReset = async () => {
    const response = await fetch(`${API_URL}/users/password-reset/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        phone_number: phoneNumber,
        code: resetCode,
        new_password: newPassword,
      }),
    });

    if (response.ok) {
      notifyMessage('رمز عبور با موفقیت تغییر کرد.');
      setResetMode('');
      setResetCode('');
      setNewPassword('');
    } else {
      setError('کد بازیابی نامعتبر یا منقضی است');
    }
  };

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
              onChange={(e) => setPhoneNumber(e.target.value.replace(/\D/g, '').slice(0, 11))}
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

          <div className="text-center text-sm">
            <button onClick={() => startReset('bot')} className="text-blue-600 ml-3">فراموشی رمز (از طریق ربات)</button>
            <button onClick={() => startReset('sms')} className="text-blue-600">فراموشی رمز (پیامک)</button>
          </div>

          {resetMode && (
            <div className="bg-gray-50 border rounded-xl p-3 space-y-2">
              <input
                className="w-full px-3 py-2 border rounded"
                placeholder="کد تایید"
                value={resetCode}
                onChange={(e) => setResetCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              />
              <input
                type="password"
                className="w-full px-3 py-2 border rounded"
                placeholder="رمز عبور جدید"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
              <button onClick={completeReset} className="w-full bg-indigo-600 text-white py-2 rounded">ثبت رمز جدید</button>
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

function AdminPanelPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loggedIn, setLoggedIn] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  const [faqs, setFaqs] = useState<any[]>([]);
  const [statusRef, setStatusRef] = useState('');
  const [statusValue, setStatusValue] = useState('Under Review');
  const [faqQuestion, setFaqQuestion] = useState('');
  const [faqAnswer, setFaqAnswer] = useState('');
  const [receiptPhotoUrl, setReceiptPhotoUrl] = useState('');
  const [receiptDescription, setReceiptDescription] = useState('');
  const [paymentLink, setPaymentLink] = useState('');
  const [messageText, setMessageText] = useState('');
  const [targetUserId, setTargetUserId] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [rateAdjustments, setRateAdjustments] = useState<Record<string, number>>({ buy_lira: 0, sell_lira: 0, buy_usdt: 0, sell_usdt: 0, usdt_to_lira: 0, lira_to_usdt: 0 });

  const loadAll = async () => {
    const qs = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`;
    const [u, t, l, r, f] = await Promise.all([
      fetch(`${API_URL}/admin/users?${qs}`),
      fetch(`${API_URL}/admin/transactions?${qs}`),
      fetch(`${API_URL}/admin/logs?${qs}`),
      fetch(`${API_URL}/admin/reports?${qs}`),
      fetch(`${API_URL}/admin/faqs?${qs}`),
    ]);
    setUsers((await u.json()).users || []);
    setTransactions((await t.json()).transactions || []);
    setLogs((await l.json()).logs || []);
    setReport((await r.json()).report || null);
    setFaqs((await f.json()).faqs || []);
    const ra = await fetch(`${API_URL}/admin/rates/adjustments?${qs}`);
    if (ra.ok) {
      const raData = await ra.json();
      setRateAdjustments(raData.adjustments || {});
    }
  };

  const login = async () => {
    const res = await fetch(`${API_URL}/admin/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (res.ok) {
      setLoggedIn(true);
      loadAll();
    } else {
      notifyMessage('نام کاربری یا رمز عبور ادمین اشتباه است');
    }
  };

  if (!loggedIn) return <div className="p-6 max-w-md mx-auto"><div className="bg-white p-6 rounded-xl shadow"><h2 className="text-xl font-bold mb-4">ورود ادمین</h2><input className="w-full border p-2 mb-2 rounded" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} /><input type="password" className="w-full border p-2 mb-3 rounded" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} /><button onClick={login} className="w-full bg-blue-600 text-white py-2 rounded">Login</button></div></div>;

  return (
    <div className="p-4 space-y-4">
      <div className="flex justify-between items-center"><h2 className="text-2xl font-bold">Admin Panel</h2><button onClick={loadAll} className="bg-blue-100 px-3 py-1 rounded">Refresh</button></div>
      <div className="bg-white p-4 rounded-xl shadow text-sm">{report && <div>Orders: {report.total_orders} | Done: {report.done_orders} | Canceled: {report.canceled_orders}</div>}</div>
      <div className="bg-white p-4 rounded-xl shadow">
        <h3 className="font-bold mb-2">کنترل سفارش</h3>
        <div className="flex gap-2 flex-wrap"><input className="border p-2 rounded flex-1" placeholder="Reference Number" value={statusRef} onChange={(e) => setStatusRef(e.target.value)} /><input className="border p-2 rounded" value={statusValue} onChange={(e) => setStatusValue(e.target.value)} /><input className="border p-2 rounded flex-1" placeholder="Receipt photo URL" value={receiptPhotoUrl} onChange={(e)=>setReceiptPhotoUrl(e.target.value)} /><input className="border p-2 rounded flex-1" placeholder="Receipt description" value={receiptDescription} onChange={(e)=>setReceiptDescription(e.target.value)} /><input className="border p-2 rounded flex-1" placeholder="Payment link" value={paymentLink} onChange={(e)=>setPaymentLink(e.target.value)} /><button onClick={async () => { await fetch(`${API_URL}/admin/transactions/${statusRef}/update-status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, status: statusValue, receipt_photo_url: receiptPhotoUrl || null, receipt_description: receiptDescription || null, payment_link: paymentLink || null }) }); loadAll(); }} className="bg-green-600 text-white px-3 rounded">Update</button></div>
      </div>
      <div className="bg-white p-4 rounded-xl shadow"><h3 className="font-bold mb-2">Users ({users.length})</h3><div className="max-h-56 overflow-auto text-xs">{users.map((u) => <div key={u.id} className="border-b py-2"><div>#{u.id} | {u.first_name} {u.last_name} - {u.phone_number}</div><div>National ID: {u.national_id} | DOB: {u.dob} | Card: {u.bank_card_number}</div><div className="flex gap-2 mt-1"><button className="text-red-600" onClick={async () => { const qs = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`; await fetch(`${API_URL}/admin/users/${u.id}?${qs}`, { method: 'DELETE' }); loadAll(); }}>Delete</button><button className="text-blue-600" onClick={async ()=>{ if(!newUserPassword){notifyMessage('رمز جدید را در کادر پایین وارد کنید');return;} await fetch(`${API_URL}/admin/users/${u.id}/reset-password`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,new_password:newUserPassword})}); notifyMessage('رمز عبور کاربر تغییر کرد'); }}>Reset Password</button></div></div>)}</div><input className="border p-2 rounded w-full mt-2" placeholder="New password for reset action" value={newUserPassword} onChange={(e)=>setNewUserPassword(e.target.value)} /></div>
      <div className="bg-white p-4 rounded-xl shadow"><h3 className="font-bold mb-2">Exchange Requests ({transactions.length})</h3><div className="max-h-56 overflow-auto text-xs">{transactions.slice(0, 100).map((t) => <div key={t.id} className="border-b py-1">#{t.reference_number} | {t.exchange_pair} | {t.status} | {t.user_name} ({t.user_phone})<div>Receipt: {t.receipt_photo_url || '-'} | Link: {t.payment_link || '-'}</div><div>{t.receipt_description || ''}</div></div>)}</div></div><div className="bg-white p-4 rounded-xl shadow"><h3 className="font-bold mb-2">ارسال پیام دستی</h3><div className="flex gap-2"><input className="border p-2 rounded flex-1" placeholder="User ID (خالی = ارسال همگانی)" value={targetUserId} onChange={(e)=>setTargetUserId(e.target.value)} /><input className="border p-2 rounded flex-[2]" placeholder="متن پیام" value={messageText} onChange={(e)=>setMessageText(e.target.value)} /><button className="bg-purple-600 text-white px-3 rounded" onClick={async ()=>{const res=await fetch(`${API_URL}/admin/messages/send`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,message:messageText,user_id:targetUserId?Number(targetUserId):null})});const data=await res.json();notifyMessage(`ارسال شد: ${data.sent ?? 0}`);}}>Send</button></div></div>
      <div className="bg-white p-4 rounded-xl shadow"><h3 className="font-bold mb-2">FAQ ({faqs.length})</h3><div className="flex gap-2 mb-2"><input className="border p-2 rounded flex-1 text-xs" placeholder="سوال" value={faqQuestion} onChange={(e)=>setFaqQuestion(e.target.value)} /><input className="border p-2 rounded flex-1 text-xs" placeholder="پاسخ" value={faqAnswer} onChange={(e)=>setFaqAnswer(e.target.value)} /><button className="bg-blue-600 text-white px-2 rounded text-xs" onClick={async ()=>{await fetch(`${API_URL}/admin/faqs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,question:faqQuestion,answer:faqAnswer})});setFaqQuestion('');setFaqAnswer('');loadAll();}}>Add</button></div><div className="max-h-40 overflow-auto text-xs">{faqs.map((f) => <div key={f.id} className="border-b py-1 flex justify-between"><span>{f.question}</span><button className="text-red-600" onClick={async () => { const qs = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`; await fetch(`${API_URL}/admin/faqs/${f.id}?${qs}`, { method: 'DELETE' }); loadAll(); }}>Delete</button></div>)}</div></div>
      <div className="bg-white p-4 rounded-xl shadow">
        <h3 className="font-bold mb-2">Rate adjustments (%)</h3>
        <div className="grid grid-cols-2 gap-2 text-sm">
          {Object.keys(rateAdjustments).map((k) => (
            <label key={k} className="flex items-center gap-2">
              <span className="w-28">{k}</span>
              <input type="number" className="border p-1 rounded w-full" value={rateAdjustments[k] ?? 0} onChange={(e) => setRateAdjustments((prev) => ({ ...prev, [k]: Number(e.target.value) }))} />
            </label>
          ))}
        </div>
        <button className="mt-3 bg-indigo-600 text-white px-3 py-1 rounded" onClick={async () => {
          const res = await fetch(`${API_URL}/admin/rates/adjustments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, adjustments: rateAdjustments }) });
          if (res.ok) notifyMessage('نرخ ها ذخیره شد'); else notifyMessage('خطا در ذخیره نرخ ها');
        }}>Save rates</button>
      </div>
      <div className="bg-white p-4 rounded-xl shadow"><h3 className="font-bold mb-2">Logs ({logs.length})</h3><div className="max-h-40 overflow-auto text-xs">{logs.slice(0, 100).map((l) => <div key={l.id} className="border-b py-1">{l.created_at} - {l.action}</div>)}</div></div>
    </div>
  );
}

// ─── PART 6: History Page ───────────────────────────────────────────────────

function HistoryPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRef, setExpandedRef] = useState<string | null>(null);
  const [receiptDescription, setReceiptDescription] = useState('');
  const [receiptDataUrl, setReceiptDataUrl] = useState('');

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

  const uploadReceipt = async (reference: string) => {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_URL}/transactions/${reference}/receipt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ receipt_photo_url: receiptDataUrl || null, receipt_description: receiptDescription || null }),
    });
    if (res.ok) {
      notifyMessage('رسید با موفقیت ثبت شد');
      setReceiptDataUrl('');
      setReceiptDescription('');
      fetchTransactions();
    } else {
      notifyMessage('ثبت رسید ناموفق بود');
    }
  };

  const cancelTx = async (reference: string) => {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_URL}/transactions/${reference}/cancel`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      notifyMessage('سفارش لغو شد');
      fetchTransactions();
    } else {
      notifyMessage('لغو سفارش انجام نشد');
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      Pending: 'bg-yellow-100 text-yellow-700',
      Done: 'bg-green-100 text-green-700',
      Rejected: 'bg-red-100 text-red-700',
      'Canceled by User': 'bg-red-100 text-red-700',
      'Canceled by Admin': 'bg-red-100 text-red-700',
    };
    return colors[status] || 'bg-gray-100 text-gray-700';
  };

  return <div className="p-4"><h2 className="text-2xl font-bold text-gray-800 mb-4">تاریخچه تراکنش‌ها</h2>{loading ? <div className="text-center py-10">...</div> : <div className="space-y-3">{transactions.map((tx) => (<div key={tx.id} className="bg-white rounded-xl p-4 shadow-md"><button className="w-full text-right" onClick={() => setExpandedRef(expandedRef === tx.reference_number ? null : tx.reference_number)}><div className="flex justify-between items-start mb-3"><div><p className="font-semibold text-gray-800">{tx.exchange_pair}</p><p className="text-xs text-gray-500 mt-1">شماره پیگیری: {tx.reference_number}</p></div><span className={`px-3 py-1 rounded-full text-xs font-semibold ${getStatusColor(tx.status)}`}>{tx.status}</span></div></button>{expandedRef === tx.reference_number && <div className="border-t pt-3 mt-3 space-y-2"><button className="bg-red-600 text-white px-3 py-2 rounded text-sm" onClick={() => cancelTx(tx.reference_number)}>لغو سفارش</button><input type="file" accept="image/*" onChange={(e) => { const file = e.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => setReceiptDataUrl(String(reader.result || '')); reader.readAsDataURL(file); }} /><input className="w-full border p-2 rounded text-sm" placeholder="توضیح رسید" value={receiptDescription} onChange={(e) => setReceiptDescription(e.target.value)} /><button className="bg-blue-600 text-white px-3 py-2 rounded text-sm" onClick={() => uploadReceipt(tx.reference_number)}>ثبت رسید</button></div>}<p className="text-xs text-gray-500 mt-3">{new Date(tx.timestamp).toLocaleString('fa-IR')}</p></div>))}</div>}</div>;
}

function FaqPage() {
  const [faqs, setFaqs] = useState<any[]>([]);

  useEffect(() => {
    fetch(`${API_URL}/faqs`).then((r) => r.json()).then((d) => setFaqs(d.faqs || [])).catch(() => setFaqs([]));
  }, []);

  return (
    <div className="p-4 space-y-3">
      <h2 className="text-2xl font-bold text-gray-800">FAQ</h2>
      {faqs.map((f) => (
        <div key={f.id} className="bg-white rounded-xl p-4 shadow">
          <p className="font-bold text-sm mb-2">{f.question}</p>
          <p className="text-sm text-gray-700">{f.answer}</p>
        </div>
      ))}
    </div>
  );
}

export default App;
