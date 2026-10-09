"""Read-only, archive-backed interface shared by HTTP API and MCP tools."""

import datetime as dt
import json
import re
from collections import defaultdict

import profiles
import receipt_archive as archive

PROVIDERS = ("coop", "rema", "trumf")
SOURCES = (*PROVIDERS, "inbox")
MAX_PAGE_SIZE = 200


class QueryError(ValueError):
    """Invalid agent query parameter."""


class ReceiptNotFound(LookupError):
    """The requested receipt does not exist in the archive."""


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise QueryError(f"{label} must be a date in YYYY-MM-DD format.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise QueryError(f"{label} must be a valid calendar date.") from error


def _range(start_date, end_date):
    start = _date(start_date, "start_date")
    end = _date(end_date, "end_date")
    if start >= end:
        raise QueryError("start_date must be before end_date; end_date is exclusive.")
    return start.isoformat(), end.isoformat()


def _profiles():
    try:
        data = json.loads(profiles.registry_path().read_text())
        members = data["profiles"]
        if isinstance(members, list) and members:
            return {item["id"]: item for item in members if isinstance(item, dict) and item.get("id")}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"default": {"id": "default", "name": "Default", "legacy": True}}


def _connected_profiles(members):
    result = []
    for member in members.values():
        directory = profiles.data_dir(member)
        providers = [
            provider
            for provider, filename in (
                ("trumf", "trumf_state.json"),
                ("rema", "rema_tokens.json"),
                ("coop", "coop_tokens.json"),
            )
            if (directory / filename).exists()
        ]
        result.append({**member, "providers": providers})
    return result


def _check_filters(member_id=None, provider=None, source=None):
    if member_id is not None and member_id not in _profiles():
        raise QueryError("Unknown member_id. Use a profile id from the household response.")
    if provider is not None and provider not in PROVIDERS:
        raise QueryError("provider must be one of coop, rema, or trumf.")
    if source is not None and source not in SOURCES:
        raise QueryError("source must be one of coop, rema, trumf, or inbox.")


def _current_record(source, row, include_lines, members=None):
    # Provider indexes already contain the normalized list fields. Read individual
    # receipt files for inbox overlays and when line items are explicitly requested.
    record = archive.read_receipt(source, row["archive_id"]) if source == "inbox" or include_lines else row
    review = record.get("review") or {}
    if source == "inbox" and review.get("state") in ("linked", "discarded"):
        return None

    members = members or _profiles()
    profile_id = record.get("profile_id") or "default"
    owner = members.get(profile_id, {"id": profile_id, "name": "Default"})
    head = record.get("source", {}).get("head", {}) if isinstance(record.get("source"), dict) else {}
    result = {
        "source": source,
        "provider": record.get("chain") if source == "inbox" else source,
        "id": str(record.get("id", row.get("id", ""))),
        "archive_id": record["archive_id"],
        "date": record.get("date"),
        "time": record.get("time"),
        "timezone": record.get("timezone") or "Europe/Oslo",
        "store": record.get("store"),
        "amount": record.get("amount"),
        "amount_minor": record.get("amount_minor"),
        "currency": record.get("currency") or ("NOK" if source in PROVIDERS else None),
        "bonus": record.get("bonus"),
        "discount": record.get("discount"),
        "profile_id": profile_id,
        "profile_name": record.get("profile_name") or owner["name"],
        "review_state": review.get("state") if source == "inbox" else "confirmed",
        "category": record.get("category"),
        "transaction_category": record.get("transaction_category") or head.get("transaksjonKategori"),
        "validation": record.get("validation"),
        "documents": record.get("documents", []),
    }
    if include_lines:
        result["lines"] = [
            {
                "line_number": line.get("line_number"),
                "name": line.get("name"),
                "ean": line.get("ean"),
                "quantity": line.get("qty"),
                "unit": line.get("unit"),
                "amount": line.get("amount"),
                "amount_minor": line.get("amount_minor"),
                "discount": line.get("discount"),
                "kind": line.get("kind"),
            }
            for line in record.get("lines", [])
        ]
    return result


def _receipt_rows(include_inbox=True):
    rows = []
    members = _profiles()
    for source in SOURCES if include_inbox else PROVIDERS:
        for row in archive.summary(source).get("receipts", []):
            record = _current_record(source, row, include_lines=False, members=members)
            if record is not None:
                rows.append(record)
    return rows


def list_receipts(
    start_date,
    end_date,
    member_id=None,
    provider=None,
    source=None,
    store=None,
    limit=50,
    offset=0,
    include_inbox=False,
    include_lines=False,
):
    """Return a page of archived purchases; start is inclusive and end is exclusive."""
    start, end = _range(start_date, end_date)
    _check_filters(member_id, provider, source)
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise QueryError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")
    if type(offset) is not int or offset < 0:
        raise QueryError("offset must be a non-negative integer.")
    needle = store.casefold().strip() if store else None
    rows = []
    for row in _receipt_rows(include_inbox):
        if row.get("transaction_category") == "CONSUME":
            continue
        date = row.get("date")
        if not isinstance(date, str) or not start <= date[:10] < end:
            continue
        if member_id and row["profile_id"] != member_id:
            continue
        if provider and row["provider"] != provider:
            continue
        if source and row["source"] != source:
            continue
        if needle and needle not in (row.get("store") or "").casefold():
            continue
        rows.append(row)
    rows.sort(key=lambda row: (row.get("date") or "", row.get("time") or "", row["archive_id"]), reverse=True)
    total = len(rows)
    page = rows[offset : offset + limit]
    if include_lines:
        members = _profiles()
        for row in page:
            row.update(
                _current_record(row["source"], {"archive_id": row["archive_id"]}, include_lines=True, members=members)
            )
    return {
        "start_date": start,
        "end_date": end,
        "member_id": member_id,
        "provider": provider,
        "source": source,
        "include_inbox": bool(include_inbox),
        "count": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < total,
        "receipts": page,
    }


def get_receipt(source, archive_id):
    if source not in SOURCES:
        raise QueryError("source must be one of coop, rema, trumf, or inbox.")
    try:
        current = _current_record(source, {"archive_id": archive_id}, include_lines=True, members=_profiles())
    except (ValueError, FileNotFoundError) as error:
        raise ReceiptNotFound("Receipt not found.") from error
    if current is None:
        raise ReceiptNotFound("Receipt is linked or discarded and is excluded from spending results.")
    return current


def spending_summary(
    start_date,
    end_date,
    member_id=None,
    provider=None,
    source=None,
    group_by="total",
    include_inbox=False,
):
    """Aggregate stored receipts by a requested dimension without summing unlike currencies."""
    start, end = _range(start_date, end_date)
    _check_filters(member_id, provider, source)
    dimensions = {
        "total": lambda row: "household",
        "month": lambda row: row["date"][:7],
        "member": lambda row: row["profile_name"],
        "provider": lambda row: row["provider"] or "unknown",
        "store": lambda row: row.get("store") or "unknown",
    }
    if group_by not in dimensions:
        raise QueryError("group_by must be one of total, month, member, provider, or store.")

    groups = {}
    for row in _receipt_rows(include_inbox):
        if row.get("transaction_category") == "CONSUME":
            continue
        date = row.get("date")
        if not isinstance(date, str) or not start <= date[:10] < end:
            continue
        if member_id and row["profile_id"] != member_id:
            continue
        if provider and row["provider"] != provider:
            continue
        if source and row["source"] != source:
            continue
        key = dimensions[group_by](row)
        group = groups.setdefault(
            key,
            {
                "group": key,
                "receipt_count": 0,
                "known_amount_count": 0,
                "unknown_amount_count": 0,
                "totals_minor": defaultdict(int),
                "bonus_minor": defaultdict(int),
                "discount_minor": defaultdict(int),
            },
        )
        group["receipt_count"] += 1
        currency = row.get("currency") or "UNKNOWN"
        amount_minor = row.get("amount_minor")
        if type(amount_minor) is int:
            group["known_amount_count"] += 1
            group["totals_minor"][currency] += amount_minor
        else:
            group["unknown_amount_count"] += 1
        for field in ("bonus", "discount"):
            value_minor = archive.minor(row.get(field))
            if value_minor is not None:
                group[field + "_minor"][currency] += value_minor

    result = []
    for key in sorted(groups):
        group = groups[key]
        result.append(
            {
                **group,
                "totals_minor": dict(group["totals_minor"]),
                "bonus_minor": dict(group["bonus_minor"]),
                "discount_minor": dict(group["discount_minor"]),
            }
        )
    return {
        "start_date": start,
        "end_date": end,
        "member_id": member_id,
        "provider": provider,
        "source": source,
        "group_by": group_by,
        "include_inbox": bool(include_inbox),
        "groups": result,
    }


def household_status():
    """Summarize archive coverage and per-profile sync freshness without exposing raw errors."""
    members = _profiles()
    connected = _connected_profiles(members)
    sources = {}
    for source in SOURCES:
        data = archive.summary(source)
        receipts = data.get("receipts", [])
        dates = sorted(row["date"][:10] for row in receipts if row.get("date"))
        raw_status = data.get("status") or {}
        account_rows = {row.get("profile_id"): row for row in (raw_status.get("profiles") or [])}
        accounts = []
        if source in PROVIDERS:
            for member in connected:
                if source not in member["providers"]:
                    continue
                row = account_rows.get(member["id"], {})
                accounts.append(
                    {
                        "profile_id": member["id"],
                        "profile_name": member["name"],
                        "connected": True,
                        "state": row.get("state", "not_started"),
                        "finished_at": row.get("finished_at"),
                        "oldest_date": row.get("oldest_date"),
                        "newest_date": row.get("newest_date"),
                        "error_count": len(row.get("errors") or []),
                    }
                )
        sources[source] = {
            "receipt_count": len(receipts),
            "oldest_date": dates[0] if dates else None,
            "newest_date": dates[-1] if dates else None,
            "status": raw_status.get("state", "not_started"),
            "updated_at": raw_status.get("updated_at"),
            "accounts": accounts,
        }
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "profiles": connected,
        "sources": sources,
    }
