import { useEffect } from 'react'

const replacements: Array<[RegExp, string]> = [
  [/صرافی\s*کیانی/g, 'صرافی'],
  [/کیانی/g, ''],
  [/KIANI\s*Exchange/gi, 'Exchange'],
  [/KIANI/gi, ''],
  [/برای تراکنش های زیر 5000 لیر کارمزد ثابت ۸۰ TL از مبلغ دریافتی کسر می‌شود\./g, 'برای تراکنش‌های زیر ۵۰۰۰ لیر، کارمزد ثابت ۱۶۰ TL از مبلغ لیر ارسالی کسر می‌شود.'],
  [/برای تراکنش های زیر 15,000,000 تومان کارمزد ثابت ۸۰ TL از مبلغ دریافتی کسر می‌شود\./g, 'برای تراکنش‌های زیر ۱۵,۰۰۰,۰۰۰ تومان، کارمزد ثابت ۱۶۰ TL از مبلغ لیر دریافتی کسر می‌شود.'],
  [/۸۰\s*TL/g, '۱۶۰ TL'],
  [/80\s*TL/gi, '160 TL'],
  [/toman_to_tl_manual_rate/g, 'Toman → TL — نرخ دستی (۰ = نرخ بازار)'],
  [/toman_to_tl_percentage/g, 'Toman → TL — درصد تعدیل'],
  [/tl_to_toman_manual_rate/g, 'TL → Toman — نرخ دستی (۰ = نرخ بازار)'],
  [/tl_to_toman_percentage/g, 'TL → Toman — درصد تعدیل'],
  [/tl_to_usdt_manual_rate/g, 'TL → USDT — نرخ دستی (۰ = نرخ بازار)'],
  [/tl_to_usdt_percentage/g, 'TL → USDT — درصد تعدیل'],
  [/usdt_to_tl_manual_rate/g, 'USDT → TL — نرخ دستی (۰ = نرخ بازار)'],
  [/usdt_to_tl_percentage/g, 'USDT → TL — درصد تعدیل'],
  [/toman_to_usdt_manual_rate/g, 'Toman → USDT — نرخ دستی (۰ = نرخ بازار)'],
  [/toman_to_usdt_percentage/g, 'Toman → USDT — درصد تعدیل'],
  [/usdt_to_toman_manual_rate/g, 'USDT → Toman — نرخ دستی (۰ = نرخ بازار)'],
  [/usdt_to_toman_percentage/g, 'USDT → Toman — درصد تعدیل'],
]

const cleanBrand = (value: string) => {
  let next = value
  for (const [pattern, replacement] of replacements) next = next.replace(pattern, replacement)
  return next.replace(/ {2,}/g, ' ').trim()
}

const sanitizeNode = (node: Node) => {
  if (node.nodeType === Node.TEXT_NODE) {
    const current = node.textContent || ''
    const cleaned = cleanBrand(current)
    if (cleaned !== current) node.textContent = cleaned
    return
  }

  if (!(node instanceof HTMLElement)) return

  for (const attr of ['title', 'aria-label', 'placeholder', 'alt']) {
    const current = node.getAttribute(attr)
    if (!current) continue
    const cleaned = cleanBrand(current)
    if (cleaned !== current) node.setAttribute(attr, cleaned)
  }

  node.childNodes.forEach(sanitizeNode)
}

export default function BrandSanitizer() {
  useEffect(() => {
    document.title = cleanBrand(document.title || 'صرافی') || 'صرافی'
    sanitizeNode(document.body)

    const observer = new MutationObserver(records => {
      for (const record of records) {
        record.addedNodes.forEach(sanitizeNode)
        if (record.type === 'characterData') sanitizeNode(record.target)
      }
    })

    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
    })

    return () => observer.disconnect()
  }, [])

  return null
}
