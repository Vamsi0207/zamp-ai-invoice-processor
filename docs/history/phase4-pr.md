# Archived Phase 4 PR description

Historical review text, retained for provenance. Use the current [README](../../README.md)
and [validation](../validation.md) for submission status.

Invoices previously needed separate manual API calls for document extraction,
invoice creation and processing. This change adds persistent workflow stages and
an integrated React/TypeScript operations UI for upload, evidence, exact master-data
matching, human confirmation, financial decisions, history, receipts and audit.

The existing deterministic engine is unchanged. Byte-identical uploads reuse one
workflow; confirmation atomically links one immutable invoice, and retries preserve
the engine's unique allocation and current-balance checks. Missing/ambiguous
references never create invented vendor/PO identifiers. Errors are persisted by stage.

Validation: 110 backend tests passed, 2 live-provider tests skipped; 7 frontend
contract tests and 3 real-Chromium end-to-end scenarios passed. TypeScript/Vite build
and built-app HTTP smoke passed. Provider HTTP mocks are explicitly separated from
real local OCR/browser/financial checks. Live Gemini/OpenAI credentials were absent.

Run instructions and five-minute walkthrough: `docs/demo.md`. Architecture and
Gemini variable/network configuration: `docs/phase4.md`. Actual validation evidence:
`docs/validation.md`. Screenshots show real synthetic browser activity.

This branch includes the earlier reconstruction commits because main still contained
only README/.gitignore when work began. No direct main push. This remains a local,
single-process prototype with self-reported reviewer identity, not a public service
with production authentication or a distributed job queue.
