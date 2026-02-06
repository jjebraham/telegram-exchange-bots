import React, { useState, useEffect } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  ArrowRightLeft,
  History,
  MessageCircle,
  Calculator,
} from "lucide-react";

declare global {
  interface Window {
    Telegram?: {
      WebApp: any;
    };
  }
}

const API_URL = "https://kiani.peerexo.com/api";

export default function KianiExchangeApp() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [rates, setRates] = useState({
    USDT_IRR: 0,
    USDT_TRY: 0,
    TRY_IRR: 0,
  });
  const [chartData, setChartData] = useState<
    { date: string; rate: number }[]
  >([]);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<any>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<
    { type: "user" | "bot"; text: string }[]
  >([]);
  const [chatInput, setChatInput] = useState("");

  const [calcFrom, setCalcFrom] = useState("IRR");
  const [calcTo, setCalcTo] = useState("USDT");
  const [calcAmount, setCalcAmount] = useState("");
  const [calcResult, setCalcResult] = useState<any>(null);

  useEffect(() => {
    initApp();
  }, []);

  const initApp = async () => {
    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp;
      tg.ready();
      tg.expand();

      const initData = tg.initDataUnsafe;
      if (initData.user) {
        await authenticateUser(initData.user);
      }
    }

    await fetchRates();
    await fetchChartData();
    setLoading(false);
  };

  const authenticateUser = async (telegramUser: {
    id: number;
    first_name: string;
    last_name?: string;
  }) => {
    try {
      const response = await fetch(`${API_URL}/auth/telegram`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          telegram_id: telegramUser.id,
          first_name: telegramUser.first_name,
          last_name: telegramUser.last_name,
        }),
      });
      const data = await response.json();

      if (data.token) {
        localStorage.setItem("token", data.token);
        setUser(data.user);
        await fetchTransactions();
      }
    } catch (error) {
      console.error("Auth error:", error);
    }
  };

  const fetchRates = async () => {
    try {
      const response = await fetch(`${API_URL}/rates/current`);
      const data = await response.json();
      setRates(data.rates);
    } catch (error) {
      console.error("Error fetching rates:", error);
    }
  };

  const fetchChartData = async () => {
    try {
      const response = await fetch(
        `${API_URL}/rates/history?currency_pair=USDT_IRR&days=7`,
      );
      const data = await response.json();

      const formattedData = data.data.map((item: any) => ({
        date: new Date(item.timestamp).toLocaleDateString("fa-IR", {
          month: "short",
          day: "numeric",
        }),
        rate: item.rate / 10,
      }));

      setChartData(formattedData);
    } catch (error) {
      console.error("Error fetching chart data:", error);
    }
  };

  const fetchTransactions = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await fetch(`${API_URL}/user/transactions`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      const data = await response.json();
      setTransactions(data.transactions || []);
    } catch (error) {
      console.error("Error fetching transactions:", error);
    }
  };

  const calculateConversion = async () => {
    if (!calcAmount) return;

    try {
      const response = await fetch(
        `${API_URL}/converter?from_currency=${calcFrom}&to_currency=${calcTo}&amount=${calcAmount}`,
      );
      const data = await response.json();
      setCalcResult(data);
    } catch (error) {
      console.error("Error calculating:", error);
    }
  };

  const sendChatMessage = async () => {
    if (!chatInput.trim()) return;

    const userMessage = { type: "user" as const, text: chatInput };
    const nextMessages = [...chatMessages, userMessage];
    setChatMessages(nextMessages);

    try {
      const response = await fetch(`${API_URL}/chatbot/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: chatInput, user_id: user?.id }),
      });
      const data = await response.json();

      const botMessage = { type: "bot" as const, text: data.answer };
      setChatMessages([...nextMessages, botMessage]);
    } catch (error) {
      console.error("Chat error:", error);
    }

    setChatInput("");
  };

  const RateCard = ({
    title,
    value,
    change,
    icon: Icon,
    color,
  }: {
    title: string;
    value: number;
    change: number;
    icon: React.ComponentType<{ className?: string }>;
    color: string;
  }) => (
    <div className={`bg-gradient-to-br ${color} rounded-2xl p-6 shadow-lg`}>
      <div className="flex items-center justify-between mb-2">
        <Icon className="w-8 h-8 text-white opacity-80" />
        {change >= 0 ? (
          <TrendingUp className="w-5 h-5 text-green-300" />
        ) : (
          <TrendingDown className="w-5 h-5 text-red-300" />
        )}
      </div>
      <h3 className="text-white text-sm font-medium opacity-90">{title}</h3>
      <p className="text-white text-2xl font-bold mt-1">
        {value ? value.toLocaleString("fa-IR") : "..."}
      </p>
      <p
        className={`text-sm mt-1 ${
          change >= 0 ? "text-green-200" : "text-red-200"
        }`}
      >
        {change >= 0 ? "+" : ""}
        {change}%
      </p>
    </div>
  );

  const DashboardTab = () => (
    <div className="p-4 space-y-6">
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-2xl p-6 text-white">
        <h1 className="text-2xl font-bold">سلام {user?.first_name}! 👋</h1>
        <p className="opacity-90 mt-1">به صرافی کیانی خوش آمدید</p>
        <div className="mt-4 flex items-center gap-2">
          <span
            className={`px-3 py-1 rounded-full text-sm ${
              user?.kyc_status === "Approved" ? "bg-green-500" : "bg-yellow-500"
            }`}
          >
            {user?.kyc_status === "Approved"
              ? "✓ تایید شده"
              : "⏳ در انتظار تایید"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <RateCard
          title="تتر به ریال"
          value={rates.USDT_IRR / 10}
          change={2.3}
          icon={DollarSign}
          color="from-emerald-500 to-teal-600"
        />
        <RateCard
          title="تتر به لیر"
          value={rates.USDT_TRY}
          change={-1.2}
          icon={TrendingUp}
          color="from-blue-500 to-indigo-600"
        />
      </div>

      <div className="bg-white rounded-2xl p-6 shadow-lg">
        <h2 className="text-lg font-bold text-gray-800 mb-4">
          نمودار قیمت تتر (7 روز اخیر)
        </h2>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="colorRate" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="date" stroke="#6b7280" style={{ fontSize: "12px" }} />
            <YAxis stroke="#6b7280" style={{ fontSize: "12px" }} />
            <Tooltip
              contentStyle={{
                background: "white",
                border: "1px solid #e5e7eb",
                borderRadius: "8px",
              }}
            />
            <Area
              type="monotone"
              dataKey="rate"
              stroke="#3b82f6"
              strokeWidth={3}
              fill="url(#colorRate)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={() => setActiveTab("exchange")}
          className="bg-gradient-to-r from-green-500 to-emerald-600 text-white p-4 rounded-xl font-semibold shadow-lg hover:shadow-xl transition-all"
        >
          💰 خرید
        </button>
        <button
          onClick={() => setActiveTab("exchange")}
          className="bg-gradient-to-r from-red-500 to-pink-600 text-white p-4 rounded-xl font-semibold shadow-lg hover:shadow-xl transition-all"
        >
          💸 فروش
        </button>
      </div>
    </div>
  );

  const ExchangeTab = () => (
    <div className="p-4 space-y-6">
      <h2 className="text-2xl font-bold text-gray-800">مبادله ارز</h2>

      <div className="bg-white rounded-2xl p-6 shadow-lg space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            نوع معامله
          </label>
          <div className="grid grid-cols-2 gap-3">
            <button className="py-3 px-4 bg-green-100 text-green-700 rounded-xl font-semibold hover:bg-green-200 transition">
              خرید تتر
            </button>
            <button className="py-3 px-4 bg-red-100 text-red-700 rounded-xl font-semibold hover:bg-red-200 transition">
              فروش تتر
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            مقدار (ریال)
          </label>
          <input
            type="number"
            placeholder="1,000,000"
            className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none text-lg"
          />
        </div>

        <div className="bg-blue-50 rounded-xl p-4">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm text-gray-600">دریافتی شما:</span>
            <span className="text-xl font-bold text-blue-600">~32.45 USDT</span>
          </div>
          <div className="flex justify-between items-center text-sm text-gray-600">
            <span>نرخ:</span>
            <span>
              1 USDT = {(rates.USDT_IRR / 10).toLocaleString("fa-IR")} تومان
            </span>
          </div>
          <div className="flex justify-between items-center text-sm text-gray-600 mt-1">
            <span>کارمزد (2%):</span>
            <span>20,000 تومان</span>
          </div>
        </div>

        <button className="w-full bg-gradient-to-r from-blue-600 to-purple-600 text-white py-4 rounded-xl font-bold text-lg shadow-lg hover:shadow-xl transition-all">
          ادامه خرید
        </button>
      </div>
    </div>
  );

  const CalculatorTab = () => (
    <div className="p-4 space-y-6">
      <h2 className="text-2xl font-bold text-gray-800">ماشین حساب ارز</h2>

      <div className="bg-white rounded-2xl p-6 shadow-lg space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            از ارز
          </label>
          <select
            value={calcFrom}
            onChange={(e) => setCalcFrom(e.target.value)}
            className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none"
          >
            <option value="IRR">ریال ایران (IRR)</option>
            <option value="TRY">لیر ترکیه (TRY)</option>
            <option value="USDT">تتر (USDT)</option>
          </select>
        </div>

        <div className="flex justify-center">
          <button
            onClick={() => {
              const temp = calcFrom;
              setCalcFrom(calcTo);
              setCalcTo(temp);
            }}
            className="p-3 bg-blue-100 rounded-full hover:bg-blue-200 transition"
          >
            <ArrowRightLeft className="w-6 h-6 text-blue-600" />
          </button>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            به ارز
          </label>
          <select
            value={calcTo}
            onChange={(e) => setCalcTo(e.target.value)}
            className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none"
          >
            <option value="IRR">ریال ایران (IRR)</option>
            <option value="TRY">لیر ترکیه (TRY)</option>
            <option value="USDT">تتر (USDT)</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            مقدار
          </label>
          <input
            type="number"
            value={calcAmount}
            onChange={(e) => setCalcAmount(e.target.value)}
            placeholder="مقدار را وارد کنید"
            className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none text-lg"
          />
        </div>

        <button
          onClick={calculateConversion}
          className="w-full bg-gradient-to-r from-purple-600 to-pink-600 text-white py-4 rounded-xl font-bold shadow-lg hover:shadow-xl transition-all"
        >
          <Calculator className="inline w-5 h-5 mr-2" />
          محاسبه
        </button>

        {calcResult && (
          <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-xl p-6 border-2 border-green-200">
            <div className="text-center">
              <p className="text-sm text-gray-600 mb-2">نتیجه تبدیل:</p>
              <p className="text-3xl font-bold text-green-600">
                {calcResult.converted_amount.toLocaleString("fa-IR")} {calcTo}
              </p>
              <p className="text-sm text-gray-500 mt-2">
                نرخ: 1 {calcFrom} = {calcResult.rate.toFixed(2)} {calcTo}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );

  const HistoryTab = () => (
    <div className="p-4 space-y-4">
      <h2 className="text-2xl font-bold text-gray-800">تاریخچه تراکنش‌ها</h2>

      {transactions.length === 0 ? (
        <div className="bg-white rounded-2xl p-8 text-center shadow-lg">
          <History className="w-16 h-16 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">هنوز تراکنشی ثبت نشده است</p>
        </div>
      ) : (
        <div className="space-y-3">
          {transactions.map((tx) => (
            <div key={tx.id} className="bg-white rounded-xl p-4 shadow-md">
              <div className="flex justify-between items-start mb-2">
                <div>
                  <p className="font-semibold text-gray-800">
                    {tx.from_currency} → {tx.to_currency}
                  </p>
                  <p className="text-sm text-gray-500">{tx.reference_code}</p>
                </div>
                <span
                  className={`px-3 py-1 rounded-full text-sm font-medium ${
                    tx.status === "completed"
                      ? "bg-green-100 text-green-700"
                      : tx.status === "pending"
                        ? "bg-yellow-100 text-yellow-700"
                        : "bg-red-100 text-red-700"
                  }`}
                >
                  {tx.status === "completed"
                    ? "تکمیل"
                    : tx.status === "pending"
                      ? "در انتظار"
                      : "لغو شده"}
                </span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span className="text-gray-600">مقدار:</span>
                <span className="font-semibold">
                  {tx.amount.toLocaleString("fa-IR")}
                </span>
              </div>
              <div className="flex justify-between items-center text-sm mt-1">
                <span className="text-gray-600">نرخ:</span>
                <span className="font-semibold">
                  {tx.rate.toLocaleString("fa-IR")}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-purple-50 flex items-center justify-center">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-gray-600">در حال بارگذاری...</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen bg-gradient-to-br from-blue-50 to-purple-50 pb-20"
      dir="rtl"
    >
      <div className="pb-6">
        {activeTab === "dashboard" && <DashboardTab />}
        {activeTab === "exchange" && <ExchangeTab />}
        {activeTab === "calculator" && <CalculatorTab />}
        {activeTab === "history" && <HistoryTab />}
      </div>

      <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-lg">
        <div className="flex justify-around py-3">
          <button
            onClick={() => setActiveTab("dashboard")}
            className={`flex flex-col items-center gap-1 px-4 py-2 ${
              activeTab === "dashboard" ? "text-blue-600" : "text-gray-400"
            }`}
          >
            <TrendingUp className="w-6 h-6" />
            <span className="text-xs font-medium">داشبورد</span>
          </button>

          <button
            onClick={() => setActiveTab("exchange")}
            className={`flex flex-col items-center gap-1 px-4 py-2 ${
              activeTab === "exchange" ? "text-blue-600" : "text-gray-400"
            }`}
          >
            <ArrowRightLeft className="w-6 h-6" />
            <span className="text-xs font-medium">مبادله</span>
          </button>

          <button
            onClick={() => setActiveTab("calculator")}
            className={`flex flex-col items-center gap-1 px-4 py-2 ${
              activeTab === "calculator" ? "text-blue-600" : "text-gray-400"
            }`}
          >
            <Calculator className="w-6 h-6" />
            <span className="text-xs font-medium">ماشین حساب</span>
          </button>

          <button
            onClick={() => setActiveTab("history")}
            className={`flex flex-col items-center gap-1 px-4 py-2 ${
              activeTab === "history" ? "text-blue-600" : "text-gray-400"
            }`}
          >
            <History className="w-6 h-6" />
            <span className="text-xs font-medium">تاریخچه</span>
          </button>
        </div>
      </div>

      <button
        onClick={() => setChatOpen(!chatOpen)}
        className="fixed bottom-24 left-4 bg-gradient-to-r from-purple-600 to-pink-600 text-white p-4 rounded-full shadow-lg hover:shadow-xl transition-all z-50"
      >
        <MessageCircle className="w-6 h-6" />
      </button>

      {chatOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end">
          <div className="bg-white w-full h-3/4 rounded-t-3xl p-4 flex flex-col">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-bold text-gray-800">
                چت با دستیار هوشمند
              </h3>
              <button
                onClick={() => setChatOpen(false)}
                className="text-gray-500 text-2xl"
              >
                ×
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 mb-4">
              {chatMessages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex ${
                    msg.type === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  <div
                    className={`max-w-[80%] px-4 py-2 rounded-2xl ${
                      msg.type === "user"
                        ? "bg-blue-600 text-white"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    {msg.text}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendChatMessage()}
                placeholder="پیام خود را بنویسید..."
                className="flex-1 px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none"
              />
              <button
                onClick={sendChatMessage}
                className="px-6 py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition"
              >
                ارسال
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
