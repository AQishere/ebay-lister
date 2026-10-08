import type { CategoryGroup, Draft, Market } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check your connection and try again.')
  }
  const body = await resp.json().catch(() => null)
  if (!resp.ok) throw new ApiError(resp.status, errorMessage(resp.status, body))
  return body as T
}

function errorMessage(status: number, body: unknown): string {
  const b = body as { detail?: unknown; error?: string } | null
  if (status === 429) return typeof b?.detail === 'string' ? b.detail : 'Too many requests. Give it a minute and try again.'
  if (b?.error === 'unsupported_category') return 'Only shoes, phones and video games are supported right now.'
  if (status === 422 && Array.isArray(b?.detail)) return 'Type at least a few characters about the item.'
  if (typeof b?.detail === 'string') return b.detail
  return `Something went wrong (${status}).`
}

export const createDraft = (notes: string, category_group: CategoryGroup | null) =>
  request<Draft>('/api/drafts', { method: 'POST', body: JSON.stringify({ notes, category_group }) })

export const getDraft = (id: string) => request<Draft>(`/api/drafts/${encodeURIComponent(id)}`)

export const getMarket = (id: string) => request<Market>(`/api/drafts/${encodeURIComponent(id)}/market`)
