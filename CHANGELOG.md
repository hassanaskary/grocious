# Changelog

## Unreleased

- Manual receipt uploads now require a household profile and retailer; new retailer names are saved for reuse.
- PDF pages are rendered as vision images, and configured OpenRouter accounts can interpret receipts with `openrouter/free`.
- Agent receipt results distinguish connected providers from manual/email/share intake channels.

- Household profiles can connect separate Trumf, Rema and Coop accounts to one shared receipt archive.
- Dashboard, statistics and monthly exports aggregate household spending by default, with member and provider filters.
- Receipt records retain the member and provider that supplied them; each profile keeps its own login state.
- Read-only agent API with date-bounded receipt search, spending summaries, per-account sync status, and bearer-token protection.
- Local stdio MCP server and repository `grocious-spending` skill for household spending analysis.

## 0.1 — 2026-09-11

First versioned release of Grocious, based on the deployed application.

- Trumf, Coop and Rema receipt archives, line items, offers and monthly exports.
- Receipt inbox with original document preservation, review, linking and duplicate handling.
- Optional AI interpretation and IMAP receipt intake.
- Mobile web interface, PWA icons, themes, sorting and receipt period filters.
- Reversible bookkeeping markers and Coop balance estimates based on a recorded opening snapshot and receipt bonuses.

This release uses the documented Docker/local development setup. The proposed
Arch package, desktop launcher and guided local login are not included yet.
Provider integrations use unofficial APIs; available data and login requirements
can differ between chains. See README.md and INBOX.md for setup and limitations.
