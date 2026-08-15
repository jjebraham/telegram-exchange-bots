import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

type Credentials = { username: string; password: string }
type RateDraft = Record<string, string>

const RATE_FIELDS = [
  ['toman_to_tl', 'Toman → TL'],
  ['tl_to_toman', 'TL → Toman'],
  ['tl_to_usdt', 'TL → USDT'],
  ['usdt_to_tl', 'USDT → TL'],
  ['toman_to_usdt', 'Toman → USDT'],
  ['usdt_to_toman', 'USDT → Toman'],
] as const

const normalizeDecimalInput = (raw: string) => raw
  .replace(/[۰-۹]/g, d => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
  .replace(/[٠-٩]/g, d => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
  .replace(/[٫,]/g, '.')

export default function AdminRateEditorFix() {
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [target, setTarget] = useState<HTMLElement | null>(null)
  const [draft, setDraft] = useState<RateDraft>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const originalCard = useRef<HTMLElement | null>(null)
  const originalFetch = useRef<typeof window.fetch | null>(null)

  const isAdminHost = typeof window !== 'undefined' && window.location.hostname.includes('kianiapp')

  useEffect(() => {
    if (!isAdminHost || originalFetch.current) return
    const baseFetch = window.fetch.bind(window)
    originalFetch.current = baseFetch

    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      try {
        if (url.includes('/admin/login') && init?.body && typeof init.body === 'string') {
          const body = JSON.parse(init.body)
          if (body?.username && body?.password) {
            setCredentials({ username: String(body.username), password: String(body.password) })
          }
        }
        if (url.includes('/admin/rates?')) {
          const parsed = new URL(url, window.location.origin)
          const username = parsed.searchParams.get('username')
          const password = parsed.searchParams.get('password')
          if (username && password) setCredentials({ username, password })
        }
      } catch {
        // Never interfere with the application's own request.
      }
      return baseFetch(input, init)
    }

    return () => {
      if (originalFetch.current) window.fetch = originalFetch.current
      originalFetch.current = null
    }
  }, [isAdminHost])

  useEffect(() => {
    if (!isAdminHost) return
    const locate = () => {
      const headings = Array.from(document.querySelectorAll('h3'))
      const heading = headings.find(el => el.textContent?.trim() === 'Rate Management') as HTMLElement | undefined
      const card = heading?.closest('.max-w-3xl') as HTMLElement | null
      if (card && card !== originalCard.current) {
        if (originalCard.current) originalCard.current.style.display = ''
        originalCard.current = card
        card.style.display = 'none'
        setTarget(card.parentElement)
      } else if (!card && originalCard.current && !document.body.contains(originalCard.current)) {
        originalCard.current = null
        setTarget(null)
      }
    }
    locate()
    const observer = new MutationObserver(locate)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => {
      observer.disconnect()
      if (originalCard.current) originalCard.current.style.display = ''
    }
  }, [isAdminHost])

  const loadRates = async () => {
    if (!credentials) return
    setLoading(true)
    try {
      const qs = new URLSearchParams(credentials).toString()
      const response = await fetch(`${API_BASE}/admin/rates?${qs}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data?.detail || 'load_failed')
      const settings = data?.settings || {}
      setDraft(Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, String(value ?? '')])))
    } catch {
      window.alert('خطا در دریافت تنظیمات نرخ')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (target && credentials) void loadRates()
  }, [target, credentials?.username, credentials?.password])

  const updateDraft = (key: string, raw: string) => {
    const value = normalizeDecimalInput(raw)
    const isPercentage = key.endsWith('_percentage')
    const pattern = isPercentage ? /^-?\d*(?:\.\d*)?$/ : /^\d*(?:\.\d*)?$/
    if (pattern.test(value)) setDraft(prev => ({ ...prev, [key]: value }))
  }

  const parsedSettings = useMemo(() => {
    const values: Record<string, number> = {}
    for (const [key, raw] of Object.entries(draft)) {
      if (raw === '' || raw === '-' || raw === '.' || raw === '-.') return null
      const value = Number(raw)
      if (!Number.isFinite(value)) return null
      if (key.endsWith('_percentage') && (value < -50 || value > 50)) return null
      if (key.endsWith('_manual_rate') && value < 0) return null
      values[key] = value
    }
    return values
  }, [draft])

  const save = async () => {
    if (!credentials || !parsedSettings) {
      window.alert('لطفاً تمام نرخ‌ها و درصدها را به صورت عدد معتبر وارد کنید. درصد می‌تواند بین 50- تا 50+ باشد.')
      return
    }
    setSaving(true)
    try {
      const response = await fetch(`${API_BASE}/admin/rates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...credentials, ...parsedSettings }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data?.detail || 'save_failed')
      const settings = data?.settings || parsedSettings
      setDraft(Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, String(value ?? '')])))
      window.alert('تنظیمات نرخ با موفقیت ذخیره شد.')
    } catch {
      window.alert('خطا در ذخیره تنظیمات نرخ')
    } finally {
      setSaving(false)
    }
  }

  if (!isAdminHost || !target) return null

  return createPortal(
    <div className="max-w-3xl mx-auto bg-gray-800/50 border border-gray-700/50 rounded-xl p-6 space-y-5" dir="rtl">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-xl font-bold text-white">مدیریت نرخ‌ها</h3>
          <p className="text-gray-400 text-sm mt-1">نرخ دستی ۰ = استفاده از نرخ بازار. درصدها اعشاری و منفی را می‌پذیرند؛ مثال: ‎-2.5</p>
        </div>
        <button onClick={loadRates} className="px-3 py-2 rounded bg-gray-700 text-gray-200">بروزرسانی</button>
      </div>

      {!credentials ? (
        <div className="text-yellow-300 text-sm">برای ویرایش نرخ‌ها یک بار از پنل ادمین خارج و دوباره وارد شوید.</div>
      ) : loading ? (
        <div className="text-gray-300">در حال دریافت...</div>
      ) : (
        <div className="space-y-4">
          {RATE_FIELDS.map(([prefix, label]) => (
            <div key={prefix} className="grid grid-cols-1 md:grid-cols-2 gap-3 border-b border-gray-700/50 pb-4">
              <label className="text-sm text-gray-300">
                <div className="mb-1">{label} — نرخ دستی (۰ = بازار)</div>
                <input
                  type="text"
                  inputMode="decimal"
                  dir="ltr"
                  value={draft[`${prefix}_manual_rate`] ?? ''}
                  onChange={e => updateDraft(`${prefix}_manual_rate`, e.target.value)}
                  className="w-full px-3 py-2 rounded bg-gray-900/50 border border-gray-700 text-white"
                />
              </label>
              <label className="text-sm text-gray-300">
                <div className="mb-1">{label} — درصد تعدیل</div>
                <input
                  type="text"
                  inputMode="decimal"
                  dir="ltr"
                  value={draft[`${prefix}_percentage`] ?? ''}
                  onChange={e => updateDraft(`${prefix}_percentage`, e.target.value)}
                  placeholder="مثال: -2.5"
                  className="w-full px-3 py-2 rounded bg-gray-900/50 border border-gray-700 text-white"
                />
              </label>
            </div>
          ))}
          <button
            onClick={save}
            disabled={saving}
            className="px-5 py-3 bg-blue-600 rounded text-white disabled:opacity-50"
          >
            {saving ? 'در حال ذخیره...' : 'ذخیره تنظیمات نرخ'}
          </button>
        </div>
      )}
    </div>,
    target,
  )
}
