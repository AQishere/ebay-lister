import { useState } from 'react'
import type { Question } from '../types'

// Three rows of two keeps every box the same size; "type your own" covers the rest.
const MAX_VISIBLE_OPTIONS = 6

interface Props {
  questions: Question[]
  loading: boolean
  onSubmit: (answers: Record<string, string>) => void
}

// Rendered with a key per draft, so answers reset for each new draft.
export function QuestionsCard({ questions, loading, onSubmit }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const answered = Object.values(answers).filter((v) => v.trim()).length

  function set(field: string, value: string) {
    setAnswers((a) => ({ ...a, [field]: value }))
  }

  return (
    <section className="card questions-card" aria-labelledby="questions-title">
      <header className="questions-head">
        <div>
          <span id="questions-title" className="eyebrow">
            Make it better
          </span>
          <p className="questions-sub">Tap an answer to fill in what your notes didn't say.</p>
        </div>
        <button
          type="button"
          className="btn-primary"
          disabled={answered === 0 || loading}
          onClick={() => onSubmit(answers)}
        >
          {loading ? 'Updating…' : answered ? `Update listing (${answered})` : 'Update listing'}
        </button>
      </header>

      <div className="questions" style={{ ['--cols' as string]: Math.min(questions.length, 3) }}>
        {questions.map((q) => {
          const value = answers[q.field] ?? ''
          const isOption = q.options.includes(value)
          return (
            <div key={q.field} className={`question ${value.trim() ? 'answered' : ''}`}>
              <span className="question-label">{q.question}</span>
              {q.options.length > 0 && (
                <div className="question-options" role="group" aria-label={q.question}>
                  {q.options.slice(0, MAX_VISIBLE_OPTIONS).map((opt) => (
                    <button
                      key={opt}
                      type="button"
                      className={`chip ${value === opt ? 'selected' : ''}`}
                      aria-pressed={value === opt}
                      onClick={() => set(q.field, value === opt ? '' : opt)}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              )}
              <input
                className="question-input"
                placeholder={q.options.length ? 'Or type your own…' : 'Type your answer…'}
                value={isOption ? '' : value}
                onChange={(e) => set(q.field, e.target.value)}
                aria-label={`${q.question} (type your own)`}
              />
            </div>
          )
        })}
      </div>
    </section>
  )
}
