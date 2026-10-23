import { useState } from 'react'

function PhotoExample({ acceptable }: { acceptable: boolean }) {
  return (
    <figure className={`overflow-hidden rounded-2xl border-2 ${acceptable ? 'border-emerald-300 bg-emerald-50' : 'border-red-200 bg-red-50'}`}>
      <figcaption className={`px-3 pt-3 text-center text-sm font-bold ${acceptable ? 'text-emerald-800' : 'text-red-800'}`}>
        {acceptable ? '✓ چیدمان مناسب عکس' : '✕ عکس غیرقابل قبول'}
      </figcaption>
      <svg
        viewBox="0 0 300 230"
        className="mx-auto w-full max-w-xs"
        role="img"
        aria-label={acceptable
          ? 'راهنمای تصویری: چهره باز، برگه دست‌نویس امضاشده و کارت ملی در کنار هم'
          : 'راهنمای تصویری: عینک آفتابی و پوشاندن نوشته‌های برگه با کارت قابل قبول نیست'}
      >
        <path d="M64 230v-55c0-32 35-54 86-54s86 22 86 54v55" fill="#334d77" />
        <path d="M134 112h32v27c-8 11-24 11-32 0z" fill="#d7a77f" />
        <path d="M112 70c0-37 76-37 76 0v24c0 54-76 54-76 0z" fill="#eac09c" />
        <path d="M111 78c-5-41 18-50 40-50 29 0 45 19 37 50l-8-18c-24 7-40 5-59-2z" fill="#263346" />
        <circle cx="135" cy="85" r="3" fill="#263346" />
        <circle cx="165" cy="85" r="3" fill="#263346" />
        <path d="M150 89v12m-12 8q12 8 24 0" stroke="#985c45" strokeWidth="3" fill="none" strokeLinecap="round" />
        {!acceptable && <g fill="#152032" stroke="#152032" strokeWidth="4">
          <rect x="118" y="76" width="28" height="19" rx="6" />
          <rect x="154" y="76" width="28" height="19" rx="6" />
          <path d="M146 82h8" />
        </g>}
        <rect x="86" y="143" width="115" height="80" rx="4" fill="#fff" stroke="#9ba9ba" strokeWidth="2" />
        <g stroke="#61748e" strokeWidth="2" strokeLinecap="round">
          <path d="M99 155h88m-88 9h84m-84 9h88m-88 9h76m-76 9h83" />
          <path d="M105 211q8-12 14-2t12-4q5 14 14-1" fill="none" />
          <path d="M162 210h22" />
        </g>
        <path d="M80 182l7-6q9-4 9 5v21q-2 12-14 11l-6-12z" fill="#eac09c" />
        <g transform={acceptable ? 'translate(212 152)' : 'translate(143 158)'}>
          <rect width="65" height="43" rx="5" fill="#d7ede8" stroke="#507c75" strokeWidth="2" />
          <rect x="7" y="7" width="18" height="28" rx="2" fill="#94b8b0" />
          <circle cx="16" cy="15" r="5" fill="#eac09c" />
          <path d="M9 32v-5a7 7 0 0114 0v5" fill="#334d77" />
          <path d="M32 12h23m-23 8h19m-19 8h23" stroke="#507c75" strokeWidth="2" />
          <path d="M58 26q14-4 14 7v15q-12 9-19-3z" fill="#eac09c" />
        </g>
      </svg>
      <p className="px-3 pb-3 text-center text-xs leading-5 text-gray-700">
        {acceptable ? 'صورت، نوشته‌ها، امضا و کارت همگی واضح و کامل' : 'چهره یا نوشته‌ها پوشیده و بخشی از مدارک ناخوانا'}
      </p>
    </figure>
  )
}

export default function KycSelfieInstructions({ declarationText }: { declarationText: string }) {
  const [copyMessage, setCopyMessage] = useState('')

  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(declarationText)
      setCopyMessage('متن کپی شد؛ آن را با دست‌خط خود روی کاغذ بنویسید.')
    } catch {
      setCopyMessage('کپی خودکار انجام نشد؛ می‌توانید متن زیر را انتخاب و کپی کنید.')
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm leading-7 text-blue-950">
        <h4 className="font-black">یک عکس، سه مورد کنار هم</h4>
        <p className="mt-1">چهره خودتان، اصل کارت ملی و برگه دست‌نویسِ امضاشده باید در یک عکس تازه، واضح و بدون ویرایش دیده شوند. از فرد دیگری بخواهید عکس بگیرد یا از تایمر دوربین استفاده کنید.</p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <PhotoExample acceptable />
        <PhotoExample acceptable={false} />
      </div>
      <p className="text-xs leading-5 text-gray-500">تصویرهای بالا فقط راهنمای چیدمان هستند؛ عکس واقعی خودتان را ارسال کنید.</p>

      <section className="rounded-2xl border border-gray-200 bg-white p-4" aria-labelledby="kyc-selfie-steps">
        <h4 id="kyc-selfie-steps" className="font-black text-gray-900">روش آماده‌کردن عکس</h4>
        <ol className="mt-3 list-decimal space-y-2 pr-5 text-sm leading-7 text-gray-700">
          <li>متن زیر را کامل و خوانا با دست‌خط خود روی یک برگه سفید بنویسید و جای خالی را با نام و نام خانوادگی خود پر کنید. برگه چاپی یا نوشته دیجیتال پذیرفته نیست.</li>
          <li>نام و نام خانوادگی، تاریخ روز عکس و امضای خود را پایین برگه بنویسید.</li>
          <li>اصل کارت ملی خود را کنار برگه و نزدیک صورت نگه دارید. انگشت‌ها یا کارت نباید متن، امضا یا اطلاعات کارت را بپوشانند.</li>
          <li>در نور کافی و بدون عینک آفتابی یا ماسک عکس بگیرید. تمام چهره، کارت و برگه در کادر باشند و همه نوشته‌ها خوانده شوند. عکس آینه‌ای، فیلترشده، کلاژ یا تصویر صفحه‌نمایش ارسال نکنید.</li>
        </ol>
      </section>

      <section className="rounded-2xl border border-blue-200 bg-white p-4" aria-labelledby="kyc-declaration-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h4 id="kyc-declaration-heading" className="font-black text-gray-900">متنی که باید با دست روی کاغذ بنویسید</h4>
          <button type="button" onClick={() => void copyText()} className="min-h-11 rounded-xl bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700">کپی متن</button>
        </div>
        <p className="mt-3 select-text whitespace-pre-line rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 p-4 text-base leading-9 text-gray-900">{declarationText}</p>
        <p className="mt-2 text-xs leading-6 text-gray-600">نام، تاریخ و امضا را حتماً روی خودِ برگه بنویسید؛ تایپ‌کردن روی عکس کافی نیست.</p>
        <p aria-live="polite" className="mt-2 text-xs leading-6 text-blue-800">{copyMessage}</p>
      </section>

      <aside className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-950">
        حساب خود را برای کار، دریافت دستمزد یا به درخواست دیگران اجاره ندهید. اگر شخص دیگری از شما خواسته احراز هویت کنید و حساب یا کد ورود را در اختیارش بگذارید، ادامه ندهید و با پشتیبانی کیانی تماس بگیرید.
      </aside>
    </div>
  )
}
