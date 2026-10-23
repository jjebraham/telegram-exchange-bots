import type { SVGProps } from 'react'

const icon = (path: string) => (props: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    <path d={path} />
  </svg>
)

export const Activity = icon('M2 12h5l3-8 4 16 3-8h5')
export const ArrowLeftRight = icon('M3 7h17m-5-4 5 4-5 4M21 17H4m5-4-5 4 5 4')
export const BarChart3 = icon('M4 3v17h17M9 16v-5m5 5V7m5 9V4')
export const CheckCircle = icon('M21 12a9 9 0 1 1-4-7.5M8 11l4 4 9-10')
export const LogOut = icon('M10 4H4v16h6m5-12 5 4-5 4M8 12h12')
export const MessageSquare = icon('M4 4h16v12H9l-5 4V4zM8 8h8m-8 4h6')
export const RefreshCw = icon('M20 8a8 8 0 0 0-14-2L3 9m0-5v5h5m-4 7a8 8 0 0 0 14 2l3-3m0 5v-5h-5')
export const Shield = icon('m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3z')
export const TrendingUp = icon('m3 17 6-6 4 4 8-10m-6 0h6v6')
export const Users = icon('M15 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0M5 21v-3a7 7 0 0 1 14 0v3M3 7a3 3 0 0 1 3-3m15 3a3 3 0 0 0-3-3')
export const XCircle = icon('M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M9 9l6 6m0-6-6 6')
