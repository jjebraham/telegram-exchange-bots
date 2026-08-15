import { useEffect, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api'

function cleanLabel(value: string) {
  return value.replace(/\s+/g, ' ').trim().slice(0, 220)
}

export default function UserActivityReporter() {
  const lastEvent = useRef('')
  const lastSentAt = useRef(0)

  useEffect(() => {
    if (typeof window === 'undefined' || window.location.hostname.includes('kianiapp')) return

    const report = (action: string, label: string) => {
      const token = localStorage.getItem('token') || localStorage.getItem('auth_token') || ''
      if (!token) return

      const normalizedLabel = cleanLabel(label || '-')
      const fingerprint = `${action}|${normalizedLabel}`
      const now = Date.now()
      if (fingerprint === lastEvent.current && now - lastSentAt.current < 1200) return
      lastEvent.current = fingerprint
      lastSentAt.current = now

      void fetch(`${API_BASE}/user/activity`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          action,
          label: normalizedLabel,
          path: window.location.pathname,
        }),
        keepalive: true,
      }).catch(() => undefined)
    }

    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      const interactive = target?.closest('button, a, [role="button"]') as HTMLElement | null
      if (!interactive) return
      report('click', interactive.innerText || interactive.getAttribute('aria-label') || interactive.getAttribute('title') || interactive.tagName)
    }

    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [])

  return null
}
