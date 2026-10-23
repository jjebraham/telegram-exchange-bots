export type ProgressStep = {
  label: string
  state: 'done' | 'active' | 'pending' | 'error'
}

type BlockingProgressModalProps = {
  open: boolean
  title: string
  description?: string
  progress: number
  status?: 'working' | 'success' | 'error'
  message?: string
  steps?: ProgressStep[]
  closeLabel?: string
  onClose?: () => void
}

export default function BlockingProgressModal({
  open,
  title,
  description,
  progress,
  status = 'working',
  message,
  steps = [],
  closeLabel = 'بستن',
  onClose,
}: BlockingProgressModalProps) {
  if (!open) return null

  const safeProgress = Math.max(0, Math.min(100, Math.round(progress)))
  const working = status === 'working'

  return (
    <div
      className="fixed inset-0 z-[160] flex items-center justify-center bg-slate-950/70 p-3 backdrop-blur-sm sm:p-6"
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-busy={working}
    >
      <div className="max-h-[calc(100dvh-1.5rem)] w-full max-w-lg overflow-y-auto rounded-3xl bg-white p-5 shadow-2xl sm:p-7">
        <div className="text-center">
          <div
            className={`mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-full ${
              status === 'success'
                ? 'bg-emerald-100 text-emerald-700'
                : status === 'error'
                  ? 'bg-red-100 text-red-700'
                  : 'bg-blue-100 text-blue-700'
            }`}
          >
            {status === 'success' ? (
              <span className="text-4xl">✓</span>
            ) : status === 'error' ? (
              <span className="text-4xl">!</span>
            ) : (
              <div className="h-9 w-9 animate-spin rounded-full border-4 border-blue-200 border-t-blue-700" />
            )}
          </div>

          <h2 className="text-xl font-black text-gray-900 sm:text-2xl">
            {title}
          </h2>

          {description && (
            <p className="mt-2 text-sm leading-6 text-gray-600">
              {description}
            </p>
          )}
        </div>

        <div className="mt-6">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="font-bold text-gray-700">
              {working ? 'در حال انجام...' : status === 'success' ? 'تکمیل شد' : 'ناموفق'}
            </span>
            <span className="font-black tabular-nums text-blue-700" dir="ltr">
              {safeProgress}%
            </span>
          </div>

          <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200">
            <div
              className={`h-full rounded-full transition-[width] duration-300 ${
                status === 'error'
                  ? 'bg-red-500'
                  : status === 'success'
                    ? 'bg-emerald-500'
                    : 'bg-blue-600'
              }`}
              style={{ width: `${safeProgress}%` }}
            />
          </div>
        </div>

        {steps.length > 0 && (
          <div className="mt-6 space-y-2">
            {steps.map((step, index) => (
              <div
                key={`${step.label}-${index}`}
                className={`flex items-center gap-3 rounded-xl border p-3 text-sm ${
                  step.state === 'done'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                    : step.state === 'active'
                      ? 'border-blue-200 bg-blue-50 text-blue-900'
                      : step.state === 'error'
                        ? 'border-red-200 bg-red-50 text-red-900'
                        : 'border-gray-200 bg-gray-50 text-gray-500'
                }`}
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white font-black shadow-sm">
                  {step.state === 'done'
                    ? '✓'
                    : step.state === 'error'
                      ? '!'
                      : step.state === 'active'
                        ? '●'
                        : index + 1}
                </span>
                <span className="font-medium">{step.label}</span>
              </div>
            ))}
          </div>
        )}

        {message && (
          <div
            className={`mt-5 rounded-2xl p-4 text-sm leading-6 ${
              status === 'error'
                ? 'bg-red-50 text-red-800'
                : status === 'success'
                  ? 'bg-emerald-50 text-emerald-900'
                  : 'bg-blue-50 text-blue-900'
            }`}
          >
            {message}
          </div>
        )}

        {working && (
          <div className="mt-5 rounded-xl bg-amber-50 p-3 text-center text-sm font-medium leading-6 text-amber-900">
            لطفاً این صفحه را نبندید و تا پایان عملیات منتظر بمانید.
          </div>
        )}

        {!working && onClose && (
          <button
            type="button"
            onClick={onClose}
            className={`mt-6 min-h-12 w-full rounded-xl px-4 py-3 font-bold text-white ${
              status === 'error'
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-emerald-600 hover:bg-emerald-700'
            }`}
          >
            {closeLabel}
          </button>
        )}
      </div>
    </div>
  )
}
