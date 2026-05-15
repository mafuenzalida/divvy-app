# Security

## Reporting

Please report security issues privately to the repository maintainers (do not open a public issue for undisclosed vulnerabilities).

## Data stored

- **Bills**: line items, names of participants, optional Fintoc username, payment-related totals.
- **Accounts** (optional): email, session cookies, magic-link tokens (hashed in Turso; raw tokens only in transit).
- **Host / participant tokens**: unguessable secrets embedded in share URLs; anyone with a link can perform the role that link allows (host edit vs participant self-assign).

## Operational notes

- Configure `ALLOWED_ORIGINS` in production (comma-separated list); do not rely on open CORS.
- Set strong `SESSION_SECRET` if you extend signed-session usage.
- Configure `MAIL_API_KEY` / `MAIL_FROM` for magic-link email (Resend).
