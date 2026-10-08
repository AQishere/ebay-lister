// Mirrors the Pydantic models in app/models.py.

export type CategoryGroup = 'shoes' | 'phones' | 'video_games'

export interface Example {
  title: string
  price: number | null
  currency: string | null
  sold_quantity: number | null
  item_url: string | null
  score?: number | null
}

export interface Question {
  field: string
  question: string
  options: string[] // empty -> free-text answer
  required: boolean
}

export interface TitleCheck {
  aspect: string
  value: string | null // null -> still unknown
  in_title: boolean
}

export interface PricePlan {
  currency?: string
  fast?: number
  recommended?: number
  max?: number
  units_sold?: number
  units_sold_at_or_below_recommended?: number
  listings?: number
}

export interface Draft {
  draft_id: string
  title: string
  item_specifics: Record<string, string>
  description: string
  category: { id: string | null; name: string | null; group: CategoryGroup }
  condition: string | null
  missing_required: string[]
  missing_info: string[]
  questions?: Question[] // absent on drafts saved before follow-up questions existed
  title_checks?: TitleCheck[]
  examples: Example[]
  retrieval_source: 'vector_search' | 'live_search' | 'none'
  warnings: string[]
  timings_ms: Record<string, number>
  cache?: Record<string, { hits: number; misses: number }>
}

export interface PriceSummary {
  count: number
  label: string
  currency?: string
  p25?: number
  median?: number
  p75?: number
  sales_weighted_median?: number
  condition?: string | null
}

export interface Market {
  draft_id: string
  price: PriceSummary
  plan?: PricePlan
  evidence: Example[]
  note: string
}
