# ADR 0002: Authentication library (Spike 2)

Date: 2026-11-17. Status: accepted.

**Question.** Is FastAPI Users still a sound choice (spec section 7)?

**Findings.** fastapi-users 15.0.5 (released 2026-03-27, repository active to 2026-08), supports Python 3.10+, async SQLAlchemy. The project declares *maintenance mode*: security updates and dependency maintenance continue, no new features. Alternatives (Authlib, hand-rolled JWT with PyJWT + pwdlib) mean more own code in a security-critical area.

**Decision.** Use FastAPI Users with cookie transport (httpOnly, SameSite=Lax) and JWT strategy, 8 h session expiry, a `role` column (admin/reviewer/viewer), password minimum 10 characters. Everything under `/api/v1` requires login; non-GET routes need reviewer or admin; user management is admin-only.

**Revisit** if security updates stop; the user table and role checks are isolated in `backend/app/auth/`, so replacing the library is contained.

**Consequences.** Argon2/bcrypt hashing via pwdlib; the auth tables use an async SQLAlchemy engine (`app/orm.py`) separate from the legacy `trust.db`.
