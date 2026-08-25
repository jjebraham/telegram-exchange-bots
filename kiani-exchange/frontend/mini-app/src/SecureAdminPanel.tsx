import React, { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  CheckCircle,
  LogOut,
  MessageSquare,
  RefreshCw,
  Shield,
  TrendingUp,
  Users,
  XCircle,
} from 'lucide-react'

import {
  adminJson,
  adminLogin,
  clearAdminSession,
  getAdminRole,
  getAdminToken,
  getAdminUsername,
} from './adminApi'

type User = {
  id: number
  first_name: string
  last_name: string
  phone_number: string
  national_id: string
  dob?: string | null
  bank_card_number: string
  kyc_status: string
  verification_level: number
}

type Transaction = {
  id: number
  user_name: string
  user_phone: string
  exchange_pair: string
  exchange_type?: string
  send_amount: number
  receive_amount: number
  reference_number: string
  status: string
  timestamp: string
  receipt_photo_url?: string | null
  receipt_description?: string | null
  payment_link?: string | null
}

type Report = {
  total_orders?: number
  done_orders?: number
  canceled_orders?: number
  total_send_amount?: number
}

type Faq = { id: number; question: string; answer: string; created_at?: string }
type AdminLog = { id: number; action: string; details?: string; created_at?: string }
type KycLogState = {
  ehraz_logs: any[]
  sms_logs: any[]
  kyc_verification_logs: any[]
}

const EMPTY_KYC_LOGS: KycLogState = {
  ehraz_logs: [],
  sms_logs: [],
  kyc_verification_logs: [],
}

const RATE_DEFAULTS: Record<string, number> = {
  toman_to_tl_manual_rate: 0,
  toman_to_tl_percentage: -0.5,
  tl_to_toman_manual_rate: 0,
  tl_to_toman_percentage: -6,
  tl_to_usdt_manual_rate: 0,
  tl_to_usdt_percentage: 2,
  usdt_to_tl_manual_rate: 0,
  usdt_to_tl_percentage: -2,
  toman_to_usdt_manual_rate: 0,
  toman_to_usdt_percentage: 1,
  usdt_to_toman_manual_rate: 0,
  usdt_to_toman_percentage: -1,
}

const formatNumber = (value: unknown) => {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString('fa-IR') : '-'
}

const roleCanWrite = (role: string) => role === 'admin' || role === 'support'

export default function SecureAdminPanel() {
  const [authenticated, setAuthenticated] = useState(Boolean(getAdminToken()))
  const [role, setRole] = useState(getAdminRole())
  const [adminUser, setAdminUser] = useState(getAdminUsername())
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState('')
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('dashboard')
  const [search, setSearch] = useState('')

  const [users, setUsers] = useState<User[]>([])
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [report, setReport] = useState<Report>({})
  const [logs, setLogs] = useState<AdminLog[]>([])
  const [faqs, setFaqs] = useState<Faq[]>([])
  const [kycLogs, setKycLogs] = useState<KycLogState>(EMPTY_KYC_LOGS)
  const [rates, setRates] = useState<Record<string, number>>(RATE_DEFAULTS)

  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [statusRef, setStatusRef] = useState('')
  const [statusValue, setStatusValue] = useState('Under Review')
  const [receiptPhotoUrl, setReceiptPhotoUrl] = useState('')
  const [receiptDescription, setReceiptDescription] = useState('')
  const [paymentLink, setPaymentLink] = useState('')
  const [broadcastText, setBroadcastText] = useState('')
  const [broadcastUserId, setBroadcastUserId] = useState('')
  const [faqQuestion, setFaqQuestion] = useState('')
  const [faqAnswer, setFaqAnswer] = useState('')
  const [message, setMessage] = useState('')

  const logout = () => {
    clearAdminSession()
    setAuthenticated(false)
    setRole('')
    setAdminUser('')
    setPassword('')
    setUsers([])
    setTransactions([])
    setSelectedUser(null)
  }

  useEffect(() => {
    const expired = () => {
      logout()
      setLoginError('نشست ادمین منقضی شد. دوباره وارد شوید.')
    }
    window.addEventListener('kiani-admin-auth-expired', expired)
    return () => window.removeEventListener('kiani-admin-auth-expired', expired)
  }, [])

  const loadAll = async () => {
    if (!getAdminToken()) return
    setLoading(true)
    setMessage('')
    try {
      const tasks: Promise<any>[] = [
        adminJson('/admin/users'),
        adminJson('/admin/transactions'),
        adminJson('/admin/reports'),
        adminJson('/admin/logs'),
        adminJson('/admin/faqs'),
        adminJson('/admin/rates'),
      ]
      if (roleCanWrite(getAdminRole())) tasks.push(adminJson('/admin/kyc-logs'))
      const data = await Promise.all(tasks)
      setUsers(data[0]?.users || [])
      setTransactions(data[1]?.transactions || [])
      setReport(data[2]?.report || {})
      setLogs(data[3]?.logs || [])
      setFaqs(data[4]?.faqs || [])
      setRates({ ...RATE_DEFAULTS, ...(data[5]?.settings || {}) })
      if (data[6]) setKycLogs(data[6])
    } catch (error) {
      console.error(error)
      if (getAdminToken()) setMessage('بخشی از اطلاعات پنل دریافت نشد. دوباره تلاش کنید.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (authenticated) void loadAll()
  }, [authenticated, role])

  const login = async () => {
    setLoading(true)
    setLoginError('')
    try {
      const data = await adminLogin(username, password)
      setRole(data.role)
      setAdminUser(data.username)
      setPassword('')
      setAuthenticated(true)
    } catch (error) {
      console.error(error)
      setLoginError('نام کاربری یا رمز عبور اشتباه است.')
    } finally {
      setLoading(false)
    }
  }

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return users
    return users.filter(user =>
      `${user.id} ${user.first_name} ${user.last_name} ${user.phone_number}`.toLowerCase().includes(q),
    )
  }, [search, users])

  const viewUser = async (userId: number) => {
    if (!roleCanWrite(role)) {
      setMessage('نقش Viewer اجازه مشاهده اطلاعات کامل هویتی را ندارد.')
      return
    }
    try {
      const data = await adminJson<{ user: User }>(`/admin/users/${userId}`)
      setSelectedUser(data.user)
    } catch (error) {
      console.error(error)
      setMessage('دریافت اطلاعات کاربر ناموفق بود.')
    }
  }

  const deleteUser = async (user: User) => {
    if (role !== 'admin') return
    if (!window.confirm(`Delete #${user.id} ${user.first_name} ${user.last_name} for re-registration?`)) return
    try {
      await adminJson(`/admin/users/${user.id}`, { method: 'DELETE' })
      setMessage('کاربر حذف شد و می‌تواند دوباره ثبت‌نام کند.')
      await loadAll()
    } catch (error) {
      console.error(error)
      setMessage('حذف کاربر انجام نشد.')
    }
  }

  const resetUserPassword = async (userId: number) => {
    if (!newPassword) {
      setMessage('رمز جدید را در کادر پایین جدول وارد کنید.')
      return
    }
    try {
      await adminJson(`/admin/users/${userId}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: newPassword }),
      })
      setNewPassword('')
      setMessage('رمز کاربر تغییر کرد.')
    } catch (error) {
      console.error(error)
      setMessage('تغییر رمز انجام نشد. رمز باید حداقل ۸ کاراکتر و شامل حروف و عدد باشد.')
    }
  }

  const updateTransaction = async () => {
    if (!statusRef.trim()) return
    try {
      await adminJson(`/admin/transactions/${encodeURIComponent(statusRef.trim())}/update-status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: statusValue,
          receipt_photo_url: receiptPhotoUrl || null,
          receipt_description: receiptDescription || null,
          payment_link: paymentLink || null,
        }),
      })
      setMessage('وضعیت تراکنش بروزرسانی شد.')
      await loadAll()
    } catch (error) {
      console.error(error)
      setMessage('بروزرسانی تراکنش انجام نشد.')
    }
  }

  const saveRates = async () => {
    try {
      const data = await adminJson<{ settings: Record<string, number> }>('/admin/rates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rates),
      })
      setRates({ ...RATE_DEFAULTS, ...(data.settings || {}) })
      setMessage('تنظیمات نرخ ذخیره شد.')
    } catch (error) {
      console.error(error)
      setMessage('ذخیره نرخ ناموفق بود. فقط نقش Admin اجازه تغییر نرخ دارد.')
    }
  }

  const sendBroadcast = async () => {
    try {
      const data = await adminJson<{ sent: number; requested: number }>('/admin/messages/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: broadcastText,
          user_id: broadcastUserId ? Number(broadcastUserId) : null,
        }),
      })
      setMessage(`پیام برای ${data.sent} از ${data.requested} کاربر ارسال شد.`)
      setBroadcastText('')
    } catch (error) {
      console.error(error)
      setMessage('ارسال پیام انجام نشد.')
    }
  }

  const addFaq = async () => {
    try {
      await adminJson('/admin/faqs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: faqQuestion, answer: faqAnswer }),
      })
      setFaqQuestion('')
      setFaqAnswer('')
      await loadAll()
    } catch (error) {
      console.error(error)
      setMessage('افزودن FAQ انجام نشد.')
    }
  }

  const deleteFaq = async (faqId: number) => {
    try {
      await adminJson(`/admin/faqs/${faqId}`, { method: 'DELETE' })
      await loadAll()
    } catch (error) {
      console.error(error)
      setMessage('حذف FAQ انجام نشد.')
    }
  }

  if (!authenticated) {
    return (
      <div className="min-h-screen bg-gray-100 p-6" dir="rtl">
        <div className="mx-auto mt-16 max-w-md rounded-2xl bg-white p-6 shadow-xl">
          <h1 className="mb-2 text-2xl font-bold text-gray-900">Kiani Admin</h1>
          <p className="mb-5 text-sm text-gray-500">ورود امن ادمین — رمز عبور در URL ذخیره یا ارسال نمی‌شود.</p>
          <div className="space-y-3">
            <input
              className="w-full rounded-lg border p-3"
              value={username}
              onChange={event => setUsername(event.target.value)}
              placeholder="نام کاربری"
              autoComplete="username"
            />
            <input
              className="w-full rounded-lg border p-3"
              value={password}
              onChange={event => setPassword(event.target.value)}
              onKeyDown={event => { if (event.key === 'Enter') void login() }}
              placeholder="رمز عبور"
              type="password"
              autoComplete="current-password"
            />
            {loginError && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{loginError}</div>}
            <button
              className="w-full rounded-lg bg-blue-600 py-3 font-bold text-white disabled:opacity-50"
              onClick={() => void login()}
              disabled={loading || !username || !password}
            >
              {loading ? 'در حال ورود...' : 'ورود'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const tabs = [
    ['dashboard', 'Dashboard', BarChart3],
    ['users', 'Users', Users],
    ['transactions', 'Transactions', ArrowLeftRight],
    ['rates', 'Rates', TrendingUp],
    ['kyc', 'KYC Logs', Shield],
    ['messages', 'Messages / FAQ', MessageSquare],
    ['logs', 'Audit Logs', Activity],
  ] as const

  return (
    <div className="min-h-screen bg-gray-950 text-white" dir="rtl">
      <header className="sticky top-0 z-40 border-b border-gray-800 bg-gray-950/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-bold">Kiani Admin</h1>
            <div className="text-xs text-gray-400">{adminUser} · {role}</div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => void loadAll()} className="rounded-lg bg-gray-800 px-3 py-2 text-sm">
              <RefreshCw className={`inline h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> بروزرسانی
            </button>
            <button onClick={logout} className="rounded-lg bg-red-950 px-3 py-2 text-sm text-red-300">
              <LogOut className="inline h-4 w-4" /> خروج
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl p-4">
        <nav className="mb-5 flex flex-wrap gap-2">
          {tabs.map(([id, label, Icon]) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`rounded-lg px-3 py-2 text-sm ${activeTab === id ? 'bg-blue-600' : 'bg-gray-800 text-gray-300'}`}
            >
              <Icon className="ml-1 inline h-4 w-4" /> {label}
            </button>
          ))}
        </nav>

        {message && (
          <div className="mb-4 flex items-center justify-between rounded-lg border border-gray-700 bg-gray-900 p-3 text-sm">
            <span>{message}</span>
            <button onClick={() => setMessage('')} className="text-gray-400">×</button>
          </div>
        )}

        {activeTab === 'dashboard' && (
          <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatCard title="Users" value={users.length} />
            <StatCard title="Orders" value={report.total_orders || 0} />
            <StatCard title="Completed" value={report.done_orders || 0} icon={<CheckCircle className="h-5 w-5 text-green-400" />} />
            <StatCard title="Pending KYC" value={users.filter(user => Number(user.verification_level || 1) < 2).length} icon={<Shield className="h-5 w-5 text-yellow-400" />} />
            <StatCard title="Canceled" value={report.canceled_orders || 0} icon={<XCircle className="h-5 w-5 text-red-400" />} />
            <StatCard title="Recorded volume" value={formatNumber(report.total_send_amount)} />
          </section>
        )}

        {activeTab === 'users' && (
          <section className="space-y-4">
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder="جستجو نام، تلفن یا ID"
              className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-3"
            />
            <div className="overflow-x-auto rounded-xl border border-gray-800">
              <table className="w-full text-sm">
                <thead className="bg-gray-900 text-gray-400">
                  <tr><th className="p-3">ID</th><th>نام</th><th>کد ملی</th><th>کارت</th><th>تلفن</th><th>سطح</th><th>عملیات</th></tr>
                </thead>
                <tbody>
                  {filteredUsers.map(user => (
                    <tr key={user.id} className="border-t border-gray-800 text-center">
                      <td className="p-3">#{user.id}</td>
                      <td>{user.first_name} {user.last_name}</td>
                      <td>{user.national_id}</td>
                      <td>{user.bank_card_number}</td>
                      <td dir="ltr">{user.phone_number}</td>
                      <td>{user.verification_level}</td>
                      <td className="space-x-1 space-x-reverse whitespace-nowrap">
                        <button onClick={() => void viewUser(user.id)} className="rounded bg-blue-900 px-2 py-1 text-blue-200">View</button>
                        {roleCanWrite(role) && <button onClick={() => void resetUserPassword(user.id)} className="rounded bg-orange-900 px-2 py-1 text-orange-200">Reset pass</button>}
                        {role === 'admin' && <button onClick={() => void deleteUser(user)} className="rounded bg-red-950 px-2 py-1 text-red-300">Delete</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {roleCanWrite(role) && (
              <input
                type="password"
                value={newPassword}
                onChange={event => setNewPassword(event.target.value)}
                placeholder="رمز جدید برای Reset pass"
                className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-3"
              />
            )}
          </section>
        )}

        {activeTab === 'transactions' && (
          <section className="space-y-4">
            {roleCanWrite(role) && (
              <div className="grid gap-2 rounded-xl border border-gray-800 bg-gray-900 p-4 md:grid-cols-3">
                <input className="rounded bg-gray-800 p-2" value={statusRef} onChange={e => setStatusRef(e.target.value)} placeholder="Reference" />
                <select className="rounded bg-gray-800 p-2" value={statusValue} onChange={e => setStatusValue(e.target.value)}>
                  {['Pending','Under Review',"Waiting for User's Payment",'Waiting for Admin to Pay','Under Process','Done','Rejected','Canceled by Admin','Canceled by User','Expired'].map(item => <option key={item}>{item}</option>)}
                </select>
                <input className="rounded bg-gray-800 p-2" value={receiptPhotoUrl} onChange={e => setReceiptPhotoUrl(e.target.value)} placeholder="Receipt URL (optional)" />
                <input className="rounded bg-gray-800 p-2" value={receiptDescription} onChange={e => setReceiptDescription(e.target.value)} placeholder="Receipt description" />
                <input className="rounded bg-gray-800 p-2" value={paymentLink} onChange={e => setPaymentLink(e.target.value)} placeholder="Payment link" />
                <button onClick={() => void updateTransaction()} className="rounded bg-green-700 p-2 font-bold">Update status</button>
              </div>
            )}
            <div className="overflow-x-auto rounded-xl border border-gray-800">
              <table className="w-full text-sm">
                <thead className="bg-gray-900 text-gray-400"><tr><th className="p-3">Ref</th><th>User</th><th>Pair</th><th>Send</th><th>Receive</th><th>Status</th></tr></thead>
                <tbody>{transactions.map(tx => <tr key={tx.reference_number} className="border-t border-gray-800 text-center"><td className="p-3 font-mono">{tx.reference_number}</td><td>{tx.user_name}</td><td>{tx.exchange_pair}</td><td>{formatNumber(tx.send_amount)}</td><td>{formatNumber(tx.receive_amount)}</td><td>{tx.status}</td></tr>)}</tbody>
              </table>
            </div>
          </section>
        )}

        {activeTab === 'rates' && (
          <section className="mx-auto max-w-4xl rounded-xl border border-gray-800 bg-gray-900 p-5">
            <div className="grid gap-3 md:grid-cols-2">
              {Object.entries(rates).map(([key, value]) => (
                <label key={key} className="text-sm text-gray-300">
                  <div className="mb-1">{key}</div>
                  <input
                    type="number"
                    step="any"
                    disabled={role !== 'admin'}
                    value={String(value)}
                    onChange={event => setRates(prev => ({ ...prev, [key]: Number(event.target.value || 0) }))}
                    className="w-full rounded bg-gray-800 p-2 disabled:opacity-60"
                  />
                </label>
              ))}
            </div>
            {role === 'admin' && <button onClick={() => void saveRates()} className="mt-4 rounded bg-blue-600 px-5 py-2 font-bold">Save rates</button>}
          </section>
        )}

        {activeTab === 'kyc' && (
          <section className="grid gap-4 lg:grid-cols-3">
            <LogBox title="Verification" items={kycLogs.kyc_verification_logs} />
            <LogBox title="EHRAZ" items={kycLogs.ehraz_logs} />
            <LogBox title="SMS" items={kycLogs.sms_logs} />
            {!roleCanWrite(role) && <div className="text-gray-400">Viewer role cannot access KYC diagnostic logs.</div>}
          </section>
        )}

        {activeTab === 'messages' && (
          <section className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <h2 className="mb-3 font-bold">Broadcast</h2>
              <input value={broadcastUserId} onChange={e => setBroadcastUserId(e.target.value.replace(/\D/g, ''))} placeholder="User ID (خالی = همه)" className="mb-2 w-full rounded bg-gray-800 p-2" />
              <textarea value={broadcastText} onChange={e => setBroadcastText(e.target.value)} placeholder="پیام" className="mb-2 min-h-28 w-full rounded bg-gray-800 p-2" />
              <button disabled={!roleCanWrite(role)} onClick={() => void sendBroadcast()} className="rounded bg-purple-700 px-4 py-2 disabled:opacity-50">Send</button>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <h2 className="mb-3 font-bold">FAQ</h2>
              {roleCanWrite(role) && <div className="mb-4 space-y-2"><input value={faqQuestion} onChange={e => setFaqQuestion(e.target.value)} placeholder="سوال" className="w-full rounded bg-gray-800 p-2" /><textarea value={faqAnswer} onChange={e => setFaqAnswer(e.target.value)} placeholder="پاسخ" className="w-full rounded bg-gray-800 p-2" /><button onClick={() => void addFaq()} className="rounded bg-blue-700 px-4 py-2">Add</button></div>}
              <div className="max-h-80 space-y-2 overflow-auto">{faqs.map(faq => <div key={faq.id} className="rounded bg-gray-800 p-2 text-sm"><div className="font-bold">{faq.question}</div><div className="text-gray-300">{faq.answer}</div>{roleCanWrite(role) && <button onClick={() => void deleteFaq(faq.id)} className="mt-1 text-xs text-red-400">Delete</button>}</div>)}</div>
            </div>
          </section>
        )}

        {activeTab === 'logs' && <LogBox title="Admin audit trail" items={logs} />}
      </div>

      {selectedUser && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/80 p-4" onClick={() => setSelectedUser(null)}>
          <div className="w-full max-w-lg rounded-xl bg-gray-900 p-5" onClick={event => event.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between"><h2 className="font-bold">User #{selectedUser.id}</h2><button onClick={() => setSelectedUser(null)}>×</button></div>
            <div className="space-y-2 text-sm">
              <div>نام: {selectedUser.first_name} {selectedUser.last_name}</div>
              <div>کد ملی: {selectedUser.national_id}</div>
              <div>تاریخ تولد: {selectedUser.dob || '-'}</div>
              <div>کارت: {selectedUser.bank_card_number}</div>
              <div>تلفن: <span dir="ltr">{selectedUser.phone_number}</span></div>
              <div>سطح احراز: {selectedUser.verification_level}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ title, value, icon }: { title: string; value: React.ReactNode; icon?: React.ReactNode }) {
  return <div className="rounded-xl border border-gray-800 bg-gray-900 p-5"><div className="flex items-center justify-between text-gray-400"><span>{title}</span>{icon}</div><div className="mt-2 text-3xl font-bold">{value}</div></div>
}

function LogBox({ title, items }: { title: string; items: any[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <h2 className="mb-3 font-bold">{title}</h2>
      <div className="max-h-[65vh] space-y-2 overflow-auto text-xs">
        {items.length === 0 && <div className="text-gray-500">No records</div>}
        {items.map((item, index) => (
          <div key={item.id ?? index} className="rounded bg-gray-800 p-2">
            <div className="text-gray-400">{item.created_at || '-'}</div>
            <div className="font-medium">{item.action || item.endpoint || item.provider || '-'}</div>
            {item.phone_number && <div>Phone: {item.phone_number}</div>}
            {item.national_id && <div>NID: {item.national_id}</div>}
            {item.details && <div className="break-all text-gray-300">{item.details}</div>}
            {item.error_message && <div className="text-red-300">{item.error_message}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
