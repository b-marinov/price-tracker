# Contributing to Price Tracker

## Adding a New Store

Adding a store is a two-minute database operation, but it triggers daily
automated scraping of a third-party website. Follow this checklist **every
time** before seeding a new `brochure_url`.

### Store Onboarding Checklist

- [ ] **robots.txt** — Fetch `https://<store-domain>/robots.txt`.
      Confirm that neither `/` nor the brochure path is disallowed for
      `User-agent: *` or `User-agent: python-requests`.

- [ ] **Terms of Service** — Read the store's ToS (usually linked in the
      footer). Look for clauses on automated access, screen scraping, or
      data re-use. If scraping is explicitly prohibited, do not add the
      store without legal sign-off.

- [ ] **Rate / Frequency** — Our scrapers run once per day via Celery Beat.
      Confirm this is within any stated crawl limits.

- [ ] **Stakeholder approval** — Get explicit written approval from
      **Boris** (project owner) in the GitHub Issue before seeding.
      Link the issue number in the `brochure_url` migration.

### How to Seed the brochure_url (after checklist is complete)

Use the admin API endpoint — it requires a `tos_confirmed=true` query
parameter as a reminder that the checklist was completed:

```bash
curl -X PATCH \
  "http://localhost:8000/admin/stores/<slug>/brochure-url?tos_confirmed=true" \
  -H "X-Admin-Key: <admin-key>" \
  -H "Content-Type: application/json" \
  -d '{"brochure_url": "https://www.example.bg/broshuri"}'
```

Alternatively, write an Alembic data migration (see
`alembic/versions/0007_store_brochure_url.py` as a template) and reference
the GitHub Issue in the migration docstring.

### Why This Gate Exists

At 4 stores, daily scraping is incidental. At 10+ stores it becomes a
systematic operation with meaningful legal exposure. The gate keeps every
addition intentional and documented. See issue #67 for the full rationale.
