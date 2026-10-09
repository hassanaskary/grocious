---
name: grocious-spending
description: Answer household grocery spending questions from Grocious receipts, with optional member, provider, store, and date filters.
---

# Grocious household spending

Use Grocious receipt data to answer questions about grocery spend, purchase history, and receipt details. Prefer the local Grocious MCP tools when connected:

- `grocious_household_status` for profile IDs, archive coverage, and sync freshness.
- `grocious_spending_summary` for totals and grouped summaries.
- `grocious_list_receipts` to find matching purchases and their archive IDs.
- `grocious_get_receipt` to inspect a specific receipt and its line items.

## Interpret the data

- Aggregate household members by default. Filter by `member_id` or provider only when requested; get member IDs from `grocious_household_status`.
- `store` is the retailer or merchant on the receipt (for example, KIWI, Coop, Elkjøp or Power). `provider` is the connected receipt account/source (`coop`, `rema`, or `trumf`). They can differ: a KIWI receipt may have provider `trumf`.
- Manually uploaded and shared inbox receipts have `provider: null`; inspect `source` and `intake_channel` to see that they came through the inbox and whether they were uploaded, shared or emailed. Their selected retailer and household profile remain filterable.
- Date intervals use `YYYY-MM-DD`, include `start_date`, and exclude `end_date`. Make the requested period explicit before querying.
- Receipt amounts, bonus, and discounts are different measures. Report spending from `totals_minor`, convert minor units using the associated currency, and present bonus and discounts separately.
- Trumf bonus consumption entries are ledger activity, not grocery purchases, and are excluded from spending totals.
- Totals are grouped by currency. Never add values in different currencies together.
- A missing amount is unknown, not zero. Include unknown receipt counts when relevant.
- Keep each receipt's profile, provider, retailer (`store`), date, and archive ID with the result. Do not invent missing line items or receipt details.
- Check household sync status before presenting a total as complete. Mention incomplete, failed, or old account syncs and limit conclusions to the available archive data and recorded date coverage.
- Inbox receipts are excluded by default because an uploaded receipt may also exist in a provider archive. Include them only when requested or when they are needed to answer the question; say that inbox records were included and note their `review_state`. Linked and discarded inbox records are excluded.
- `provider` filters by the connected receipt account (`coop`, `rema`, or `trumf`); `store` filters by retailer; `source="inbox"` filters to inbox records when `include_inbox` is enabled.
- A store receipt belongs to the loyalty account scanned at checkout. Preserve the imported account provenance and do not try to merge receipts across household profiles.

## Example workflow

For “How much did we spend at Kiwi last month?”:

1. Resolve “last month” to an explicit inclusive start date and exclusive end date.
2. Call `grocious_spending_summary` with `group_by="store"` and the date interval.
3. Use `grocious_list_receipts` with `store="Kiwi"` if receipt-level details are needed.
4. Report the matching currency total, receipt count, date interval, and any sync gaps.

For direct HTTP access, use the read-only endpoints documented in [`agent/openapi.yaml`](../../../agent/openapi.yaml). They require a bearer token configured as `GROCIOUS_AGENT_API_TOKEN`; the API is disabled when no token is configured. Do not expose or request loyalty login credentials.
