import React, { useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

type Submission = {
  id: number
  status: 'pending' | 'approved' | 'rejected'
  rejection_reason?: string | null
  created_at?: string
}

type KycStatus = {
  verification_level: number
  level1: { status: 'approved' }
  level2: Submission | null
  level3: Submission | null
}

const statusFa: Record<string, string> = {
  pending: 'در انتظار بررسی ادمین',
  approved: 'تایید شده',
  rejected: 'رد شده؛ لطفاً دوباره ارسال کنید',
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('token') || localStorage.getItem('auth_token') || ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function StepBadge({ done, active, children }: { done: boolean; active: boolean; children: React.ReactNode }) {
  return (
    <div className={`rounded-xl border p-4 ${done ? 'border-green-300 bg-green-50' : active ? 'border-blue-300 bg-blue-50' : 'border-gray-200 bg-gray-50'}`}>
      <div className="flex items-center justify-between gap-3">
        <strong>{children}</strong>
        <span className={`rounded-full px-3 py-1 text-xs ${done ? 'bg-green-600 text-white' : active ? 'bg-blue-600 text-white' : 'bg-gray-300 text-gray-700'}`}>
          {done ? 'تایید شده' : active ? 'مرحله فعلی' : 'قفل'}
        </span>
      </div>
    </div>
  )
}

export default function KycFlow() {
  const [status, setStatus] = useState<KycStatus | null>(null)
  const [front, setFront] = useState<File | null>(null)
  const [back, setBack] = useState<File | null>(null)
  const [selfie, setSelfie] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  const loadStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/kyc/status`, { headers: authHeaders() })
      if (!response.ok) throw new Error(`status_${response.status}`)
      setStatus(await response.json())
    } catch (error) {
      console.error('KYC status failed', error)
      setMessage('برای ادامه احراز هویت ابتدا وارد حساب کاربری شوید.')
    }
  }

  useEffect(() => { void loadStatus() }, [])

  const level2Pending = status?.level2?.status === 'pending'
  const level2Rejected = status?.level2?.status === 'rejected'
  const level3Pending = status?.level3?.status === 'pending'
  const level3Rejected = status?.level3?.status === 'rejected'
  const level2Approved = (status?.verification_level || 0) >= 2
  const level3Approved = (status?.verification_level || 0) >= 3

  const frontBackSame = useMemo(() => {
    if (!front || !back) return false
    return front === back || (
      front.name === back.name &&
      front.size === back.size &&
      front.lastModified === back.lastModified
    )
  }, [front, back])

  const submitLevel2 = async () => {
    if (!front || !back) {
      setMessage('لطفاً عکس روی کارت ملی و پشت کارت ملی را انتخاب کنید.')
      return
    }
    if (frontBackSame) {
      setMessage('عکس روی کارت و پشت کارت نباید یک فایل یکسان باشند.')
      return
    }
    setLoading(true)
    setMessage('')
    try {
      const body = new FormData()
      body.append('front', front)
      body.append('back', back)
      const response = await fetch(`${API_BASE}/kyc/level2`, {
        method: 'POST',
        headers: authHeaders(),
        body,
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `upload_${response.status}`)
      setMessage('مدارک سطح ۲ ارسال شد. پس از بررسی ادمین، وضعیت شما در همین صفحه به‌روزرسانی می‌شود.')
      setFront(null)
      setBack(null)
      await loadStatus()
    } catch (error: any) {
      const detail = String(error?.message || '')
      setMessage(detail.includes('front_and_back_must_be_different')
        ? 'عکس روی کارت و پشت کارت یکسان است. دو تصویر متفاوت ارسال کنید.'
        : 'ارسال مدارک انجام نشد. لطفاً دوباره تلاش کنید.')
    } finally {
      setLoading(false)
    }
  }

  const submitLevel3 = async () => {
    if (!selfie) {
      setMessage('لطفاً تصویر سلفی با کارت ملی در دست را انتخاب کنید.')
      return
    }
    setLoading(true)
    setMessage('')
    try {
      const body = new FormData()
      body.append('selfie', selfie)
      const response = await fetch(`${API_BASE}/kyc/level3`, {
        method: 'POST',
        headers: authHeaders(),
        body,
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `upload_${response.status}`)
      setMessage('مدرک سطح ۳ ارسال شد و در انتظار بررسی ادمین است.')
      setSelfie(null)
      await loadStatus()
    } catch (error) {
      console.error(error)
      setMessage('ارسال سلفی انجام نشد. لطفاً دوباره تلاش کنید.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section dir="rtl" className="mx-auto max-w-2xl space-y-5 rounded-2xl bg-white p-5 shadow-sm">
      <div>
        <h2 className="text-xl font-bold">احراز هویت</h2>
        <p className="mt-2 text-sm text-gray-600">سطح احراز هویت فعلی شما: <strong>{status?.verification_level || 1}</strong></p>
      </div>

      <div className="grid gap-3">
        <StepBadge done active>سطح ۱ — تطبیق اطلاعات با سرویس احراز</StepBadge>
        <StepBadge done={level2Approved} active={!level2Approved}>سطح ۲ — تصویر روی و پشت کارت ملی</StepBadge>
        <StepBadge done={level3Approved} active={level2Approved && !level3Approved}>سطح ۳ — سلفی با کارت ملی در دست</StepBadge>
      </div>

      <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-sm text-green-900">
        ✅ سطح ۱ را با موفقیت گذرانده‌اید. برای افزایش سطح احراز و حدود استفاده، مدارک سطح ۲ را ارسال کنید.
      </div>

      {!level2Approved && (
        <div className="space-y-4 rounded-xl border p-4">
          <h3 className="font-bold">سطح ۲</h3>
          {level2Pending ? (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">مدارک شما در انتظار بررسی ادمین است.</p>
          ) : (
            <>
              {level2Rejected && (
                <p className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
                  درخواست قبلی رد شد. {status?.level2?.rejection_reason || 'لطفاً تصاویر واضح‌تر را دوباره بارگذاری کنید.'}
                </p>
              )}
              <label className="block text-sm font-medium">تصویر روی کارت ملی
                <input className="mt-2 block w-full" type="file" accept="image/jpeg,image/png,image/webp" onChange={e => setFront(e.target.files?.[0] || null)} />
              </label>
              <label className="block text-sm font-medium">تصویر پشت کارت ملی
                <input className="mt-2 block w-full" type="file" accept="image/jpeg,image/png,image/webp" onChange={e => setBack(e.target.files?.[0] || null)} />
              </label>
              {frontBackSame && <p className="text-sm font-medium text-red-600">دو فایل انتخاب‌شده یکسان هستند.</p>}
              <button disabled={loading || frontBackSame} onClick={submitLevel2} className="w-full rounded-xl bg-blue-600 px-4 py-3 font-bold text-white disabled:opacity-50">
                {loading ? 'در حال ارسال...' : 'ارسال مدارک سطح ۲'}
              </button>
            </>
          )}
        </div>
      )}

      {level2Approved && !level3Approved && (
        <div className="space-y-4 rounded-xl border p-4">
          <div className="rounded-lg bg-green-50 p-3 text-sm text-green-900">✅ سطح ۲ تایید شده است.</div>
          <h3 className="font-bold">سطح ۳ — اختیاری برای افزایش حدود استفاده</h3>
          <p className="text-sm text-gray-600">یک سلفی واضح بگیرید که کارت ملی را در دست خود نگه داشته‌اید و صورت و کارت در تصویر قابل مشاهده باشند.</p>
          {level3Pending ? (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">سلفی شما در انتظار بررسی ادمین است.</p>
          ) : (
            <>
              {level3Rejected && (
                <p className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
                  درخواست قبلی رد شد. {status?.level3?.rejection_reason || 'لطفاً تصویر جدیدی ارسال کنید.'}
                </p>
              )}
              <input className="block w-full" type="file" accept="image/jpeg,image/png,image/webp" capture="user" onChange={e => setSelfie(e.target.files?.[0] || null)} />
              <button disabled={loading} onClick={submitLevel3} className="w-full rounded-xl bg-blue-600 px-4 py-3 font-bold text-white disabled:opacity-50">
                {loading ? 'در حال ارسال...' : 'ارسال سلفی سطح ۳'}
              </button>
            </>
          )}
        </div>
      )}

      {level3Approved && <div className="rounded-xl bg-green-100 p-4 font-bold text-green-900">✅ سطح ۳ احراز هویت شما تایید شده است.</div>}

      {message && <div className="rounded-xl bg-gray-100 p-3 text-sm">{message}</div>}
      <button onClick={() => void loadStatus()} className="text-sm font-medium text-blue-700">به‌روزرسانی وضعیت</button>
    </section>
  )
}
