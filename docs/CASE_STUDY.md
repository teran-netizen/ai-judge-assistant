# AI Judge Assistant Case Study

## Summary

AI Judge Assistant is a legal-document workflow product that turns large Russian-language case-file uploads into draft legal documents. It combines OCR, document classification, fact extraction, case-context assembly, LLM generation, citation handling, streaming progress, billing gates, and `.docx` export.

This repository is a sanitized portfolio snapshot. It is meant to show the architecture, AI workflow decisions, and production constraints without exposing user data, secrets, backups, or deployment-specific infrastructure.

## Product Problem

Legal teams often work with fragmented case materials: scans, PDFs, photos, text files, contracts, correspondence, and procedural documents. The user does not just need a chatbot answer. They need a structured workflow that can ingest many files, recover from long-running failures, preserve progress, and produce a document that a professional can review and edit.

The product goal was to reduce the time from "I have a pile of case files" to "I have a usable draft and extracted case context".

## Core Workflow

1. User creates a case and uploads files.
2. Upload/session metadata is stored in PostgreSQL.
3. Background workers classify files, run OCR where needed, and extract useful facts.
4. The system builds case context and generates a draft document through a DeepSeek-compatible LLM layer.
5. Redis carries job state and progress events so the frontend can stream updates.
6. The user can refine the generated result in a chat-like flow and export to `.docx`.

## Engineering Decisions

### Async application boundary

FastAPI, SQLAlchemy async sessions, Redis, and arq workers were used because the product is dominated by I/O-heavy work: uploads, OCR calls, LLM calls, streaming responses, payment checks, and background recovery.

### Worker-first generation

Generation and OCR are not handled as normal request/response work. They run through workers with heartbeat and recovery logic, which lets the HTTP API remain responsive while long-running jobs continue independently.

### Progress streaming with recovery

The SSE layer uses Redis-backed state so the frontend can catch up after reconnects instead of losing the progress stream. This matters for large case files, mobile networks, and long LLM responses.

### Context before generation

The system does not send raw uploads directly to the final generation step. It uses classification, OCR, extraction, summarization, reference extraction, and context assembly first. This reduces noise, makes generation more predictable, and gives the product places to recover or inspect intermediate state.

### Explicit schema evolution

Alembic migrations are kept in the repository because the product changed over time: billing models, upload sessions, case runs, ratings, assistants, activity logging, and recovery metadata all evolved with production use.

## AI Engineering Notes

- The LLM layer is isolated behind service modules so model/provider changes do not rewrite the API surface.
- Prompted extraction and summarization are separated from final document generation.
- Token and cost estimates are tracked near generation paths.
- Norm/reference extraction is treated as a separate concern from prose generation.
- Streaming is user-facing, but intermediate state is also persisted for recovery.

## Reliability And Safety

- Uploads use session/chunk concepts rather than assuming small single-request files.
- Workers include recovery/reconciliation paths for interrupted jobs.
- Authentication uses cookies, refresh-token fallback, and revocation support.
- Middleware and tests cover security headers, auth behavior, rate limits, and webhook/payment validation patterns.
- Production secrets, uploads, database dumps, and backups are intentionally excluded from this public snapshot.

## What I Would Improve Next

1. Build a redacted golden-case evaluation suite for extraction quality, citation quality, and final document usefulness.
2. Add deterministic fake OCR/LLM adapters so CI can run more behavioral backend tests without live services.
3. Add OpenTelemetry traces across upload, worker, Redis, LLM, and export stages.
4. Move more prompt/version metadata into explicit records for auditability and regression analysis.
5. Add a small public demo mode with sample redacted case files and fake generation output.

## Why It Is Relevant For AI Companies

This project sits at the intersection of AI product design and production engineering. It is not only a prompt wrapper: it deals with messy input data, long-running jobs, model orchestration, product UX, billing, reliability, security, and document output. Those are the same categories of problems that appear in many applied AI teams.

## Code Review Map

- `app/services/ingest.py` - file classification, OCR/extraction flow, summary creation.
- `app/services/generate_from_context.py` - final LLM generation path and usage tracking.
- `app/services/redis_stream.py` - progress stream state and SSE recovery.
- `app/workers/generation_worker.py` - worker orchestration for long-running jobs.
- `app/api/cases.py` - case lifecycle API surface.
- `app/middleware/security.py` and `app/utils/auth.py` - auth/security mechanics.
- `frontend/src/pages/CasePage.jsx` - primary user workflow in the frontend.
