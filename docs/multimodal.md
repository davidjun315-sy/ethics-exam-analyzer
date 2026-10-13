# Image-first extraction implementation

PDFium renders 144 DPI PNGs and retains asset metadata. Image assets are shared across exam links and extraction runs.
Mock receives real images and optional page text; it does not invoke legacy regex extraction or pretend to perform vision/OCR.
It produces explicitly labeled full-page placeholders. Scans use the same pipeline and can be manually transcribed.

Structured candidates use a strict Pydantic/JSON Schema contract. Valid page references and normalized non-empty boxes are
checked before persistence. Regions are stored separately and referenced from reviewed Questions. Candidate edits keep old
rows inactive; original batch responses and legacy JSON remain unchanged. QuestionAnalysis and publications are independent.

Local jobs execute inline. Redis/RQ jobs persist database state and execute in a separate worker with progress. Object storage
is a Protocol with atomic local and private S3-compatible implementations. Local PDF caches are recovered from private objects
by SHA256. Deployment uses PostgreSQL, Redis and shared object storage, never relying on web/worker disk sharing.

The current provider batches two pages without overlap and makes one placeholder per page. A real provider adapter must add
vision requests, credentials, prompt/schema versioning, overlapping-context stitching and real-document evaluation. No external
API request or paid deployment is made by this implementation. HTTPS single-owner access is gated by ACCESS_PASSWORD.
