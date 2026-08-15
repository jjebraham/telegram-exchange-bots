import { useEffect, useRef, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

type Profile = {
  id: number
  first_name: string
  last_name: string
  phone_number: string
  date_of_birth: string
  kyc_status: string
  verification_level: number
  email: string
  has_profile_picture: boolean
  telegram_connected: boolean
  telegram_username: string
}

const authHeaders = () => ({ Authorization: `Bearer ${localStorage.getItem('token') || ''}` })

export default function ProfilePageOverlay() {
  const [open, setOpen] = useState(false)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [email, setEmail] = useState('')
  const [pictureUrl, setPictureUrl] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const pollRef = useRef<number | null>(null)

  const isAdminHost = typeof window !== 'undefined' && window.location.hostname.includes('kianiapp')

  const loadProfile = async () => {
    const token = localStorage.getItem('token')
    if (!token) return
    const response = await fetch(`${API_BASE}/profile`, { headers: authHeaders() })
    if (!response.ok) return
    const data = await response.json()
    const next = data.profile as Profile
    setProfile(next)
    setEmail(next.email || '')
    if (next.has_profile_picture) {
      const picture = await fetch(`${API_BASE}/profile/picture?ts=${Date.now()}`, { headers: authHeaders() })
      if (picture.ok) {
        const blob = await picture.blob()
        setPictureUrl(old => {
          if (old) URL.revokeObjectURL(old)
          return URL.createObjectURL(blob)
        })
      }
    } else {
      setPictureUrl(old => {
        if (old) URL.revokeObjectURL(old)
        return ''
      })
    }
    return next
  }

  useEffect(() => {
    if (isAdminHost) return
    const onClick = (event: MouseEvent) => {
      const button = (event.target as HTMLElement | null)?.closest('button')
      if (!button || !button.textContent?.includes('پروفایل')) return
      if (!localStorage.getItem('token')) return
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()
      setOpen(true)
      void loadProfile()
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [isAdminHost])

  useEffect(() => () => {
    if (pictureUrl) URL.revokeObjectURL(pictureUrl)
    if (pollRef.current) window.clearInterval(pollRef.current)
  }, [pictureUrl])

  const saveEmail = async () => {
    setBusy(true)
    try {
      const response = await fetch(`${API_BASE}/profile/email`, {
        method: 'PUT',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (!response.ok) throw new Error()
      window.alert('ایمیل با موفقیت ذخیره شد.')
      await loadProfile()
    } catch {
      window.alert('ایمیل معتبر وارد کنید.')
    } finally {
      setBusy(false)
    }
  }

  const uploadPicture = async (file?: File) => {
    if (!file) return
    const form = new FormData()
    form.append('picture', file)
    setBusy(true)
    try {
      const response = await fetch(`${API_BASE}/profile/picture`, {
        method: 'POST', headers: authHeaders(), body: form,
      })
      if (!response.ok) throw new Error()
      await loadProfile()
    } catch {
      window.alert('آپلود تصویر انجام نشد. فایل باید JPG، PNG یا WEBP و حداکثر ۵ مگابایت باشد.')
    } finally {
      setBusy(false)
    }
  }

  const changePassword = async () => {
    if (newPassword !== confirmPassword) {
      window.alert('رمز جدید و تکرار آن یکسان نیستند.')
      return
    }
    setBusy(true)
    try {
      const response = await fetch(`${API_BASE}/profile/change-password`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        if (data?.detail === 'current_password_incorrect') throw new Error('current')
        throw new Error('weak')
      }
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      window.alert('رمز عبور با موفقیت تغییر کرد.')
    } catch (error) {
      window.alert(error instanceof Error && error.message === 'current'
        ? 'رمز عبور فعلی صحیح نیست.'
        : 'رمز جدید باید حداقل ۸ کاراکتر و شامل حرف و عدد باشد.')
    } finally {
      setBusy(false)
    }
  }

  const connectTelegram = async () => {
    setBusy(true)
    try {
      const response = await fetch(`${API_BASE}/profile/telegram-link/start`, {
        method: 'POST', headers: authHeaders(),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.deep_link) throw new Error()
      const tg = (window as any)?.Telegram?.WebApp
      if (tg?.openTelegramLink) tg.openTelegramLink(data.deep_link)
      else window.open(data.deep_link, '_blank', 'noopener,noreferrer')

      window.alert('ربات تلگرام باز شد. دکمه Start را بزنید تا اتصال کامل شود. این لینک ۱۰ دقیقه اعتبار دارد.')
      if (pollRef.current) window.clearInterval(pollRef.current)
      pollRef.current = window.setInterval(async () => {
        const next = await loadProfile()
        if (next?.telegram_connected && pollRef.current) {
          window.clearInterval(pollRef.current)
          pollRef.current = null
        }
      }, 3000)
    } catch {
      window.alert('اتصال به ربات تلگرام در حال حاضر در دسترس نیست.')
    } finally {
      setBusy(false)
    }
  }

  const disconnectTelegram = async () => {
    setBusy(true)
    try {
      const response = await fetch(`${API_BASE}/profile/telegram-link`, {
        method: 'DELETE', headers: authHeaders(),
      })
      if (!response.ok) throw new Error()
      await loadProfile()
    } catch {
      window.alert('قطع اتصال تلگرام انجام نشد.')
    } finally {
      setBusy(false)
    }
  }

  if (isAdminHost || !open) return null

  return (
    <div className="fixed inset-0 z-[75] overflow-y-auto bg-gray-100" dir="rtl">
      <header className="sticky top-0 z-10 bg-gradient-to-r from-blue-700 to-purple-700 text-white shadow">
        <div className="mx-auto flex max-w-2xl items-center justify-between p-4">
          <h1 className="text-xl font-bold">پروفایل</h1>
          <button onClick={() => setOpen(false)} className="rounded-lg bg-white/20 px-4 py-2">بازگشت</button>
        </div>
      </header>

      <main className="mx-auto max-w-2xl space-y-4 p-4 pb-12">
        {!profile ? (
          <div className="rounded-2xl bg-white p-8 text-center shadow">در حال بارگذاری...</div>
        ) : (
          <>
            <section className="rounded-2xl bg-white p-5 shadow">
              <div className="flex flex-col items-center gap-3">
                <div className="flex h-28 w-28 items-center justify-center overflow-hidden rounded-full bg-gray-200 text-4xl">
                  {pictureUrl ? <img src={pictureUrl} alt="تصویر پروفایل" className="h-full w-full object-cover" /> : '👤'}
                </div>
                <label className="cursor-pointer rounded-lg bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700">
                  افزودن / تغییر تصویر پروفایل
                  <input type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={e => void uploadPicture(e.target.files?.[0])} />
                </label>
                <div className="text-xl font-bold text-gray-900">{profile.first_name} {profile.last_name}</div>
                <div className="text-sm text-gray-500">سطح احراز هویت: {profile.verification_level}</div>
              </div>
              <div className="mt-5 space-y-3 border-t pt-4 text-sm">
                <div className="flex justify-between"><span className="text-gray-500">شماره موبایل</span><span dir="ltr" className="font-semibold">{profile.phone_number}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">تاریخ تولد</span><span dir="ltr" className="font-semibold">{profile.date_of_birth || '-'}</span></div>
              </div>
            </section>

            <section className="rounded-2xl bg-white p-5 shadow">
              <h2 className="mb-3 font-bold">ایمیل</h2>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input type="email" dir="ltr" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@example.com" className="flex-1 rounded-xl border px-3 py-3" />
                <button disabled={busy} onClick={saveEmail} className="rounded-xl bg-blue-600 px-5 py-3 text-white disabled:opacity-50">ذخیره</button>
              </div>
            </section>

            <section className="rounded-2xl bg-white p-5 shadow">
              <h2 className="mb-3 font-bold">تغییر رمز عبور</h2>
              <div className="space-y-2">
                <input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} placeholder="رمز عبور فعلی" className="w-full rounded-xl border px-3 py-3" />
                <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="رمز عبور جدید" className="w-full rounded-xl border px-3 py-3" />
                <input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} placeholder="تکرار رمز عبور جدید" className="w-full rounded-xl border px-3 py-3" />
                <button disabled={busy} onClick={changePassword} className="w-full rounded-xl bg-indigo-600 px-5 py-3 text-white disabled:opacity-50">تغییر رمز عبور</button>
              </div>
            </section>

            <section className="rounded-2xl bg-white p-5 shadow">
              <h2 className="font-bold">اعلان‌های تلگرام</h2>
              <p className="mt-2 text-sm text-gray-600">پس از اتصال، تغییر وضعیت سفارش و نتیجه احراز هویت از طریق ربات برای شما ارسال می‌شود.</p>
              {profile.telegram_connected ? (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-green-50 p-3 text-green-800">
                  <span>✅ تلگرام متصل است {profile.telegram_username ? `@${profile.telegram_username}` : ''}</span>
                  <button disabled={busy} onClick={disconnectTelegram} className="rounded-lg bg-white px-3 py-2 text-sm text-red-600">قطع اتصال</button>
                </div>
              ) : (
                <button disabled={busy} onClick={connectTelegram} className="mt-4 w-full rounded-xl bg-sky-500 px-5 py-3 font-semibold text-white disabled:opacity-50">اتصال به تلگرام</button>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  )
}
