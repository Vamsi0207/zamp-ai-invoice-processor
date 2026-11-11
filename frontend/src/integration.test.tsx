// Frontend HTTP-contract/component tests use explicit fetch mocks. Browser tests use the real API.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api, type Run, type Config } from './api'
import { Badge, Timeline, UploadCard } from './App'

describe('HTTP integration contracts', () => {
  it('shows safe rate-limit messages without auto retrying', async () => {
    const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Shared demo usage limit reached' }), { status: 429 }))
    vi.stubGlobal('fetch', mock)
    await expect(api('/workflows/run/retry', { method: 'POST', body: '{}' })).rejects.toThrow('Shared demo usage limit reached')
    expect(mock).toHaveBeenCalledTimes(1)
  })

  it('disables the unsupported public OpenAI option', () => {
    const config = { providers: { gemini: { configured: false }, openai: { configured: false } }, public_demo: { enabled: true } } as Config
    render(<UploadCard config={config} onUploaded={() => {}}/>)
    expect(screen.getByRole('option', { name: /OpenAI/ })).toBeDisabled()
    expect(screen.getByRole('option', { name: /Manual review/ })).not.toBeDisabled()
  })
  it('sends JSON to actual API paths and preserves error details', async () => {
    const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Select an existing purchase order' }), { status: 422 }))
    vi.stubGlobal('fetch', mock)
    await expect(api('/workflows/run/review', { method: 'POST', body: '{}' })).rejects.toThrow('Select an existing purchase order')
    expect(mock).toHaveBeenCalledWith('/api/workflows/run/review', expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }))
  })

  it('explains schema validation errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ loc: ['body', 'invoice', 'total'], msg: 'Required' }] }), { status: 422 })))
    await expect(api('/workflows/run/review')).rejects.toThrow('invoice.total: Required')
  })

  it('does not assign stage progress based on elapsed time', () => {
    const stages = Object.fromEntries(['upload', 'pdf_extraction', 'ai_extraction', 'matching', 'validation', 'decision'].map(key => [key, { status: key === 'upload' ? 'completed' : 'pending', detail: key === 'upload' ? 'Durably stored' : 'Waiting' }]))
    const run = { stages, status: 'queued', attempt: 1 } as unknown as Run
    render(<Timeline run={run}/>)
    expect(screen.getAllByText('pending')).toHaveLength(5)
    expect(screen.getByText('completed')).toBeInTheDocument()
    expect(screen.queryByText('Approved')).not.toBeInTheDocument()
  })

  it('renders backend decision status', () => {
    render(<Badge status="Review"/>)
    expect(screen.getByText('Needs review')).toBeInTheDocument()
  })

  it('uploads multipart data without inventing an AI result', async () => {
    const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'persisted-run', status: 'queued' }), { status: 202 }))
    vi.stubGlobal('fetch', mock)
    const uploaded = vi.fn()
    render(<UploadCard onUploaded={uploaded}/>)
    const file = new File(['%PDF-actual-bytes'], 'invoice.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Upload invoice PDF'), { target: { files: [file] } })
    await waitFor(() => expect(uploaded).toHaveBeenCalled())
    const form = mock.mock.calls[0][1].body as FormData
    expect(form.get('provider')).toBe('manual')
    expect(form.get('idempotency_key')).toBeTruthy()
    expect(form.get('file')).toBeInstanceOf(File)
    expect(location.hash).toBe('#/runs/persisted-run')
  })

  it('rejects unsupported file types before HTTP upload', () => {
    const mock = vi.fn(); vi.stubGlobal('fetch', mock)
    render(<UploadCard onUploaded={() => {}}/>)
    fireEvent.change(screen.getByLabelText('Upload invoice PDF'), { target: { files: [new File(['x'], 'invoice.txt')] } })
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a PDF file')
    expect(mock).not.toHaveBeenCalled()
  })

  it('shows failed HTTP upload and reuses its retry key', async () => {
    const mock = vi.fn().mockRejectedValueOnce(new Error('Network interrupted')).mockResolvedValueOnce(new Response(JSON.stringify({ id: 'retry-run' }), { status: 202 }))
    vi.stubGlobal('fetch', mock)
    render(<UploadCard onUploaded={() => {}}/>)
    fireEvent.change(screen.getByLabelText('Upload invoice PDF'), { target: { files: [new File(['%PDF-'], 'invoice.pdf', { type: 'application/pdf' })] } })
    await screen.findByText('Network interrupted')
    fireEvent.click(screen.getByText('Retry upload'))
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(2))
    expect((mock.mock.calls[0][1].body as FormData).get('idempotency_key')).toBe((mock.mock.calls[1][1].body as FormData).get('idempotency_key'))
  })
})
