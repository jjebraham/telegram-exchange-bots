import React, { useEffect, useState } from 'react'

import { adminFetch, adminJson, getAdminRole, getAdminToken } from './adminApi'

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
  declaration_version?: string | null
  declaration_accepted_at?: string | null
  declaration_text?: string | null
}

type RetainedGroup = {
  user_id: number
  account_present: boolean
  first_name: string
  last_name: string
  phone_number: string
  previous_status?: string | null
  files: { id: string; name: string; kind: string; level: number | null; uploaded_at: string }[]
}

export default function AdminKycReview({ initiallyOpen = false }: { initiallyOpen?: boolean } = {}) {
  const isAdminHost = typeof window !== 'undefined' && window.location.hostname.includes('kianiapp')
  const [open, setOpen] = useState(initiallyOpen)
  const [items, setItems] = useState<Submission[]>([])
  const [retained, setRetained] = useState<RetainedGroup[]>([])
  const [statusFilter, setStatusFilter] = useState('pending')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [preview, setPreview] = useState<{
    url: string
    label: string
    mimeType: string
  } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [viewedSelfies, setViewedSelfies] = useState<Record<number, boolean>>({})
  const [reviewedSelfies, setReviewedSelfies] = useState<Record<number, boolean>>({})

  const load = async () => {
    if (!getAdminToken()) {
      setMessage('ابتدا از پنل ادمین وارد شوید.')
      return
    }
    setLoading(true)
    setMessage('')
    try {
      const [data, files] = await Promise.all([
        adminJson<{ submissions: Submission[] }>(`/admin/kyc/submissions${statusFilter ? `?status=${statusFilter}` : ''}`),
        adminJson<{ groups: RetainedGroup[] }>('/admin/kyc/retained-files'),
      ])
      setItems(Array.isArray(data?.submissions) ? data.submissions : [])
      setReviewedSelfies({})
      setRetained(Array.isArray(files?.groups) ? files.groups : [])
    } catch (error) {
      console.error(error)
      setMessage('دریافت درخواست‌های KYC ناموفق بود.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) void load()
  }, [open, statusFilter])

  useEffect(() => () => {
    if (preview?.url) URL.revokeObjectURL(preview.url)
  }, [preview?.url])

  const closePreview = () => {
    if (preview?.url) URL.revokeObjectURL(preview.url)
    setPreview(null)
  }

  const openFile = async (
    item: Submission,
    kind: 'front' | 'back' | 'selfie',
    label: string,
  ) => {
    const opened = await openPreview(`/admin/kyc/submissions/${item.id}/file/${kind}`, label)
    if (opened && kind === 'selfie') {
      setViewedSelfies(current => ({ ...current, [item.id]: true }))
    }
  }

  const openPreview = async (path: string, label: string) => {
    if (!getAdminToken()) {
      setMessage('نشست ادمین وجود ندارد. دوباره وارد شوید.')
      return
    }
    setPreviewLoading(true)
    setMessage('')
    try {
      const response = await adminFetch(path)
      if (!response.ok) throw new Error(`http_${response.status}`)
      const blob = await response.blob()

      if (preview?.url) {
        URL.revokeObjectURL(preview.url)
      }

      setPreview({
        url: URL.createObjectURL(blob),
        label,
        mimeType:
          blob.type ||
          response.headers.get('content-type') ||
          'application/octet-stream',
      })
      return true
    } catch (error) {
      console.error(error)
      setMessage('نمایش تصویر مدرک انجام نشد.')
      return false
    } finally {
      setPreviewLoading(false)
    }
  }

  const decide = async (item: Submission, action: 'approve' | 'reject') => {
    if (action === 'approve' && item.level === 3 && !reviewedSelfies[item.id]) {
      setMessage('ابتدا عکس سطح ۳ را باز کنید و بررسی چهره، کارت ملی، متن دست‌نویس، تاریخ و امضا را تأیید کنید.')
      return
    }
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
        body: JSON.stringify({ reason, level3_photo_reviewed: item.level === 3 && !!reviewedSelfies[item.id] }),
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
              <h2 className="text-xl font-bold">بررسی مدارک احراز هویت KYC</h2>
              <div className="flex gap-2">
                <button disabled={loading} onClick={() => void load()} className="rounded-lg bg-blue-600 px-4 py-2 disabled:opacity-50">
                  {loading ? 'در حال دریافت...' : 'بروزرسانی'}
                </button>
                <button onClick={() => setOpen(false)} className="rounded-lg bg-gray-700 px-4 py-2">بستن</button>
              </div>
            </div>

            {message && <div className="mb-4 rounded-lg bg-gray-800 p-3 text-sm">{message}</div>}

            <label className="mb-4 flex items-center gap-3 text-sm">
              وضعیت درخواست
              <select aria-label="وضعیت درخواست" value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className="rounded-lg bg-gray-800 p-2 text-white">
                <option value="pending">در انتظار بررسی</option>
                <option value="approved">تایید شده</option>
                <option value="rejected">رد شده</option>
                <option value="">همه درخواست‌ها</option>
              </select>
            </label>

            <div className="space-y-3">
              {!loading && items.length === 0 && (
                <div className="rounded-xl border border-gray-700 p-5 text-gray-400">
                  در این فهرست درخواستی وجود ندارد. مدارک نگهداری‌شده را نیز در بخش پایین بررسی کنید.
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
                        <div>وضعیت درخواست: {item.status}</div>
                        <div>
                          مدارک: {item.level === 2
                            ? `${item.has_front ? 'روی کارت ✓' : 'روی کارت ✗'} / ${item.has_back ? 'پشت کارت ✓' : 'پشت کارت ✗'}`
                            : `${item.has_selfie ? 'سلفی ✓' : 'سلفی ✗'}`}
                        </div>
                      </div>
                    </div>
                    {item.status === 'pending' && getAdminRole() === 'admin' && <div className="flex gap-2">
                      <button disabled={loading || (item.level === 3 && !reviewedSelfies[item.id])} onClick={() => void decide(item, 'approve')} className="rounded-lg bg-green-600 px-4 py-2 font-bold disabled:opacity-50">تایید</button>
                      <button disabled={loading} onClick={() => void decide(item, 'reject')} className="rounded-lg bg-red-600 px-4 py-2 font-bold disabled:opacity-50">رد / ارسال مجدد</button>
                    </div>}
                  </div>

                  {item.level === 3 && (
                    <section className="mt-4 space-y-3 rounded-xl border border-blue-400/40 bg-blue-950/40 p-4 text-sm leading-7">
                      <h4 className="font-bold">بررسی عکس با کارت ملی و تعهدنامه دست‌نویس</h4>
                      <p className="text-gray-300">
                        {item.declaration_version && item.declaration_accepted_at
                          ? 'تأیید تهیه برگه دست‌نویس هنگام ارسال این درخواست ثبت شده است؛ محتوای عکس باید دستی بررسی شود.'
                          : 'این درخواست با راهنمای قبلی ارسال شده و تأیید تعهدنامه برای آن ثبت نشده است. وجود برگه را در عکس بررسی کنید؛ اگر کامل نیست، با توضیح دلیل درخواست ارسال مجدد بدهید.'}
                      </p>
                      <ul className="list-disc space-y-1 pr-5 text-gray-200">
                        <li>چهره با کارت ملی و اطلاعات حساب مطابقت دارد و هر سه مورد در یک عکس واقعی و بدون ویرایش دیده می‌شوند.</li>
                        <li>متن کامل تعهدنامه کیانی با دست نوشته شده و نام و نام خانوادگی متعلق به صاحب حساب است.</li>
                        <li>تاریخ روز عکس و امضا روی برگه وجود دارد و تمام نوشته‌ها و اطلاعات کارت خوانا هستند.</li>
                      </ul>
                      {item.declaration_text && (
                        <details>
                          <summary className="cursor-pointer font-bold text-blue-200">متن تعهدنامه مربوط به این درخواست</summary>
                          <p className="mt-2 whitespace-pre-line rounded-lg bg-gray-900 p-3 text-gray-200">{item.declaration_text}</p>
                        </details>
                      )}
                      {item.status === 'pending' && getAdminRole() === 'admin' && (
                        <label className="flex cursor-pointer items-start gap-3">
                          <input type="checkbox" className="mt-1.5 h-5 w-5 shrink-0 accent-emerald-500" disabled={loading || !viewedSelfies[item.id]} checked={!!reviewedSelfies[item.id]} onChange={event => setReviewedSelfies(current => ({ ...current, [item.id]: event.target.checked }))} />
                          <span>{viewedSelfies[item.id] ? 'عکس را مشاهده کردم و تطبیق چهره و کارت، متن کامل دست‌نویس، تاریخ و امضا را بررسی و تأیید می‌کنم.' : 'ابتدا «مشاهده عکس و تعهدنامه» را باز کنید؛ سپس نتیجه بررسی موارد بالا را تأیید کنید.'}</span>
                        </label>
                      )}
                    </section>
                  )}

                  <div className="mt-4 flex flex-wrap gap-2">
                    {item.level === 2 && item.has_front && (
                      <button disabled={previewLoading} onClick={() => void openFile(item, 'front', 'روی کارت ملی')} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold disabled:opacity-50">مشاهده روی کارت</button>
                    )}
                    {item.level === 2 && item.has_back && (
                      <button disabled={previewLoading} onClick={() => void openFile(item, 'back', 'پشت کارت ملی')} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold disabled:opacity-50">مشاهده پشت کارت</button>
                    )}
                    {item.level === 3 && item.has_selfie && (
                      <button disabled={previewLoading} onClick={() => void openFile(item, 'selfie', 'سلفی با کارت ملی و تعهدنامه امضاشده')} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold disabled:opacity-50">مشاهده عکس و تعهدنامه</button>
                    )}
                  </div>

                </article>
              ))}
            </div>

            {retained.length > 0 && (
              <section className="mt-6 border-t border-gray-700 pt-5">
                <h3 className="text-lg font-bold">مدارک نگهداری‌شده ({retained.reduce((count, group) => count + group.files.length, 0)} فایل)</h3>
                <p className="mt-2 text-sm leading-6 text-gray-300">
                  این فایل‌ها از قبل باقی مانده‌اند و برای مشاهده در دسترس هستند. وضعیت فعلی آن‌ها مشخص نیست؛ تایید یا رد حساب از این بخش انجام نمی‌شود.
                </p>
                <div className="mt-4 space-y-4">
                  {retained.map(group => (
                    <article key={group.user_id} className="rounded-xl border border-amber-700/60 bg-gray-800 p-4">
                      <h4 className="font-bold">{group.first_name} {group.last_name} — کاربر #{group.user_id}</h4>
                      {group.phone_number && <p className="mt-1 text-sm text-gray-300" dir="ltr">{group.phone_number}</p>}
                      <p className="mt-2 text-sm text-amber-200">
                        {group.account_present ? 'حساب کاربر در فهرست فعلی موجود است.' : 'حساب این کاربر در فهرست فعلی موجود نیست؛ مدارک قابل مشاهده هستند.'}
                        {group.previous_status === 'pending' && ' در نسخه پشتیبان، یک درخواست در انتظار بررسی ثبت شده است.'}
                      </p>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        {group.files.map(file => (
                          <button key={file.id} disabled={previewLoading} onClick={() => void openPreview(`/admin/kyc/retained-files/${file.id}`, `کاربر #${group.user_id} — ${file.kind === 'front' ? 'روی کارت' : file.kind === 'back' ? 'پشت کارت' : file.kind === 'selfie' ? 'سلفی' : 'مدرک'}`)} className="rounded-lg bg-blue-600 p-3 text-right text-sm disabled:opacity-50">
                            <span className="block font-bold">{file.kind === 'front' ? 'مشاهده روی کارت' : file.kind === 'back' ? 'مشاهده پشت کارت' : file.kind === 'selfie' ? 'مشاهده سلفی' : 'مشاهده فایل'}{file.level ? ` — سطح ${file.level}` : ''}</span>
                            <span className="mt-1 block text-xs text-blue-100" dir="ltr">{new Date(file.uploaded_at).toLocaleString('fa-IR')}</span>
                          </button>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            )}
          </div>
        </div>
      )}

      {preview && (
        <div
          className="fixed inset-0 z-[120] overflow-y-auto bg-black/90 p-3 sm:p-6"
          onClick={closePreview}
          dir="rtl"
        >
          <div
            className="mx-auto flex min-h-[calc(100dvh-1.5rem)] w-full max-w-5xl flex-col justify-center"
            onClick={event => event.stopPropagation()}
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-white">
              <div>
                <strong className="block">{preview.label}</strong>
                <span
                  className="mt-1 block text-xs text-gray-400"
                  dir="ltr"
                >
                  {preview.mimeType}
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                <a
                  href={preview.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-h-11 rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white"
                >
                  باز کردن فایل
                </a>

                <button
                  type="button"
                  onClick={closePreview}
                  className="min-h-11 rounded-lg bg-gray-700 px-4 py-2 font-bold"
                >
                  بستن
                </button>
              </div>
            </div>

            {preview.mimeType === 'application/pdf' ? (
              <div className="overflow-hidden rounded-2xl bg-white shadow-2xl">
                <iframe
                  src={preview.url}
                  title={preview.label}
                  className="h-[78dvh] min-h-[420px] w-full"
                />
              </div>
            ) : preview.mimeType === 'image/jpeg' ||
              preview.mimeType === 'image/png' ||
              preview.mimeType === 'image/webp' ? (
              <div className="flex justify-center rounded-2xl bg-white p-2 shadow-2xl">
                <img
                  src={preview.url}
                  alt={preview.label}
                  className="max-h-[82dvh] max-w-full rounded-xl object-contain"
                />
              </div>
            ) : (
              <div className="rounded-2xl bg-white p-6 text-center text-gray-900 shadow-2xl sm:p-10">
                <div className="text-6xl">📄</div>

                <h3 className="mt-4 text-lg font-black">
                  پیش‌نمایش مستقیم این فایل در مرورگر پشتیبانی نمی‌شود
                </h3>

                <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-gray-600">
                  فایل با موفقیت و از مسیر امن دریافت شده است.
                  برای فایل‌های HEIC یا HEIF از دکمه «باز کردن فایل»
                  استفاده کنید.
                </p>

                <a
                  href={preview.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-6 inline-flex min-h-12 items-center justify-center rounded-xl bg-blue-600 px-6 py-3 font-bold text-white"
                >
                  باز کردن فایل
                </a>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
