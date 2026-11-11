// Real public-mode HTTP/browser checks, synthetic PDFs, no live provider calls.
import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'

async function upload(page: Page, fixture: string) {
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Public synthetic demo' })).toBeVisible()
  await page.getByLabel('Extraction method', { exact: true }).selectOption('manual')
  await page.getByLabel('Upload invoice PDF').setInputFiles(path.resolve('../fixtures', fixture))
  await expect(page).toHaveURL(/#\/runs\//)
}

async function confirm(page: Page, number: string, quantity: number) {
  await expect(page.getByRole('heading', { name: 'Review invoice details' })).toBeVisible()
  await page.getByLabel('Invoice number', { exact: true }).fill(number)
  await page.getByLabel('Vendor', { exact: true }).selectOption('DEMO-VENDOR')
  await page.getByLabel('Purchase order', { exact: true }).selectOption('DEMO-PO')
  await page.getByLabel('Currency', { exact: true }).selectOption('USD')
  await page.getByRole('button', { name: 'Add line' }).click()
  await page.getByLabel('PO line 1', { exact: true }).selectOption('L1')
  await page.getByLabel('Description', { exact: true }).fill('Office chairs')
  await page.getByLabel('Quantity', { exact: true }).fill(String(quantity))
  await page.getByLabel('Unit price', { exact: true }).fill('100.00')
  for (const field of ['Tax', 'Shipping', 'Discount']) await page.getByLabel(field, { exact: true }).fill('0.00')
  await page.getByLabel('Invoice total', { exact: true }).fill(String(quantity * 100))
  await expect(page.getByLabel('Reviewed by')).toHaveValue('demo-reviewer')
  await expect(page.getByLabel('Reviewed by')).not.toBeEditable()
  await expect(page.getByLabel('Review note')).not.toBeEditable()
  await page.getByRole('checkbox').check() // Public mode still requires explicit human confirmation.
  await page.getByRole('button', { name: 'Confirm & process' }).click()
}

test('login-free public dashboard and real approval/duplicate/over-budget controls', async ({ page, request }) => {
  const response = await page.goto('/')
  expect(response?.status()).toBe(200)
  expect(response?.headers()['www-authenticate']).toBeUndefined()
  await expect(page.getByText('Backend connected')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Duplicate variant', exact: true })).toBeVisible()
  await upload(page, 'native_invoice.pdf')
  await confirm(page, 'SYN-001', 4)
  await expect(page.getByRole('heading', { name: 'Approved with confidence.' })).toBeVisible()
  const approved = page.url()
  await upload(page, 'native_invoice.pdf')
  await expect(page).toHaveURL(approved)
  await upload(page, 'duplicate_invoice_variant.pdf')
  await confirm(page, 'SYN-001', 4)
  await expect(page.getByRole('heading', { name: 'This invoice was rejected.' })).toBeVisible()
  await expect(page.getByText('This vendor’s invoice number has already been submitted.')).toBeVisible()
  await upload(page, 'over_budget_invoice.pdf')
  await confirm(page, 'SYN-002', 7)
  await expect(page.getByRole('heading', { name: 'This invoice was rejected.' })).toBeVisible()
  await expect(page.getByText('Cumulative invoice value exceeds the authorized PO ceiling.')).toBeVisible()
  await page.goto('/#/master-data')
  await expect(page.getByRole('button', { name: 'Record receipt' })).toHaveCount(0)
  await expect(page.getByText('Receipts are fixed in this public synthetic demo.')).toBeVisible()
  const data = await (await request.get('http://127.0.0.1:8911/api/master-data')).json()
  expect(data.purchase_orders[0].remaining_cents).toBe(60000)
  expect((await request.post('http://127.0.0.1:8911/api/receipts', { data: {} })).status()).toBe(403)
})
