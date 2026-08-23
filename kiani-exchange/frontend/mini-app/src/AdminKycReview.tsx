import React, { useEffect, useState } from 'react'

import { adminFetch, adminJson, getAdminToken } from './adminApi'

type Submission = {
  id: number
  user_id: number
  level: number
  status: string
  first_name: string
  last_name: string
  phone_number: string
  national_id: string
  verification_level: number
  rejection_reason?: string | null
  created_at?: string
  has_front?: boolean
  has_back?: boolean
  has_selfie?: boolean
}

export default function AdminKycReview() {
  const isAdminHost = typeof window !== 'undefined' && window.location.hostname.includes('kianiapp')
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Submission[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [preview, setPreview] = useState<{ url: string; label: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const load = async () => {
    if (!getAdminToken()) {
      setMessage('ابتدا از پنل ادمین وارد شوید.')
      return
    }
    setLoading(true)
    setMessage('')
    try {
      const data = await adminJson<{ submissions: Submission[] }>('/admin/kyc/submissions?status=pending')
      setItems(Array.isArray(data?.submissions) ? data.submissions : [])
    } catch (error) {
      console.error(error)
      setMessage('دریافت درخواست‌های KYC ناموفق بود.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) void load()
  }, [open])

  const closePreview = () => {
    if (preview?.url) URL.revokeObjectURL(preview.url)
    setPreview(null)
  }

  const openFile = async (
    item: Submission,
    kind: 'front' | 'back' | 'selfie',
    label: string,
  ) => {
    if (!getAdminToken()) {
      setMessage('نشست ادمین وجود ندارد. دوباره وارد شوید.')
      return
    }
    setPreviewLoading(true)
    setMessage('')
    try {
      const response = await adminFetch(`/admin/kyc/submissions/${item.id}/file/${kind}`)
      if (!response.ok) throw new Error(`http_${response.status}`)
      const blob = await response.blob()
      if (preview?.url) URL.revokeObjectURL(preview.url)
      setPreview({ url: URL.createObjectURL(blob), label })
    } catch (error) {
      console.error(error)
      setMessage('نمایش تصویر مدرک انجام نشد.')
    } finally {
      setPreviewLoading(false)
    }
  }

  const decide = async (item: Submission, action: 'approve' | 'reject') => {
    let reason: string | undefined
    if (action === 'reject') {
      reason = window.prompt(
        'دلیل رد و درخواست بارگذاری مجدد را بنویسید:',
        'تصویر واضح نیست؛ لطفاً دوباره بارگذاری کنید.',
      ) || undefined
      if (!reason) return
    }

    setLoading(true)
    setMessage('')
    try {
      await adminJson(`/admin/kyc/submissions/${item.id}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      })
      setItems(current => current.filter(row => row.id !== item.id))
      setMessage(
        action === 'approve'
          ? `KYC سطح ${item.level} کاربر تایید شد.`
          : 'درخواست رد شد و کاربر می‌تواند دوباره بارگذاری کند.',
      )
    } catch (error) {
      console.error(error)
      setMessage('ثبت تصمیم انجام نشد. نقش Admin برای تایید/رد لازم است.')
    } finally {
      setLoading(false)
    }
  }

  if (!isAdminHost) return null

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-[90] rounded-xl bg-emerald-600 px-4 py-3 font-bold text-white shadow-xl"
      >
        بررسی KYC
      </button>

      {open && (
        <div className="fixed inset-0 z-[100] overflow-y-auto bg-black/70 p-4 text-white" dir="rtl">
          <div className="mx-auto mt-6 max-w-4xl rounded-2xl border border-gray-700 bg-gray-900 p-5 shadow-2xl">
            <div className="mb-5 flex items-center justify-between gap-3">
              <h2 className="text-xl font-bold">درخواست‌های در انتظار بررسی KYC</h2>
              <div className="flex gap-2">
                <button disabled={loading} onClick={() => void load()} className="rounded-lg bg-blue-600 px-4 py-2 disabled:opacity-50">
                  {loading ? 'در حال دریافت...' : 'بروزرسانی'}
                </button>
                <button onClick={() => setOpen(false)} className="rounded-lg bg-gray-700 px-4 py-2">بستن</button>
              </div>
            </div>

            {message && <div className="mb-4 rounded-lg bg-gray-800 p-3 text-sm">{message}</div>}

            <div className="space-y-3">
              {!loading && items.length === 0 && (
                <div className="rounded-xl border border-gray-700 p-5 text-gray-400">
                  درخواست در انتظار بررسی وجود ندارد یا هنوز وارد پنل ادمین نشده‌اید.
                </div>
              )}
              {items.map(item => (
                <article key={item.id} className="rounded-xl border border-gray-700 bg-gray-800/60 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="font-bold">{item.first_name} {item.last_name} — سطح {item.level}</h3>
                      <div className="mt-2 space-y-1 text-sm text-gray-300">
                        <div>Submission #{item.id}</div>
                        <div>تلفن: {item.phone_number}</div>
                        <div>کد ملی: {item.national_id}</div>
                        <div>سطح فعلی: {item.verification_level}</div>
                        <div>
                          مدارک: {item.level === 2
                            ? `${item.has_front ? 'روی کارت ✓' : 'روی کارت ✗'} / ${item.has_back ? 'پشت کارت ✓' : 'پشت کارت ✗'}`
                            : `${item.has_selfie ? 'سلفی ✓' : 'سلفی ✗'}`}
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button disabled={loading} onClick={() => void decide(item, 'approve')} className="rounded-lg bg-green-600 px-4 py-2 font-bold disabled:opacity-50">تایید</button>
                      <button disabled={loading} onClick={() => void decide(item, 'reject')} className="rounded-lg bg-red-600 px-4 py-2 font-bold disabled:opacity-50">رد / ارسال مجدد</button>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {item.level === 2 && item.has_front && (
                      <button disabled={previewLoading} onClick={() => void openFile(item, 'front', 'روی کارت ملی')} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold disabled:opacity-50">مشاهده روی کارت</button>
                    )}
                    {item.level === 2 && item.has_back && (
                      <button disabled={previewLoading} onClick={() => void openFile(item, 'back', 'پشت کارت ملی')} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold disabled:opacity-50">مشاهده پشت کارت</button>
                    )}
                    {item.level === 3 && item.has_selfie && (
                      <button disabled={previewLoading} onClick={() => void openFile(item, 'selfie', 'سلفی با کارت ملی')} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold disabled:opacity-50">مشاهده سلفی</button>
                    )}
                  </div>

                  <p className="mt-3 text-xs text-gray-400">
                    تصویر فقط با نشست ادمین معتبر دریافت می‌شود و پاسخ مرورگر با no-store برگردانده می‌شود.
                  </p>
                </article>
              ))}
            </div>
          </div>
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/90 p-4" onClick={closePreview}>
          <div className="max-h-[95vh] max-w-4xl" onClick={event => event.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between gap-4 text-white">
              <strong>{preview.label}</strong>
              <button onClick={closePreview} className="rounded-lg bg-gray-700 px-4 py-2">بستن</button>
            </div>
            <img src={preview.url} alt={preview.label} className="max-h-[85vh] max-w-full rounded-xl bg-white object-contain" />
          </div>
        </div>
      )}
    </>
  )
}
