import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import KycGate from './KycGate'
import './index.css'
import './daylight.css'
import './daylight-shell.css'
import './daylight-phase2.css'
import './daylight-phase2-auth.css'
import './daylight-phase3.css'
import './daylight-phase3-fixes.css'
import './market-theme.css'

const telegramWebApp = (window as any)?.Telegram?.WebApp
telegramWebApp?.ready?.()
telegramWebApp?.expand?.()

const rootElement = document.getElementById('root')!
rootElement.setAttribute('dir', 'rtl')
rootElement.setAttribute('lang', 'fa')
if (!window.location.hostname.includes('kianiapp')) {
  rootElement.setAttribute('data-ke', '')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
    <KycGate />
  </React.StrictMode>,
)
