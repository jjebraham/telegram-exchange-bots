import React, { useState, useEffect } from "react";
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  Users,
  CheckCircle,
  Clock,
  DollarSign,
  TrendingUp,
  MessageSquare,
  Settings,
  LogOut,
  Send,
  Plus,
  Edit,
  Trash2,
  Eye,
} from "lucide-react";

const API_URL = "https://kiani.peerexo.com/api";

export default function AdminPanel() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [activeSection, setActiveSection] = useState("dashboard");
  const [stats, setStats] = useState<any>({});
  const [users, setUsers] = useState<any[]>([]);
  const [faqs, setFaqs] = useState<any[]>([]);
  const [selectedUser, setSelectedUser] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [broadcastMessage, setBroadcastMessage] = useState("");
  const [broadcastTarget, setBroadcastTarget] = useState("all");

  const [faqForm, setFaqForm] = useState({
    question_fa: "",
    answer_fa: "",
    question_en: "",
    answer_en: "",
    category: "general",
    order: 0,
  });
  const [editingFaq, setEditingFaq] = useState<number | null>(null);

  const login = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const response = await fetch(`${API_URL}/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();
      if (data.token) {
        localStorage.setItem("admin_token", data.token);
        setIsLoggedIn(true);
        loadDashboard();
      }
    } catch (error) {
      alert("خطا در ورود");
    }
  };

  const loadDashboard = async () => {
    const token = localStorage.getItem("admin_token");
    try {
      const response = await fetch(`${API_URL}/admin/dashboard`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      setStats(data.stats);
    } catch (error) {
      console.error("Error loading dashboard:", error);
    }
  };

  const loadUsers = async (kycStatus: string | null = null) => {
    const token = localStorage.getItem("admin_token");
    try {
      const url = kycStatus
        ? `${API_URL}/admin/users?kyc_status=${kycStatus}`
        : `${API_URL}/admin/users`;

      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      setUsers(data.users);
    } catch (error) {
      console.error("Error loading users:", error);
    }
  };

  const loadFAQs = async () => {
    try {
      const response = await fetch(`${API_URL}/faqs`);
      const data = await response.json();
      setFaqs(data.faqs);
    } catch (error) {
      console.error("Error loading FAQs:", error);
    }
  };

  const loadLogs = async () => {
    const token = localStorage.getItem("admin_token");
    try {
      const response = await fetch(`${API_URL}/admin/logs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      setLogs(data.logs);
    } catch (error) {
      console.error("Error loading logs:", error);
    }
  };

  const approveKYC = async (userId: number) => {
    const token = localStorage.getItem("admin_token");
    try {
      await fetch(`${API_URL}/admin/kyc/${userId}/approve`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      alert("KYC تایید شد");
      loadUsers("Pending");
    } catch (error) {
      alert("خطا در تایید");
    }
  };

  const rejectKYC = async (userId: number) => {
    const reason = prompt("دلیل رد:");
    if (!reason) return;

    const token = localStorage.getItem("admin_token");
    try {
      await fetch(`${API_URL}/admin/kyc/${userId}/reject`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ reason }),
      });
      alert("KYC رد شد");
      loadUsers("Pending");
    } catch (error) {
      alert("خطا در رد");
    }
  };

  const saveFAQ = async () => {
    const token = localStorage.getItem("admin_token");
    try {
      const url = editingFaq
        ? `${API_URL}/admin/faq/${editingFaq}`
        : `${API_URL}/admin/faq`;

      const method = editingFaq ? "PUT" : "POST";

      await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(faqForm),
      });

      alert("FAQ ذخیره شد");
      setFaqForm({
        question_fa: "",
        answer_fa: "",
        question_en: "",
        answer_en: "",
        category: "general",
        order: 0,
      });
      setEditingFaq(null);
      loadFAQs();
    } catch (error) {
      alert("خطا در ذخیره");
    }
  };

  const deleteFAQ = async (faqId: number) => {
    if (!confirm("آیا مطمئن هستید؟")) return;

    const token = localStorage.getItem("admin_token");
    try {
      await fetch(`${API_URL}/admin/faq/${faqId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      alert("FAQ حذف شد");
      loadFAQs();
    } catch (error) {
      alert("خطا در حذف");
    }
  };

  const sendBroadcast = async () => {
    if (!broadcastMessage) {
      alert("پیام را وارد کنید");
      return;
    }

    const token = localStorage.getItem("admin_token");
    try {
      await fetch(`${API_URL}/admin/broadcast`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: broadcastMessage,
          target_group: broadcastTarget,
        }),
      });
      alert("پیام ارسال شد");
      setBroadcastMessage("");
    } catch (error) {
      alert("خطا در ارسال");
    }
  };

  useEffect(() => {
    const token = localStorage.getItem("admin_token");
    if (token) {
      setIsLoggedIn(true);
      loadDashboard();
    }
  }, []);

  if (!isLoggedIn) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-blue-900 to-purple-900 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-md">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-gray-800 mb-2">
              پنل مدیریت
            </h1>
            <p className="text-gray-600">صرافی کیانی</p>
          </div>

          <form onSubmit={login} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                نام کاربری
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                رمز عبور
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none"
                required
              />
            </div>

            <button
              type="submit"
              className="w-full bg-gradient-to-r from-blue-600 to-purple-600 text-white py-3 rounded-xl font-bold shadow-lg hover:shadow-xl transition-all"
            >
              ورود
            </button>
          </form>
        </div>
      </div>
    );
  }

  const StatCard = ({
    title,
    value,
    icon: Icon,
    color,
    subtitle,
  }: {
    title: string;
    value: number;
    icon: React.ComponentType<{ className?: string }>;
    color: string;
    subtitle?: string;
  }) => (
    <div className={`bg-gradient-to-br ${color} rounded-xl p-6 shadow-lg text-white`}>
      <div className="flex items-center justify-between mb-3">
        <Icon className="w-10 h-10 opacity-80" />
        <span className="text-3xl font-bold">{value}</span>
      </div>
      <h3 className="text-lg font-semibold opacity-90">{title}</h3>
      {subtitle && <p className="text-sm opacity-75 mt-1">{subtitle}</p>}
    </div>
  );

  const DashboardSection = () => (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="کل کاربران"
          value={stats.total_users || 0}
          icon={Users}
          color="from-blue-500 to-blue-600"
        />
        <StatCard
          title="در انتظار تایید"
          value={stats.pending_kyc || 0}
          icon={Clock}
          color="from-yellow-500 to-orange-600"
        />
        <StatCard
          title="تایید شده"
          value={stats.approved_kyc || 0}
          icon={CheckCircle}
          color="from-green-500 to-emerald-600"
        />
        <StatCard
          title="تراکنش‌های امروز"
          value={stats.today_transactions || 0}
          icon={DollarSign}
          color="from-purple-500 to-pink-600"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl p-6 shadow-lg">
          <h3 className="text-xl font-bold text-gray-800 mb-4">
            نمودار کاربران
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={[
                { name: "شنبه", users: 12 },
                { name: "یکشنبه", users: 19 },
                { name: "دوشنبه", users: 15 },
                { name: "سه‌شنبه", users: 25 },
                { name: "چهارشنبه", users: 22 },
                { name: "پنج‌شنبه", users: 30 },
                { name: "جمعه", users: 28 },
              ]}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="users" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl p-6 shadow-lg">
          <h3 className="text-xl font-bold text-gray-800 mb-4">
            توزیع وضعیت KYC
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={[
                  { name: "تایید شده", value: stats.approved_kyc || 0 },
                  { name: "در انتظار", value: stats.pending_kyc || 0 },
                  { name: "رد شده", value: 5 },
                ]}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) =>
                  `${name}: ${(percent * 100).toFixed(0)}%`
                }
                outerRadius={100}
                fill="#8884d8"
                dataKey="value"
              >
                <Cell fill="#10b981" />
                <Cell fill="#f59e0b" />
                <Cell fill="#ef4444" />
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );

  const KYCSection = () => {
    useEffect(() => {
      loadUsers("Pending");
    }, []);

    return (
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="text-2xl font-bold text-gray-800">مدیریت KYC</h2>
          <div className="flex gap-2">
            <button
              onClick={() => loadUsers("Pending")}
              className="px-4 py-2 bg-yellow-100 text-yellow-700 rounded-lg font-semibold hover:bg-yellow-200 transition"
            >
              در انتظار
            </button>
            <button
              onClick={() => loadUsers("Approved")}
              className="px-4 py-2 bg-green-100 text-green-700 rounded-lg font-semibold hover:bg-green-200 transition"
            >
              تایید شده
            </button>
            <button
              onClick={() => loadUsers("Rejected")}
              className="px-4 py-2 bg-red-100 text-red-700 rounded-lg font-semibold hover:bg-red-200 transition"
            >
              رد شده
            </button>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  نام
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  شماره تلفن
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  وضعیت
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  تاریخ ثبت
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  عملیات
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-medium text-gray-900">
                      {user.first_name} {user.last_name}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {user.phone_number}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${
                        user.kyc_status === "Approved"
                          ? "bg-green-100 text-green-800"
                          : user.kyc_status === "Pending"
                            ? "bg-yellow-100 text-yellow-800"
                            : "bg-red-100 text-red-800"
                      }`}
                    >
                      {user.kyc_status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {new Date(user.created_at).toLocaleDateString("fa-IR")}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <button
                      onClick={() => setSelectedUser(user)}
                      className="text-blue-600 hover:text-blue-900 mr-3"
                    >
                      <Eye className="w-5 h-5 inline" />
                    </button>
                    {user.kyc_status === "Pending" && (
                      <>
                        <button
                          onClick={() => approveKYC(user.id)}
                          className="text-green-600 hover:text-green-900 mr-3"
                        >
                          ✓
                        </button>
                        <button
                          onClick={() => rejectKYC(user.id)}
                          className="text-red-600 hover:text-red-900"
                        >
                          ✗
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const FAQSection = () => {
    useEffect(() => {
      loadFAQs();
    }, []);

    return (
      <div className="space-y-6">
        <h2 className="text-2xl font-bold text-gray-800">
          مدیریت سوالات متداول
        </h2>

        <div className="bg-white rounded-xl p-6 shadow-lg">
          <h3 className="text-lg font-semibold mb-4">
            {editingFaq ? "ویرایش FAQ" : "افزودن FAQ جدید"}
          </h3>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  سوال (فارسی)
                </label>
                <input
                  type="text"
                  value={faqForm.question_fa}
                  onChange={(e) =>
                    setFaqForm({ ...faqForm, question_fa: e.target.value })
                  }
                  className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  سوال (انگلیسی)
                </label>
                <input
                  type="text"
                  value={faqForm.question_en}
                  onChange={(e) =>
                    setFaqForm({ ...faqForm, question_en: e.target.value })
                  }
                  className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                پاسخ (فارسی)
              </label>
              <textarea
                value={faqForm.answer_fa}
                onChange={(e) =>
                  setFaqForm({ ...faqForm, answer_fa: e.target.value })
                }
                rows={4}
                className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                پاسخ (انگلیسی)
              </label>
              <textarea
                value={faqForm.answer_en}
                onChange={(e) =>
                  setFaqForm({ ...faqForm, answer_en: e.target.value })
                }
                rows={4}
                className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  دسته‌بندی
                </label>
                <select
                  value={faqForm.category}
                  onChange={(e) =>
                    setFaqForm({ ...faqForm, category: e.target.value })
                  }
                  className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
                >
                  <option value="general">عمومی</option>
                  <option value="registration">ثبت‌نام</option>
                  <option value="kyc">احراز هویت</option>
                  <option value="transactions">تراکنش‌ها</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  ترتیب نمایش
                </label>
                <input
                  type="number"
                  value={faqForm.order}
                  onChange={(e) =>
                    setFaqForm({
                      ...faqForm,
                      order: Number.parseInt(e.target.value, 10),
                    })
                  }
                  className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={saveFAQ}
                className="flex-1 bg-blue-600 text-white py-2 rounded-lg font-semibold hover:bg-blue-700 transition"
              >
                <Plus className="inline w-5 h-5 mr-2" />
                {editingFaq ? "به‌روزرسانی" : "افزودن"}
              </button>
              {editingFaq && (
                <button
                  onClick={() => {
                    setEditingFaq(null);
                    setFaqForm({
                      question_fa: "",
                      answer_fa: "",
                      question_en: "",
                      answer_en: "",
                      category: "general",
                      order: 0,
                    });
                  }}
                  className="px-6 py-2 bg-gray-200 text-gray-700 rounded-lg font-semibold hover:bg-gray-300 transition"
                >
                  لغو
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    سوال
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    دسته
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    ترتیب
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    عملیات
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {faqs.map((faq) => (
                  <tr key={faq.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-900">
                        {faq.question}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="px-2 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded-full">
                        {faq.category}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {faq.order || 0}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                      <button
                        onClick={() => {
                          setEditingFaq(faq.id);
                          setFaqForm({
                            question_fa: faq.question,
                            answer_fa: faq.answer,
                            question_en: "",
                            answer_en: "",
                            category: faq.category,
                            order: faq.order || 0,
                          });
                        }}
                        className="text-blue-600 hover:text-blue-900 mr-3"
                      >
                        <Edit className="w-5 h-5 inline" />
                      </button>
                      <button
                        onClick={() => deleteFAQ(faq.id)}
                        className="text-red-600 hover:text-red-900"
                      >
                        <Trash2 className="w-5 h-5 inline" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  const BroadcastSection = () => (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-800">
        ارسال پیام گروهی
      </h2>

      <div className="bg-white rounded-xl p-6 shadow-lg">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              گروه هدف
            </label>
            <select
              value={broadcastTarget}
              onChange={(e) => setBroadcastTarget(e.target.value)}
              className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
            >
              <option value="all">همه کاربران</option>
              <option value="verified">کاربران تایید شده</option>
              <option value="pending">کاربران در انتظار</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              پیام
            </label>
            <textarea
              value={broadcastMessage}
              onChange={(e) => setBroadcastMessage(e.target.value)}
              rows={6}
              placeholder="پیام خود را وارد کنید..."
              className="w-full px-4 py-2 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
            />
          </div>

          <button
            onClick={sendBroadcast}
            className="w-full bg-gradient-to-r from-purple-600 to-pink-600 text-white py-3 rounded-lg font-bold shadow-lg hover:shadow-xl transition-all"
          >
            <Send className="inline w-5 h-5 mr-2" />
            ارسال پیام
          </button>
        </div>
      </div>
    </div>
  );

  const LogsSection = () => {
    useEffect(() => {
      loadLogs();
    }, []);

    return (
      <div className="space-y-4">
        <h2 className="text-2xl font-bold text-gray-800">لاگ سیستم</h2>

        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    نوع عملیات
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    جزئیات
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    تاریخ
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`px-2 py-1 text-xs font-medium rounded-full ${
                          log.action_type.includes("approve")
                            ? "bg-green-100 text-green-800"
                            : log.action_type.includes("reject")
                              ? "bg-red-100 text-red-800"
                              : "bg-blue-100 text-blue-800"
                        }`}
                      >
                        {log.action_type}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900">
                      {log.details}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(log.created_at).toLocaleString("fa-IR")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gray-100" dir="rtl">
      <nav className="bg-white shadow-lg">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <h1 className="text-2xl font-bold text-gray-800">
                پنل مدیریت صرافی کیانی
              </h1>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-gray-600">مدیر: {username}</span>
              <button
                onClick={() => {
                  localStorage.removeItem("admin_token");
                  setIsLoggedIn(false);
                }}
                className="flex items-center gap-2 px-4 py-2 bg-red-100 text-red-600 rounded-lg hover:bg-red-200 transition"
              >
                <LogOut className="w-5 h-5" />
                خروج
              </button>
            </div>
          </div>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex gap-6">
          <div className="w-64 bg-white rounded-xl shadow-lg p-4 h-fit sticky top-8">
            <nav className="space-y-2">
              <button
                onClick={() => setActiveSection("dashboard")}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg font-semibold transition ${
                  activeSection === "dashboard"
                    ? "bg-blue-100 text-blue-600"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                <TrendingUp className="w-5 h-5" />
                داشبورد
              </button>

              <button
                onClick={() => setActiveSection("kyc")}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg font-semibold transition ${
                  activeSection === "kyc"
                    ? "bg-blue-100 text-blue-600"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                <CheckCircle className="w-5 h-5" />
                مدیریت KYC
              </button>

              <button
                onClick={() => setActiveSection("faq")}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg font-semibold transition ${
                  activeSection === "faq"
                    ? "bg-blue-100 text-blue-600"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                <MessageSquare className="w-5 h-5" />
                مدیریت FAQ
              </button>

              <button
                onClick={() => setActiveSection("broadcast")}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg font-semibold transition ${
                  activeSection === "broadcast"
                    ? "bg-blue-100 text-blue-600"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                <Send className="w-5 h-5" />
                پیام گروهی
              </button>

              <button
                onClick={() => setActiveSection("logs")}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg font-semibold transition ${
                  activeSection === "logs"
                    ? "bg-blue-100 text-blue-600"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                <Settings className="w-5 h-5" />
                لاگ سیستم
              </button>
            </nav>
          </div>

          <div className="flex-1">
            {activeSection === "dashboard" && <DashboardSection />}
            {activeSection === "kyc" && <KYCSection />}
            {activeSection === "faq" && <FAQSection />}
            {activeSection === "broadcast" && <BroadcastSection />}
            {activeSection === "logs" && <LogsSection />}
          </div>
        </div>
      </div>

      {selectedUser && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl p-8 max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-2xl font-bold text-gray-800">
                جزئیات کاربر
              </h3>
              <button
                onClick={() => setSelectedUser(null)}
                className="text-gray-500 hover:text-gray-700 text-3xl"
              >
                ×
              </button>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium text-gray-500">
                    نام
                  </label>
                  <p className="text-lg text-gray-800">
                    {selectedUser.first_name}
                  </p>
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-500">
                    نام خانوادگی
                  </label>
                  <p className="text-lg text-gray-800">
                    {selectedUser.last_name}
                  </p>
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-500">
                    شماره تلفن
                  </label>
                  <p className="text-lg text-gray-800">
                    {selectedUser.phone_number}
                  </p>
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-500">
                    وضعیت KYC
                  </label>
                  <p className="text-lg text-gray-800">
                    {selectedUser.kyc_status}
                  </p>
                </div>
              </div>

              <div className="pt-4 border-t">
                <h4 className="font-semibold text-gray-800 mb-3">
                  مدارک احراز هویت
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-gray-500 mb-2">روی کارت ملی</p>
                    <div className="bg-gray-100 rounded-lg h-48 flex items-center justify-center">
                      <span className="text-gray-400">تصویر موجود نیست</span>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 mb-2">پشت کارت ملی</p>
                    <div className="bg-gray-100 rounded-lg h-48 flex items-center justify-center">
                      <span className="text-gray-400">تصویر موجود نیست</span>
                    </div>
                  </div>
                </div>
              </div>

              {selectedUser.kyc_status === "Pending" && (
                <div className="flex gap-3 pt-4">
                  <button
                    onClick={() => {
                      approveKYC(selectedUser.id);
                      setSelectedUser(null);
                    }}
                    className="flex-1 bg-green-600 text-white py-3 rounded-lg font-semibold hover:bg-green-700 transition"
                  >
                    تایید
                  </button>
                  <button
                    onClick={() => {
                      rejectKYC(selectedUser.id);
                      setSelectedUser(null);
                    }}
                    className="flex-1 bg-red-600 text-white py-3 rounded-lg font-semibold hover:bg-red-700 transition"
                  >
                    رد
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
