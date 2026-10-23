import kianiBrandLockup from './assets/kiani-brand-lockup.png';
import { isTradeReady, MINIMUM_TRADE_SOURCES } from './rateAvailability';
import type { RateSources, RateSourceState } from './rateAvailability';
import { useState, useEffect, useCallback, useRef } from 'react';
import { calculateFee, calculateReceiveAmount } from './exchangeMath';
import type { ExchangeType, Rates } from './exchangeMath';
import CustomerMarketDashboard from './CustomerMarketDashboard';
import SecureAdminPanel from './SecureAdminPanel';
import SmsPasswordReset from './SmsPasswordReset';
import AppNotice, { notifyMessage } from './AppNotice';
import BlockingProgressModal from './BlockingProgressModal';
import type { ProgressStep } from './BlockingProgressModal';

const API_URL = import.meta.env.VITE_API_URL || '/api';

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
}

type TabType = 'dashboard' | 'exchange' | 'register' | 'login' | 'history' | 'admin';

// ─── Helper Components ──────────────────────────────────────────────────────

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
  const [displayRates, setDisplayRates] = useState<Rates>(rates);
  const [rateError, setRateError] = useState(false);
  const [rateSources, setRateSources] = useState<RateSources>({
    shahidi: { ok: false, receivedAt: null },
    canonical: { ok: false, receivedAt: null },
    current: { ok: false, receivedAt: null },
  });
  const [rateUpdatedAt, setRateUpdatedAt] = useState<number | null>(null);
  const [rateRefreshedAt, setRateRefreshedAt] = useState<number | null>(null);
  const [rateDeltas, setRateDeltas] = useState({ usdt: 0, try: 0 });
  const [changedRates, setChangedRates] = useState<Set<string>>(new Set());
  const [customerScheme, setCustomerScheme] = useState<'light' | 'dark'>(() =>
    localStorage.getItem('kiani_theme_preference') === 'dark' ? 'dark' : 'light'
  );
  const [selectedExchange, setSelectedExchange] = useState<ExchangeType | null>(null);
  const displayRatesRef = useRef<Rates>(rates);
  const hasLoadedRatesRef = useRef(false);
  const rateRequestRef = useRef(false);
  const changedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isAdminHost) return;
    const background = customerScheme === 'dark' ? '#0F171C' : '#F4F6F7';
    document.getElementById('root')?.setAttribute('data-scheme', customerScheme);
    document.documentElement.style.backgroundColor = background;
    document.body.style.backgroundColor = background;
    (window as any)?.Telegram?.WebApp?.setHeaderColor?.(background);
    (window as any)?.Telegram?.WebApp?.setBackgroundColor?.(background);
  }, [customerScheme]);

  const toggleCustomerTheme = () => {
    setCustomerScheme((current) => {
      const next = current === 'dark' ? 'light' : 'dark';
      localStorage.setItem('kiani_theme_preference', next);
      const background = next === 'dark' ? '#0F171C' : '#F4F6F7';
      (window as any)?.Telegram?.WebApp?.setHeaderColor?.(background);
      (window as any)?.Telegram?.WebApp?.setBackgroundColor?.(background);
      return next;
    });
  };

  // Check for existing session on mount
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      fetchUserProfile(token);
    }
    void fetchRates();
    const interval = window.setInterval(() => void fetchRates(), 20000);
    return () => {
      window.clearInterval(interval);
      if (changedTimerRef.current) clearTimeout(changedTimerRef.current);
    };
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

  const fetchRates = async (): Promise<boolean> => {
    if (rateRequestRef.current) return false;
    rateRequestRef.current = true;
    setRateError(false);
    if (!hasLoadedRatesRef.current) setLoading(true);

    const fetchJson = async (path: string) => {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(`${API_URL}${path}`, {
          cache: 'no-store',
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Rate API HTTP ${response.status}`);
        }
        return await response.json();
      } finally {
        window.clearTimeout(timer);
      }
    };

    const applyDisplayRates = (
      values: Rates,
      sourceState: RateSourceState,
      tryState: RateSourceState,
    ) => {
      const previous = displayRatesRef.current;
      const next = values;
      displayRatesRef.current = next;
      setDisplayRates(next);

      setRateDeltas({
        usdt: previous.buy_usdt > 0
          ? ((values.buy_usdt - previous.buy_usdt) / previous.buy_usdt) * 100 : 0,
        try: previous.buy_lira > 0
          ? ((values.buy_lira - previous.buy_lira) / previous.buy_lira) * 100 : 0,
      });

      const changed = new Set<string>();
      if (previous.buy_usdt > 0 && previous.buy_usdt !== next.buy_usdt)
        changed.add('usdt-buy');
      if (previous.sell_usdt > 0 && previous.sell_usdt !== next.sell_usdt)
        changed.add('usdt-sell');
      if (previous.buy_lira > 0 && previous.buy_lira !== next.buy_lira)
        changed.add('try-buy');
      if (previous.sell_lira > 0 && previous.sell_lira !== next.sell_lira)
        changed.add('try-sell');

      if (changed.size) {
        setChangedRates(changed);
        if (changedTimerRef.current) clearTimeout(changedTimerRef.current);
        changedTimerRef.current = setTimeout(
          () => setChangedRates(new Set()),
          1100,
        );
      }

      setRateSources((old) => ({
        ...old,
        current: sourceState,
        currentTry: tryState,
        shahidi: sourceState,
      }));
      setRateUpdatedAt(sourceState.receivedAt);
      setRateRefreshedAt(Date.now());
      hasLoadedRatesRef.current = true;
      setLoading(false);
    };

    const loadShahidi = async (): Promise<boolean> => {
      try {
        const data = await fetchJson('/rates/current');
        const source = data?.rates;
        const values = {
          buy_lira: Number(source?.buy_lira),
          sell_lira: Number(source?.sell_lira),
          buy_usdt: Number(source?.buy_usdt),
          sell_usdt: Number(source?.sell_usdt),
          lira_to_usdt: Number(source?.lira_to_usdt),
          usdt_to_lira: Number(source?.usdt_to_lira),
          foreign_payment: Number(source?.foreign_payment),
        };

        const transactionRatesAvailable =
          source?.transaction_rates_available === true &&
          source?.rate_mode === 'confirmed' &&
          Number.isInteger(source?.market_source_count) &&
          source.market_source_count >= MINIMUM_TRADE_SOURCES;
        const sourceCount = Number(source?.market_source_count);
        if (!Number.isInteger(sourceCount) || sourceCount < 1 || sourceCount > 7)
          throw new Error('Invalid display source count');
        const marketState = (market: 'usdt' | 'try', validValues: boolean): RateSourceState => {
          const metadata = source?.market_status?.[market];
          if (metadata?.available === false || !validValues)
            return { ok: false, receivedAt: null, transactionRatesAvailable: false, sourceCount };
          const age = Number(metadata?.age_seconds ?? (market === 'try'
            ? Math.max(Number(source?.market_age_seconds), Number(source?.market_usdt_try_age_seconds ?? source?.market_age_seconds))
            : source?.market_age_seconds));
          const receivedAt = Date.now() - age * 1000;
          const expiresAt = Math.min(Date.parse(metadata?.valid_until_utc ?? source?.market_feed_valid_until_utc), receivedAt + 90_000);
          if (!Number.isFinite(age) || age < 0 || age > 90 || !Number.isFinite(expiresAt) || expiresAt <= Date.now())
            return { ok: false, receivedAt: null, transactionRatesAvailable: false, sourceCount };
          return { ok: true, receivedAt, expiresAt, transactionRatesAvailable, sourceCount };
        };
        const positive = (items: number[]) => items.every((v) => Number.isFinite(v) && v > 0);
        const usdtState = marketState('usdt', positive([values.buy_usdt, values.sell_usdt, values.foreign_payment]) && values.buy_usdt >= values.sell_usdt);
        const tryState = marketState('try', positive([values.buy_lira, values.sell_lira, values.lira_to_usdt, values.usdt_to_lira]) && values.buy_lira >= values.sell_lira && values.lira_to_usdt >= values.usdt_to_lira);
        if (!usdtState.ok && !tryState.ok) throw new Error('No fresh display market');
        if (!usdtState.ok) { values.buy_usdt = 0; values.sell_usdt = 0; values.foreign_payment = 0; }
        if (!tryState.ok) { values.buy_lira = 0; values.sell_lira = 0; values.lira_to_usdt = 0; values.usdt_to_lira = 0; }
        applyDisplayRates(values, usdtState, tryState);
        setRates((old) => ({
          ...old,
          buy_usdt: values.buy_usdt,
          sell_usdt: values.sell_usdt,
          lira_to_usdt: values.lira_to_usdt,
          usdt_to_lira: values.usdt_to_lira,
          foreign_payment: values.foreign_payment,
        }));
        return true;
      } catch (error) {
        console.error('Shahidi rates unavailable:', error);
        setRateSources((old) => ({
          ...old,
          shahidi: { ...old.shahidi, ok: false },
          // Keep the display's original expiry through a temporary refresh failure.
          // Transaction readiness is revoked immediately by shahidi.ok above.
        }));
        return false;
      }
    };

    const loadCanonical = async (): Promise<boolean> => {
      try {
        const data = await fetchJson('/rates/try');
        const source = data?.rates;
        const age = Number(source?.market_age_seconds);
        const buyAdjustment = Number(source?.buy_adjustment_pct);
        const sellAdjustment = Number(source?.sell_adjustment_pct);
        const sourceCount = Number(source?.source_count);
        const validSource = (
          source?.source === 'channel-hybrid-usdt+btcturk' &&
          Number.isInteger(sourceCount) && sourceCount >= MINIMUM_TRADE_SOURCES && sourceCount <= 7
        );
        const values = {
          buy_lira: Number(source?.buy_lira),
          sell_lira: Number(source?.sell_lira),
        };

        if (
          !validSource ||
          !Number.isFinite(age) || age < 0 || age > 90 ||
          !Number.isFinite(buyAdjustment) ||
          Math.abs(buyAdjustment) > 50 ||
          !Number.isFinite(sellAdjustment) ||
          Math.abs(sellAdjustment) > 50 ||
          Object.values(values).some(
            (v) => !Number.isFinite(v) || v <= 0
          ) ||
          values.buy_lira < values.sell_lira
        ) {
          throw new Error('Invalid canonical TRY rates');
        }

        const receivedAt = Date.now() - age * 1000;
        setRates((old) => ({ ...old, ...values }));
        setRateSources((old) => ({
          ...old,
          canonical: { ok: true, receivedAt, expiresAt: receivedAt + 90_000, transactionRatesAvailable: true, sourceCount },
        }));
        return true;
      } catch (error) {
        console.error('Canonical TRY rates unavailable:', error);
        setRateSources((old) => ({
          ...old,
          canonical: { ...old.canonical, ok: false },
        }));
        return false;
      }
    };

    try {
      const [shahidiOk] = await Promise.all([
        loadShahidi(),
        loadCanonical(),
      ]);
      setRateError(!shahidiOk);
      return shahidiOk;
    } finally {
      rateRequestRef.current = false;
      setLoading(false);
    }
  };

  const handleExchangeClick = (exchangeType: ExchangeType) => {
    if (!user || user.kyc_status !== 'Approved') {
      setActiveTab('login');
      return;
    }
    if (!isTradeReady(
      rateSources,
      exchangeType,
      Date.now(),
    )) {
      notifyMessage('نرخ این معامله موقتاً در دسترس نیست.');
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
    <div data-ke="" data-scheme={customerScheme} className="min-h-screen bg-gray-100 pb-20">
      <AppNotice />
      {/* Header */}
      <header className="bg-gradient-to-r from-blue-700 to-purple-700 text-white p-4 shadow-lg">
        <div className="flex justify-between items-center">
          <h1 className="ke-main-brand">
            <img
              src={kianiBrandLockup}
              alt="صرافی کیانی — kiani.exchange"
              width={200}
              height={82}
              className="ke-brand-lockup"
            />
          </h1>
          <div className="ke-header-actions">
            <button
              type="button"
              onClick={toggleCustomerTheme}
              aria-label={customerScheme === 'dark' ? 'فعال کردن حالت روشن' : 'فعال کردن حالت تاریک'}
              aria-pressed={customerScheme === 'dark'}
              className={`relative inline-flex h-10 w-[72px] shrink-0 rounded-full transition-colors duration-300 ${
                customerScheme === 'dark' ? 'bg-[#292f39]' : 'bg-[#bdbdbd]'
              }`}
            >
              <span
                className={`absolute left-1 top-1 flex h-8 w-8 items-center justify-center rounded-[13px] bg-white text-[#171b22] shadow-sm transition-transform duration-300 ${
                  customerScheme === 'dark' ? 'translate-x-9' : 'translate-x-0'
                }`}
                aria-hidden="true"
              >
                {customerScheme === 'dark' ? (
                  <svg width="23" height="23" viewBox="0 0 24 24"
                    fill="none" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5
                             8.5 8.5 0 1 0 20.5 14.2Z" />
                  </svg>
                ) : (
                  <svg width="23" height="23" viewBox="0 0 24 24"
                    fill="none" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round">
                    <circle cx="12" cy="12" r="4" />
                    <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42
                             M17.65 17.65l1.42 1.42M2 12h2M20 12h2
                             M4.93 19.07l1.42-1.42
                             M17.65 6.35l1.42-1.42" />
                  </svg>
                )}
              </span>
            </button>
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
        </div>
      </header>

      {/* Main Content */}
      <main className={activeTab === 'dashboard' ? 'ke-main ke-dashboard-main' : 'ke-main ke-legacy-main'}>
        {activeTab === 'dashboard' && (
          <CustomerMarketDashboard
            rates={displayRates}
            loading={loading}
            onExchangeClick={handleExchangeClick}
            onRefresh={fetchRates}
            updatedAt={rateUpdatedAt}
            refreshedAt={rateRefreshedAt}
            deltas={rateDeltas}
            changed={changedRates}
            rateError={rateError}
            rateSources={rateSources}
          />
        )}
        {activeTab === 'exchange' && selectedExchange && (
          <ExchangePage
            rates={rates}
            user={user}
            selectedExchange={selectedExchange}
            rateSources={rateSources}
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

// ─── PART 3: Exchange Page ──────────────────────────────────────────────────

function ExchangePage({
  rates,
  user,
  selectedExchange,
  rateSources,
  onBack,
}: {
  rates: Rates;
  user: User | null;
  selectedExchange: ExchangeType;
  rateSources: RateSources;
  onBack: () => void;
}) {
  const [amount, setAmount] = useState('');
  const [quoteClock, setQuoteClock] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(
      () => setQuoteClock(Date.now()),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);

  const quoteAvailable = isTradeReady(
    rateSources,
    selectedExchange,
    quoteClock,
  );
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
    if (!isTradeReady(
      rateSources,
      selectedExchange,
      Date.now(),
    )) {
      notifyMessage('نرخ این معامله معتبر نیست. لطفاً بروزرسانی کنید.');
      return;
    }
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
        const confirmed = await response.json();
        const confirmedReceive = Number(confirmed?.receive_amount);

        if (Number.isFinite(confirmedReceive) && confirmedReceive >= 0) {
          setReceiveAmount(confirmedReceive);
          adminNotificationData.receive_amount = confirmedReceive;
        } else {
          console.error('Transaction confirmation missing valid receive_amount');
        }

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
                {quoteAvailable ? formatReceiveAmount(receiveAmount, selectedExchange, 'receive') : '—'}
              </p>
            </div>
          </div>

          {/* Submit Button */}
          <button
            onClick={handleSubmit}
            disabled={
              !user ||
              user.kyc_status !== 'Approved' ||
              !amount ||
              !quoteAvailable
            }
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
  fatherName: string;
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
  type RegistrationStage = 'precheck' | 'mobile' | 'civil' | 'card' | 'creating' | 'done';
  const [verificationStage, setVerificationStage] = useState<RegistrationStage>('precheck');
  const [verificationModalStatus, setVerificationModalStatus] = useState<'idle' | 'working' | 'success' | 'error'>('idle');
  const [verificationMessage, setVerificationMessage] = useState('');
  const [registrationCompleted, setRegistrationCompleted] = useState(false);
  const progressCeilingRef = useRef(18);
  const [showTerms, setShowTerms] = useState(false);
  const [registrationAvailability, setRegistrationAvailability] = useState<'loading' | 'ready' | 'paused' | 'unavailable'>('loading');
  useEffect(() => {
    let active = true;
    fetch(`${API_URL}/users/registration-options`, { cache: 'no-store' })
      .then(async (response) => {
        const options = await response.json().catch(() => null);
        if (!active) return;
        setRegistrationAvailability(response.ok && options?.registration_enabled === true ? 'ready'
          : response.ok && options?.reason === 'birth_date_verification_unavailable' ? 'paused' : 'unavailable');
      })
      .catch(() => { if (active) setRegistrationAvailability('unavailable'); });
    return () => { active = false; };
  }, []);
  const [formData, setFormData] = useState<RegistrationFormData>({
    firstName: '',
    lastName: '',
    fatherName: '',
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

  useEffect(() => {
    if (!submitting) return;
    const preventLeave = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', preventLeave);
    return () => window.removeEventListener('beforeunload', preventLeave);
  }, [submitting]);

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
    if (!formData.fatherName || !isPersianText(formData.fatherName)) {
      newErrors.fatherName = 'لطفاً نام پدر را با حروف فارسی وارد کنید';
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
    if (field === 'fatherName' && strValue && !isPersianText(strValue)) {
      nextErrors.fatherName = 'لطفاً نام پدر را با حروف فارسی وارد کنید';
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


  const failVerification = (message: string) => {
    setVerificationMessage(message);
    setVerificationModalStatus('error');
  };

  const handleSubmit = async () => {
    if (submitting || !validateForm()) return;
    if (attempts >= 5) {
      notifyMessage('شما امروز ۵ بار تلاش کرده‌اید. لطفاً فردا دوباره تلاش کنید.');
      return;
    }

    setSubmitting(true);
    setRegistrationCompleted(false);
    setVerificationModalStatus('working');
    setVerificationStage('precheck');
    setVerificationMessage('در حال بررسی اولیه اطلاعات وارد شده...');
    setProgress(5);
    progressCeilingRef.current = 18;
    const progressTimer = window.setInterval(() => {
      setProgress((previous) => Math.min(progressCeilingRef.current, previous + 1));
    }, 900);

    const stage = (next: RegistrationStage, value: number, ceiling: number, message: string) => {
      setVerificationStage(next);
      setProgress((previous) => Math.max(previous, value));
      progressCeilingRef.current = ceiling;
      setVerificationMessage(message);
    };
    const checkMatch = async (path: string, payload: Record<string, string>, mismatch: string, requireBirthDateProof = false) => {
      const response = await fetch(`${API_URL}${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok && data?.detail === 'ownership_lookup_unconfirmed') {
        failVerification(path === '/verify/ehraz-mobile'
          ? 'تطبیق شماره موبایل و کد ملی تأیید نشد. کد ملی را بررسی کنید و از شماره موبایل متعلق به همان کد ملی استفاده کنید. اگر اطلاعات صحیح است، کمی بعد دوباره تلاش کنید. این بررسی از سهمیه تلاش‌ها کم نمی‌کند.'
          : 'تطبیق مالکیت کارت بانکی و کد ملی تأیید نشد. شماره کارت و کد ملی را بررسی کنید و فقط کارت متعلق به خودتان را وارد کنید. اگر اطلاعات صحیح است، کمی بعد دوباره تلاش کنید. این بررسی از سهمیه تلاش‌ها کم نمی‌کند.');
        return false;
      }
      if (!response.ok && path === '/verify/ehraz-identity' && data?.detail === 'identity_lookup_unconfirmed') {
        failVerification('ثبت احوال نتوانست اطلاعات واردشده را تأیید کند. نام، نام خانوادگی، نام پدر و تاریخ تولد را مطابق مدارک بررسی کنید. اگر اطلاعات صحیح است، کمی بعد دوباره تلاش کنید. این خطا از تعداد تلاش‌های شما کم نمی‌کند.');
        return false;
      }
      if (!response.ok || typeof data?.matched !== 'boolean') {
        failVerification('سرویس بررسی این مرحله موقتاً در دسترس نیست. لطفاً کمی بعد دوباره تلاش کنید. این خطا از تعداد تلاش‌های شما کم نمی‌کند.');
        return false;
      }
      if (data.matched !== true) {
        incrementAttempts();
        failVerification(mismatch);
        return false;
      }
      if (requireBirthDateProof && data.birth_date_verified !== true) {
        failVerification('تطبیق نام و نام پدر انجام شد، اما تاریخ تولد به‌طور مستقل تأیید نشده است. ثبت‌نام جدید تا فراهم شدن این تأیید موقتاً متوقف است.');
        return false;
      }
      return true;
    };

    try {
      // Check availability before any paid identity lookup.
      const optionsResponse = await fetch(`${API_URL}/users/registration-options`, { cache: 'no-store' });
      const options = await optionsResponse.json().catch(() => null);
      if (!optionsResponse.ok || options?.registration_enabled !== true) {
        failVerification(options?.reason === 'birth_date_verification_unavailable'
          ? 'ثبت‌نام جدید موقتاً متوقف است؛ تأیید مستقل تاریخ تولد هنوز در دسترس نیست. اگر حساب دارید، از صفحه ورود استفاده کنید.'
          : 'امکان بررسی وضعیت ثبت‌نام موقتاً وجود ندارد. لطفاً کمی بعد دوباره تلاش کنید.');
        return;
      }
      stage('mobile', 20, 36, 'در حال تطبیق مالکیت شماره موبایل با کد ملی...');
      if (!await checkMatch('/verify/ehraz-mobile', {
        nationalCode: formData.nationalId, mobileNumber: formData.phoneNumber,
      }, 'شماره موبایل و کد ملی با هم تطابق ندارند. کد ملی را بررسی کنید و از شماره موبایل متعلق به همان کد ملی استفاده کنید.')) return;

      stage('civil', 38, 62, 'در حال بررسی مشخصات هویتی، نام پدر و تاریخ تولد...');
      if (!await checkMatch('/verify/ehraz-identity', {
        nationalCode: formData.nationalId,
        birthDate: formData.dateOfBirth.replace(/\//g, ''),
        firstName: formData.firstName, lastName: formData.lastName,
        fatherName: formData.fatherName,
      }, 'مشخصات هویتی یا تاریخ تولد مطابقت ندارد. نام، نام خانوادگی، نام پدر و تاریخ تولد را دقیقاً مطابق مدارک هویتی وارد کنید.', true)) return;

      stage('card', 65, 83, 'در حال تطبیق مالکیت کارت بانکی با کد ملی...');
      if (!await checkMatch('/verify/ehraz', {
        cardNumber: formData.bankCardNumber.replace(/\s/g, ''),
        nationalCode: formData.nationalId,
        birthDate: formData.dateOfBirth.replace(/\//g, ''),
      }, 'کارت بانکی با کد ملی تطابق ندارد. فقط کارت بانکی متعلق به خودتان را وارد کنید.')) return;

      stage('creating', 86, 98, 'بررسی نهایی اطلاعات و ایجاد حساب کاربری...');
      const response = await fetch(`${API_URL}/users/register`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          first_name: formData.firstName, last_name: formData.lastName,
          father_name: formData.fatherName, national_id: formData.nationalId,
          date_of_birth: formData.dateOfBirth.replace(/\//g, ''),
          bank_card_number: formData.bankCardNumber.replace(/\s/g, ''),
          phone_number: formData.phoneNumber, password: formData.password,
        }),
      });
      const data = await response.json().catch(() => null);
      if (response.ok) {
        setProgress(100);
        setVerificationStage('done');
        setRegistrationCompleted(true);
        setVerificationMessage('ثبت نام با موفقیت انجام شد. اکنون می‌توانید وارد حساب خود شوید.');
        setVerificationModalStatus('success');
        return;
      }
      if (response.status === 409) {
        failVerification('این اطلاعات قبلاً ثبت شده‌اند. اگر حساب دارید، از صفحه ورود استفاده کنید.');
        return;
      }
      if (data?.detail === 'identity_birth_mismatch') {
        incrementAttempts();
        setVerificationStage('civil');
        failVerification('مشخصات هویتی یا تاریخ تولد مطابقت ندارد. لطفاً اطلاعات صحیح را وارد کنید.');
        return;
      }
      if (data?.detail === 'phone_national_mismatch' || data?.detail === 'card_national_mismatch') {
        incrementAttempts();
        setVerificationStage(data.detail === 'phone_national_mismatch' ? 'mobile' : 'card');
        failVerification('مالکیت شماره موبایل یا کارت بانکی با کد ملی مطابقت ندارد.');
        return;
      }
      failVerification('تأیید نهایی احراز هویت موقتاً در دسترس نیست. لطفاً کمی بعد دوباره تلاش کنید. این خطا از تعداد تلاش‌های شما کم نمی‌کند.');
    } catch {
      failVerification('ارتباط با سرور قطع شد. لطفاً اینترنت خود را بررسی کرده و دوباره تلاش کنید. این خطا از تعداد تلاش‌های شما کم نمی‌کند.');
    } finally {
      window.clearInterval(progressTimer);
      setSubmitting(false);
    }
  };

  const registrationStageOrder = { precheck: 0, mobile: 1, civil: 2, card: 3, creating: 4, done: 5 } as const;
  const currentStage = registrationStageOrder[verificationStage];
  const registrationSteps: ProgressStep[] = [
    'بررسی اولیه اطلاعات',
    'تطبیق موبایل و کد ملی',
    'تطبیق مشخصات هویتی و تاریخ تولد',
    'تطبیق کارت بانکی و کد ملی',
    'ایجاد حساب کاربری',
  ].map((label, index): ProgressStep => ({
    label,
    state: verificationModalStatus === 'error' && index === currentStage ? 'error'
      : verificationStage === 'done' || index < currentStage ? 'done'
      : index === currentStage ? 'active' : 'pending',
  }));


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
    <>
      <BlockingProgressModal
        open={verificationModalStatus !== 'idle'}
        title={verificationModalStatus === 'success' ? 'ثبت نام با موفقیت انجام شد'
          : verificationModalStatus === 'error' ? 'بررسی اطلاعات انجام نشد'
          : 'در حال بررسی اطلاعات شما'}
        description={verificationModalStatus === 'working'
          ? 'تا پایان بررسی همه مراحل، لطفاً این صفحه را باز نگه دارید.' : undefined}
        progress={progress}
        status={verificationModalStatus === 'success' ? 'success'
          : verificationModalStatus === 'error' ? 'error' : 'working'}
        message={verificationMessage}
        steps={registrationSteps}
        closeLabel={registrationCompleted ? 'رفتن به صفحه ورود' : 'بستن و اصلاح اطلاعات'}
        onClose={verificationModalStatus === 'working' ? undefined : () => {
          setVerificationModalStatus('idle');
          if (registrationCompleted) onLoginRedirect();
        }}
      />

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
            {registrationAvailability !== 'ready' && (
              <div role="status" className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">
                {registrationAvailability === 'paused'
                  ? 'ثبت‌نام جدید موقتاً متوقف است؛ تأیید مستقل تاریخ تولد هنوز در دسترس نیست. اگر حساب دارید، از صفحه ورود استفاده کنید.'
                  : registrationAvailability === 'loading' ? 'در حال بررسی امکان ثبت‌نام...'
                  : 'وضعیت ثبت‌نام موقتاً در دسترس نیست. لطفاً کمی بعد دوباره تلاش کنید.'}
              </div>
            )}

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

            <FormField
              label="نام پدر (فارسی)"
              error={errors.fatherName}
              placeholder="نام پدر مطابق مدرک هویتی"
              value={formData.fatherName}
              onChange={(v) => updateField('fatherName', v)}
              onBlur={(v) => validateSingleField('fatherName', v)}
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
              disabled={registrationAvailability !== 'ready' || submitting || attempts >= 5}
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
    </>
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

  const startReset = (channel: 'bot' | 'sms') => {
    setError('');
    if (channel === 'bot') {
      notifyMessage('در تلگرام به ربات پیام /resetpassword بدهید و شماره خود را با Share Contact ارسال کنید.');
    } else {
      setResetMode('sms');
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

  if (resetMode === 'sms') {
    return <SmsPasswordReset initialPhone={phoneNumber} onBack={() => setResetMode('')}
      onComplete={(phone) => { setPhoneNumber(phone); setPassword(''); setResetMode(''); setError(''); }} />;
  }

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
  return <SecureAdminPanel />;
}

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
      'Canceled by User': 'bg-red-100 text-red-700',
      'Canceled by Admin': 'bg-red-100 text-red-700',
      'Under Review': 'bg-blue-100 text-blue-700',
      'Under Process': 'bg-purple-100 text-purple-700',
      'Waiting for User\'s Payment': 'bg-orange-100 text-orange-700',
      'Waiting for Admin to Pay': 'bg-orange-100 text-orange-700',
      Done: 'bg-green-100 text-green-700',
      Rejected: 'bg-red-100 text-red-700',
    };
    return colors[status] || 'bg-gray-100 text-gray-700';
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      Pending: 'در انتظار',
      Approved: 'تایید شده',
      Expired: 'منقضی شده',
      Canceled: 'لغو شده',
      'Canceled by User': 'لغو شده توسط کاربر',
      'Canceled by Admin': 'لغو شده توسط ادمین',
      'Under Review': 'در حال بررسی',
      'Under Process': 'در حال پردازش',
      'Waiting for User\'s Payment': 'در انتظار پرداخت کاربر',
      'Waiting for Admin to Pay': 'در انتظار پرداخت ادمین',
      Done: 'انجام شده',
      Rejected: 'رد شده',
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
