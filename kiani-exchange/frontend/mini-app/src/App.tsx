import { useEffect, useState } from 'react'
import axios from 'axios'

interface TelegramWebApp {
  ready: () => void
  expand: () => void
  initDataUnsafe: {
    user?: {
      id: number
      first_name: string
      last_name?: string
      username?: string
      language_code?: string
    }
  }
  colorScheme: 'light' | 'dark'
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp }
  }
}

interface Faq {
  id: number
  question: string
  answer: string
}

function App() {
  const [user, setUser] = useState<TelegramWebApp['initDataUnsafe']['user'] | null>(null)
  const [faqs, setFaqs] = useState<Faq[]>([])
  const [faqError, setFaqError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedFaq, setExpandedFaq] = useState<number | null>(null)

  useEffect(() => {
    const tg = window.Telegram?.WebApp
    if (tg) {
      tg.ready()
      tg.expand()
      if (tg.initDataUnsafe?.user) {
        setUser(tg.initDataUnsafe.user)
      }
    }

    axios
      .get<{faqs: Faq[]}>('/api/faqs')
      .then((res) => {
        setFaqs(res.data.faqs)
        setFaqError(null)
      })
      .catch((err) => {
        setFaqError(err.message || 'Failed to load FAQs')
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-blue-600 text-white px-4 py-5 shadow-md">
        <div className="mx-auto max-w-md">
          <h1 className="text-xl font-bold">Kiani Exchange</h1>
          <p className="mt-1 text-sm text-blue-100">صرافی کیانی</p>
        </div>
      </header>

      <main className="mx-auto max-w-md px-4 py-6 space-y-6">
        {/* User Card */}
        <section className="bg-white rounded-xl shadow-sm p-4">
          <h2 className="text-lg font-semibold text-gray-800 mb-2">
            خوش آمدید
          </h2>
          {user ? (
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 bg-blue-100 text-blue-600 rounded-full font-bold text-lg">
                {user.first_name.charAt(0)}
              </div>
              <div>
                <p className="text-gray-900 font-medium">
                  {user.first_name} {user.last_name || ''}
                </p>
                {user.username && (
                  <p className="text-sm text-gray-500">@{user.username}</p>
                )}
              </div>
            </div>
          ) : (
            <p className="text-gray-500 text-sm">
              برای استفاده کامل، از طریق تلگرام وارد شوید.
            </p>
          )}
        </section>

        {/* Quick Actions */}
        <section className="grid grid-cols-2 gap-3">
          <div className="bg-white rounded-xl shadow-sm p-4 text-center">
            <div className="text-2xl mb-1">💱</div>
            <p className="text-sm font-medium text-gray-700">نرخ ارز</p>
          </div>
          <div className="bg-white rounded-xl shadow-sm p-4 text-center">
            <div className="text-2xl mb-1">📋</div>
            <p className="text-sm font-medium text-gray-700">سوالات متداول</p>
          </div>
          <div className="bg-white rounded-xl shadow-sm p-4 text-center">
            <div className="text-2xl mb-1">💳</div>
            <p className="text-sm font-medium text-gray-700">کارت‌های بانکی</p>
          </div>
          <div className="bg-white rounded-xl shadow-sm p-4 text-center">
            <div className="text-2xl mb-1">📞</div>
            <p className="text-sm font-medium text-gray-700">تماس با ما</p>
          </div>
        </section>

        {/* FAQs */}
        <section className="bg-white rounded-xl shadow-sm p-4">
          <h2 className="text-lg font-semibold text-gray-800 mb-3">
            سوالات متداول
          </h2>
          {loading ? (
            <div className="flex justify-center py-4">
              <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : faqError ? (
            <p className="text-red-500 text-sm">{faqError}</p>
          ) : faqs.length === 0 ? (
            <p className="text-gray-500 text-sm">هیچ سوالی یافت نشد.</p>
          ) : (
            <div className="space-y-2">
              {faqs.map((faq) => (
                <div key={faq.id} className="border border-gray-100 rounded-lg">
                  <button
                    className="w-full text-right px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    onClick={() =>
                      setExpandedFaq(expandedFaq === faq.id ? null : faq.id)
                    }
                  >
                    {faq.question}
                  </button>
                  {expandedFaq === faq.id && (
                    <p className="px-3 pb-2 text-sm text-gray-600">
                      {faq.answer}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
