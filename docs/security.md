# Security Notes

This document summarizes the public security posture of the portfolio snapshot.

## Authentication

- HttpOnly cookies are used for browser sessions.
- Refresh-token state is kept in Redis for recovery flows.
- OAuth callbacks use state/nonce and provider-specific validation.
- VK-style flows use PKCE where applicable.
- Logout revokes active sessions through server-side state.

## Request Hardening

- Security middleware adds defensive headers such as CSP, `X-Content-Type-Options`, frame protection, and referrer policy.
- CORS is configured as a whitelist, not a wildcard with credentials.
- Sensitive endpoints are protected by Redis-backed rate limits.
- Upload/session endpoints are designed around explicit ownership checks.

## Data Safety

- Runtime secrets are read from environment variables.
- Production `.env` files, uploads, database dumps, and backups are not part of this repository.
- SQL access goes through SQLAlchemy and parameterized statements.
- JSONB mutation paths explicitly mark changed fields where required by SQLAlchemy.

## Billing And Webhooks

- Payment confirmation paths use idempotency checks.
- Webhook-like flows validate amount/order state before crediting balance.
- Tests cover duplicate payment and mismatch scenarios.

## Logging

- Application logs avoid raw secrets and tokens.
- Structured logs include operational metadata such as case id, user id, duration, and usage estimates where useful.
- External monitoring should be configured with PII collection disabled.

## Review Pointers

- `app/middleware/security.py`
- `app/utils/auth.py`
- `app/utils/rate_limit.py`
- `tests/test_security.py`
- `tests/test_sse_contract.py`
