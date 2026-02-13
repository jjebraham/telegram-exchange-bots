import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import './index.css'

const rootElement = document.getElementById('root')!
const root = ReactDOM.createRoot(rootElement)

const renderFatalFallback = (message: string) => {
  rootElement.innerHTML = `
    <div style="min-height:100vh;background:#f3f4f6;display:flex;align-items:center;justify-content:center;padding:24px;font-family:system-ui,-apple-system,sans-serif;">
      <div style="max-width:480px;width:100%;background:#fff;border-radius:16px;padding:24px;box-shadow:0 10px 30px rgba(0,0,0,.08);text-align:center;">
        <h2 style="margin:0 0 12px 0;color:#111827;font-size:22px;font-weight:700;">KIANI Exchange</h2>
        <p style="margin:0 0 10px 0;color:#dc2626;font-size:14px;">خطا در بارگذاری برنامه</p>
        <p style="margin:0 0 16px 0;color:#6b7280;font-size:12px;word-break:break-word;" dir="ltr">${message}</p>
        <button onclick="window.location.reload()" style="background:#2563eb;color:#fff;border:none;border-radius:10px;padding:10px 16px;cursor:pointer;">بارگذاری مجدد</button>
      </div>
    </div>
  `
}

const renderApp = () => {
  root.render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  )
}

window.addEventListener('error', (event) => {
  console.error('Global runtime error:', event.error || event.message)
  renderFatalFallback(String(event.error?.message || event.message || 'runtime_error'))
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled promise rejection:', event.reason)
  const message = typeof event.reason === 'string'
    ? event.reason
    : (event.reason?.message || 'unhandled_rejection')
  renderFatalFallback(String(message))
})

renderApp()
