import React, { useEffect, useRef, useState } from 'react'
import KycFlow from './KycFlow'

const API_BASE = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api'

export default function KycGate() {
  const [visible, setVisible] = useState(false)
  const [open, setOpen] = useState(false)
  const [level, setLevel] = useState<number | null>(null)
  const previousToken = useRef('')
  const previousLevel = useRef<number | null>(null)
  const previousLevel2Status = useRef<string | null>(null)
  const previousLevel3Status = useRef<string | null>(null)

  useEffect(() => {
    if (typeof window === 'undefined' || window.location.hostname.includes('kianiapp')) return

    let cancelled = false

    const check = async () => {
      const token = localStorage.getItem('token') || localStorage.getItem('auth_token') || ''
      if (!token) {
        previousToken.current = ''
        previousLevel.current = null
        previousLevel2Status.current = null
        previousLevel3Status.current = null
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
        const level2Status = data?.level2?.status || null
        const level3Status = data?.level3?.status || null
        if (cancelled) return

        setLevel(nextLevel)
        setVisible(nextLevel < 3)

        // A fresh Level-1 login immediately continues into the KYC flow.
        if (previousToken.current !== token && nextLevel === 1) {
          setOpen(true)
        }

        // Re-open the KYC panel when an admin decision changes what the user
        // needs to do next (approved => next level, rejected => re-upload).
        if (previousLevel.current !== null && nextLevel > previousLevel.current) {
          setOpen(true)
        }
        if (previousLevel2Status.current === 'pending' && level2Status === 'rejected') {
          setOpen(true)
        }
        if (previousLevel3Status.current === 'pending' && level3Status === 'rejected') {
          setOpen(true)
        }

        previousToken.current = token
        previousLevel.current = nextLevel
        previousLevel2Status.current = level2Status
        previousLevel3Status.current = level3Status
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
