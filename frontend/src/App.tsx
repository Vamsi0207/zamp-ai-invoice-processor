import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Activity, ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpRight, Check, CheckCircle2, ChevronRight, Circle, Clock3, Database, FileCheck2, FileText, History, Inbox, LayoutDashboard, Loader2, Plus, RefreshCw, Search, ShieldCheck, Sparkles, Trash2, TriangleAlert, UploadCloud, X, XCircle } from 'lucide-react'
import { api, date, explain, labels, money, type Config, type Dashboard, type Invoice, type MasterData, type Provider, type Run } from './api'
import { useQuery, useRoute } from './hooks'

const activeStates = ['queued', 'processing']
const stageNames = ['upload', 'pdf_extraction', 'ai_extraction', 'matching', 'validation', 'decision']

export function Badge({ status }: { status: string }) {
  const display = status === 'Review' ? 'Needs review' : status === 'failed' ? 'Failed' : activeStates.includes(status) ? 'Processing' : status
  const Icon = status === 'Approved' ? CheckCircle2 : status === 'Rejected' ? XCircle : status === 'Review' ? Clock3 : status === 'failed' ? TriangleAlert : Loader2
  return <span className={`badge badge-${status.toLowerCase()}`}><Icon size={13} aria-hidden="true" className={activeStates.includes(status) ? 'animate-spin' : ''} />{display}</span>
}

function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return <div className="error-box" role="alert"><TriangleAlert size={18}/><div><strong>Something needs your attention</strong><p>{error}</p></div>{retry && <button className="button subtle" onClick={retry}><RefreshCw size={14}/>Retry</button>}</div>
}

function Loading() { return <div className="loading" role="status"><Loader2 size={20} className="animate-spin"/>Loading workspace…</div> }

export function UploadCard({ config, onUploaded, compact = false }: { config?: Config; onUploaded: () => void; compact?: boolean }) {
  const [provider, setProvider] = useState<Provider>('manual')
  const [touched, setTouched] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [lastFile, setLastFile] = useState<File>()
  const attempt = useRef<{ file: File; key: string } | null>(null)
  const inputId = compact ? 'upload-modal-file' : 'upload-dashboard-file'
  useEffect(() => {
    if (!touched && config) setProvider(config.providers.gemini.configured ? 'gemini' : config.providers.openai.configured ? 'openai' : 'manual')
  }, [config, touched])
  async function upload(file: File) {
    if (busy) return
    setLastFile(file); setError('')
    if (!file.name.toLowerCase().endsWith('.pdf')) { setError('Choose a PDF file. Other file formats are not supported.'); return }
    if (file.size > 10 * 1024 * 1024) { setError('This file exceeds the 10 MiB limit.'); return }
    if (!attempt.current || attempt.current.file !== file) attempt.current = { file, key: crypto.randomUUID() }
    const form = new FormData()
    form.set('file', file, file.name); form.set('provider', provider); form.set('idempotency_key', attempt.current.key)
    setBusy(true)
    try {
      const run = await api<Run>('/workflows', { method: 'POST', body: form })
      location.hash = `/runs/${run.id}`; onUploaded()
    } catch (e) { setError(e instanceof Error ? e.message : 'Upload failed. Retry the same file safely.') }
    finally { setBusy(false) }
  }
  return <section className={`upload-card ${compact ? 'compact' : ''}`}>
    <div className="eyebrow"><Sparkles size={14}/>DOCUMENT INTAKE</div>
    <div className="upload-intro"><div><h2>Bring your next invoice.</h2><p>One PDF. A clear path from source to decision.</p></div><span className="small-pill">PDF → decision</span></div>
    <div className={`drop-zone ${dragging ? 'dragging' : ''} ${busy ? 'is-busy' : ''}`}
      onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}
      onDrop={e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files.length > 1) setError('Upload one invoice PDF at a time.'); else if (e.dataTransfer.files[0]) void upload(e.dataTransfer.files[0]) }}>
      <span className="upload-icon">{busy ? <Loader2 className="animate-spin" size={25}/> : <UploadCloud size={25}/>}</span>
      <strong>{busy ? `Uploading ${lastFile?.name}…` : 'Drop an invoice here'}</strong>
      <p>{busy ? 'Waiting for the backend to store your document.' : 'or select a PDF from your computer'}</p>
      <label className={`button secondary ${busy ? 'disabled' : ''}`} htmlFor={inputId}><Plus size={15}/>Browse files</label>
      <input id={inputId} aria-label="Upload invoice PDF" className="sr-only" type="file" accept="application/pdf,.pdf" disabled={busy} onChange={e => { if (e.target.files?.[0]) void upload(e.target.files[0]); e.target.value = '' }}/>
      <span className="drop-limit">PDF only · Up to 10 MiB · 20 pages</span>
    </div>
    <div className="upload-settings"><label htmlFor={`${inputId}-provider`}>Extraction method</label><select id={`${inputId}-provider`} aria-label="Extraction method" value={provider} disabled={busy} onChange={e => { setTouched(true); setProvider(e.target.value as Provider) }}>
      <option value="gemini">Gemini {config?.providers.gemini.configured ? '· configured' : '· not configured'}</option>
      <option value="openai">OpenAI {config?.providers.openai.configured ? '· configured' : '· not configured'}</option><option value="manual">Manual review · no AI call</option>
    </select></div>
    <p className="upload-footnote"><ShieldCheck size={14}/>{provider === 'manual' ? 'Real PDF text extraction. You enter and verify the invoice fields.' : 'Fields are evidence-backed. Human confirmation is required.'}</p>
    {error && <><ErrorBox error={error}/>{lastFile && <button className="button secondary" onClick={() => void upload(lastFile)} disabled={busy}>Retry upload</button>}</>}
  </section>
}

function RunTable({ runs, empty = 'Your invoice queue is clear.' }: { runs: Run[]; empty?: string }) {
  if (!runs.length) return <div className="empty"><span className="empty-icon"><Inbox size={28}/></span><h3>{empty}</h3><p>Upload a PDF to start a real processing run.</p></div>
  return <div className="table-scroll"><table className="runs-table"><thead><tr><th>Invoice / document</th><th>Status</th><th>Current stage</th><th>Amount</th><th>Received</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>{runs.map(run => {
    const stage = stageNames.find(s => ['running', 'failed', 'needs_review'].includes(run.stages[s].status))
    return <tr key={run.id}><td><a className="document-cell" href={`#/runs/${run.id}`}><span className="file-icon"><FileText size={19}/></span><span><strong>{run.draft?.number || run.filename}</strong><small>{run.draft?.number ? run.filename : `Run ${run.id.slice(0, 8)}`} · {run.provider === 'manual' ? 'Manual review' : run.provider}</small></span></a></td><td><Badge status={run.status}/></td><td className="muted">{stage ? labels[stage] : run.invoice_id ? 'Decision recorded' : 'Waiting to start'}</td><td className="amount">{run.decision ? money(run.decision.invoice_total_cents, run.draft?.currency) : run.draft?.total ? money(Math.round(Number(run.draft.total) * 100), run.draft.currency) : '—'}</td><td className="muted nowrap">{date(run.created_at)}</td><td><a className="icon-link" aria-label={`Open ${run.filename}`} href={`#/runs/${run.id}`}><ChevronRight size={18}/></a></td></tr>
  })}</tbody></table></div>
}

function DashboardView({ summary, config, uploaded }: { summary?: Dashboard; config?: Config; uploaded: () => void }) {
  const metrics = [{ label: 'Documents received', value: summary?.total, icon: FileText, color: 'purple', note: `${summary?.invoice_count ?? '—'} confirmed invoices` },
    { label: 'Approved', value: summary ? summary.counts.Approved || 0 : undefined, icon: CheckCircle2, color: 'green', note: 'Validated & allocated' },
    { label: 'Needs review', value: summary ? summary.counts.Review || 0 : undefined, icon: Clock3, color: 'amber', note: 'Human action required' },
    { label: 'Rejected', value: summary ? summary.counts.Rejected || 0 : undefined, icon: XCircle, color: 'rose', note: 'Financial checks blocked' }]
  return <><div className="metrics">{metrics.map(m => <section className="metric" key={m.label}><div className="metric-top"><span>{m.label}</span><m.icon size={18} className={`text-${m.color}`}/></div><strong>{m.value ?? '—'}</strong><small>{m.note}</small></section>)}</div>
    <div className="intake-grid"><UploadCard config={config} onUploaded={uploaded}/><aside className="assurance-card"><span className="assurance-icon"><ShieldCheck size={27}/></span><div className="eyebrow">BUILT FOR CONFIDENCE</div><h2>Every decision.<br/>Fully accounted for.</h2><p>Automation with a trail you can follow, from the original document to the PO balance.</p><ul><li><Check size={16}/>Source evidence for extracted fields</li><li><Check size={16}/>Deterministic financial checks</li><li><Check size={16}/>Atomic allocations & safe retries</li></ul><a href="#/master-data">Explore your master data <ArrowUpRight size={15}/></a><div className="assurance-decoration" aria-hidden="true"><FileCheck2 size={82} strokeWidth={0.8}/></div></aside></div>
    <section className="panel recent-panel"><div className="panel-heading"><div><h2>Recent activity <span className="count-tag">{summary?.total ?? '—'}</span></h2><p>A live view of your invoice pipeline.</p></div><a className="text-link" href="#/history">View all runs <ArrowRight size={15}/></a></div>{summary ? <RunTable runs={summary.recent}/> : <Loading/>}</section>
    <div className="bottom-note"><ShieldCheck size={14}/>Decisions come from your financial engine. No simulated results.<a href="/api/samples/native" download>Download a synthetic sample <ArrowDownToLine size={13}/></a></div>
  </>
}

function HistoryView({ reviewOnly }: { reviewOnly: boolean }) {
  const [filter, setFilter] = useState(reviewOnly ? 'Review' : '')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const query = useQuery<{ items: Run[]; total: number }>(`/workflows?limit=20&offset=${offset}&status=${encodeURIComponent(filter)}&search=${encodeURIComponent(search)}`, 3000)
  return <section className="panel"><div className="history-controls"><div className="filter-tabs" aria-label="Filter by status">{(reviewOnly ? ['Review'] : ['', 'Review', 'Approved', 'Rejected', 'failed']).map(f => <button key={f} className={filter === f ? 'active' : ''} onClick={() => { setFilter(f); setOffset(0) }}>{f === '' ? 'All runs' : f === 'Review' ? 'Needs review' : f === 'failed' ? 'Failed' : f}</button>)}</div><label className="search-box"><Search size={16}/><input aria-label="Search runs" placeholder="Search document or invoice…" value={search} onChange={e => { setSearch(e.target.value); setOffset(0) }}/></label></div>
    {query.error && <ErrorBox error={query.error} retry={query.refresh}/>} {query.data ? <RunTable runs={query.data.items} empty={reviewOnly ? 'No invoices awaiting review.' : 'No matching runs.'}/> : <Loading/>}
    <div className="pagination"><span>{query.data?.total ?? '—'} runs{query.data?.total ? ` · ${offset + 1}–${Math.min(offset + 20, query.data.total)}` : ''}</span><div><button className="button subtle" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button><button className="button subtle" disabled={!query.data || offset + 20 >= query.data.total} onClick={() => setOffset(offset + 20)}>Next</button></div></div>
  </section>
}

export function Timeline({ run }: { run: Run }) {
  return <section className="panel timeline-panel"><div className="panel-heading"><div><h2>Processing timeline</h2><p>Recorded backend stages · Attempt {run.attempt}</p></div>{activeStates.includes(run.status) && <span className="live-label"><span/>Live</span>}</div><ol className="timeline">{stageNames.map((stage, i) => {
    const state = run.stages[stage]
    const Icon = state.status === 'completed' ? Check : state.status === 'running' ? Loader2 : state.status === 'failed' ? X : state.status === 'needs_review' ? Clock3 : state.status === 'skipped' ? ArrowRight : Circle
    return <li key={stage} className={`stage stage-${state.status}`}><div className="stage-marker"><Icon size={15} className={state.status === 'running' ? 'animate-spin' : ''}/></div><div><strong>{labels[stage]}</strong><p>{state.detail}</p></div><span>{state.status.replace('_', ' ')}</span>{i < stageNames.length - 1 && <i/>}</li>
  })}</ol></section>
}

function SourcePanel({ run }: { run: Run }) {
  const [tab, setTab] = useState('evidence')
  return <section className="panel source-panel"><div className="panel-heading"><div><h2>Source & evidence</h2><p>The document behind every extracted value.</p></div><a className="icon-link" href={`/api/workflows/${run.id}/pdf`} aria-label="Download original PDF" download><ArrowDownToLine size={18}/></a></div><div className="source-tabs"><button className={tab === 'evidence' ? 'active' : ''} onClick={() => setTab('evidence')}>Field evidence</button><button className={tab === 'text' ? 'active' : ''} onClick={() => setTab('text')}>Document text</button></div>
    <div className="source-content">{tab === 'evidence' ? run.extraction?.evidence.length ? run.extraction.evidence.map((e, i) => <div className="evidence" key={i}><div><strong>{e.field.replaceAll('_', ' ')}</strong><span>PAGE {e.page}</span></div><blockquote>“{e.quote}”</blockquote></div>) : <div className="empty small"><FileText size={25}/><h3>No AI evidence recorded</h3><p>{run.provider === 'manual' ? 'Manual mode does not generate AI fields. Read the document text and enter verified values.' : 'Evidence appears after a successful AI extraction.'}</p><button className="text-link" onClick={() => setTab('text')}>Read document text <ArrowRight size={14}/></button></div> : run.document?.pages.map(page => <section className="source-page" key={page.page}><div className="eyebrow">PAGE {page.page} <span>{page.method === 'ocr' ? 'OCR text' : 'Native PDF text'}</span></div><pre>{page.text}</pre></section>) || <p className="muted">The PDF extraction has not completed.</p>}</div>
  </section>
}

function ReviewForm({ run, master, onSaved }: { run: Run; master: MasterData; onSaved: () => void }) {
  const [form, setForm] = useState<Invoice>(() => ({ vendor_id: '', po_id: null, number: '', currency: '', total: '', tax: '', shipping: '', discount: '', lines: [], ...run.draft } as Invoice))
  const [reviewer, setReviewer] = useState('')
  const [note, setNote] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const po = master.purchase_orders.find(p => p.id === form.po_id)
  const set = (name: string, value: unknown) => setForm(f => ({ ...f, [name]: value }))
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      await api(`/workflows/${run.id}/review`, { method: 'POST', body: JSON.stringify({ invoice: { ...form, lines: form.lines.map(l => ({ ...l, quantity: Number(l.quantity) })) }, reviewer, note, confirmed }) })
      onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to confirm invoice') }
    finally { setBusy(false) }
  }
  const lineSet = (index: number, field: string, value: unknown) => setForm(f => ({ ...f, lines: f.lines.map((l, i) => i === index ? { ...l, [field]: value } : l) }))
  return <section className="panel review-panel"><div className="panel-heading"><div><div className="eyebrow amber">HUMAN CHECKPOINT</div><h2>Review invoice details</h2><p>Verify the source, resolve mappings, then run financial checks.</p></div><ShieldCheck size={23} className="muted"/></div>
    {run.matching && <div className="matching-notice"><TriangleAlert size={18}/><div><strong>Review before processing</strong><ul>{run.matching.issues.map(code => <li key={code}>{explain(code)}</li>)}</ul>{!!run.matching.suggested_po_ids.length && <p>Suggested POs: <strong>{run.matching.suggested_po_ids.join(', ')}</strong> · Choose explicitly below.</p>}</div></div>}
    <form onSubmit={submit} className="review-form"><fieldset disabled={busy}><legend className="sr-only">Invoice fields and master-data mappings</legend><div className="form-grid">
      <label>Invoice number<input required value={form.number || ''} onChange={e => set('number', e.target.value)} placeholder="As printed on invoice"/></label>
      <label>Vendor<select aria-label="Vendor" required value={form.vendor_id} onChange={e => { set('vendor_id', e.target.value); set('po_id', null); setForm(f => ({ ...f, lines: f.lines.map(l => ({ ...l, po_line_id: '' })) })) }}><option value="">Select existing vendor</option>{master.vendors.map(v => <option key={v.id} value={v.id}>{v.name} · {v.id}{!v.active && ' (inactive)'}</option>)}</select></label>
      <label>Purchase order<select aria-label="Purchase order" required value={form.po_id || ''} onChange={e => { set('po_id', e.target.value || null); setForm(f => ({ ...f, lines: f.lines.map(l => ({ ...l, po_line_id: '' })) })) }}><option value="">Select existing PO</option>{master.purchase_orders.filter(p => p.vendor_id === form.vendor_id).map(p => <option key={p.id} value={p.id}>{p.id} · {money(p.remaining_cents, p.currency)} remaining</option>)}</select></label>
      <label>Currency<select required aria-label="Currency" value={form.currency || ''} onChange={e => set('currency', e.target.value)}><option value="">Select printed currency</option>{Array.from(new Set(['USD', 'EUR', 'GBP', 'INR', ...master.purchase_orders.map(p => p.currency)])).map(c => <option key={c}>{c}</option>)}</select></label>
    </div>
    {po && <div className="po-context"><Database size={15}/><span>PO ceiling <strong>{money(po.total_cents, po.currency)}</strong></span><span>Allocated <strong>{money(po.allocated_cents, po.currency)}</strong></span><span>{po.tolerance_enabled ? '2% tolerance authorized' : 'No tolerance authorized'}</span></div>}
    <div className="section-title"><h3>Invoice lines</h3><button type="button" className="text-link" onClick={() => set('lines', [...form.lines, { po_line_id: '', description: '', quantity: '', unit_price: '' }])}><Plus size={14}/>Add line</button></div>
    {!form.lines.length && <p className="field-help">No lines have been extracted. Add a line and verify it against the PDF.</p>}
    {form.lines.map((line, index) => <div className="line-form" key={index}><div className="line-heading"><strong>Line {index + 1}</strong><button type="button" className="icon-link" aria-label={`Remove line ${index + 1}`} onClick={() => set('lines', form.lines.filter((_, i) => i !== index))}><Trash2 size={15}/></button></div><div className="form-grid"><label>PO line<select required aria-label={`PO line ${index + 1}`} value={line.po_line_id} onChange={e => lineSet(index, 'po_line_id', e.target.value)}><option value="">Select PO line</option>{po?.lines.map(l => <option key={l.id} value={l.id}>{l.id} · {l.description} · {l.received_quantity}/{l.quantity} received</option>)}</select></label><label>Description<input required value={line.description || ''} onChange={e => lineSet(index, 'description', e.target.value)}/></label><label>Quantity<input required type="number" min="1" step="1" value={line.quantity ?? ''} onChange={e => lineSet(index, 'quantity', e.target.value)}/></label><label>Unit price<input required type="number" min="0" step="0.01" value={line.unit_price ?? ''} onChange={e => lineSet(index, 'unit_price', e.target.value)}/></label></div></div>)}
    <div className="section-title"><h3>Amounts <span className="muted">{form.currency}</span></h3><span className="field-help">Use explicit zeroes where verified.</span></div><div className="form-grid amounts-grid">{(['tax', 'shipping', 'discount', 'total'] as const).map(field => <label key={field} className={field === 'total' ? 'total-field' : ''}>{field === 'total' ? 'Invoice total' : field[0].toUpperCase() + field.slice(1)}<input required type="number" min="0" step="0.01" value={form[field] ?? ''} onChange={e => set(field, e.target.value)} /></label>)}</div>
    <div className="review-signoff"><label>Reviewed by<input required maxLength={120} placeholder="Your name" value={reviewer} onChange={e => setReviewer(e.target.value)}/></label><label>Review note<textarea required maxLength={2000} placeholder="What did you verify or resolve?" value={note} onChange={e => setNote(e.target.value)}/></label><label className="checkbox-label"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/><span>I checked the invoice fields and PO mappings against the source document.</span></label></div>
    {error && <ErrorBox error={error}/>}<div className="form-footer"><p><ShieldCheck size={14}/>Confirmation records an audit entry.<br/>The financial engine makes the decision.</p><button className="button primary" disabled={busy || !form.lines.length}>{busy ? <Loader2 size={16} className="animate-spin"/> : <ShieldCheck size={16}/>}Confirm & process</button></div>
    </fieldset></form>
  </section>
}

function DecisionPanel({ run }: { run: Run }) {
  if (!run.decision) return null
  return <section className={`panel decision-panel decision-${run.status.toLowerCase()}`}><div className="decision-header"><span className="decision-icon">{run.status === 'Approved' ? <ShieldCheck size={29}/> : run.status === 'Rejected' ? <XCircle size={29}/> : <Clock3 size={29}/>}</span><div><div className="eyebrow">FINANCIAL ENGINE RESULT</div><h2>{run.status === 'Approved' ? 'Approved with confidence.' : run.status === 'Rejected' ? 'This invoice was rejected.' : 'This invoice needs attention.'}</h2></div><Badge status={run.status}/></div><ul className="decision-reasons">{run.decision.reasons.map(r => <li key={r}><ChevronRight size={15}/>{explain(r)}</li>)}</ul><div className="decision-amounts"><div><span>Invoice amount</span><strong>{money(run.decision.invoice_total_cents, run.draft?.currency)}</strong></div><div><span>Previously allocated</span><strong>{money(run.decision.previously_allocated_cents, run.draft?.currency)}</strong></div><div><span>PO ceiling</span><strong>{run.decision.po_total_cents === null ? '—' : money(run.decision.po_total_cents, run.draft?.currency)}</strong></div></div><p className="field-help">{run.decision.policy_version} · Invoice #{run.invoice_id} · Approved allocations are committed atomically. This application does not initiate payments.</p></section>
}

function AuditTrail({ run }: { run: Run }) {
  return <section className="panel audit-panel"><div className="panel-heading"><div><h2>Audit trail</h2><p>Persisted events, in the order they happened.</p></div><History size={19} className="muted"/></div><div className="audit-list">{run.events.map(event => {
    let detail: ReactNode = event.detail
    if (event.status === 'confirmed') { try { const parsed = JSON.parse(event.detail); detail = <><strong>{parsed.reviewer}</strong> · {parsed.note}</> } catch { /* retain original safe React text */ } }
    return <div key={event.id} className="audit-event"><span className="audit-dot"/><div><strong>{labels[event.stage] || 'Workflow'} <span>{event.status.replaceAll('_', ' ')}</span></strong><p>{detail}</p><time>{date(event.created_at)} · local time</time></div></div>
  })}</div></section>
}

function RunDetail({ id, master, config, refreshWorkspace }: { id: string; master?: MasterData; config?: Config; refreshWorkspace: () => void }) {
  const query = useQuery<Run>(`/workflows/${encodeURIComponent(id)}`, 1500)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retryProvider, setRetryProvider] = useState<Provider | ''>('')
  const run = query.data
  async function retry() {
    setBusy(true); setError('')
    try { await api(`/workflows/${id}/retry`, { method: 'POST', body: JSON.stringify(retryProvider ? { provider: retryProvider } : {}) }); query.refresh(); refreshWorkspace() }
    catch (e) { setError(e instanceof Error ? e.message : 'Retry failed') }
    finally { setBusy(false) }
  }
  if (!run) return query.error ? <ErrorBox error={query.error} retry={query.refresh}/> : <Loading/>
  return <><a className="back-link" href="#/history"><ArrowLeft size={15}/>All processing runs</a><div className="detail-heading"><div><div className="eyebrow">RUN {run.id.slice(0, 8)} · {run.provider.toUpperCase()}</div><h1>{run.draft?.number || run.filename}</h1><p>{run.filename} · Received {date(run.created_at)}</p></div><Badge status={run.status}/></div>
    {(query.error || error) && <ErrorBox error={error || query.error} retry={query.refresh}/>}
    {run.error && <div className="failure-card"><ErrorBox error={`${run.error.message} (${run.error.code})`}/><div className="failure-actions">{!run.invoice_id && <select aria-label="Retry extraction method" value={retryProvider} onChange={e => setRetryProvider(e.target.value as Provider | '')}><option value="">Keep {run.provider}</option><option value="manual">Switch to manual review</option><option value="gemini">Gemini{!config?.providers.gemini.configured && ' (not configured)'}</option><option value="openai">OpenAI{!config?.providers.openai.configured && ' (not configured)'}</option></select>}<button className="button secondary" disabled={busy} onClick={() => void retry()}><RefreshCw size={15} className={busy ? 'animate-spin' : ''}/>Retry safely</button></div></div>}
    <DecisionPanel run={run}/>
    {run.status === 'Review' && run.invoice_id && <div className="review-retry"><p>The confirmed invoice is preserved. Resolve the discrepancy in master data, then rerun financial checks.</p><a className="text-link" href="#/master-data">Master data <ArrowUpRight size={14}/></a><button className="button secondary" disabled={busy} onClick={() => void retry()}><RefreshCw size={15}/>Rerun checks</button></div>}
    <div className="details-grid"><div className="detail-main"><Timeline run={run}/>{run.status === 'Review' && !run.invoice_id && (master ? <ReviewForm key={run.id} run={run} master={master} onSaved={() => { query.refresh(); refreshWorkspace() }}/> : <Loading/>)}{run.invoice_id && run.draft && <section className="panel confirmed-fields"><div className="panel-heading"><div><h2>Confirmed invoice</h2><p>Immutable submission retained for this decision.</p></div><FileCheck2 size={21}/></div><dl>{Object.entries(run.draft).filter(([k]) => k !== 'lines').map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value ?? '—')}</dd></div>)}</dl><div className="table-scroll"><table><thead><tr><th>PO line</th><th>Description</th><th>Quantity</th><th>Unit price</th></tr></thead><tbody>{run.draft.lines.map((line, i) => <tr key={i}><td>{line.po_line_id}</td><td>{line.description}</td><td>{line.quantity}</td><td>{line.unit_price}</td></tr>)}</tbody></table></div></section>}<AuditTrail run={run}/></div><SourcePanel run={run}/></div>
  </>
}

function MasterDataView({ master, refresh }: { master?: MasterData; refresh: () => void }) {
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function receipt(e: FormEvent<HTMLFormElement>, poId: string) {
    e.preventDefault(); const form = new FormData(e.currentTarget); setBusy(true); setError('')
    try { await api('/receipts', { method: 'POST', body: JSON.stringify({ id: crypto.randomUUID(), po_id: poId, po_line_id: form.get('line'), quantity: Number(form.get('quantity')) }) }); setSelected(''); refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to record receipt') }
    finally { setBusy(false) }
  }
  if (!master) return <Loading/>
  return <>{error && <ErrorBox error={error}/>}<div className="master-intro"><Database size={21}/><p>Match invoices against real vendors, purchase orders and received quantities. No identifiers are generated on your behalf.</p></div><section className="panel"><div className="panel-heading"><div><h2>Vendors</h2><p>{master.vendors.length} master-data records</p></div></div><div className="vendor-grid">{master.vendors.length ? master.vendors.map(v => <div className="vendor-card" key={v.id}><span className="vendor-avatar">{v.name.slice(0, 1)}</span><div><strong>{v.name}</strong><p>{v.id}</p></div><span className={`small-pill ${v.active ? 'green' : ''}`}>{v.active ? 'Active' : 'Inactive'}</span></div>) : <p className="muted">No vendors yet. Seed the synthetic demo dataset or use the documented vendor API.</p>}</div></section><div className="section-title master-title"><h2>Purchase orders</h2><span className="count-tag">{master.purchase_orders.length}</span></div><div className="po-grid">{master.purchase_orders.map(po => <section className="panel po-card" key={po.id}><div className="panel-heading"><div><div className="eyebrow">{po.vendor_id}</div><h2>{po.id}</h2></div><Database size={20} className="text-purple"/></div><div className="po-values"><div><span>Remaining balance</span><strong>{money(po.remaining_cents, po.currency)}</strong></div><div><span>Original ceiling</span><b>{money(po.total_cents, po.currency)}</b></div></div><div className="balance-track"><span style={{ width: `${Math.min(100, Math.max(0, po.allocated_cents / (po.total_cents || 1) * 100))}%` }}/></div><p className="field-help">{po.tolerance_enabled ? 'Conditional 2% tolerance authorized' : 'Tolerance not authorized'}</p><div className="po-lines">{po.lines.map(line => <div key={line.id}><span><strong>{line.id} · {line.description}</strong><small>{money(line.unit_price_cents, po.currency)} per unit</small></span><span>{line.received_quantity} / {line.quantity}<small>units received</small></span></div>)}</div>{selected === po.id ? <form className="receipt-form" onSubmit={e => void receipt(e, po.id)}><label>PO receipt line<select required name="line">{po.lines.map(l => <option key={l.id} value={l.id}>{l.id} · {l.description}</option>)}</select></label><label>Quantity received<input required name="quantity" type="number" min="1" step="1"/></label><div><button className="button primary" disabled={busy}>Save receipt</button><button type="button" className="button subtle" onClick={() => setSelected('')}>Cancel</button></div></form> : <button className="button secondary full-width" onClick={() => setSelected(po.id)}><Plus size={14}/>Record receipt</button>}</section>)}</div></>
}

export default function App() {
  const route = useRoute()
  const summary = useQuery<Dashboard>('/dashboard', 4000)
  const config = useQuery<Config>('/configuration', 10000)
  const master = useQuery<MasterData>('/master-data', 8000)
  const [uploadOpen, setUploadOpen] = useState(false)
  const modalRef = useRef<HTMLDialogElement>(null)
  const isDetail = route.startsWith('/runs/')
  const section = isDetail ? 'history' : route.slice(1) || 'dashboard'
  const titles: Record<string, [string, string]> = { dashboard: ['Invoice operations', 'From invoice to decision. Every step, accounted for.'], history: ['Processing history', 'Every document, decision and retry in one place.'], review: ['Human review', 'Resolve uncertainty. Keep every decision grounded.'], 'master-data': ['Master data', 'The source of truth for matching and financial validation.'] }
  const title = titles[section] || titles.dashboard
  function refresh() { summary.refresh(); master.refresh() }
  useEffect(() => { if (uploadOpen) modalRef.current?.showModal(); else modalRef.current?.close() }, [uploadOpen])
  const nav = [{ id: 'dashboard', href: '#/', icon: LayoutDashboard, label: 'Overview' }, { id: 'history', href: '#/history', icon: History, label: 'All invoices' }, { id: 'review', href: '#/review', icon: FileCheck2, label: 'Needs review' }, { id: 'master-data', href: '#/master-data', icon: Database, label: 'Master data' }]
  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="#/" aria-label="Zamp home"><span className="brand-symbol">z</span>zamp<span className="brand-period">.</span></a><div className="workspace-switch"><span className="workspace-avatar">Z</span><div><strong>Invoice workspace</strong><small>PS-1 · Local environment</small></div><ChevronRight size={14}/></div><div className="nav-label">WORKSPACE</div><nav>{nav.map(item => <a key={item.id} aria-label={item.label} className={section === item.id ? 'active' : ''} href={item.href}><item.icon size={18}/><span>{item.label}</span>{item.id === 'review' && !!summary.data?.counts.Review && <b>{summary.data.counts.Review}</b>}</a>)}</nav><div className="sidebar-note"><span className="sidebar-note-icon"><ShieldCheck size={20}/></span><strong>Clarity at every step.</strong><p>Real documents.<br/>Traceable decisions.</p></div><div className="provider-status"><span className={`status-dot ${config.data?.providers.gemini.configured ? 'online' : ''}`}/><div><strong>{config.data?.providers.gemini.configured ? 'Gemini configured' : 'Manual review available'}</strong><small>{config.data?.providers.gemini.configured ? config.data.providers.gemini.model : 'No live Gemini key configured'}</small></div></div><div className="sidebar-footer"><span className="profile-avatar">AP</span><div><strong>Accounts payable</strong><small>Local demo workspace</small></div></div></aside>
    <div className="main-shell"><header className="topbar"><div>Workspace <ChevronRight size={13}/><strong>{isDetail ? 'Run details' : title[0]}</strong></div><span className="workspace-health"><span className={`status-dot ${summary.data && !summary.error ? 'online' : ''}`}/>{summary.error ? 'Connection interrupted' : summary.data ? 'Backend connected' : 'Connecting…'}</span></header><main><div className="page-heading" hidden={isDetail}><div><div className="eyebrow">ACCOUNTS PAYABLE</div><h1>{title[0]}</h1><p>{title[1]}</p></div><button className="button primary" onClick={() => setUploadOpen(true)}><Plus size={17}/>Upload invoice</button></div>
      {(summary.error || master.error || config.error) && <ErrorBox error={summary.error || master.error || config.error} retry={() => { refresh(); config.refresh() }}/>}
      {isDetail ? <RunDetail key={route} id={route.split('/')[2]} master={master.data} config={config.data} refreshWorkspace={refresh}/> : section === 'history' || section === 'review' ? <HistoryView key={section} reviewOnly={section === 'review'}/> : section === 'master-data' ? <MasterDataView master={master.data} refresh={master.refresh}/> : <DashboardView summary={summary.data} config={config.data} uploaded={refresh}/>}
    </main><footer className="app-footer"><span>Zamp PS-1 <span>·</span> Invoice intelligence, with control.</span><span><ShieldCheck size={13}/>Auditable by design</span></footer></div>
    <dialog ref={modalRef} onCancel={() => setUploadOpen(false)} onClick={e => { if (e.target === e.currentTarget) setUploadOpen(false) }} aria-label="Upload an invoice">{uploadOpen && <><button className="modal-close icon-link" aria-label="Close upload" onClick={() => setUploadOpen(false)}><X size={20}/></button><UploadCard compact config={config.data} onUploaded={() => { setUploadOpen(false); refresh() }}/></>}</dialog>
  </div>
}
