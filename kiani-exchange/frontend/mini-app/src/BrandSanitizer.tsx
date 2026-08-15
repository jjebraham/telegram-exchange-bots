import { useEffect } from 'react'

const replacements: Array<[RegExp, string]> = [
  [/صرافی\s*کیانی/g, 'صرافی'],
  [/کیانی/g, ''],
  [/KIANI\s*Exchange/gi, 'Exchange'],
  [/KIANI/gi, ''],
  [/۸۰\s*TL/g, '۱۶۰ TL'],
  [/80\s*TL/gi, '160 TL'],
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
