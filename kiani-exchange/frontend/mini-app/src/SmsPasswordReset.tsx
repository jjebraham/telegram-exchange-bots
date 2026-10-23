import { useEffect, useState } from 'react';

const API_URL = import.meta.env.VITE_API_URL || '/api';
const digits = (value: string) => value
  .replace(/[۰-۹]/g, (c) => String(c.charCodeAt(0) - 1776))
  .replace(/[٠-٩]/g, (c) => String(c.charCodeAt(0) - 1632));
const normalizePhone = (value: string) => {
  let phone = digits(value).replace(/[\s+()-]/g, '');
  if (phone.startsWith('0098')) phone = `0${phone.slice(4)}`;
  else if (phone.startsWith('98')) phone = `0${phone.slice(2)}`;
  return phone;
};

async function request(path: string, body?: Record<string, string>) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    return { response, data };
  } finally {
    window.clearTimeout(timer);
  }
}

export default function SmsPasswordReset({ initialPhone, onBack, onComplete }: {
  initialPhone: string;
  onBack: () => void;
  onComplete: (phone: string) => void;
}) {
  const [phone, setPhone] = useState(initialPhone);
  const [challenge, setChallenge] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState<boolean | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [expiresAt, setExpiresAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const remaining = Math.max(0, Math.ceil((expiresAt - now) / 1000));
  const cooldown = Math.max(0, Math.ceil((retryAt - now) / 1000));

  useEffect(() => {
    let mounted = true;
    void request('/users/password-reset/options').then(({ response, data }) => {
      if (mounted) setReady(response.ok && data.sms_enabled === true);
    }).catch(() => { if (mounted) setReady(false); });
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { mounted = false; window.clearInterval(timer); };
  }, []);

  const send = async () => {
    if (busy || cooldown || !ready) return;
    const normalized = normalizePhone(phone);
    if (!/^09\d{9}$/.test(normalized)) {
      setError('شماره موبایل معتبر وارد کنید؛ مانند ۰۹۱۲۳۴۵۶۷۸۹.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const { response, data } = await request('/users/password-reset/start', {
        phone_number: normalized, channel: 'sms',
      });
      if (response.status === 429) {
        const wait = Math.max(1, Number(response.headers.get('Retry-After')) || 60);
        setRetryAt(Date.now() + wait * 1000);
        setError('تعداد درخواست‌ها زیاد است. پس از پایان زمان انتظار دوباره تلاش کنید.');
      } else if (!response.ok || data.status !== 'accepted' || !/^[a-f0-9]{32}$/.test(data.challenge_id ?? '')) {
        setError(response.status === 400 ? 'شماره موبایل معتبر نیست.' : 'درخواست بازیابی انجام نشد؛ کمی بعد دوباره تلاش کنید.');
      } else {
        setPhone(normalized);
        setChallenge(data.challenge_id);
        setCode('');
        setExpiresAt(Date.now() + Number(data.expires_in) * 1000);
        setRetryAt(Date.now() + Number(data.retry_after) * 1000);
        setNow(Date.now());
      }
    } catch {
      setError('ارتباط با سرور برقرار نشد. اتصال اینترنت را بررسی و دوباره تلاش کنید.');
    } finally { setBusy(false); }
  };

  const complete = async () => {
    if (busy || !remaining) return;
    if (!/^\d{6}$/.test(code)) { setError('کد شش‌رقمی پیامک را وارد کنید.'); return; }
    if (password.length < 8 || password.length > 128) { setError('رمز جدید باید بین ۸ تا ۱۲۸ کاراکتر باشد.'); return; }
    if (password !== confirmation) { setError('تکرار رمز عبور یکسان نیست.'); return; }
    setBusy(true);
    setError('');
    try {
      const { response, data } = await request('/users/password-reset/complete', {
        phone_number: phone, challenge_id: challenge, code, new_password: password,
      });
      if (response.ok && data.status === 'success') {
        setPassword(''); setConfirmation(''); setCode(''); setSuccess(true);
      } else if (data.detail === 'password_length') {
        setError('رمز جدید باید بین ۸ تا ۱۲۸ کاراکتر باشد.');
      } else {
        setError('کد نامعتبر، منقضی یا غیرقابل استفاده است. کد جدید درخواست کنید.');
      }
    } catch {
      setError('ارتباط با سرور برقرار نشد. دوباره تلاش کنید.');
    } finally { setBusy(false); }
  };

  const input = 'w-full px-4 py-3 border-2 border-gray-200 rounded-xl focus:border-blue-500 focus:outline-none';
  return (
    <div className="p-4" dir="rtl">
      <section className="bg-white rounded-2xl p-6 shadow-lg max-w-md mx-auto space-y-4" aria-busy={busy}>
        <h2 className="text-2xl font-bold text-gray-800 text-center">بازیابی رمز با پیامک</h2>
        {success ? <>
          <p className="text-green-700" role="status">رمز عبور با موفقیت تغییر کرد. با رمز جدید وارد شوید.</p>
          <button type="button" onClick={() => onComplete(phone)} className="w-full bg-emerald-600 text-white rounded-xl p-3">بازگشت به ورود</button>
        </> : <>
          <label className="block text-sm font-medium text-gray-700" htmlFor="sms-reset-phone">شماره موبایل حساب</label>
          <input id="sms-reset-phone" type="tel" inputMode="tel" autoComplete="tel-national"
            className={input} value={phone} disabled={busy || Boolean(challenge)} maxLength={16}
            onChange={(e) => setPhone(digits(e.target.value))} placeholder="09123456789" dir="ltr" />
          {ready === false && <p className="text-red-600 text-sm" role="alert">بازیابی پیامکی موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید یا از بازیابی در ربات استفاده کنید.</p>}
          {ready === null && <p className="text-sm text-gray-500" role="status">در حال اتصال به سرویس بازیابی…</p>}
          {!challenge ? <button type="button" onClick={() => void send()} disabled={busy || !ready || cooldown > 0}
            className="w-full bg-indigo-600 text-white rounded-xl p-3 disabled:opacity-50">
            {busy ? 'در حال ثبت درخواست…' : cooldown ? `تلاش دوباره در ${cooldown} ثانیه` : 'ارسال کد بازیابی'}
          </button> : <>
            <p className="text-sm text-gray-600" role="status">اگر با این شماره حسابی داشته باشید، کد بازیابی برایتان پیامک می‌شود.</p>
            <label className="block text-sm font-medium text-gray-700" htmlFor="sms-reset-code">کد شش‌رقمی</label>
            <input id="sms-reset-code" className={input} inputMode="numeric" autoComplete="one-time-code"
              value={code} maxLength={6} dir="ltr" disabled={busy}
              onChange={(e) => setCode(digits(e.target.value).replace(/\D/g, '').slice(0, 6))} />
            <p className="text-xs text-gray-500">{remaining ? `اعتبار کد: ${Math.floor(remaining / 60)} دقیقه و ${remaining % 60} ثانیه` : 'اعتبار کد تمام شد؛ کد جدید درخواست کنید.'}</p>
            <label className="block text-sm font-medium text-gray-700" htmlFor="sms-reset-password">رمز عبور جدید</label>
            <input id="sms-reset-password" className={input} type="password" autoComplete="new-password"
              value={password} minLength={8} maxLength={128} disabled={busy} onChange={(e) => setPassword(e.target.value)} />
            <label className="block text-sm font-medium text-gray-700" htmlFor="sms-reset-confirmation">تکرار رمز جدید</label>
            <input id="sms-reset-confirmation" className={input} type="password" autoComplete="new-password"
              value={confirmation} maxLength={128} disabled={busy} onChange={(e) => setConfirmation(e.target.value)} />
            <button type="button" onClick={() => void complete()} disabled={busy || !remaining}
              className="w-full bg-emerald-600 text-white rounded-xl p-3 disabled:opacity-50">{busy ? 'در حال بررسی…' : 'ذخیره رمز جدید'}</button>
            <button type="button" onClick={() => void send()} disabled={busy || cooldown > 0 || !ready}
              className="w-full text-blue-600 py-2 disabled:text-gray-400">{cooldown ? `ارسال دوباره در ${cooldown} ثانیه` : 'ارسال دوباره کد'}</button>
          </>}
          {error && <p className="bg-red-50 border border-red-200 rounded-xl p-3 text-red-600 text-sm" role="alert">{error}</p>}
          <button type="button" onClick={onBack} disabled={busy} className="w-full text-gray-600 py-2">بازگشت به ورود</button>
        </>}
      </section>
    </div>
  );
}
