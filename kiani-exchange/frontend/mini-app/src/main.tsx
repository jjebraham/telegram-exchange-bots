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
import './daylight-phase3-fixes.css'

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

type CustomerThemePreference = 'system' | 'light' | 'dark'
type CustomerScheme = 'light' | 'dark'

const THEME_PREFERENCE_KEY = 'kiani_theme_preference'

const getThemePreference = (): CustomerThemePreference => {
  const stored = localStorage.getItem(THEME_PREFERENCE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

const getSystemScheme = (): CustomerScheme => {
  // Preserve the previous Telegram-first behavior when the Mini App is actually
  // running inside Telegram. In a normal browser, respect OS/browser theme.
  if (telegramWebApp?.initData) {
    return telegramWebApp.colorScheme === 'dark' ? 'dark' : 'light'
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

const applyCustomerScheme = (
  scheme: CustomerScheme,
  preference: CustomerThemePreference = getThemePreference(),
) => {
  if (isAdminHost) return

  const background = scheme === 'dark' ? '#0F171C' : '#F4F6F7'

  rootElement.dataset.scheme = scheme
  rootElement.dataset.themePreference = preference
  document.documentElement.style.backgroundColor = background
  document.body.style.backgroundColor = background

  telegramWebApp?.setHeaderColor?.(background)
  telegramWebApp?.setBackgroundColor?.(background)

  window.dispatchEvent(
    new CustomEvent('kiani-theme-applied', {
      detail: { scheme, preference },
    }),
  )
}

const applyCustomerTheme = () => {
  const preference = getThemePreference()
  const scheme = preference === 'system' ? getSystemScheme() : preference
  applyCustomerScheme(scheme, preference)
}

const setCustomerThemePreference = (preference: CustomerThemePreference) => {
  if (preference === 'system') {
    localStorage.removeItem(THEME_PREFERENCE_KEY)
  } else {
    localStorage.setItem(THEME_PREFERENCE_KEY, preference)
  }

  applyCustomerTheme()
}

window.addEventListener('kiani-theme-preference-change', (event: Event) => {
  if (isAdminHost) return

  const detail = (event as CustomEvent<{ preference?: CustomerThemePreference }>).detail
  const preference = detail?.preference

  if (preference === 'system' || preference === 'light' || preference === 'dark') {
    setCustomerThemePreference(preference)
  }
})

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

  telegramWebApp?.ready?.()
  telegramWebApp?.expand?.()

  applyCustomerTheme()

  // System changes only update the UI while the user has not manually chosen
  // light or dark. A manual choice stays persisted across visits.
  const syncSystemTheme = () => {
    if (getThemePreference() === 'system') {
      applyCustomerTheme()
    }
  }

  telegramWebApp?.onEvent?.('themeChanged', syncSystemTheme)

  const media = window.matchMedia('(prefers-color-scheme: dark)')
  media.addEventListener?.('change', syncSystemTheme)
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
