import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import KycGate from './KycGate'
import AdminKycReview from './AdminKycReview'
import SecureAdminPanel from './SecureAdminPanel'
import './index.css'

const rootElement = document.getElementById('root')!
const root = ReactDOM.createRoot(rootElement)
const isAdminHost = typeof window !== 'undefined' && window.location.hostname.includes('kianiapp')

// Telegram's WebApp object may exist when this site is opened in a normal
// browser even though native Telegram popup methods are not actually usable.
const hardenTelegramBrowserFallback = () => {
  const tg = (window as any)?.Telegram?.WebApp

  if (!tg || typeof tg.showPopup !== 'function') return

  const originalShowPopup = tg.showPopup.bind(tg)

  tg.showPopup = (
    params: any,
    callback?: (buttonId?: string) => void,
  ) => {
    const insideTelegram = Boolean(tg.initData)

    if (!insideTelegram) {
      window.alert(String(params?.message || ''))
      callback?.('ok')
      return
    }

    try {
      originalShowPopup(params, callback)
    } catch (error) {
      console.warn('Telegram popup unavailable; using browser alert:', error)
      window.alert(String(params?.message || ''))
      callback?.('ok')
    }
  }
}

hardenTelegramBrowserFallback()

const renderApp = () => {
  root.render(
    <React.StrictMode>
      <ErrorBoundary>
        {isAdminHost ? (
          <>
            <SecureAdminPanel />
            <AdminKycReview />
          </>
        ) : (
          <>
            <App />
            <KycGate />
          </>
        )}
      </ErrorBoundary>
    </React.StrictMode>,
  )
}

window.addEventListener('error', (event) => {
  // Browser extensions, wallet providers and Telegram's browser shim can
  // generate global errors that are unrelated to the React application.
  console.error('Global runtime error:', event.error || event.message)
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled promise rejection:', event.reason)
})

renderApp()
