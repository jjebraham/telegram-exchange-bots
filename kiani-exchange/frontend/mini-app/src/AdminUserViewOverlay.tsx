import { useEffect, useState } from 'react'

type UserRowDetails = {
  id: string
  name: string
  nationalId: string
  dob: string
  card: string
  phone: string
  status: string
}

function cellText(cells: HTMLTableCellElement[], index: number): string {
  return (cells[index]?.innerText || '').trim() || '-'
}

export default function AdminUserViewOverlay() {
  const isAdminHost = typeof window !== 'undefined' && window.location.hostname.includes('kianiapp')
  const [selectedUser, setSelectedUser] = useState<UserRowDetails | null>(null)

  useEffect(() => {
    if (!isAdminHost) return

    const handleClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      const button = target?.closest('button') as HTMLButtonElement | null
      if (!button || button.textContent?.trim() !== 'View') return

      const row = button.closest('tr')
      if (!row) return

      const cells = Array.from(row.querySelectorAll('td')) as HTMLTableCellElement[]
      if (cells.length < 8) return

      // The User Management table currently renders columns in this order:
      // ID, Name, National ID, DOB, Card, Phone, Status, Actions.
      setSelectedUser({
        id: cellText(cells, 0),
        name: cellText(cells, 1),
        nationalId: cellText(cells, 2),
        dob: cellText(cells, 3),
        card: cellText(cells, 4),
        phone: cellText(cells, 5),
        status: cellText(cells, 6),
      })
    }

    document.addEventListener('click', handleClick, true)
    return () => document.removeEventListener('click', handleClick, true)
  }, [isAdminHost])

  useEffect(() => {
    if (!selectedUser) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedUser(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedUser])

  if (!isAdminHost || !selectedUser) return null

  const details = [
    ['ID', selectedUser.id],
    ['Name', selectedUser.name],
    ['National ID', selectedUser.nationalId],
    ['Date of Birth', selectedUser.dob],
    ['Bank Card', selectedUser.card],
    ['Phone', selectedUser.phone],
    ['KYC Status', selectedUser.status],
  ]

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="User details"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) setSelectedUser(null)
      }}
    >
      <div className="w-full max-w-xl rounded-2xl border border-gray-700 bg-gray-900 p-5 text-white shadow-2xl">
        <div className="mb-5 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold">User Details</h2>
            <p className="mt-1 text-sm text-gray-400">{selectedUser.name}</p>
          </div>
          <button
            type="button"
            onClick={() => setSelectedUser(null)}
            className="rounded-lg border border-gray-600 bg-gray-800 px-4 py-2 text-sm text-gray-200 hover:bg-gray-700"
          >
            Close
          </button>
        </div>

        <div className="overflow-hidden rounded-xl border border-gray-700/70">
          {details.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[140px_1fr] gap-3 border-b border-gray-700/60 px-4 py-3 last:border-b-0">
              <div className="text-sm font-medium text-gray-400">{label}</div>
              <div className="break-all text-sm font-semibold text-gray-100" dir={label === 'Name' ? 'auto' : 'ltr'}>
                {value}
              </div>
            </div>
          ))}
        </div>

        <p className="mt-4 text-xs leading-5 text-gray-500">
          Level 2 is complete only after the user's Level 2 KYC submission is approved by an admin.
        </p>
      </div>
    </div>
  )
}
