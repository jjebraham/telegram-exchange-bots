import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

const telegramWebApp = (window as any)?.Telegram?.WebApp
telegramWebApp?.ready?.()
telegramWebApp?.expand?.()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
