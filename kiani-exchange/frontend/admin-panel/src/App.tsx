import { useEffect, useState } from 'react'
import axios from 'axios'

interface Faq {
  id: number
  question: string
  answer: string
}

function App() {
  const [faqs, setFaqs] = useState<Faq[]>([])
  const [faqError, setFaqError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios
      .get<Faq[]>('/api/faqs')
      .then((res) => {
        setFaqs(res.data)
        setFaqError(null)
      })
      .catch((err) => {
        setFaqError(err.message || 'Failed to load FAQs')
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Sidebar placeholder + header */}
      <header className="bg-white shadow-sm border-b border-gray-200 px-6 py-4">
        <div className="mx-auto max-w-7xl flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">
            پنل مدیریت - صرافی کیانی
          </h1>
          <span className="text-sm text-gray-500">Admin Panel</span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {/* Stats cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <div className="bg-white rounded-lg shadow-sm p-5">
            <p className="text-sm text-gray-500">کاربران</p>
            <p className="mt-1 text-2xl font-bold text-gray-900">—</p>
          </div>
          <div className="bg-white rounded-lg shadow-sm p-5">
            <p className="text-sm text-gray-500">در انتظار تایید KYC</p>
            <p className="mt-1 text-2xl font-bold text-yellow-600">—</p>
          </div>
          <div className="bg-white rounded-lg shadow-sm p-5">
            <p className="text-sm text-gray-500">تراکنش‌های امروز</p>
            <p className="mt-1 text-2xl font-bold text-green-600">—</p>
          </div>
          <div className="bg-white rounded-lg shadow-sm p-5">
            <p className="text-sm text-gray-500">وضعیت API</p>
            <p className="mt-1 text-2xl font-bold text-blue-600">فعال</p>
          </div>
        </div>

        {/* FAQs section - verifies API connectivity */}
        <section className="bg-white rounded-lg shadow-sm p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">
            سوالات متداول (تست API)
          </h2>
          {loading ? (
            <div className="flex justify-center py-4">
              <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : faqError ? (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-red-700 text-sm">
                خطا در اتصال به API: {faqError}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-right py-2 px-3 text-gray-600 font-medium">
                      #
                    </th>
                    <th className="text-right py-2 px-3 text-gray-600 font-medium">
                      سوال
                    </th>
                    <th className="text-right py-2 px-3 text-gray-600 font-medium">
                      پاسخ
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {faqs.map((faq) => (
                    <tr
                      key={faq.id}
                      className="border-b border-gray-100 hover:bg-gray-50"
                    >
                      <td className="py-2 px-3 text-gray-500">{faq.id}</td>
                      <td className="py-2 px-3 text-gray-800">{faq.question}</td>
                      <td className="py-2 px-3 text-gray-600">{faq.answer}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {faqs.length === 0 && (
                <p className="text-center py-4 text-gray-500">
                  هیچ سوالی یافت نشد.
                </p>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
