"""Opt-in, read-only HTTP API for agent clients."""

import hmac
import os
import re

from flask import Blueprint, jsonify, request

import agent_api

bp = Blueprint("agent_api", __name__, url_prefix="/api/agent/v1")


def _authorized():
    expected = os.environ.get("GROCIOUS_AGENT_API_TOKEN", "")
    if not expected:
        return jsonify(error="Agent API is disabled; configure GROCIOUS_AGENT_API_TOKEN."), 503
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not token or not hmac.compare_digest(token, expected):
        return jsonify(error="Bearer token required."), 401
    return None


@bp.before_request
def require_read_token():
    error = _authorized()
    if error:
        return error


@bp.after_request
def prevent_agent_response_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(agent_api.QueryError)
def invalid_query(error):
    return jsonify(error=str(error)), 400


@bp.errorhandler(agent_api.ReceiptNotFound)
def missing_receipt(error):
    return jsonify(error=str(error)), 404


def _boolean(name, default=False):
    value = request.args.get(name)
    if value is None:
        return default
    if value.casefold() in ("1", "true", "yes"):
        return True
    if value.casefold() in ("0", "false", "no"):
        return False
    raise agent_api.QueryError(f"{name} must be true or false.")


def _integer(name, default):
    value = request.args.get(name)
    if value is None:
        return default
    if not re.fullmatch(r"\d+", value):
        raise agent_api.QueryError(f"{name} must be a non-negative integer.")
    return int(value)


@bp.get("/household")
def household():
    return jsonify(agent_api.household_status())


@bp.get("/receipts")
def receipts():
    return jsonify(
        agent_api.list_receipts(
            request.args.get("start_date"),
            request.args.get("end_date"),
            member_id=request.args.get("member_id") or None,
            provider=request.args.get("provider") or None,
            source=request.args.get("source") or None,
            store=request.args.get("store") or None,
            limit=_integer("limit", 50),
            offset=_integer("offset", 0),
            include_inbox=_boolean("include_inbox"),
            include_lines=_boolean("include_lines"),
        )
    )


@bp.get("/receipts/<source>/<archive_id>")
def receipt(source, archive_id):
    return jsonify(agent_api.get_receipt(source, archive_id))


@bp.get("/spending")
def spending():
    return jsonify(
        agent_api.spending_summary(
            request.args.get("start_date"),
            request.args.get("end_date"),
            member_id=request.args.get("member_id") or None,
            provider=request.args.get("provider") or None,
            source=request.args.get("source") or None,
            group_by=request.args.get("group_by", "total"),
            include_inbox=_boolean("include_inbox"),
        )
    )
