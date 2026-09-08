import {
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
} from 'react'

import BlockingProgressModal from './BlockingProgressModal'

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  '/api'

const MAX_FILE_BYTES = 10 * 1024 * 1024

const ACCEPTED_FILES =
  '.jpg,.jpeg,.png,.webp,.heic,.heif,.pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf'

const ACCEPTED_EXTENSIONS = new Set([
  'jpg',
  'jpeg',
  'png',
  'webp',
  'heic',
  'heif',
  'pdf',
])

type Submission = {
  id: number
  status: 'pending' | 'approved' | 'rejected'
  rejection_reason?: string | null
  created_at?: string
  updated_at?: string
  has_front?: boolean
  has_back?: boolean
  has_selfie?: boolean
}

type KycStatus = {
  verification_level: number
  level1: { status: 'approved' }
  level2: Submission | null
  level3: Submission | null
}

type UploadDialog = {
  open: boolean
  status: 'working' | 'success' | 'error'
  title: string
  description: string
  message: string
  progress: number
}

const initialDialog: UploadDialog = {
  open: false,
  status: 'working',
  title: '',
  description: '',
  message: '',
  progress: 0,
}

function authToken() {
  return (
    localStorage.getItem('token') ||
    localStorage.getItem('auth_token') ||
    ''
  )
}

function authHeaders(): Record<string, string> {
  const token = authToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function formatSize(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getExtension(file: File) {
  return file.name.split('.').pop()?.toLowerCase() || ''
}

function validateSelectedFile(file: File): string | null {
  if (file.size <= 0) {
    return 'فایل انتخاب‌شده خالی است.'
  }

  if (file.size > MAX_FILE_BYTES) {
    return 'حجم هر فایل باید حداکثر ۱۰ مگابایت باشد.'
  }

  if (!ACCEPTED_EXTENSIONS.has(getExtension(file))) {
    return 'فرمت فایل پشتیبانی نمی‌شود. JPG، PNG، WebP، HEIC، HEIF یا PDF انتخاب کنید.'
  }

  return null
}

function mapUploadError(detail: string, status?: number) {
  if (status === 413 || detail.includes('too_large')) {
    return 'حجم یکی از فایل‌ها بیشتر از ۱۰ مگابایت است.'
  }

  if (
    detail.includes('unsupported_file_type') ||
    detail.includes('must_be_jpeg')
  ) {
    return 'فرمت فایل پشتیبانی نمی‌شود. JPG، PNG، WebP، HEIC، HEIF یا PDF انتخاب کنید.'
  }

  if (detail.includes('is_empty')) {
    return 'یکی از فایل‌های انتخاب‌شده خالی است.'
  }

  if (detail.includes('front_and_back_must_be_different')) {
    return 'تصویر روی کارت و پشت کارت نباید یک فایل یکسان باشند.'
  }

  if (
    detail.includes('already_pending') ||
    status === 409
  ) {
    return 'یک درخواست احراز هویت از قبل در انتظار بررسی است.'
  }

  if (status === 401 || status === 403) {
    return 'نشست شما معتبر نیست. لطفاً دوباره وارد حساب کاربری شوید.'
  }

  if (detail === 'network_error') {
    return 'ارتباط با سرور قطع شد. اینترنت خود را بررسی کرده و دوباره تلاش کنید.'
  }

  if (detail === 'request_timeout') {
    return 'ارسال بیش از حد طول کشید. لطفاً اتصال اینترنت را بررسی کرده و دوباره تلاش کنید.'
  }

  return 'ارسال مدارک انجام نشد. لطفاً دوباره تلاش کنید.'
}

function uploadForm(
  url: string,
  body: FormData,
  onProgress: (percent: number, message: string) => void,
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    xhr.open('POST', url, true)
    xhr.timeout = 120000

    const token = authToken()
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    }

    xhr.upload.onprogress = event => {
      if (!event.lengthComputable || event.total <= 0) return

      // Reserve the last few percent for server-side validation,
      // storage and submission creation.
      const raw = event.loaded / event.total
      const percent = Math.min(93, Math.max(5, Math.round(raw * 88) + 5))

      onProgress(
        percent,
        percent < 45
          ? 'در حال ارسال فایل‌ها...'
          : percent < 80
            ? 'بارگذاری ادامه دارد...'
            : 'تقریباً تمام شد...',
      )
    }

    xhr.upload.onload = () => {
      onProgress(
        95,
        'فایل‌ها به سرور رسیدند؛ در حال بررسی و ثبت درخواست...',
      )
    }

    xhr.onload = () => {
      let data: Record<string, unknown> = {}

      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : {}
      } catch {
        data = {}
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data)
        return
      }

      reject({
        status: xhr.status,
        detail: String(data?.detail || `http_${xhr.status}`),
      })
    }

    xhr.onerror = () => {
      reject({ status: 0, detail: 'network_error' })
    }

    xhr.ontimeout = () => {
      reject({ status: 0, detail: 'request_timeout' })
    }

    xhr.send(body)
  })
}

function StepBadge({
  done,
  active,
  children,
}: {
  done: boolean
  active: boolean
  children: string
}) {
  return (
    <div
      className={`rounded-2xl border p-4 ${
        done
          ? 'border-emerald-200 bg-emerald-50'
          : active
            ? 'border-blue-200 bg-blue-50'
            : 'border-gray-200 bg-gray-50'
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <strong className="text-sm sm:text-base">{children}</strong>

        <span
          className={`shrink-0 rounded-full px-3 py-1 text-xs font-bold ${
            done
              ? 'bg-emerald-600 text-white'
              : active
                ? 'bg-blue-600 text-white'
                : 'bg-gray-300 text-gray-700'
          }`}
        >
          {done ? 'تایید شده' : active ? 'مرحله فعلی' : 'قفل'}
        </span>
      </div>
    </div>
  )
}

function FileUploadField({
  label,
  description,
  file,
  disabled,
  onChange,
  onError,
}: {
  label: string
  description: string
  file: File | null
  disabled?: boolean
  onChange: (file: File | null) => void
  onError: (message: string) => void
}) {
  const [previewUrl, setPreviewUrl] = useState('')

  const previewable =
    file &&
    ['image/jpeg', 'image/png', 'image/webp'].includes(
      file.type.toLowerCase(),
    )

  useEffect(() => {
    if (!file || !previewable) {
      setPreviewUrl('')
      return
    }

    const url = URL.createObjectURL(file)
    setPreviewUrl(url)

    return () => URL.revokeObjectURL(url)
  }, [file, previewable])

  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] || null

    if (!selected) return

    const error = validateSelectedFile(selected)

    if (error) {
      event.target.value = ''
      onError(error)
      return
    }

    onError('')
    onChange(selected)
  }

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3">
        <div className="font-bold text-gray-900">{label}</div>
        <div className="mt-1 text-xs leading-5 text-gray-500">
          {description}
        </div>
      </div>

      {!file ? (
        <label
          className={`flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-blue-200 bg-blue-50/60 p-5 text-center transition hover:border-blue-400 hover:bg-blue-50 ${
            disabled ? 'pointer-events-none opacity-50' : ''
          }`}
        >
          <span className="text-4xl">📤</span>
          <span className="mt-3 font-bold text-blue-800">
            انتخاب فایل
          </span>
          <span className="mt-2 text-xs leading-5 text-gray-600">
            JPG، PNG، WebP، HEIC، HEIF یا PDF
            <br />
            حداکثر ۱۰ مگابایت
          </span>

          <input
            type="file"
            accept={ACCEPTED_FILES}
            className="hidden"
            disabled={disabled}
            onChange={choose}
          />
        </label>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-emerald-200 bg-emerald-50">
          {previewUrl ? (
            <div className="flex justify-center bg-gray-100 p-2">
              <img
                src={previewUrl}
                alt={label}
                className="max-h-52 max-w-full rounded-xl object-contain"
              />
            </div>
          ) : (
            <div className="flex h-28 items-center justify-center bg-gray-100 text-5xl">
              {getExtension(file) === 'pdf' ? '📄' : '🖼️'}
            </div>
          )}

          <div className="p-4">
            <div className="flex items-start gap-3">
              <span className="mt-0.5 text-xl text-emerald-700">✓</span>

              <div className="min-w-0 flex-1">
                <div className="truncate font-bold text-gray-900" dir="ltr">
                  {file.name}
                </div>
                <div className="mt-1 text-xs text-gray-600">
                  {formatSize(file.size)}
                </div>
                <div className="mt-2 text-xs font-bold text-emerald-700">
                  فایل آماده ارسال است
                </div>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2">
              <label
                className={`flex min-h-11 cursor-pointer items-center justify-center rounded-xl bg-blue-600 px-3 py-2 text-sm font-bold text-white ${
                  disabled ? 'pointer-events-none opacity-50' : ''
                }`}
              >
                تغییر فایل
                <input
                  type="file"
                  accept={ACCEPTED_FILES}
                  className="hidden"
                  disabled={disabled}
                  onChange={choose}
                />
              </label>

              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(null)}
                className="min-h-11 rounded-xl bg-red-50 px-3 py-2 text-sm font-bold text-red-700 disabled:opacity-50"
              >
                حذف
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function KycFlow() {
  const [status, setStatus] = useState<KycStatus | null>(null)
  const [front, setFront] = useState<File | null>(null)
  const [back, setBack] = useState<File | null>(null)
  const [selfie, setSelfie] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [uploadDialog, setUploadDialog] =
    useState<UploadDialog>(initialDialog)

  const loadStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/kyc/status`, {
        headers: authHeaders(),
      })

      if (!response.ok) {
        throw new Error(`status_${response.status}`)
      }

      setStatus(await response.json())
    } catch (error) {
      console.error('KYC status failed', error)
      setMessage(
        'دریافت وضعیت احراز هویت انجام نشد. در صورت ادامه مشکل دوباره وارد حساب کاربری شوید.',
      )
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  const level2Pending = status?.level2?.status === 'pending'
  const level2Rejected = status?.level2?.status === 'rejected'
  const level3Pending = status?.level3?.status === 'pending'
  const level3Rejected = status?.level3?.status === 'rejected'

  const level2Approved = (status?.verification_level || 0) >= 2
  const level3Approved = (status?.verification_level || 0) >= 3

  useEffect(() => {
    if (!level2Pending && !level3Pending) return

    const timer = window.setInterval(() => {
      void loadStatus()
    }, 5000)

    return () => window.clearInterval(timer)
  }, [level2Pending, level3Pending])

  const frontBackSame = useMemo(() => {
    if (!front || !back) return false

    return (
      front === back ||
      (
        front.name === back.name &&
        front.size === back.size &&
        front.lastModified === back.lastModified
      )
    )
  }, [front, back])

  const updateUploadProgress = (
    progress: number,
    description: string,
  ) => {
    setUploadDialog(current => ({
      ...current,
      progress,
      description,
    }))
  }

  const startUploadDialog = (title: string) => {
    setUploadDialog({
      open: true,
      status: 'working',
      title,
      description: 'در حال آماده‌سازی فایل‌ها...',
      message:
        'لطفاً تا پایان ارسال در همین صفحه بمانید و دکمه ارسال را دوباره فشار ندهید.',
      progress: 3,
    })
  }

  const finishUploadDialog = (title: string, messageText: string) => {
    setUploadDialog({
      open: true,
      status: 'success',
      title,
      description: 'مدارک با موفقیت دریافت شدند.',
      message: messageText,
      progress: 100,
    })
  }

  const failUploadDialog = (errorMessage: string) => {
    setUploadDialog(current => ({
      ...current,
      open: true,
      status: 'error',
      title: 'ارسال مدارک انجام نشد',
      description: 'مدارک شما ثبت نشده‌اند.',
      message: errorMessage,
      progress: current.progress,
    }))
  }

  const submitLevel2 = async () => {
    if (!front || !back) {
      setMessage(
        'لطفاً فایل روی کارت ملی و پشت کارت ملی را انتخاب کنید.',
      )
      return
    }

    if (frontBackSame) {
      setMessage(
        'فایل روی کارت و پشت کارت نباید یک فایل یکسان باشند.',
      )
      return
    }

    const frontError = validateSelectedFile(front)
    const backError = validateSelectedFile(back)

    if (frontError || backError) {
      setMessage(frontError || backError || '')
      return
    }

    setLoading(true)
    setMessage('')
    startUploadDialog('ارسال مدارک سطح ۲')

    try {
      const body = new FormData()
      body.append('front', front)
      body.append('back', back)

      const result = await uploadForm(
        `${API_BASE}/kyc/level2`,
        body,
        updateUploadProgress,
      )

      setFront(null)
      setBack(null)

      const submissionId = result?.submission_id
        ? ` شماره درخواست: ${String(result.submission_id)}`
        : ''

      const successMessage =
        `مدارک سطح ۲ ثبت شدند و اکنون در انتظار بررسی ادمین هستند.${submissionId}`

      setMessage(successMessage)

      finishUploadDialog(
        'مدارک با موفقیت ارسال شد',
        'وضعیت شما «در انتظار بررسی» است. لازم نیست دوباره مدارک را ارسال کنید؛ نتیجه پس از بررسی در همین صفحه نمایش داده می‌شود.',
      )

      void loadStatus()
    } catch (error: any) {
      console.error('Level 2 upload failed', error)

      const errorMessage = mapUploadError(
        String(error?.detail || ''),
        Number(error?.status || 0),
      )

      setMessage(errorMessage)
      failUploadDialog(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  const submitLevel3 = async () => {
    if (!selfie) {
      setMessage(
        'لطفاً فایل سلفی با کارت ملی در دست را انتخاب کنید.',
      )
      return
    }

    const selfieError = validateSelectedFile(selfie)

    if (selfieError) {
      setMessage(selfieError)
      return
    }

    setLoading(true)
    setMessage('')
    startUploadDialog('ارسال مدرک سطح ۳')

    try {
      const body = new FormData()
      body.append('selfie', selfie)

      const result = await uploadForm(
        `${API_BASE}/kyc/level3`,
        body,
        updateUploadProgress,
      )

      setSelfie(null)

      const submissionId = result?.submission_id
        ? ` شماره درخواست: ${String(result.submission_id)}`
        : ''

      const successMessage =
        `مدرک سطح ۳ ثبت شد و در انتظار بررسی است.${submissionId}`

      setMessage(successMessage)

      finishUploadDialog(
        'مدرک با موفقیت ارسال شد',
        'درخواست سطح ۳ ثبت شده و اکنون در انتظار بررسی ادمین است.',
      )

      void loadStatus()
    } catch (error: any) {
      console.error('Level 3 upload failed', error)

      const errorMessage = mapUploadError(
        String(error?.detail || ''),
        Number(error?.status || 0),
      )

      setMessage(errorMessage)
      failUploadDialog(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <BlockingProgressModal
        open={uploadDialog.open}
        title={uploadDialog.title}
        description={uploadDialog.description}
        progress={uploadDialog.progress}
        status={uploadDialog.status}
        message={uploadDialog.message}
        closeLabel={
          uploadDialog.status === 'error'
            ? 'بستن و تلاش دوباره'
            : 'متوجه شدم'
        }
        onClose={
          uploadDialog.status === 'working'
            ? undefined
            : () =>
                setUploadDialog(current => ({
                  ...current,
                  open: false,
                }))
        }
      />

      <section
        dir="rtl"
        className="mx-auto w-full max-w-2xl space-y-5 bg-white p-4 shadow-sm sm:rounded-3xl sm:p-6"
      >
        <div>
          <h2 className="text-xl font-black text-gray-900 sm:text-2xl">
            احراز هویت
          </h2>

          <p className="mt-2 text-sm leading-6 text-gray-600">
            سطح احراز هویت فعلی شما:{' '}
            <strong>
              {status?.verification_level || 1}
            </strong>
          </p>
        </div>

        <div className="grid gap-3">
          <StepBadge done active>
            سطح ۱ — تطبیق اطلاعات هویتی
          </StepBadge>

          <StepBadge
            done={level2Approved}
            active={!level2Approved}
          >
            سطح ۲ — روی و پشت کارت ملی
          </StepBadge>

          <StepBadge
            done={level3Approved}
            active={level2Approved && !level3Approved}
          >
            سطح ۳ — سلفی با کارت ملی
          </StepBadge>
        </div>

        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-900">
          ✓ سطح ۱ با موفقیت تایید شده است. برای افزایش سطح
          احراز، مدارک مرحله بعد را ارسال کنید.
        </div>

        {!level2Approved && (
          <div className="space-y-4 rounded-2xl border border-gray-200 bg-gray-50/60 p-3 sm:p-5">
            <div>
              <h3 className="text-lg font-black text-gray-900">
                سطح ۲
              </h3>
              <p className="mt-1 text-sm leading-6 text-gray-600">
                روی و پشت کارت ملی را جداگانه بارگذاری کنید.
              </p>
            </div>

            {level2Pending ? (
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-start gap-3">
                  <span className="text-2xl">⏳</span>

                  <div>
                    <div className="font-black text-amber-900">
                      مدارک دریافت شد
                    </div>

                    <p className="mt-1 text-sm leading-6 text-amber-800">
                      درخواست شما در انتظار بررسی ادمین است.
                      لازم نیست دوباره مدارک را ارسال کنید.
                    </p>

                    <div className="mt-3 space-y-1 text-xs font-bold text-amber-900">
                      <div>
                        {status?.level2?.has_front ? '✓' : '○'} روی کارت ملی
                      </div>
                      <div>
                        {status?.level2?.has_back ? '✓' : '○'} پشت کارت ملی
                      </div>
                      {status?.level2?.id && (
                        <div>
                          شماره درخواست: {status.level2.id}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <>
                {level2Rejected && (
                  <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                    <strong>درخواست قبلی رد شده است.</strong>
                    <div className="mt-1">
                      {status?.level2?.rejection_reason ||
                        'لطفاً فایل‌های واضح‌تری دوباره بارگذاری کنید.'}
                    </div>
                  </div>
                )}

                <FileUploadField
                  label="روی کارت ملی"
                  description="تصویر یا فایل واضح روی کارت ملی"
                  file={front}
                  disabled={loading}
                  onChange={setFront}
                  onError={setMessage}
                />

                <FileUploadField
                  label="پشت کارت ملی"
                  description="تصویر یا فایل واضح پشت کارت ملی"
                  file={back}
                  disabled={loading}
                  onChange={setBack}
                  onError={setMessage}
                />

                {frontBackSame && (
                  <div className="rounded-xl bg-red-50 p-3 text-sm font-bold text-red-700">
                    روی کارت و پشت کارت یک فایل یکسان هستند.
                  </div>
                )}

                <button
                  type="button"
                  disabled={
                    loading ||
                    !front ||
                    !back ||
                    frontBackSame
                  }
                  onClick={submitLevel2}
                  className="min-h-14 w-full rounded-2xl bg-blue-600 px-4 py-3 text-base font-black text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ارسال مدارک سطح ۲
                </button>
              </>
            )}
          </div>
        )}

        {level2Approved && !level3Approved && (
          <div className="space-y-4 rounded-2xl border border-gray-200 bg-gray-50/60 p-3 sm:p-5">
            <div className="rounded-xl bg-emerald-50 p-3 text-sm font-bold text-emerald-900">
              ✓ سطح ۲ تایید شده است.
            </div>

            <div>
              <h3 className="font-black text-gray-900">
                سطح ۳ — اختیاری
              </h3>
              <p className="mt-2 text-sm leading-6 text-gray-600">
                یک سلفی واضح ارسال کنید که صورت شما و کارت
                ملی در دستتان قابل مشاهده باشد.
              </p>
            </div>

            {level3Pending ? (
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
                <strong>✓ فایل دریافت شد.</strong>
                <div className="mt-1">
                  درخواست سطح ۳ در انتظار بررسی ادمین است.
                </div>

                {status?.level3?.id && (
                  <div className="mt-2 text-xs font-bold">
                    شماره درخواست: {status.level3.id}
                  </div>
                )}
              </div>
            ) : (
              <>
                {level3Rejected && (
                  <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                    <strong>درخواست قبلی رد شده است.</strong>
                    <div className="mt-1">
                      {status?.level3?.rejection_reason ||
                        'لطفاً فایل جدیدی ارسال کنید.'}
                    </div>
                  </div>
                )}

                <FileUploadField
                  label="سلفی با کارت ملی"
                  description="صورت و کارت ملی باید واضح و قابل مشاهده باشند."
                  file={selfie}
                  disabled={loading}
                  onChange={setSelfie}
                  onError={setMessage}
                />

                <button
                  type="button"
                  disabled={loading || !selfie}
                  onClick={submitLevel3}
                  className="min-h-14 w-full rounded-2xl bg-blue-600 px-4 py-3 text-base font-black text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ارسال مدرک سطح ۳
                </button>
              </>
            )}
          </div>
        )}

        {level3Approved && (
          <div className="rounded-2xl border border-emerald-300 bg-emerald-100 p-5 text-center font-black text-emerald-900">
            ✓ سطح ۳ احراز هویت شما تایید شده است.
          </div>
        )}

        {message && (
          <div className="rounded-2xl bg-gray-100 p-4 text-sm leading-6 text-gray-800">
            {message}
          </div>
        )}

        <button
          type="button"
          disabled={loading}
          onClick={() => void loadStatus()}
          className="min-h-11 w-full rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700 disabled:opacity-50 sm:w-auto"
        >
          بروزرسانی وضعیت
        </button>
      </section>
    </>
  )
}
