import { useState } from 'react'

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard can be blocked (http, iframes); the text is still selectable.
    }
  }

  return (
    <button type="button" className="btn-ghost" onClick={copy} aria-live="polite">
      {copied ? 'Copied' : label}
    </button>
  )
}
