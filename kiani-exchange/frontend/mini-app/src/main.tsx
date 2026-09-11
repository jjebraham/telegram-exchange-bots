import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './ErrorBoundary'
import KycGate from './KycGate'
import AdminKycReview from './AdminKycReview'
import SecureAdminPanel from './SecureAdminPanel'
import './index.css'
import './daylight.css'
import './daylight-shell.css'
import './daylight-phase2.css'
import './daylight-phase2-auth.css'
import './daylight-phase3.css'

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

const telegramWebApp = (window as any)?.Telegram?.WebApp

const applyCustomerScheme = (scheme: 'light' | 'dark') => {
  if (isAdminHost) return

  const background = scheme === 'dark' ? '#0F171C' : '#F4F6F7'

  rootElement.dataset.scheme = scheme
  document.documentElement.style.backgroundColor = background
  document.body.style.backgroundColor = background

  telegramWebApp?.setHeaderColor?.(background)
  telegramWebApp?.setBackgroundColor?.(background)
}

const syncCustomerViewport = () => {
  if (isAdminHost) return

  const viewportHeight = window.visualViewport?.height || window.innerHeight
  rootElement.style.setProperty('--ke-viewport-height', `${Math.round(viewportHeight)}px`)
}

const initializeCustomerViewport = () => {
  if (isAdminHost) return

  syncCustomerViewport()
  window.addEventListener('resize', syncCustomerViewport, { passive: true })
  window.visualViewport?.addEventListener('resize', syncCustomerViewport, { passive: true })
  window.visualViewport?.addEventListener('scroll', syncCustomerViewport, { passive: true })
}

const initializeCustomerChrome = () => {
  if (isAdminHost) return

  rootElement.setAttribute('data-ke', '')
  rootElement.setAttribute('dir', 'rtl')
  rootElement.setAttribute('lang', 'fa')

  if (telegramWebApp) {
    telegramWebApp.ready?.()
    telegramWebApp.expand?.()

    const syncTelegramScheme = () => {
      applyCustomerScheme(
        telegramWebApp.colorScheme === 'dark' ? 'dark' : 'light',
      )
    }

    syncTelegramScheme()
    telegramWebApp.onEvent?.('themeChanged', syncTelegramScheme)
    return
  }

  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const syncBrowserScheme = () => {
    applyCustomerScheme(media.matches ? 'dark' : 'light')
  }

  syncBrowserScheme()
  media.addEventListener?.('change', syncBrowserScheme)
}

initializeCustomerChrome()
initializeCustomerViewport()

// Keep the existing Telegram lifecycle calls for compatibility with clients
// where the customer theme wrapper is not active (for example the admin host).
telegramWebApp?.ready?.()
telegramWebApp?.expand?.()

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
