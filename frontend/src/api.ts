export type Provider = 'gemini' | 'openai' | 'manual'
export type Stage = { status: string; detail: string }
export type Line = { po_line_id: string; description: string; quantity: number | string; unit_price: string }
export type Invoice = { vendor_id: string; po_id: string | null; number: string; currency: string; total: string; tax: string; shipping: string; discount: string; lines: Line[] }
export type Evidence = { field: string; page: number; quote: string }
export type Run = {
  id: string; filename: string; status: string; provider: Provider; created_at: string; updated_at: string; attempt: number
  stages: Record<string, Stage>; invoice_id: number | null; draft: Invoice | null
  document: { pages: { page: number; method: string; text: string }[] } | null
  extraction: { invoice: Record<string, unknown>; evidence: Evidence[] } | null
  matching: { issues: string[]; suggested_po_ids: string[]; explanation: string } | null
  error: { code: string; stage: string; message: string } | null
  decision: { decision: string; reasons: string[]; invoice_total_cents: number; previously_allocated_cents: number; po_total_cents: number | null; policy_version: string } | null
  events: { id: number; stage: string; status: string; detail: string; created_at: string }[]
}
export type Config = { providers: Record<'gemini' | 'openai', { configured: boolean; model: string }>; manual_review_available: boolean }
export type Dashboard = { total: number; invoice_count: number; counts: Record<string, number>; recent: Run[] }
export type PO = { id: string; vendor_id: string; currency: string; total_cents: number; remaining_cents: number; allocated_cents: number; tolerance_enabled: boolean; lines: { id: string; description: string; quantity: number; received_quantity: number; unit_price_cents: number }[] }
export type MasterData = { vendors: { id: string; name: string; active: boolean }[]; purchase_orders: PO[] }

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, headers: { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((e: { loc?: string[]; msg: string }) => `${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; ') : `Request failed (${response.status})`
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export function money(cents: number | undefined, currency = 'USD') {
  if (cents === undefined) return '—'
  try { return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(cents / 100) }
  catch { return `${currency} ${(cents / 100).toFixed(2)}` }
}
export function date(value: string) {
  return new Date(value.includes('T') ? value : value.replace(' ', 'T') + 'Z').toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
export const labels: Record<string, string> = {
  upload: 'Document received', pdf_extraction: 'PDF & OCR extraction', ai_extraction: 'AI field extraction', matching: 'Master-data matching', validation: 'Human validation', decision: 'Financial decision',
  HUMAN_CONFIRMATION_REQUIRED: 'Confirm the extracted fields against the source document.', VENDOR_MAPPING_REQUIRED: 'Select a vendor from existing master data.', PO_MAPPING_REQUIRED: 'The PO reference is missing or unmatched. Select the correct purchase order.', PO_LINE_MAPPING_REQUIRED: 'Resolve each invoice line to an existing PO line.', MISSING_FIELDS: 'Some required invoice fields were not present. Enter verified values.',
  ALL_CHECKS_PASSED: 'All financial checks passed.', DUPLICATE_INVOICE: 'This vendor’s invoice number has already been submitted.', INVALID_TOTAL: 'Invoice total does not equal line subtotal + tax + shipping − discount.', PO_BALANCE_EXCEEDED: 'Cumulative invoice value exceeds the authorized PO ceiling.', ORDERED_QUANTITY_EXCEEDED: 'Cumulative invoiced quantity exceeds the ordered quantity.', RECEIPT_SHORTFALL: 'Received quantities do not cover this invoice. Record the receipt before retrying.', UNIT_PRICE_VARIANCE: 'An invoice unit price differs from its PO line.', TOLERANCE_NOT_AUTHORIZED: 'The PO has not authorized a 2% overrun.', WITHIN_AUTHORIZED_2_PERCENT_TOLERANCE: 'The overrun is within this PO’s explicitly authorized 2% tolerance.', UNKNOWN_VENDOR: 'The vendor was not found.', INACTIVE_VENDOR: 'This vendor is inactive.', PO_VENDOR_MISMATCH: 'The PO belongs to a different vendor.', CURRENCY_MISMATCH: 'Invoice currency differs from PO currency.', UNKNOWN_PO_LINE: 'A line reference does not exist on this PO.', PO_REQUIRED: 'An explicit PO reference is required.', PO_NOT_FOUND: 'The referenced PO was not found.',
}
export function explain(code: string) { return labels[code] || code.replaceAll('_', ' ').toLowerCase() }
