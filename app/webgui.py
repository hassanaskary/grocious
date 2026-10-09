#!/usr/bin/env python3
"""grocious.example.com — self-hosted grocery dashboard (Trumf + Rema).
Bonus, offers/coupons (with manual activate), receipts + JSON/CSV/PDF export.
Read-only except opt-in Rema offer activation. Behind tinyauth; binds 127.0.0.1."""
import json, os, io, csv, re, uuid, datetime, functools
import requests
from flask import Flask, Response, render_template, redirect, abort, request, jsonify, send_file
import receipt_archive
import navigation
import bookkeeping
import agent_routes
import coop_receipt_ui
from inbox import store as inbox_store
from inbox.routes import bp as inbox_bp
import demo, themes, ui, i18n, dashboard_stats, bonus_sources, offers as offer_ui, profiles, retailers

DATA = os.environ.get("GROCERY_DATA", "/data")
REMA_PHONE = os.environ.get("REMA_PHONE", "")
DEMO = os.environ.get("GROCIOUS_DEMO", "") not in ("", "0", "false")
if DEMO and "GROCERY_DATA" not in os.environ:  # demo archive (Coop) lives with the fixtures
    os.environ["GROCERY_DATA"] = str(demo.FIXTURES / "data")
app = Flask(__name__, template_folder="templates", static_folder="static")
app.jinja_env.filters.update(ui.FILTERS)
app.register_blueprint(navigation.bp)
app.register_blueprint(bookkeeping.bp)
app.register_blueprint(agent_routes.bp)

@app.context_processor
def navigation_context():
    household = [{"id":"default","name":"Demo","providers":["trumf","rema","coop"]}] if DEMO else profiles.connected_profiles()
    return {"navigation": navigation.load(), "household_profiles": household, "language": ui.language(), "inbox_pending_count": sum(
        row.get("review", {}).get("state") == "needs_review"
        for row in receipt_archive.summary("inbox")["receipts"]
    )}


@app.after_request
def localize_html(response):
    if response.mimetype == "text/html" and not response.direct_passthrough:
        response.set_data(i18n.translate_html(response.get_data(as_text=True), ui.language()))
    return response


@app.post("/language")
def set_language():
    selected = request.form.get("language")
    if selected not in i18n.LANGUAGES:
        return "Invalid language", 400
    target = request.form.get("next", "/")
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        target = "/"
    response = redirect(target, 303)
    response.set_cookie(
        "grocious_language",
        selected,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        secure=request.is_secure,
        samesite="Lax",
        path="/",
    )
    return response


@app.get("/translations.js")
def translations_js():
    payload = "window.grociousTranslations=" + json.dumps(i18n.TRANSLATIONS, ensure_ascii=False) + ";"
    return Response(payload, mimetype="application/javascript", headers={"Cache-Control": "public, max-age=3600"})


def _cache(ttl):
    def deco(fn):
        box = {}
        @functools.wraps(fn)
        def wrap(*a):
            now = datetime.datetime.now().timestamp()
            if a not in box or now - box[a][0] > ttl:
                box[a] = (now, fn(*a))
            return box[a][1]
        wrap.clear = box.clear
        return wrap
    return deco

def _line_cache(chain):
    """Receipt lines never change: cache them as JSON under GROCERY_DATA/cache/ keyed by receipt id,
    so /api/export/<ym>.json?lines=1 is instant after the first fetch. Empty results are not cached."""
    def deco(fn):
        @functools.wraps(fn)
        def wrap(rid, profile_id="default"):
            path = os.path.join(DATA, "cache", f"{chain}-{profile_id}-{rid}.json")
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                pass
            lines = fn(rid, profile_id)
            if lines:
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump(lines, fh, ensure_ascii=False)
                    os.replace(tmp, path)
                except OSError:
                    pass
            return lines
        return wrap
    return deco

def _rsc_objects(txt, must_have):
    out = []
    for m in re.finditer('"' + must_have + '"', txt):
        start = txt.rfind("{", 0, m.start())
        if start < 0: continue
        depth = 0
        for j in range(start, min(start + 4000, len(txt))):
            if txt[j] == "{": depth += 1
            elif txt[j] == "}":
                depth -= 1
                if depth == 0:
                    try: out.append(json.loads(txt[start:j+1]))
                    except Exception: pass
                    break
    return out

# ---------------- Trumf ----------------
def trumf_session(data_dir=None):
    st = json.load(open(os.path.join(data_dir or DATA, "trumf_state.json")))
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36"
    for c in st.get("cookies", []):
        if "trumf.no" in c.get("domain", ""):
            s.cookies.set(c["name"], c["value"], domain=c["domain"].lstrip("."), path=c.get("path", "/"))
    return s

@_cache(300)
def trumf_data(profile_id="default"):
    try:
        profile = profiles.find(profile_id) or {"id":"default", "name":"Default", "legacy":True}
        s = trumf_session(profiles.data_dir(profile))
        at = s.get("https://www.trumf.no/api/auth/session", timeout=20).json().get("accessToken")
        h = {"Authorization": "Bearer " + at, "Accept": "application/json"}
        B = "https://platform-rest-prod.ngdata.no"
        saldo = s.get(f"{B}/trumf/husstand/saldo", headers=h, timeout=20).json()
        offers = s.get(f"{B}/trumf/kampanjeavtale/beskrivelser", headers=h, timeout=20).json()
        txt = s.get("https://www.trumf.no/profil/kvitteringer", headers={"RSC": "1"}, timeout=25).content.decode("utf-8", "ignore")
        seen, recs = set(), []
        for o in _rsc_objects(txt, "batchId"):
            bid = o.get("batchId")
            if not bid or bid in seen or "belop" not in o: continue
            seen.add(bid)
            recs.append({"id": bid, "date": (o.get("bonusberegningTidspunkt") or "").replace("$D", "")[:10],
                         "store": o.get("beskrivelse"), "amount": o.get("belop"), "bonus": o.get("bonus"),
                         "chain": o.get("filterCategory"), "hasReceipt": o.get("harKvittering"), "transaction_category": o.get("transaksjonKategori")})
        recs.sort(key=lambda x: x["date"], reverse=True)
        return {"ok": True, "saldo": saldo.get("trumfSaldo"), "akkumulert": saldo.get("totaltAkkumulertTrumf"), "account_balance": saldo.get("bokfortSaldo"), "account_available": saldo.get("trumfSaldo"),
                "oppdatert": (saldo.get("sistOppdatert") or "")[:10], "count": len(recs), "receipts": recs,
                "offers": [offer_ui.normalize("trumf", o)
                           for o in (offers if isinstance(offers, list) else [])]}
    except Exception as e:
        return {"ok": False, "err": str(e)}

@_line_cache("trumf")
def trumf_lines(bid, profile_id="default"):
    profile = profiles.find(profile_id) or {"id":"default", "name":"Default", "legacy":True}
    s = trumf_session(profiles.data_dir(profile))
    txt = s.get(f"https://www.trumf.no/profil/kvitteringer/{bid}", headers={"RSC": "1"}, timeout=25).content.decode("utf-8", "ignore")
    seen, out = set(), []
    for o in _rsc_objects(txt, "produktBeskrivelse"):
        g = o.get("varelinjeGuid")
        if g in seen: continue
        seen.add(g)
        ean = o.get("ean"); ean = None if ean == "$undefined" else ean
        out.append({"name": o.get("produktBeskrivelse"), "ean": ean, "qty": o.get("antall"), "amount": o.get("belop")})
    return out

# ---------------- Rema ----------------
def rema_headers(data_dir=None):
    data_dir = data_dir or DATA
    tok = json.load(open(os.path.join(data_dir, "rema_tokens.json")))
    r = requests.post("https://id.rema.no/token", data={"grant_type": "refresh_token",
        "client_id": "android-251010", "refresh_token": tok["refresh_token"]}, timeout=20).json()
    if "refresh_token" in r: json.dump(r, open(os.path.join(data_dir, "rema_tokens.json"), "w"))
    try: phone = json.load(open(os.path.join(data_dir, "rema_phone.json"))).get("phone", "")
    except (OSError, ValueError): phone = REMA_PHONE
    return {"Authorization": "Bearer " + r["access_token"], "ocp-apim-subscription-key": "fb5e24884b504d0bad761098f77e6605",
            "x-platform": "android", "x-correlation-id": str(uuid.uuid4()), "x-device-id": str(uuid.uuid4()),
            "x-mobile-nr": phone, "x-app": "bella", "x-app-version": "3.0.12 #110549", "Accept": "application/json"}

@_cache(300)
def rema_data(profile_id="default"):
    try:
        profile = profiles.find(profile_id) or {"id":"default", "name":"Default", "legacy":True}
        data_dir = profiles.data_dir(profile)
        H = rema_headers(data_dir)
        heads = requests.get("https://api.rema.no/v1/bella/transaction/v2/heads", headers=H, timeout=30).json()
        offers = requests.get("https://api.rema.no/v1/bella/offers/v2/available-offers/", headers=H, timeout=20).json()
        balance = None
        try:
            profile = requests.get("https://api.rema.no/bella/v2/customers", headers=H, timeout=15)
            profile.raise_for_status(); profile = profile.json()
            if profile.get("currencyCode") == "NOK" and not profile.get("member", {}).get("spennUser"):
                balance = profile.get("member", {}).get("bonusBalanceDecimal")
        except (requests.RequestException, ValueError, AttributeError):
            pass
        olist = offers if isinstance(offers, list) else offers.get("offers", [])
        txs = [{"id": t["id"], "date": datetime.datetime.fromtimestamp(t["purchaseDate"]/1000).strftime("%Y-%m-%d %H:%M"),
                "store": t.get("storeName"), "amount": t.get("amount"), "discount": t.get("discount", 0), "bonus": t.get("bonusPointsDecimal")}
               for t in heads.get("transactions", [])]
        txs.sort(key=lambda x: x["date"], reverse=True)
        return {"ok": True, "purchaseTotal": heads.get("purchaseTotal"), "discountTotal": heads.get("discountTotal"),
                "count": len(txs), "receipts": txs, "bonus_balance": balance, "bonus_accumulated": None,
                "offers": [offer_ui.normalize("rema", o) for o in olist]}
    except Exception as e:
        return {"ok": False, "err": str(e)}

@_line_cache("rema")
def rema_lines(tid, profile_id="default"):
    profile = profiles.find(profile_id) or {"id":"default", "name":"Default", "legacy":True}
    rows = requests.get(f"https://api.rema.no/v1/bella/transaction/v2/rows/{tid}", headers=rema_headers(profiles.data_dir(profile)), timeout=20).json()
    rows = rows if isinstance(rows, list) else rows.get("rows", [])
    return [{"name": r.get("productDescription") or r.get("prodtxt1"), "ean": r.get("prodtxt3"),
             "qty": r.get("quantity", 1), "amount": r.get("amount")} for r in rows]

def rema_activate(code, profile_id="default"):
    profile = profiles.find(profile_id) or {"id":"default", "name":"Default", "legacy":True}
    requests.post("https://api.rema.no/v1/bella/offers/activate", headers=rema_headers(profiles.data_dir(profile)), json=[code], timeout=20)

def provider_lines(source, receipt_id, profile_id="default"):
    loader = trumf_lines if source == "trumf" else rema_lines
    return loader(receipt_id) if DEMO else loader(receipt_id, profile_id)

# ---------------- downloads ----------------
def _download(chain, rid, fmt, lines, title):
    if fmt == "json":
        return Response(json.dumps({"id": rid, "lines": lines}, ensure_ascii=False, indent=2),
                        mimetype="application/json", headers={"Content-Disposition": f"attachment;filename={chain}-{rid}.json"})
    if fmt == "csv":
        buf = io.StringIO(); w = csv.writer(buf); w.writerow(["vare", "ean", "antall", "beløp"])
        for l in lines: w.writerow([l["name"], l["ean"], l["qty"], l["amount"]])
        return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={chain}-{rid}.csv"})
    if fmt == "pdf":
        from reportlab.lib.pagesizes import A6
        from reportlab.pdfgen import canvas
        buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A6); w, h = A6
        y = h - 30; c.setFont("Helvetica-Bold", 10); c.drawString(20, y, title[:44]); y -= 18
        c.setFont("Helvetica", 8); tot = 0
        for l in lines:
            if y < 26: c.showPage(); y = h - 30; c.setFont("Helvetica", 8)
            c.drawString(20, y, str(l["name"] or "")[:32]); c.drawRightString(w-20, y, f"{(l['amount'] or 0):.2f}")
            y -= 12; tot += (l["amount"] or 0)
        y -= 6; c.setFont("Helvetica-Bold", 9); c.drawString(20, y, "Sum"); c.drawRightString(w-20, y, f"{tot:.2f}")
        c.showPage(); c.save(); buf.seek(0)
        return Response(buf.read(), mimetype="application/pdf", headers={"Content-Disposition": f"attachment;filename={chain}-{rid}.pdf"})
    abort(404)

# Presentation lives in templates/ + static/ (helpers in ui.py); themes in themes/ (themes.py).


if DEMO:  # anonymised fixtures, no tokens, no network — the real functions above stay as they are
    trumf_data, rema_data, trumf_lines, rema_lines, rema_activate = (
        demo.trumf_data, demo.rema_data, demo.trumf_lines, demo.rema_lines, demo.rema_activate)

def household_provider(source, selected=None):
    loader = trumf_data if source == "trumf" else rema_data
    if DEMO:
        result = loader()
        for row in result.get("receipts", []):
            row.setdefault("profile_id", "default"); row.setdefault("profile_name", "Demo")
        return result
    accounts = profiles.connected_profiles()
    if selected:
        accounts = [p for p in accounts if p["id"] == selected]
    accounts = [p for p in accounts if source in p["providers"]]
    combined = {"ok":False,"receipts":[],"offers":[],"errors":[]}
    additive = ("saldo", "akkumulert", "account_balance", "account_available", "bonus_balance", "bonus_accumulated")
    metrics = {key: [] for key in additive}
    for account in accounts:
        data = loader(account["id"])
        if not data.get("ok"):
            combined["errors"].append({"profile":account["name"],"error":data.get("err","provider unavailable")})
            continue
        combined["ok"] = True
        for row in data.get("receipts",[]):
            combined["receipts"].append({**row,"profile_id":account["id"],"profile_name":account["name"]})
        for offer in data.get("offers",[]):
            combined["offers"].append({**offer,"profile_id":account["id"],"profile_name":account["name"]})
        for key in additive:
            if isinstance(data.get(key),(int,float)):
                metrics[key].append(data[key])
    for key, values in metrics.items():
        combined[key] = sum(values) if values and (selected or len(accounts) == 1) else None
    combined["count"] = len(combined["receipts"])
    combined["receipts"].sort(key=lambda x:x.get("date", ""), reverse=True)
    combined["offers"].sort(key=lambda x:x.get("title", ""))
    if combined["errors"]:
        combined["err"] = "Could not refresh: " + ", ".join(x["profile"] for x in combined["errors"])
    return combined

@_cache(300)
def coop_bonus(data_dir=None):
    return {} if DEMO else bonus_sources.coop_data(data_dir)

@_cache(300)
def coop_offers(profile_id="default"):
    if DEMO:return {"offers": []}
    profile=profiles.find(profile_id) or {"id":"default","name":"Default","legacy":True}
    return offer_ui.coop_data(profiles.data_dir(profile))

def coop_dashboard(selected=None):
    summary=coop_receipt_ui.enrich(receipt_archive.summary('coop'))
    receipts=[]
    for row in summary.get('receipts',[]):
        row={**row,'profile_id':row.get('profile_id') or 'default'}
        row['profile_name']='Demo' if DEMO else profiles.receipt_owner(row)['name']
        receipts.append(row)
    if selected:receipts=[x for x in receipts if (x.get('profile_id') or 'default')==selected]
    summary={**summary,'receipts':receipts,'count':len(receipts)}
    accounts=[] if DEMO else [p for p in profiles.connected_profiles() if 'coop' in p['providers'] and (not selected or p['id']==selected)]
    metrics=[];offers=[]
    for account in accounts:
        data_dir=profiles.data_dir(account)
        bonus=coop_bonus(str(data_dir));metrics.append(bonus)
        if not DEMO:
            offers.extend({**o,'profile_id':account['id'],'profile_name':account['name']} for o in coop_offers(account['id']).get('offers',[]))
    result={**summary,'offers':offers}
    additive=('bonus_year','discounts_year','coupons_year')
    for key in additive:
        values=[m[key] for m in metrics if isinstance(m.get(key),(int,float))]
        result[key]=sum(values) if values else None
    for key in ('bonus_year_period','savings_year_period'):
        values={m.get(key) for m in metrics if m.get(key) is not None}
        result[key]=next(iter(values)) if len(values)==1 else None
    for key in ('bonus_year_basis','savings_year_basis'):
        values=[m.get(key) for m in metrics if m.get(key)]
        result[key]=('provider_sum' if len(values)>1 else values[0]) if values else None
    result['bonus_year_note']=next((m.get('bonus_year_note') for m in metrics if m.get('bonus_year_note')),None)
    result['savings_year_note']=next((m.get('savings_year_note') for m in metrics if m.get('savings_year_note')),None)
    if len(accounts)==1:
        result.update(metrics[0] if metrics else {})
        result.update({} if DEMO else bonus_sources.account_observation('coop',profiles.data_dir(accounts[0]),receipts))
    else:
        result.update(account_balance=None,account_available=None,account_basis=None,bonus_balance=None,bonus_accumulated=None)
    return result

@app.route("/")
def index():
    selected = request.args.get("member") or None
    provider = request.args.get("provider") or ""
    selected_store = request.args.get("store", "").strip()
    member_rows = [{"id":"default","name":"Demo"}] if DEMO else profiles.all()
    inbox_rows = sorted(
        (x for x in receipt_archive.summary("inbox")["receipts"] if x.get("review", {}).get("state") not in ("linked", "discarded")),
        key=lambda x: x.get("intake", {}).get("received_at", ""), reverse=True,
    )
    t, r = household_provider("trumf", selected), household_provider("rema", selected)
    c = coop_dashboard(selected)
    if provider:
        if provider != "trumf": t={**t,"receipts":[],"count":0}
        if provider != "rema": r={**r,"receipts":[],"count":0}
        if provider != "coop": c={**c,"receipts":[],"count":0}
    inbox_rows = [x for x in inbox_rows if not selected or (x.get("profile_id") or "default")==selected]
    if selected_store:
        needle = selected_store.casefold()
        inbox_rows = [x for x in inbox_rows if needle in (x.get("store") or "").casefold()]
        for data in (t, r, c):
            data["receipts"] = [x for x in data.get("receipts", []) if needle in (x.get("store") or "").casefold()]
            if "count" in data:
                data["count"] = len(data["receipts"])
    return render_template("index.html", t=t, r=r, c=c, members=member_rows, selected_member=selected, selected_provider=provider,
      selected_store=selected_store, retailers=retailers.all(),
      offer_cards=[o for source, data in [("rema",r),("trumf",t),("coop",c)] for o in offer_ui.cards(source,data.get("offers"))],
      stats=dashboard_stats.cards(t,r,c,profile_id=selected,provider=provider or None,store=selected_store or None), inbox=inbox_store.summary(), inbox_rows=inbox_rows, demo=DEMO, **ui.context(t, r, c))

@app.get("/offers/<source>/<oid>")
def offer_detail(source, oid):
    if source not in ("trumf", "rema", "coop"):
        abort(404)
    profile_id=request.args.get("profile_id")
    if DEMO:
        loaders={"trumf":trumf_data,"rema":rema_data,"coop":coop_offers}
        data=loaders[source]()
    elif source=="coop":
        data=coop_offers(profile_id or "default")
        owner=profiles.find(profile_id or "default") or {"id":"default","name":"Default"}
        data={**data,"offers":[{**o,"profile_id":owner["id"],"profile_name":owner["name"]} for o in data.get("offers",[])]}
    else:data=household_provider(source,profile_id)
    rows = offer_ui.cards(source, data.get("offers"))
    offer = next((o for o in rows if o["id"] == oid), None)
    if offer is None:
        abort(404)
    return render_template("offer_detail.html", o=offer, demo=DEMO, themes=themes.load_themes())

@app.get("/favicon.ico")
def favicon():
    return send_file(os.path.join(app.static_folder, "brand", "favicon.ico"), mimetype="image/vnd.microsoft.icon")

@app.route("/themes.css")
def themes_css():
    return Response(themes.render_css(), mimetype="text/css", headers={"Cache-Control": "public, max-age=300"})

@app.route("/rema/offer/<code>/activate", methods=["POST"])
def rema_offer_activate(code):
    profile_id=request.form.get("profile_id") or "default"
    rema_activate(code, profile_id) if not DEMO else rema_activate(code)
    rema_data.clear()
    return redirect("/")

@app.route("/trumf/receipt/<bid>.<fmt>")
def trumf_receipt(bid, fmt):
    return _download("trumf", bid, fmt, trumf_lines(bid), f"Trumf kvittering {bid[:10]}")

@app.route("/trumf/receipt/<profile_id>/<bid>.<fmt>")
def trumf_member_receipt(profile_id, bid, fmt):
    return _download("trumf", bid, fmt, provider_lines("trumf", bid, profile_id), f"Trumf kvittering {bid[:10]}")

@app.route("/rema/receipt/<int:tid>.<fmt>")
def rema_receipt(tid, fmt):
    return _download("rema", tid, fmt, rema_lines(tid), f"Rema 1000 — {tid}")

@app.route("/rema/receipt/<profile_id>/<int:tid>.<fmt>")
def rema_member_receipt(profile_id, tid, fmt):
    return _download("rema", tid, fmt, provider_lines("rema", tid, profile_id), f"Rema 1000 — {tid}")

# ---------------- machine API (agents / bookkeeping) ----------------
@app.route("/api/summary")
def api_summary():
    selected=request.args.get("member") or None
    household=[{"id":"default","name":"Demo","providers":["trumf","rema","coop"]}] if DEMO else profiles.connected_profiles()
    return jsonify({"trumf": household_provider("trumf",selected), "rema": household_provider("rema",selected), "coop": coop_dashboard(selected), "inbox": inbox_store.summary(), "profiles": household})

@app.get("/api/profiles")
def api_profiles():
    return jsonify([{"id":"default","name":"Demo","providers":["trumf","rema","coop"]}] if DEMO else profiles.connected_profiles())

@app.post("/api/profiles")
def api_add_profile():
    if DEMO:abort(403)
    origin=request.headers.get("Origin")
    if request.headers.get("Sec-Fetch-Site")=="cross-site" or (origin and origin.split("//",1)[-1].split("/",1)[0]!=request.host):
        abort(403)
    if not request.is_json or not isinstance(request.get_json(),dict):
        return jsonify(error="Send a JSON object with a profile name."),400
    try: profile=profiles.ensure(request.get_json().get("name"))
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(profile),201

@app.patch("/api/profiles/<profile_id>")
def api_rename_profile(profile_id):
    if DEMO:abort(403)
    origin=request.headers.get("Origin")
    if request.headers.get("Sec-Fetch-Site")=="cross-site" or (origin and origin.split("//",1)[-1].split("/",1)[0]!=request.host):
        abort(403)
    if not request.is_json or not isinstance(request.get_json(),dict):
        return jsonify(error="Send a JSON object with a profile name."),400
    try:profile=profiles.rename(profile_id,request.get_json().get("name"))
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(profile)

@app.route('/api/coop/status')
def coop_status():
    return jsonify(receipt_archive.summary('coop')['status'])

def coop_record(rid):
    try: return receipt_archive.read_receipt('coop', rid)
    except (ValueError, FileNotFoundError): abort(404)

@app.route('/coop/receipt/<rid>')
def coop_detail(rid):
    r=coop_record(rid)
    r['profile_name']='Demo' if DEMO else profiles.receipt_owner(r)['name']
    return render_template("coop_detail.html", r=r, demo=DEMO, themes=themes.load_themes(),
      benefits=[(label,r['benefits'].get(k)) for k,label in [('purchaseReturn','Kjøpeutbytte'),('memberDiscount','Medlemsrabatt'),('couponDiscount','Kupongrabatt'),('coopMastercard','Coop Mastercard'),('totalMemberBenefit','Oppgitt medlemsfordel')]])

@app.route('/coop/receipt/<rid>.<fmt>')
def coop_download(rid,fmt):
    r=coop_record(rid)
    if fmt=='json':return Response(json.dumps(r,ensure_ascii=False,indent=2),mimetype='application/json',headers={'Content-Disposition':f'attachment;filename=coop-{r["archive_id"]}.json'})
    if fmt=='csv':return Response(receipt_archive.receipt_csv(r),mimetype='text/csv',headers={'Content-Disposition':f'attachment;filename=coop-{r["archive_id"]}.csv'})
    if fmt=='pdf':
        doc=next((d for d in r['documents'] if d['role']=='original' and d['mimetype']=='application/pdf'),None)
        if not doc:abort(404)
        path,_=receipt_archive.document('coop',rid,doc['filename'])
        return send_file(path,mimetype='application/pdf',as_attachment=True,download_name=f'coop-{r["receipt_id"]}.pdf')
    abort(404)

def _month_receipts(ym, with_lines=False, selected=None, provider=None):
    out = []
    t, r = household_provider("trumf",selected), household_provider("rema",selected)
    if t.get("ok"):
        for x in t["receipts"]:
            if x["date"].startswith(ym):
                rec = {"chain": "trumf", "id": str(x["id"]), "date": x["date"], "store": x["store"],"profile_id":x.get("profile_id") or "default","profile_name":x.get("profile_name") or "Default",
                       "amount": x["amount"], "bonus": x.get("bonus") or 0, "discount": 0}
                rec["archive_id"] = receipt_archive.key("trumf", rec["id"], rec["profile_id"])
                if with_lines and x.get("hasReceipt"):
                    rec["lines"] = provider_lines("trumf",x["id"],rec["profile_id"])
                out.append(rec)
    if r.get("ok"):
        for x in r["receipts"]:
            if x["date"].startswith(ym):
                rec = {"chain": "rema", "id": str(x["id"]), "date": x["date"][:10], "store": x["store"],"profile_id":x.get("profile_id") or "default","profile_name":x.get("profile_name") or "Default",
                       "amount": x["amount"], "bonus": 0, "discount": x.get("discount") or 0}
                rec["archive_id"] = receipt_archive.key("rema", rec["id"], rec["profile_id"])
                if with_lines:
                    rec["lines"] = provider_lines("rema",int(x["id"]),rec["profile_id"])
                out.append(rec)
    for x in receipt_archive.summary('coop')['receipts']:
        if (x.get('date') or '').startswith(ym):
            profile_id=x.get('profile_id') or 'default'
            profile_name='Demo' if DEMO else profiles.receipt_owner({'profile_id':profile_id})['name']
            rec={"chain":"coop","id":x['id'],"date":x['date'],'store':x['store'],'amount':x['amount'],'bonus':x.get('bonus') or 0,'discount':0,'archive_id':x['archive_id'],'profile_id':profile_id,'profile_name':profile_name}
            if with_lines:
                full=receipt_archive.read_receipt('coop',x['archive_id'])
                rec.update(full)
                # Existing combined totals require numbers; the source value stays explicit.
                rec['bonus']=full.get('bonus') or 0;rec['discount']=full.get('discount') or 0
            out.append(rec)
    # Add integer money and available archive metadata without changing legacy amount fields.
    for rec in out:
        source = rec['chain']
        rid = rec.get('archive_id') or receipt_archive.key(source, rec['id'])
        try:
            archived = receipt_archive.read_receipt(source, rid)
        except FileNotFoundError:
            archived = {}
        rec['amount_minor'] = archived.get('amount_minor')
        if rec['amount_minor'] is None:
            rec['amount_minor'] = receipt_archive.minor(rec.get('amount'))
        rec['payment'] = archived.get('payment')
        rec['currency'] = archived.get('currency') or 'NOK'
        if with_lines:
            for line in rec.get('lines', []):
                if line.get('amount_minor') is None:
                    line['amount_minor'] = receipt_archive.minor(line.get('amount'))
    out.extend(inbox_store.exports(ym, with_lines))
    if selected:out=[x for x in out if (x.get("profile_id") or "default")==selected]
    if provider:out=[x for x in out if x.get("chain")==provider]
    out.sort(key=lambda x: x["date"])
    return out

@app.route("/api/export/<ym>.<fmt>")
def api_export(ym, fmt):
    if not re.fullmatch(r"\d{4}-\d{2}", ym) or fmt not in ("json", "csv"):
        abort(404)
    with_lines = request.args.get("lines") == "1"
    recs = _month_receipts(ym, with_lines, request.args.get("member") or None, request.args.get("provider") or None)
    if fmt == "json":
        return jsonify({"month": ym, "count": len(recs),
                        "total": round(sum((x["amount"] or 0) for x in recs if x.get("currency", "NOK") == "NOK"), 2),
                        "bonus": round(sum(x["bonus"] for x in recs), 2),
                        "discount": round(sum(x["discount"] for x in recs), 2),
                        "total_currency": "NOK", "total_minor": sum(x["amount_minor"] or 0 for x in recs if x.get("currency") == "NOK"), "receipts": recs})
    buf = io.StringIO(); w = csv.writer(buf)
    extra_fields = ['profile_name', 'profile_id', 'source', 'archive_id', 'currency', 'category', 'review_state', 'confidence', 'linked_to', 'amount_minor', 'payment', 'interpretation_notes']
    def extra(x):
        return [json.dumps(x.get(k), ensure_ascii=False) if isinstance(x.get(k), (dict, list)) else
                x.get(k, 'NOK' if k == 'currency' else '') for k in extra_fields]
    if with_lines:
        w.writerow(["chain", "receipt_id", "date", "store", "item", "ean", "qty", "amount", "line_amount_minor", "kind"] + extra_fields)
        for x in recs:
            for l in x.get("lines", []):
                w.writerow([x["chain"], x["id"], x["date"], x["store"], l["name"], l["ean"], l["qty"], l["amount"], l.get("amount_minor"), l.get("kind")] + extra(x))
    else:
        w.writerow(["chain", "receipt_id", "date", "store", "amount", "bonus", "discount"] + extra_fields)
        for x in recs:
            w.writerow([x["chain"], x["id"], x["date"], x["store"], x["amount"], x["bonus"], x["discount"]] + extra(x))
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename=grocious-{ym}{'-lines' if with_lines else ''}.csv"})



# Independent archive routes preserve existing download contracts.
def archived_record(source,rid):
    try:return receipt_archive.read_receipt(source,rid)
    except (ValueError,FileNotFoundError):abort(404)

@app.route('/api/archive/<source>')
def archived_summary(source):
    try:return jsonify(receipt_archive.summary(source))
    except ValueError:abort(404)

@app.route('/archive/<source>')
def archived_list(source):
    try:data=receipt_archive.summary(source)
    except ValueError:abort(404)
    for row in data.get('receipts',[]):
        row['profile_name']='Demo' if DEMO else profiles.receipt_owner(row)['name']
    return render_template("archive_list.html", provider=source, data=data, demo=DEMO, themes=themes.load_themes())

# archive pages: templates/archive_list.html + archive_detail.html

@app.route('/archive/<source>/<rid>')
def archived_detail(source,rid):
    r=archived_record(source,rid)
    r['profile_name']='Demo' if DEMO else profiles.receipt_owner(r)['name']
    return render_template("archive_detail.html", r=r, provider=source, raw=json.dumps(r['source'], ensure_ascii=False, indent=2),
                           demo=DEMO, themes=themes.load_themes())

@app.route('/archive/<source>/<rid>.<fmt>')
def archived_download(source,rid,fmt):
    r=archived_record(source,rid)
    if fmt=='json':return Response(json.dumps(r,ensure_ascii=False,indent=2),mimetype='application/json',headers={'Content-Disposition':f'attachment;filename={source}-{rid}.json'})
    if fmt=='zip':
        import zipfile
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('receipt.json',json.dumps(r,ensure_ascii=False,indent=2))
            for d in r['documents']:
                path,_=receipt_archive.document(source,rid,d['filename']);z.write(path,d['filename'])
        buf.seek(0);return send_file(buf,mimetype='application/zip',as_attachment=True,download_name=f'{source}-{rid}.zip')
    abort(404)

@app.route('/archive/<source>/<rid>/file/<filename>')
def archived_file(source,rid,filename):
    archived_record(source,rid)
    try:path,doc=receipt_archive.document(source,rid,filename)
    except (ValueError,FileNotFoundError):abort(404)
    return send_file(path,mimetype=doc['mimetype'],as_attachment=not doc['mimetype'].startswith('image/'),download_name=filename)


app.config["MAX_CONTENT_LENGTH"] = 321 * 1024 * 1024
app.register_blueprint(inbox_bp)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "3012")))
