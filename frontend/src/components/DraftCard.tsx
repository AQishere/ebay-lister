import { useState } from 'react'
import type { Draft, Market } from '../types'
import { CopyButton } from './CopyButton'
import { PricePlan } from './PricePlan'

const TITLE_MAX = 80

const squash = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '')

interface Props {
  draft: Draft
  market: Market | null
  marketLoading: boolean
}

// Rendered with a key per draft, so a new draft starts with fresh edit state.
export function DraftCard({ draft, market, marketLoading }: Props) {
  const [title, setTitle] = useState(draft.title)
  const [description, setDescription] = useState(draft.description)
  const [specifics, setSpecifics] = useState(draft.item_specifics)

  const specificsText = Object.entries(specifics)
    .map(([k, v]) => `${k}: ${v}`)
    .join('\n')
  const over = title.length > TITLE_MAX
  // Re-checked against the live title, so edits and taps update the checklist.
  const checks = (draft.title_checks ?? []).map((c) => ({
    ...c,
    in_title: c.value != null && squash(title).includes(squash(c.value)),
  }))

  function addToTitle(value: string) {
    setTitle((t) => (t.length + value.length + 1 <= TITLE_MAX ? `${t.trim()} ${value}` : t))
  }

  return (
    <article className="card draft-card">
      <header className="card-head">
        <span className="eyebrow">Your listing</span>
        <span className="mono muted">#{draft.draft_id.slice(-6)}</span>
      </header>

      <div className="meta-row">
        {draft.category.name && <span className="tag">{draft.category.name}</span>}
        {draft.condition && <span className="tag">{draft.condition}</span>}
      </div>

      <PricePlan plan={market?.plan} loading={marketLoading} />

      <section className="field">
        <div className="field-head">
          <label htmlFor="title">Title</label>
          <span className={`counter ${over ? 'bad' : ''}`}>
            {title.length}/{TITLE_MAX}
          </span>
          <CopyButton text={title} />
        </div>
        <textarea
          id="title"
          className="title-input"
          value={title}
          rows={2}
          onChange={(e) => setTitle(e.target.value.replace(/\n/g, ' '))}
        />
        <div className="meter" aria-hidden>
          <div className={`meter-fill ${over ? 'bad' : ''}`} style={{ width: `${Math.min(100, (title.length / TITLE_MAX) * 100)}%` }} />
        </div>

        {checks.length > 0 && (
          <div className="checks">
            <span className="checks-label">Buyers search by</span>
            <ul>
              {checks.map((c) => (
                <li key={c.aspect} className={c.in_title ? 'ok' : c.value ? 'add' : 'unknown'}>
                  <span className="check-icon" aria-hidden>
                    {c.in_title ? '✓' : c.value ? '+' : '?'}
                  </span>
                  <span className="check-name">{c.aspect}</span>
                  {c.in_title && <span className="check-value">{c.value}</span>}
                  {!c.in_title && c.value && (
                    <button
                      type="button"
                      className="check-add"
                      onClick={() => addToTitle(c.value!)}
                      disabled={title.length + c.value.length + 1 > TITLE_MAX}
                      title="Add to title"
                    >
                      Add “{c.value}”
                    </button>
                  )}
                  {!c.value && <span className="check-value muted">answer above</span>}
                </li>
              ))}
            </ul>
            {title.length < 60 && (
              <p className="fineprint">{TITLE_MAX - title.length} characters left. Titles that use more of the 80 match more searches.</p>
            )}
          </div>
        )}
      </section>

      {Object.keys(specifics).length > 0 && (
        <section className="field">
          <div className="field-head">
            <span className="label">Item specifics</span>
            <CopyButton text={specificsText} label="Copy all" />
          </div>
          <dl className="specifics">
            {Object.entries(specifics).map(([k, v]) => (
              <div key={k} className="spec-row">
                <dt>{k}</dt>
                <dd>
                  <input
                    value={v}
                    aria-label={k}
                    onChange={(e) => setSpecifics((s) => ({ ...s, [k]: e.target.value }))}
                  />
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <section className="field">
        <div className="field-head">
          <label htmlFor="desc">Description</label>
          <CopyButton text={description} />
        </div>
        <textarea id="desc" className="desc-input" value={description} rows={5} onChange={(e) => setDescription(e.target.value)} />
      </section>

      {draft.warnings.length > 0 && (
        <ul className="warnings">
          {draft.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </article>
  )
}
