import type { Market } from '../types'

// Whole dollars from $100 up or when there are no cents; cents otherwise ($34.99).
const money = (v: number | null | undefined, currency = 'USD') => {
  if (v == null) return '–'
  const digits = v >= 100 || Number.isInteger(v) ? 0 : 2
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)
}

interface Props {
  market: Market | null
  loading: boolean
  error: string | null
  onRetry: () => void
}

export function MarketPanel({ market, loading, error, onRetry }: Props) {
  if (loading) {
    return (
      <aside className="card market-card">
        <header className="card-head">
          <span className="eyebrow">Market</span>
        </header>
        <p className="progress" role="status">
          <span className="spinner" aria-hidden /> Checking current eBay prices…
        </p>
        <div className="skeleton big" />
        <div className="skeleton" />
      </aside>
    )
  }
  if (error) {
    return (
      <aside className="card market-card">
        <header className="card-head">
          <span className="eyebrow">Market</span>
        </header>
        <p className="error-text">{error}</p>
        <button type="button" className="btn-ghost" onClick={onRetry}>
          Try again
        </button>
      </aside>
    )
  }
  if (!market) return null

  const p = market.price
  const cur = p.currency ?? 'USD'
  const hasRange = p.count > 0 && p.p25 != null && p.p75 != null && p.median != null
  const span = hasRange ? p.p75! - p.p25! : 0
  const medianPos = hasRange && span > 0 ? ((p.median! - p.p25!) / span) * 100 : 50

  return (
    <aside className="card market-card">
      <header className="card-head">
        <span className="eyebrow">Market</span>
        {p.condition && <span className="tag">{p.condition === 'NEW' ? 'New' : 'Used'}</span>}
      </header>

      {hasRange ? (
        <>
          <div className="price-hero">
            <span className="price-big">{money(p.median, cur)}</span>
            <span className="muted small">median asking price · {p.count} listings</span>
          </div>

          <div className="range" aria-label={`Middle half of asking prices: ${money(p.p25, cur)} to ${money(p.p75, cur)}`}>
            <div className="range-bar">
              <span className="range-marker" style={{ left: `${medianPos}%` }} />
            </div>
            <div className="range-labels">
              <span>{money(p.p25, cur)}</span>
              <span>{money(p.p75, cur)}</span>
            </div>
          </div>
          <p className="fineprint">{p.label}. The bar is the middle half of prices.</p>
        </>
      ) : (
        <p className="muted">{p.label}</p>
      )}

      {market.evidence.length > 0 && (
        <section className="field evidence-section">
          <span className="label">Similar current listings, most sold first</span>
          <ul className="evidence">
            {market.evidence.map((e, i) => (
              <li key={`${e.item_url ?? e.title}-${i}`}>
                <a href={e.item_url ?? undefined} target="_blank" rel="noreferrer">
                  {e.title}
                </a>
                <span className="evidence-meta">
                  <strong>{money(e.price, e.currency ?? cur)}</strong>
                  {e.sold_quantity ? <span className="muted"> · {e.sold_quantity} sold</span> : null}
                </span>
              </li>
            ))}
          </ul>
          <p className="fineprint">{market.note}</p>
        </section>
      )}
    </aside>
  )
}
