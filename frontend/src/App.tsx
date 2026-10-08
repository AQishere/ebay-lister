import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, createDraft, getDraft, getMarket } from './api'
import { DraftCard } from './components/DraftCard'
import { HowItWorks } from './components/HowItWorks'
import { MarketPanel } from './components/MarketPanel'
import { NotesForm } from './components/NotesForm'
import { QuestionsCard } from './components/QuestionsCard'
import type { CategoryGroup, Draft, Market } from './types'

const REPO_URL = 'https://github.com/AQishere/ebay-lister'

type Theme = 'light' | 'dark'

function draftIdFromPath(): string | null {
  const m = window.location.pathname.match(/^\/d\/([a-f0-9]{24})\/?$/i)
  return m ? m[1] : null
}

function readStoredTheme(): Theme | null {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

export default function App() {
  const [notes, setNotes] = useState('')
  const [category, setCategory] = useState<CategoryGroup | null>(null)
  const [condition, setCondition] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [market, setMarket] = useState<Market | null>(null)
  const [marketLoading, setMarketLoading] = useState(false)
  const [marketError, setMarketError] = useState<string | null>(null)
  const [theme, setTheme] = useState<Theme | null>(readStoredTheme)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme
    else delete document.documentElement.dataset.theme
  }, [theme])

  function toggleTheme() {
    const current = theme ?? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
    const next: Theme = current === 'dark' ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem('theme', next)
    } catch {
      // Storage can be unavailable; the toggle still works for this visit.
    }
  }

  const loadMarket = useCallback(async (id: string) => {
    setMarket(null)
    setMarketError(null)
    setMarketLoading(true)
    try {
      setMarket(await getMarket(id))
    } catch (e) {
      setMarketError(e instanceof ApiError ? e.message : 'Could not load prices.')
    } finally {
      setMarketLoading(false)
    }
  }, [])

  const showDraft = useCallback(
    (d: Draft) => {
      setDraft(d)
      void loadMarket(d.draft_id)
    },
    [loadMarket],
  )

  // Open a shared link (/d/<id>) and follow back/forward navigation.
  useEffect(() => {
    async function fromUrl() {
      const id = draftIdFromPath()
      if (!id) {
        setDraft(null)
        setMarket(null)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const d = await getDraft(id)
        if (d.notes) setNotes(d.notes)
        showDraft(d)
      } catch (e) {
        setError(e instanceof ApiError && e.status === 404 ? 'That draft does not exist.' : 'Could not load that draft.')
      } finally {
        setLoading(false)
      }
    }
    void fromUrl()
    window.addEventListener('popstate', fromUrl)
    return () => window.removeEventListener('popstate', fromUrl)
  }, [showDraft])

  // The condition chip is sent as a line of notes so the backend needs no new field.
  async function generate(text = notes, group = category) {
    const sent = [text.trim(), condition && !/condition:/i.test(text) ? `Condition: ${condition}` : '']
      .filter(Boolean)
      .join('\n')
    setLoading(true)
    setError(null)
    try {
      const d = await createDraft(sent, group)
      window.history.pushState(null, '', `/d/${d.draft_id}`)
      showDraft(d)
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  // Answers become visible lines in the notes box, then the draft is regenerated
  // in the same category, so the seller can see and edit exactly what was sent.
  function answerQuestions(answers: Record<string, string>) {
    if (!draft) return
    const lines = Object.entries(answers)
      .filter(([, v]) => v.trim())
      .map(([field, v]) => `${field}: ${v.trim()}`)
    const next = [notes.trim(), ...lines].join('\n')
    setNotes(next)
    void generate(next, draft.category.group)
  }

  return (
    <>
      <div className="glow" aria-hidden />
      <nav className="nav">
        <a href="/" className="brand">
          Lister<span className="brand-dot">.</span>
        </a>
        <div className="nav-links">
          <a href={REPO_URL} target="_blank" rel="noreferrer">
            GitHub
          </a>
          <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Switch light or dark theme">
            <span className="theme-icon" aria-hidden />
          </button>
        </div>
      </nav>

      <main>
        <section className="hero">
          <p className="eyebrow">AI listing assistant for eBay sellers</p>
          <h1>
            Rough notes in.
            <br />
            <span className="gradient-text">eBay listings</span> out.
          </h1>
          <p className="lede">
            Type what you're selling the way you'd text a friend. Get a title, item specifics and a description grounded in
            real eBay listings, plus what similar items are asking.
          </p>
          <NotesForm
            notes={notes}
            category={category}
            condition={condition}
            loading={loading}
            onNotes={setNotes}
            onCategory={setCategory}
            onCondition={setCondition}
            onSubmit={() => void generate()}
          />
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
        </section>

        {!draft && !loading && <HowItWorks />}

        {draft && (
          <div className="results" ref={resultRef}>
            {draft.questions && draft.questions.length > 0 && (
              <QuestionsCard
                key={`questions-${draft.draft_id}`}
                questions={draft.questions}
                loading={loading}
                onSubmit={answerQuestions}
              />
            )}
            <DraftCard key={`draft-${draft.draft_id}`} draft={draft} market={market} marketLoading={marketLoading} />
            <div className="side">
              <MarketPanel
                market={market}
                loading={marketLoading}
                error={marketError}
                onRetry={() => void loadMarket(draft.draft_id)}
              />
            </div>
          </div>
        )}
      </main>

      <footer className="footer">
        <span>Portfolio project · not affiliated with eBay Inc.</span>
        <span>Prices are asking prices of current listings, not sold prices.</span>
      </footer>
    </>
  )
}
