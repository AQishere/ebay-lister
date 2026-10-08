import { listPrice } from '../money'
import type { PricePlan as Plan } from '../types'
import { CopyButton } from './CopyButton'

interface Props {
  plan: Plan | undefined
  loading: boolean
}

export function PricePlan({ plan, loading }: Props) {
  if (loading) {
    return (
      <section className="plan">
        <span className="label">Your price</span>
        <div className="plan-tiles">
          <div className="skeleton tile" />
          <div className="skeleton tile" />
          <div className="skeleton tile" />
        </div>
      </section>
    )
  }
  if (!plan?.recommended) {
    return (
      <section className="plan">
        <span className="label">Your price</span>
        <p className="muted small">Not enough similar listings to recommend a price yet.</p>
      </section>
    )
  }

  const cur = plan.currency ?? 'USD'
  const units = plan.units_sold ?? 0
  const below = plan.units_sold_at_or_below_recommended ?? 0
  const share = units ? Math.round((below / units) * 100) : null

  return (
    <section className="plan">
      <div className="field-head">
        <span className="label">Your price</span>
        <CopyButton text={plan.recommended.toFixed(2)} label="Copy price" />
      </div>
      <div className="plan-tiles">
        <div className="tile">
          <span className="tile-label">Sell fast</span>
          <strong>{listPrice(plan.fast, cur)}</strong>
          <span className="tile-note">below most competitors</span>
        </div>
        <div className="tile recommended">
          <span className="tile-label">Recommended</span>
          <strong>{listPrice(plan.recommended, cur)}</strong>
          <span className="tile-note">where similar items sell</span>
        </div>
        <div className="tile">
          <span className="tile-label">Max</span>
          <strong>{listPrice(plan.max, cur)}</strong>
          <span className="tile-note">expect to wait longer</span>
        </div>
      </div>
      <p className="plan-why">
        {share != null ? (
          <>
            {share}% of the {units.toLocaleString('en-US')} units sold on similar listings were priced at or below{' '}
            {listPrice(plan.recommended, cur)}.
          </>
        ) : (
          <>Based on the asking prices of {plan.listings} similar listings in the same condition.</>
        )}
      </p>
    </section>
  )
}
