import React, { useEffect, useRef, useState } from 'react'
import KycFlow from './KycFlow'

const API_BASE = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api'

export default function KycGate() {
  const [visible, setVisible] = useState(false)
  const [open, setOpen] = useState(false)
  const [level, setLevel] = useState<number | null>(null)
  const previousToken = useRef('')

  useEffect(() => {
    if (typeof window === 'undefined' || window.location.hostname.includes('kianiapp')) return

    let cancelled = false

    const check = async () => {
      const token = localStorage.getItem('token') || localStorage.getItem('auth_token') || ''
      if (!token) {
        previousToken.current = ''
        if (!cancelled) {
          setVisible(false)
          setOpen(false)
          setLevel(null)
        }
        return
      }

      try {
        const response = await fetch(`${API_BASE}/kyc/status`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!response.ok) return
        const data = await response.json()
        const nextLevel = Number(data?.verification_level || 1)
        if (cancelled) return

        setLevel(nextLevel)
        setVisible(nextLevel < 3)

        // When a user has just logged in and is only Level 1, immediately show
        // the next KYC step once so the Level-1 success is obvious.
        if (previousToken.current !== token && nextLevel === 1) {
          setOpen(true)
        }
        previousToken.current = token
      } catch (error) {
        console.error('KYC gate status check failed', error)
      }
    }

    void check()
    const timer = window.setInterval(() => void check(), 2500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  if (!visible) return null

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-24 left-4 z-[70] rounded-full bg-emerald-600 px-4 py-3 text-sm font-bold text-white shadow-xl"
      >
        احراز هویت — سطح {level || 1}
      </button>

      {open && (
        <div className="fixed inset-0 z-[80] overflow-y-auto bg-black/60 p-4" dir="rtl">
          <div className="mx-auto mt-6 max-w-2xl">
            <div className="mb-2 flex justify-end">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-lg bg-white px-4 py-2 font-bold text-gray-800 shadow"
              >
                بستن
              </button>
            </div>
            <KycFlow />
          </div>
        </div>
      )}
    </>
  )
}
