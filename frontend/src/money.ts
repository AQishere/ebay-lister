// Exact list price with cents ($232.99); whole numbers without them ($230).
export function listPrice(v: number | null | undefined, currency = 'USD'): string {
  if (v == null) return '–'
  const digits = Number.isInteger(v) ? 0 : 2
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)
}
