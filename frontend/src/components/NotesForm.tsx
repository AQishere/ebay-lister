import { useEffect, useRef, useState } from 'react'
import type { CategoryGroup } from '../types'

const MIN_NOTES = 3

const EXAMPLES: { label: string; notes: string }[] = [
  { label: 'Jordan 1 Chicago', notes: 'jordan 1 retro high og chicago, mens size 10, worn twice, original box' },
  { label: 'iPhone 13', notes: 'iphone 13' },
  { label: 'Mario Kart 8', notes: 'mario kart 8 deluxe nintendo switch, cartridge and case, works perfectly' },
  { label: 'Samsung S23', notes: 'samsung galaxy s23 256gb phantom black, unlocked, screen protector on since day one, no box' },
  { label: 'Adidas Samba', notes: 'adidas samba og white black gum, womens 8, brand new in box, never worn' },
]

const CONDITIONS = ['New', 'Like new', 'Used - good', 'Used - fair', 'For parts']

const PLACEHOLDERS: Record<CategoryGroup | 'auto', string> = {
  auto: 'What are you selling? Even "iphone 13" is enough to start. We will ask for the rest.',
  shoes: 'Brand, model, size, colour, condition, box? e.g. "jordan 1 chicago, mens 10, worn twice"',
  phones: 'Model, storage, colour, locked or unlocked, battery health? e.g. "iphone 13 128gb unlocked"',
  video_games: 'Game, platform, what is included? e.g. "mario kart 8 switch, cartridge and case"',
}

const STEPS = ['Reading your notes', 'Finding similar eBay listings', 'Writing title and specifics', 'Checking against eBay rules']

// Mounted only while loading, so each run starts again from the first step.
function Progress() {
  const [step, setStep] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1600)
    return () => clearInterval(t)
  }, [])

  return (
    <p className="progress" role="status">
      <span className="spinner" aria-hidden /> {STEPS[step]}…
    </p>
  )
}

interface Props {
  notes: string
  category: CategoryGroup | null
  condition: string | null
  loading: boolean
  onNotes: (v: string) => void
  onCategory: (v: CategoryGroup | null) => void
  onCondition: (v: string | null) => void
  onSubmit: () => void
}

export function NotesForm({ notes, category, condition, loading, onNotes, onCategory, onCondition, onSubmit }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const tooShort = notes.trim().length < MIN_NOTES

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [notes])

  function submit(e?: React.FormEvent) {
    e?.preventDefault()
    if (!tooShort && !loading) onSubmit()
  }

  return (
    <form className="notes-form" onSubmit={submit}>
      <div className="notes-box">
        <textarea
          ref={ref}
          value={notes}
          onChange={(e) => onNotes(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit()
          }}
          placeholder={PLACEHOLDERS[category ?? 'auto']}
          rows={2}
          maxLength={2000}
          aria-label="Item notes"
        />
        <div className="condition-row" role="group" aria-label="Condition">
          <span className="chips-label">Condition</span>
          {CONDITIONS.map((c) => (
            <button
              key={c}
              type="button"
              className={`chip ${condition === c ? 'selected' : ''}`}
              aria-pressed={condition === c}
              onClick={() => onCondition(condition === c ? null : c)}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="notes-actions">
          <select
            value={category ?? ''}
            onChange={(e) => onCategory((e.target.value || null) as CategoryGroup | null)}
            aria-label="Category"
          >
            <option value="">Auto-detect category</option>
            <option value="shoes">Shoes</option>
            <option value="phones">Phones</option>
            <option value="video_games">Video games</option>
          </select>
          <button type="submit" className="btn-primary" disabled={tooShort || loading}>
            {loading ? 'Generating…' : 'Generate listing'}
          </button>
        </div>
      </div>

      {loading ? (
        <Progress />
      ) : (
        <div className="chips" aria-label="Example notes">
          <span className="chips-label">Try:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex.label} type="button" className="chip" onClick={() => onNotes(ex.notes)}>
              {ex.label}
            </button>
          ))}
        </div>
      )}
    </form>
  )
}
