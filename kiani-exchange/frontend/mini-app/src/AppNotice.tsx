import { useEffect, useState } from 'react';

type Notice = { title: string; message: string };
const NOTICE_EVENT = 'kiani:notice';

export const notifyMessage = (message: string, title = 'KIANI Exchange') => {
  try {
    const telegram = (window as any)?.Telegram?.WebApp;
    if (typeof telegram?.initData === 'string' && telegram.initData.length > 0 &&
        typeof telegram.isVersionAtLeast === 'function' && telegram.isVersionAtLeast('6.2') &&
        typeof telegram.showPopup === 'function') {
      telegram.showPopup({ title, message, buttons: [{ type: 'ok', text: 'باشه' }] });
      return;
    }
  } catch {
    // Notification support must never change the result of a completed action.
  }
  window.dispatchEvent(new CustomEvent<Notice>(NOTICE_EVENT, { detail: { title, message } }));
};

export default function AppNotice() {
  const [notices, setNotices] = useState<Notice[]>([]);
  useEffect(() => {
    const receive = (event: Event) => {
      const notice = (event as CustomEvent<Notice>).detail;
      if (typeof notice?.message === 'string' && typeof notice?.title === 'string') {
        setNotices((current) => [...current, notice]);
      }
    };
    window.addEventListener(NOTICE_EVENT, receive);
    return () => window.removeEventListener(NOTICE_EVENT, receive);
  }, []);
  if (!notices.length) return null;
  const notice = notices[0];
  const close = () => setNotices((current) => current.slice(1));
  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/50 p-4" dir="rtl">
      <section role="alertdialog" aria-modal="true" aria-labelledby="app-notice-title" aria-describedby="app-notice-message"
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" onKeyDown={(event) => { if (event.key === 'Escape') close(); }}>
        <h2 id="app-notice-title" className="mb-4 text-lg font-bold text-gray-800">{notice.title}</h2>
        <p id="app-notice-message" className="max-h-[60vh] overflow-y-auto whitespace-pre-line text-gray-700">{notice.message}</p>
        <button type="button" autoFocus onClick={close} className="mt-6 w-full rounded-xl bg-emerald-600 px-4 py-3 font-semibold text-white">باشه</button>
      </section>
    </div>
  );
}
