# grocious

Current release: **0.1**. See [CHANGELOG.md](CHANGELOG.md) for release notes.

<img src="app/static/brand/grocious-readme.png" alt="grocious" width="560">

**Your groceries. Your receipts. Your overview.**

Self-hosted tooling that pulls your Norwegian grocery loyalty data — **receipts with line
items, bonus balances and campaign offers** — straight from the chains' own APIs, keeps a
tamper-evident archive of the originals, and hands it back to you as JSON, CSV or PDF.

Built for one specific annoyance: the Trumf, Coop and Rema apps are painful or impossible
on a de-Googled Android (GrapheneOS), and none of them let you get your own purchase
history out in a form you can actually use. Runs as a handful of small containers on your
own machine. Chain fetching needs no additional cloud account. Optional AI receipt interpretation
uses the provider you configure; rules-only interpretation stays local.

## Status

| Chain | Bonus | Receipts | Line items | Offers | Notes |
|---|---|---|---|---|---|
| **Trumf / NorgesGruppen** (Kiwi, Meny, Spar, Joker, Gigaboks) | ✅ | ✅ | ✅ | ✅ | Vendor receipt images (JPEG) archived too |
| **Rema 1000** | ⚠️ | ✅ | ✅ | ✅ | Coupons only; kroner bonus was replaced by Reitan's *Spenn* points in June 2026 and is not exposed by the API |
| **Coop** | ✅ | ✅ | ✅ | ✅ | Original PDFs archived; balance needs a separate login the app API does not cover |

Offers open a detail page with provider text, terms and images when supplied. Rema activation is
**manual**; Trumf and Coop offers are read-only. Nothing is auto-activated.

## How it works

Two runtimes, on purpose:

- **`login/`** — the only part that needs a browser. Playwright drives the real login flow
  once (roughly yearly): Trumf's NextAuth → `id.trumf.no` IdentityServer (OAuth2 + PKCE,
  `offline_access`) including the SMS OTP step, Rema's passwordless SMS flow, and Coop's
  Auth0 flow with MFA. Sessions are stored under the selected household member.
- **`app/`** — browser-free runtime. `trumf_client.py`, `rema_client.py` and the Coop
  modules read the stored session, exchange it for a bearer token and call the chains'
  own endpoints for balances, transactions and offers. This is what runs day to day;
  it needs no browser and no interaction.

The session cookie is long-lived and refreshed server-side, so re-running the login is an
exception, not a routine.

## Household profiles

Add household members and rename them from **Settings → Household**. Each member can connect their own
Trumf, Rema, and Coop logins. Receipt imports go into one shared household archive; the dashboard,
statistics, and monthly exports aggregate all members and providers by default. Use the member and
provider filters above the receipt list to see one member, one provider, or both together. Each
receipt keeps the member and provider that supplied it, so its account provenance remains visible.
Because checkout uses one loyalty account, each store receipt is imported through the account
that was scanned and contributes once to the household total.

Manual upload batches require a household member, and each file requires its retailer. The retailer is the
merchant on the receipt (for example, KIWI, Elkjøp or Power); connected provider/account (such as Trumf
or Coop) and intake channel (such as web upload, mobile share or email) are separate provenance fields.
The retailer picker learns new names and shares them across the household. The household dashboard
aggregates spending by default; member, retailer and provider remain available for filtering.

Run the login command for each member and provider. Non-default members are prompted for
their credentials and the one-time SMS code, even when the `.env` contains the Default
member's values. Passwords are not saved. For example:

```bash
docker compose --profile login run --rm -e GROCIOUS_PROFILE="Partner" trumf-login
docker compose --profile login run --rm -e GROCIOUS_PROFILE="Partner" rema-login
docker compose --profile login run --rm -e GROCIOUS_PROFILE="Partner" coop-login
```

Then fetch receipts for all connected member/provider accounts:

```bash
app/sync_provider_archives.sh
```

The existing data directory is kept in place as the initial **Default** member. New member
sessions and Rema phone metadata live under `data/profiles/<profile-id>/`; receipt originals and
household exports remain in the shared archive. The profile registry is `data/profiles.json`.
Removing or disconnecting a login does not remove receipts already imported. Each provider account
imports the purchases visible to that account; receipts retain the account that supplied them.

## The receipt archive

The part that matters if you care about your own records. Every purchase gets its own
folder under `data/receipts/<source>/<archive_id>/`:

- **Originals are never modified or deleted.** Files are named by their SHA-256 and
  written once; a changed original becomes a new file next to the old one.
- **`archive_id`** is a stable receipt key. It uses the provider and provider receipt id, scoped
  to the supplying member account, so re-running a fetch is idempotent and the receipt retains
  its account provenance. Existing Default-member archive IDs remain compatible.
- **`receipt.json`** holds normalised fields next to the untouched `source` payload. Unknown
  vendor fields are preserved rather than dropped, and `documents[]` lists every stored file
  with its `role`, `filename`, `sha256`, `bytes` and `mimetype`.
- Vendor-produced images are labelled as such. A PDF that grocious renders itself is a
  *derived view*, never presented as the store's original.

Archive jobs run for every connected account (`app/provider_archive.py {rema,trumf}`,
`app/coop_archive.py`), support `--incremental` for the recent window after an account's initial
backfill, and can be resumed. The first sync for an account backfills its available history.
`app/sync_provider_archives.sh` wraps the jobs for a scheduled run.

## HTTP API

| Endpoint | Returns |
|---|---|
| `GET /api/summary` | Dashboard data per chain, inbox status, and household profiles |
| `GET /api/profiles` | Household members and the providers connected to each |
| `GET /api/export/<YYYY-MM>.json` | Monthly household receipts, including pending/confirmed inbox records; linked/discarded inbox records excluded. Add `?member=<profile-id>` or `?provider=<chain>` to filter, and `?lines=1` for item lines |
| `GET /api/export/<YYYY-MM>.csv` | Same data as CSV — one row per receipt, or per item with `?lines=1`; accepts the same member/provider filters |
| `GET /api/agent/v1/household` | Opt-in, token-protected profile, archive coverage, and sync status |
| `GET /api/agent/v1/receipts` | Date-bounded, paginated receipt search; supports member, connected provider, archive source, retailer (`store`), inbox, and line filters |
| `GET /api/agent/v1/receipts/<source>/<archive_id>` | One normalized archived receipt with line items and provenance |
| `GET /api/agent/v1/spending` | Date-bounded sums grouped by household, month, member, connected provider, or retailer (`store`); totals remain separate by currency |
| `GET /api/archive/<source>` | Archive index: count, `archive_id`s, `documents[]` with checksums |
| `GET /archive/<source>` | Browsable archive, independent of a live login |
| `GET /archive/<source>/<rid>` | One purchase: normalised view plus raw JSON |
| `GET /archive/<source>/<rid>.json` \| `.zip` | Full record, or every original file as a ZIP |
| `GET /archive/<source>/<rid>/file/<name>` | A single original document |

Line items are cached on disk under `GROCERY_DATA/cache/` after the first fetch (they never
change), so a second `?lines=1` export is fast.

## Agent access

Grocious includes an opt-in, read-only agent API and a local MCP server. The MCP server uses
the same archive-backed HTTP API as other agent clients and runs over stdio; it does not open
a listener or need direct access to `data/` or grocery-provider credentials. It needs the
Grocious web service running and a bearer token for the agent API.

Install the optional MCP SDK in a separate environment:

```bash
uv venv .venv-agent
uv pip install --python .venv-agent/bin/python -r agent/requirements.txt
```

Configure your MCP host to start the server, replacing both paths with absolute paths:

```json
{
  "mcpServers": {
    "grocious": {
      "command": "/path/to/grocious/.venv-agent/bin/python",
      "args": ["/path/to/grocious/agent/server.py"],
      "env": {
        "GROCIOUS_AGENT_API_URL": "http://127.0.0.1:3012/api/agent/v1",
        "GROCIOUS_AGENT_API_TOKEN": "<same token configured in Grocious .env>"
      }
    }
  }
}
```

Set the token in the MCP host configuration to the same value used by the Grocious web
container. The MCP server exposes household sync status, receipt search, receipt details, and
spending summaries. Inbox receipts are excluded from agent spending by default because an
uploaded receipt can also exist in a provider archive; set `include_inbox` when needed and keep
review state visible.
The repository skill at `.agents/skills/grocious-spending/SKILL.md` gives compatible agents the
household-specific rules for interpreting these tools.

The HTTP endpoints are documented in [agent/openapi.yaml](agent/openapi.yaml) under
`/api/agent/v1`. Set `GROCIOUS_AGENT_API_TOKEN` in `.env` and recreate the web container with
`docker compose up -d --build web` to enable them; requests require `Authorization: Bearer <token>`.
Generate a token with `openssl rand -hex 32`. Keep Grocious
behind the existing local bind or an authenticated reverse proxy, and only share the token
with a trusted agent. Use HTTPS when configuring a non-local MCP API URL; the MCP client
rejects non-local HTTP URLs. The HTTP agent API returns normalized receipt data and omits raw
provider payloads and document contents.

## Web UI

The settings menu includes an optional navigation bar in the header. Add display
names and HTTP(S) URLs, edit or remove links, and toggle the bar on/off. Settings
are shared across devices and stored in `GROCERY_DATA/navigation.json`; fresh
installations have no predefined links. Links open in a new tab.

Flask, server-rendered Jinja, no CDN and no JS framework. Mobile first: receipts expand in
place and filter per chain and month, with 50 receipts per page (newest first). Offer dismissal
is remembered in this browser and can be reset with “Vis skjulte tilbud igjen”. Trumf campaign
agreement data has no images; Coop coupons exclude redeemed, expired and future entries. `app/ui.py` handles Norwegian formatting (`1 234,50 kr`,
`dd.mm.yyyy`).

**Themes** are one JSON file each in `app/themes/` — `light`, `dark`, `gruvbox`,
`zenburn`, `ink`, and all four Catppuccin flavors (`latte`, `frappe`, `macchiato`, `mocha`) ship.
These seven named palettes match Chattr; Light and Dark remain available. Drop in another file (`{"label": "…", "scheme":
"light|dark", "colors": {...}}` with keys from `themes.COLOR_KEYS`; missing keys fall back to
the base scheme) and restart, and it appears in the picker. The picker remembers the choice
in `localStorage`, «Auto» follows `prefers-color-scheme`, and `?theme=<id>` forces one.

## Receipt inbox

Upload, phone sharing, selectable receipt interpretation and optional IMAP IDLE intake: see [INBOX.md](INBOX.md). Local extraction also requires Poppler (`pdfinfo`, `pdftotext`, `pdftoppm`); the web Docker image includes it.

## Running it

```bash
cp .env.example .env
docker compose --profile login run --rm trumf-login    # once; paste the SMS code when prompted
docker compose up -d web                               # UI on 127.0.0.1:3012
app/sync_provider_archives.sh                          # archive all connected accounts
```

Compose reads `.env` and `data/` from the project directory. To keep runtime files and
secrets outside the checkout, set `GROCIOUS_HOME=/path/to/private/runtime` in the local
`.env`; that directory then needs its own `.env` and `data/`. Export the same variable when
running `app/sync_provider_archives.sh` outside Compose.

### Configuration

| Variable | Purpose |
|---|---|
| `GROCIOUS_PROFILE` | Optional household member name for a login command (defaults to `Default`) |
| `TRUMF_PHONE`, `TRUMF_PASSWORD` | Optional Trumf login inputs; prompted securely when unset |
| `REMA_PHONE` | Optional Rema login phone; prompted when unset and saved per member for API requests |
| `COOP_USER`, `COOP_PASSWORD` | Optional Coop login inputs; prompted securely when unset |
| `GROCIOUS_USE_ENV_CREDENTIALS=1` | Explicitly reuse environment login inputs for a non-default member |
| `GROCIOUS_HOME` | Private runtime directory holding `.env` and `data/` |
| `GROCERY_DATA` | Data path inside the container (default `/data`) |
| `GROCIOUS_AGENT_API_TOKEN` | Optional bearer token that enables the read-only `/api/agent/v1` endpoints |
| `NTFY_URL` | Optional [ntfy](https://ntfy.sh) topic for fetch summaries |
| `GROCIOUS_DEMO` | `1` serves anonymised fixtures — no tokens, no network |

## Development

```bash
python -m venv .venv
.venv/bin/pip install flask requests reportlab waitress pillow pillow-heif html2text anthropic openai jsonschema imapclient pytest ruff
GROCIOUS_DEMO=1 PORT=3012 .venv/bin/python app/webgui.py
.venv/bin/pytest && .venv/bin/ruff check .
```

Demo mode serves anonymised fixtures from `app/fixtures/` for all three chains — no
credentials, no network calls — which is also what the route tests run against. Regenerate
them with `python scripts/gen_fixtures.py`.

## Data and privacy

Your household's loyalty accounts, your own machine, your own data. Secrets (`.env`) and
session state (`data/`) are `.gitignore`d and have never been committed. Tokens are stored
outside the shared receipt archive, and authentication headers are never archived alongside a receipt.

The chains' APIs are **unofficial and reverse-engineered**. They can change without notice,
and Grocious is self-hosted tooling for you and your household, not a public multi-user
service. Watch the fetch job; when a chain changes something, it will break there first.

## Roadmap

- [x] Trumf — bonus balance, receipts with line items, offers
- [x] Rema 1000 — receipts with line items, offers, coupon discounts
- [x] Coop — receipts with line items and original PDFs
- [x] Content-addressed original archive with checksummed documents
- [x] Web UI, themes, month export (JSON/CSV) and per-receipt download (JSON/CSV/PDF/ZIP)
- [x] Inbox — upload, share target, selectable interpretation and optional IMAP IDLE intake ([setup and acceptance checks](INBOX.md))
- [ ] Deployed phone sharing, live mail and vision-model acceptance checks
- [ ] Scheduled fetch with ntfy summary

## Credits

Reverse-engineering groundwork:
[HelgeSverre's write-up on Norwegian grocery apps](https://helgesver.re/articles/reverse-engineering-norwegian-grocery-apps)
and [his decompiled Rema API notes](https://gist.github.com/HelgeSverre/80a7f34f874336324184a0c513c2e6a2);
Trumf transaction fields from [ttyridal/trumf-data-fetch](https://github.com/ttyridal/trumf-data-fetch).
Both are unofficial descriptions — every call and response here was verified locally.

**Built by** Pål Hatlem, with [Claude](https://claude.com/claude-code) and
[Codex](https://openai.com/codex) as coding agents. Individual authorship is recorded in the
`Co-Authored-By` trailers on new agent-assisted commits; older history is preserved.

## License

[AGPL-3.0](LICENSE) — use it, self-host it, modify it; derivatives, including hosted
services, must stay open under the AGPL. No taking this private to monetise grocery data.

The wordmark uses locally hosted [Space Grotesk](https://github.com/floriankarsten/space-grotesk),
licensed under the SIL Open Font License (included in `app/static/fonts/`).
