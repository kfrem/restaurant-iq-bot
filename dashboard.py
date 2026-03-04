"""
dashboard.py — Restaurant-IQ Interactive Web Dashboard

Serves a beautiful, interactive chart dashboard at the Flask server root.

Access at:  http://localhost:8080/
            http://YOUR-SERVER-IP:8080/

If DASHBOARD_TOKEN is set in .env, add it to the URL:
  http://localhost:8080/?token=YOUR_TOKEN

All charts are interactive:
  • Click segments on the overhead donut to see subcategory breakdown
  • Change the date range and all charts update instantly
  • Search any entry — type "salmon" to see every mention with dates and £ values
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request

from database import (
    _db,
    get_all_restaurants,
    get_entries_for_period,
    get_menu_items,
    get_noshow_logs,
    get_noshow_summary,
    get_overhead_summary,
    get_restaurant_by_id,
)
from intelligence import BENCHMARKS

# ── Config ────────────────────────────────────────────────────────────────────

DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")

dashboard_bp = Blueprint("dashboard", __name__)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _check_token() -> bool:
    if not DASHBOARD_TOKEN:
        return True  # open-access dev mode
    token = (
        request.args.get("token", "")
        or request.headers.get("X-Dashboard-Token", "")
    )
    return token == DASHBOARD_TOKEN


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _check_token():
            html = (
                "<html><body style='background:#0a0b14;color:#f87171;"
                "font-family:Inter,sans-serif;display:flex;align-items:center;"
                "justify-content:center;height:100vh;margin:0'>"
                "<div style='text-align:center'><h1 style='font-size:48px'>🔒</h1>"
                "<h2 style='color:#e2e8f0;margin:16px 0 8px'>Access Denied</h2>"
                "<p style='color:#64748b'>Set DASHBOARD_TOKEN in your .env file, "
                "then add <code style='color:#818cf8'>?token=YOUR_TOKEN</code> to the URL.</p>"
                "</div></body></html>"
            )
            return html, 401, {"Content-Type": "text/html"}
        return f(*args, **kwargs)
    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_sd(entry) -> dict:
    raw = entry["structured_data"] if "structured_data" in entry.keys() else None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _sum_entries(entries) -> dict:
    t = defaultdict(float)
    for e in entries:
        d = _parse_sd(e)
        t["revenue"]     += float(d.get("revenue",     d.get("total_revenue",     0)) or 0)
        t["food_cost"]   += float(d.get("food_cost",   d.get("total_food_cost",   0)) or 0)
        t["covers"]      += float(d.get("covers",      d.get("total_covers",      0)) or 0)
        t["labour_cost"] += float(d.get("labour_cost", d.get("total_labour_cost", 0)) or 0)
        t["waste_cost"]  += float(d.get("waste_cost",  0) or 0)
    return t


def _get_rid() -> int | None:
    rid = request.args.get("restaurant_id", type=int)
    if rid:
        return rid
    rs = get_all_restaurants()
    return rs[0]["id"] if rs else None


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── Routes ────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/")
@token_required
def index():
    open_notice = "" if DASHBOARD_TOKEN else (
        "<div id='sec-notice'>"
        "ℹ️ Open access mode — set <code>DASHBOARD_TOKEN</code> in .env for security"
        "</div>"
    )
    html = _DASHBOARD_HTML.replace("__OPEN_NOTICE__", open_notice) \
                          .replace("__TOKEN__", DASHBOARD_TOKEN)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@dashboard_bp.route("/api/restaurants")
@token_required
def api_restaurants():
    return jsonify([
        {"id": r["id"], "name": r["name"], "type": r.get("restaurant_type", "casual")}
        for r in get_all_restaurants()
    ])


@dashboard_bp.route("/api/kpis")
@token_required
def api_kpis():
    rid       = _get_rid()
    from_date = request.args.get("from", _days_ago(30))
    to_date   = request.args.get("to",   _today())
    if not rid:
        return jsonify({"error": "no restaurant"}), 404

    r_row  = get_restaurant_by_id(rid)
    rtype  = r_row.get("restaurant_type", "casual") if r_row else "casual"
    bench  = BENCHMARKS.get(rtype, BENCHMARKS["casual"])

    entries = get_entries_for_period(rid, from_date, to_date)
    t = _sum_entries(entries)

    rev  = t["revenue"]
    fc   = t["food_cost"]
    cov  = int(t["covers"])
    lab  = t["labour_cost"]
    wst  = t["waste_cost"]

    return jsonify({
        "revenue":        round(rev, 2),
        "food_cost":      round(fc, 2),
        "covers":         cov,
        "avg_spend":      round(rev / cov, 2) if cov else 0,
        "food_cost_pct":  round(fc / rev * 100, 1) if rev else 0,
        "gp_pct":         round((1 - fc / rev) * 100, 1) if rev else 0,
        "labour_cost":    round(lab, 2),
        "labour_pct":     round(lab / rev * 100, 1) if rev else 0,
        "waste_cost":     round(wst, 2),
        "restaurant_type": rtype,
        "benchmark":      dict(bench),
    })


@dashboard_bp.route("/api/revenue-trend")
@token_required
def api_revenue_trend():
    rid   = _get_rid()
    weeks = request.args.get("weeks", 8, type=int)
    if not rid:
        return jsonify({"weeks": []})

    end   = datetime.now().date()
    start = end - timedelta(weeks=weeks)
    entries = get_entries_for_period(rid, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    weekly: dict = defaultdict(lambda: defaultdict(float))
    for e in entries:
        d = _parse_sd(e)
        try:
            dt = datetime.strptime(e["entry_date"], "%Y-%m-%d")
            ws = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
        except Exception:
            continue
        weekly[ws]["revenue"]     += float(d.get("revenue",     d.get("total_revenue",   0)) or 0)
        weekly[ws]["food_cost"]   += float(d.get("food_cost",   d.get("total_food_cost", 0)) or 0)
        weekly[ws]["covers"]      += float(d.get("covers",      0) or 0)
        weekly[ws]["labour_cost"] += float(d.get("labour_cost", 0) or 0)

    result = []
    for ws in sorted(weekly):
        w   = weekly[ws]
        rev = w["revenue"]
        fc  = w["food_cost"]
        result.append({
            "week":          ws,
            "revenue":       round(rev, 2),
            "food_cost":     round(fc, 2),
            "food_cost_pct": round(fc / rev * 100, 1) if rev else 0,
            "covers":        int(w["covers"]),
            "labour_cost":   round(w["labour_cost"], 2),
        })
    return jsonify({"weeks": result})


@dashboard_bp.route("/api/overhead")
@token_required
def api_overhead():
    rid  = _get_rid()
    days = request.args.get("days", 30, type=int)
    if not rid:
        return jsonify({"categories": [], "total": 0})

    raw   = get_overhead_summary(rid, days=days)
    cats  = []
    total = 0.0
    for cat, subs in raw.items():
        ct = sum(s["total"] for s in subs.values())
        total += ct
        cats.append({
            "category": cat,
            "total":    round(ct, 2),
            "subcategories": sorted(
                [{"name": n, "total": round(s["total"], 2), "entries": s["entries"]}
                 for n, s in subs.items()],
                key=lambda x: x["total"], reverse=True,
            ),
        })
    cats.sort(key=lambda x: x["total"], reverse=True)
    return jsonify({"categories": cats, "total": round(total, 2), "days": days})


@dashboard_bp.route("/api/overhead-trend")
@token_required
def api_overhead_trend():
    rid = _get_rid()
    if not rid:
        return jsonify({"months": []})

    months = []
    today  = datetime.now().date()
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        ms = f"{y}-{m:02d}-01"
        me = f"{y}-{m + 1:02d}-01" if m < 12 else f"{y + 1}-01-01"
        with _db() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT SUM(amount) AS total FROM overhead_expenses "
                "WHERE restaurant_id = ? AND bill_date >= ? AND bill_date < ?",
                (rid, ms, me),
            )
            row = c.fetchone()
        months.append({
            "month": datetime(y, m, 1).strftime("%b %y"),
            "total": round(row["total"] or 0, 2) if row else 0,
        })
    return jsonify({"months": months})


@dashboard_bp.route("/api/menu")
@token_required
def api_menu():
    rid = _get_rid()
    if not rid:
        return jsonify({"items": []})

    items  = get_menu_items(rid)
    result = []
    for item in items:
        fc    = item["food_cost"]    or 0
        price = item["selling_price"] or 0
        gp    = round((price - fc) / price * 100, 1) if price > 0 else 0
        result.append({
            "name":          item["dish_name"],
            "food_cost":     round(fc, 2),
            "selling_price": round(price, 2),
            "gp_pct":        gp,
            "margin":        round(price - fc, 2),
        })
    result.sort(key=lambda x: x["gp_pct"], reverse=True)
    return jsonify({"items": result})


@dashboard_bp.route("/api/noshows")
@token_required
def api_noshows():
    rid  = _get_rid()
    days = request.args.get("days", 90, type=int)
    if not rid:
        return jsonify({"logs": [], "summary": {}})

    logs    = get_noshow_logs(rid, days=days)
    summary = get_noshow_summary(rid, days=days)
    return jsonify({
        "logs":    [dict(r) for r in logs],
        "summary": summary or {},
    })


@dashboard_bp.route("/api/entries/search")
@token_required
def api_entries_search():
    rid = _get_rid()
    q   = request.args.get("q", "").strip().lower()
    fd  = request.args.get("from", _days_ago(90))
    td  = request.args.get("to",   _today())
    if not rid:
        return jsonify({"entries": [], "count": 0})

    entries = get_entries_for_period(rid, fd, td)
    results = []
    for e in entries:
        raw = (e["raw_text"]        or "").lower()
        sd  = (e["structured_data"] or "").lower()
        if not q or q in raw or q in sd:
            d = _parse_sd(e)
            results.append({
                "date":      e["entry_date"],
                "time":      (e["entry_time"] or "")[:5],
                "category":  e.get("category", "") or "",
                "text":      (e["raw_text"] or "")[:280],
                "revenue":   round(float(d.get("revenue",   d.get("total_revenue",   0)) or 0), 2),
                "food_cost": round(float(d.get("food_cost", d.get("total_food_cost", 0)) or 0), 2),
            })

    results.sort(key=lambda x: x["date"], reverse=True)
    return jsonify({"entries": results[:100], "count": len(results)})


# ── Dashboard HTML ────────────────────────────────────────────────────────────
# All JS and CSS is self-contained. No build step. No extra files.
# Chart.js and Inter font are loaded from CDN.

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Restaurant-IQ Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080a12;--bg2:#0d0f1c;--card:rgba(255,255,255,0.045);
  --border:rgba(255,255,255,0.07);--text:#e2e8f0;--muted:#64748b;
  --primary:#818cf8;--green:#34d399;--red:#f87171;
  --amber:#fbbf24;--blue:#60a5fa;--purple:#a78bfa;
  --pink:#f472b6;--orange:#fb923c;
}
html,body{height:100%;font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:3px}

/* ── Nav ── */
nav{
  position:sticky;top:0;z-index:100;
  background:rgba(8,10,18,0.9);backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);
  padding:10px 22px;
  display:flex;align-items:center;gap:14px;flex-wrap:wrap;
}
.brand{display:flex;align-items:center;gap:10px}
.brand h1{font-size:17px;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--blue));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.brand .rtag{font-size:11px;color:var(--muted);background:rgba(129,140,248,0.12);padding:2px 8px;border-radius:20px;font-weight:500}
.nav-right{display:flex;align-items:center;gap:8px;margin-left:auto;flex-wrap:wrap}
select,input[type=date]{
  background:rgba(255,255,255,0.05);border:1px solid var(--border);
  color:var(--text);padding:5px 10px;border-radius:8px;font-size:12px;
  font-family:inherit;cursor:pointer;outline:none;transition:border-color .2s;
}
select:hover,input[type=date]:hover{border-color:var(--primary)}
.qbtns{display:flex;gap:3px}
.qbtn{
  background:transparent;border:1px solid var(--border);color:var(--muted);
  padding:4px 9px;border-radius:6px;font-size:11px;font-family:inherit;
  cursor:pointer;transition:all .15s;
}
.qbtn:hover,.qbtn.on{background:var(--primary);border-color:var(--primary);color:#fff}

/* ── Layout ── */
main{padding:18px 22px;max-width:1680px;margin:0 auto}
#sec-notice{
  background:rgba(124,58,237,.12);border:1px solid rgba(124,58,237,.3);
  border-radius:8px;padding:7px 14px;font-size:12px;color:var(--purple);margin-bottom:14px;
}
#sec-notice code{background:rgba(129,140,248,.15);padding:1px 5px;border-radius:4px}

/* ── KPI cards ── */
.kpi-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.kcard{
  background:var(--card);border:1px solid var(--border);border-radius:13px;
  padding:16px 18px;position:relative;overflow:hidden;
  transition:border-color .2s,transform .15s;animation:fadeUp .4s ease both;
}
.kcard:hover{border-color:rgba(129,140,248,.35);transform:translateY(-2px)}
.kcard::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--kline,var(--primary))}
.kcard .lbl{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-bottom:8px}
.kcard .val{font-size:26px;font-weight:700;letter-spacing:-.5px;line-height:1.1}
.kcard .sub{font-size:11px;color:var(--muted);margin-top:6px;display:flex;align-items:center;gap:5px}
.badge{font-size:10px;padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap}
.bg{background:rgba(52,211,153,.14);color:var(--green)}
.br{background:rgba(248,113,113,.14);color:var(--red)}
.ba{background:rgba(251,191,36,.14);color:var(--amber)}

/* ── Chart cards ── */
.row2{display:grid;gap:14px;margin-bottom:14px}
.r3-1{grid-template-columns:2fr 1fr}
.r2{grid-template-columns:1fr 1fr}
.r1-2{grid-template-columns:1fr 2fr}
.cc{background:var(--card);border:1px solid var(--border);border-radius:13px;padding:18px}
.ch{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:14px}
.cht{font-size:13px;font-weight:600}
.chs{font-size:11px;color:var(--muted);margin-top:2px}
.cw{position:relative;height:260px}
.cw canvas{width:100%!important;height:100%!important}

/* ── Legend ── */
.leg{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.li{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted);cursor:pointer;transition:color .15s}
.li:hover{color:var(--text)}
.ld{width:8px;height:8px;border-radius:50%;flex-shrink:0}

/* ── Table ── */
.tbl{width:100%;border-collapse:collapse;font-size:12px}
.tbl th{text-align:left;padding:7px 10px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:1px solid var(--border)}
.tbl td{padding:9px 10px;border-bottom:1px solid rgba(255,255,255,0.035);color:var(--text)}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:rgba(255,255,255,0.02)}
.gph{background:rgba(52,211,153,.14);color:var(--green);padding:2px 7px;border-radius:12px;font-size:11px;font-weight:600}
.gpm{background:rgba(251,191,36,.14);color:var(--amber);padding:2px 7px;border-radius:12px;font-size:11px;font-weight:600}
.gpl{background:rgba(248,113,113,.14);color:var(--red);padding:2px 7px;border-radius:12px;font-size:11px;font-weight:600}

/* ── Search ── */
.sbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.si{
  flex:1;min-width:200px;background:rgba(255,255,255,0.05);
  border:1px solid var(--border);color:var(--text);padding:8px 14px;
  border-radius:8px;font-size:13px;font-family:inherit;outline:none;transition:border-color .2s;
}
.si:focus{border-color:var(--primary)}
.si::placeholder{color:var(--muted)}
.sbtn{
  background:var(--primary);border:none;color:#fff;padding:7px 16px;
  border-radius:8px;font-size:12px;font-family:inherit;cursor:pointer;
  transition:opacity .15s;
}
.sbtn:hover{opacity:.85}
.rc{font-size:11px;color:var(--muted)}

/* ── Empty / spinner ── */
.empty{text-align:center;padding:36px;color:var(--muted)}
.empty strong{display:block;font-size:22px;margin-bottom:6px}
.spin{width:26px;height:26px;border:3px solid rgba(129,140,248,.15);border-top-color:var(--primary);border-radius:50%;animation:spin .7s linear infinite;margin:36px auto}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* ── Responsive ── */
@media(max-width:960px){.r3-1,.r2,.r1-2{grid-template-columns:1fr}main{padding:10px}}
</style>
</head>
<body>

<nav>
  <div class="brand">
    <h1>🍽 Restaurant-IQ</h1>
    <span class="rtag" id="rtype-badge">loading…</span>
  </div>
  <div class="nav-right">
    <select id="rsel" onchange="onRChange()"><option>Loading…</option></select>
    <div class="qbtns">
      <button class="qbtn" onclick="setRange(7,this)">7D</button>
      <button class="qbtn on" onclick="setRange(30,this)">30D</button>
      <button class="qbtn" onclick="setRange(90,this)">90D</button>
      <button class="qbtn" onclick="setRange(365,this)">1Y</button>
    </div>
    <input type="date" id="fd" onchange="refresh()">
    <input type="date" id="td" onchange="refresh()">
  </div>
</nav>

<main>
  __OPEN_NOTICE__

  <!-- KPI row -->
  <div class="kpi-row" id="krow"><div class="spin"></div></div>

  <!-- Revenue trend + Overhead donut -->
  <div class="row2 r3-1">
    <div class="cc">
      <div class="ch">
        <div><div class="cht">Revenue &amp; Food Cost</div><div class="chs">Weekly trend</div></div>
        <select id="twks" onchange="loadTrend()" style="font-size:11px;padding:3px 7px">
          <option value="8">8 weeks</option>
          <option value="13">13 weeks</option>
          <option value="26">26 weeks</option>
        </select>
      </div>
      <div class="cw"><canvas id="cRevenue"></canvas></div>
    </div>
    <div class="cc">
      <div class="ch">
        <div><div class="cht">Overhead by Category</div><div class="chs" id="oh-lbl">last 30 days</div></div>
      </div>
      <div class="cw" style="height:220px"><canvas id="cDonut"></canvas></div>
      <div class="leg" id="ohleg"></div>
    </div>
  </div>

  <!-- Food cost % + Overhead bar -->
  <div class="row2 r2">
    <div class="cc">
      <div class="ch">
        <div><div class="cht">Food Cost %</div><div class="chs">vs your benchmark</div></div>
      </div>
      <div class="cw"><canvas id="cFC"></canvas></div>
    </div>
    <div class="cc">
      <div class="ch">
        <div><div class="cht">Monthly Overhead Spend</div><div class="chs">Last 6 months</div></div>
      </div>
      <div class="cw"><canvas id="cOhBar"></canvas></div>
    </div>
  </div>

  <!-- Menu + No-shows -->
  <div class="row2 r2">
    <div class="cc">
      <div class="ch">
        <div><div class="cht">Menu Profitability</div><div class="chs">🟢 Star dish  🟡 Rethink pricing  🔴 Losing money</div></div>
      </div>
      <div id="mwrap" style="max-height:290px;overflow-y:auto"><div class="spin"></div></div>
    </div>
    <div class="cc">
      <div class="ch">
        <div><div class="cht">No-Show Tracker</div><div class="chs">Booking no-shows &amp; revenue impact</div></div>
      </div>
      <div id="nswrap"><div class="spin"></div></div>
    </div>
  </div>

  <!-- Entry Search -->
  <div class="cc" style="margin-bottom:16px">
    <div class="ch">
      <div>
        <div class="cht">🔍 Entry Search</div>
        <div class="chs">Search every voice note, photo and text — try "salmon", "chicken", "rent", "waste"</div>
      </div>
      <span class="rc" id="src"></span>
    </div>
    <div class="sbar">
      <input class="si" id="sq" type="text" placeholder="Type an ingredient, supplier, expense…" oninput="onSI()">
      <input type="date" id="sfd" style="font-size:11px;padding:4px 8px">
      <input type="date" id="std" style="font-size:11px;padding:4px 8px">
      <button class="sbtn" onclick="doSearch()">Search</button>
    </div>
    <div id="sres"></div>
  </div>
</main>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
const TOKEN = "__TOKEN__";
let rid = null, rtype = "casual";
let fd = dAgo(30), td = dNow();

// Chart handles
let cRev, cDonut, cFC, cOhBar;

const BENCH = {
  casual:    {food_cost_pct:30,gp_pct:70,avg_spend:28,covers_week:400},
  fine:      {food_cost_pct:35,gp_pct:65,avg_spend:75,covers_week:200},
  qsr:       {food_cost_pct:30,gp_pct:70,avg_spend:12,covers_week:800},
  cafe:      {food_cost_pct:27,gp_pct:73,avg_spend:15,covers_week:500},
  gastropub: {food_cost_pct:31,gp_pct:69,avg_spend:22,covers_week:550},
};
const CAT_COLOR = {
  energy:'#fbbf24',occupancy:'#f87171',staffing:'#a78bfa',
  compliance:'#34d399',marketing:'#60a5fa',finance:'#f472b6',
  operations:'#fb923c',admin:'#94a3b8',custom:'#6b7280',
};

// Chart.js global defaults
Chart.defaults.color = '#64748b';
Chart.defaults.font.family = 'Inter, sans-serif';
Chart.defaults.font.size = 11;

// ── Utils ─────────────────────────────────────────────────────────────────────
function dNow(){ return new Date().toISOString().split('T')[0]; }
function dAgo(n){ const d=new Date(); d.setDate(d.getDate()-n); return d.toISOString().split('T')[0]; }
function gbp(n){ return '£'+(n||0).toLocaleString('en-GB',{minimumFractionDigits:0,maximumFractionDigits:0}); }
function gbpD(n){ return '£'+(n||0).toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function pct(n){ return (n||0).toFixed(1)+'%'; }

function apiUrl(path, p={}){
  const u = new URL(path, location.origin);
  Object.entries(p).forEach(([k,v])=>{ if(v!==null&&v!==undefined) u.searchParams.set(k,v); });
  if(TOKEN) u.searchParams.set('token', TOKEN);
  return u.toString();
}
async function api(path, p={}){
  const r = await fetch(apiUrl(path, p));
  if(!r.ok) throw new Error(r.status);
  return r.json();
}

function ttCfg(extra={}){
  return {
    backgroundColor:'rgba(13,15,28,.96)',
    borderColor:'rgba(255,255,255,.1)',borderWidth:1,
    titleColor:'#e2e8f0',bodyColor:'#94a3b8',
    padding:10,cornerRadius:8,...extra
  };
}
function scaleCfg(){
  return {
    x:{grid:{color:'rgba(255,255,255,0.035)'},ticks:{color:'#475569'}},
    y:{grid:{color:'rgba(255,255,255,0.035)'},ticks:{color:'#475569'}},
  };
}

// ── Boot ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async ()=>{
  document.getElementById('fd').value = fd;
  document.getElementById('td').value = td;
  document.getElementById('sfd').value = dAgo(90);
  document.getElementById('std').value = dNow();

  const rs = await api('/api/restaurants');
  const sel = document.getElementById('rsel');
  sel.innerHTML = '';
  if(!rs.length){ sel.innerHTML='<option>No restaurants registered</option>'; return; }
  rs.forEach((r,i)=>{
    const o = document.createElement('option');
    o.value = r.id; o.text = r.name;
    if(i===0){ rid=r.id; rtype=r.type||'casual'; }
    sel.appendChild(o);
  });
  refresh();
});

function onRChange(){
  const sel = document.getElementById('rsel');
  rid = parseInt(sel.value);
  refresh();
}
function setRange(n, btn){
  fd = dAgo(n); td = dNow();
  document.getElementById('fd').value = fd;
  document.getElementById('td').value = td;
  document.querySelectorAll('.qbtn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  refresh();
}
function refresh(){
  fd = document.getElementById('fd').value || dAgo(30);
  td = document.getElementById('td').value || dNow();
  loadKPIs(); loadTrend(); loadOverhead(); loadOhBar(); loadMenu(); loadNoshows();
}

// ── KPI Cards ─────────────────────────────────────────────────────────────────
async function loadKPIs(){
  const g = document.getElementById('krow');
  g.innerHTML = '<div class="spin"></div>';
  try {
    const d = await api('/api/kpis',{restaurant_id:rid,from:fd,to:td});
    rtype = d.restaurant_type || 'casual';
    document.getElementById('rtype-badge').textContent =
      rtype.charAt(0).toUpperCase() + rtype.slice(1);
    const b = BENCH[rtype]||BENCH.casual;
    const spd = b.avg_spend>0? ((d.avg_spend-b.avg_spend)/b.avg_spend*100).toFixed(1) : 0;
    const fcOk = d.food_cost_pct <= b.food_cost_pct;
    const gpOk = d.gp_pct >= b.gp_pct;
    const lbOk = d.labour_pct <= 30;
    const lbWrn = !lbOk && d.labour_pct <= 35;
    g.innerHTML = `
      <div class="kcard" style="--kline:linear-gradient(90deg,#60a5fa,#818cf8);animation-delay:.05s">
        <div class="lbl">Revenue</div>
        <div class="val" style="color:var(--blue)">${gbp(d.revenue)}</div>
        <div class="sub">${fd} → ${td}</div>
      </div>
      <div class="kcard" style="--kline:linear-gradient(90deg,#a78bfa,#818cf8);animation-delay:.1s">
        <div class="lbl">Covers</div>
        <div class="val" style="color:var(--purple)">${(d.covers||0).toLocaleString()}</div>
        <div class="sub">Benchmark ${b.covers_week}/wk</div>
      </div>
      <div class="kcard" style="--kline:linear-gradient(90deg,#34d399,#60a5fa);animation-delay:.15s">
        <div class="lbl">Avg Spend / Head</div>
        <div class="val" style="color:var(--green)">${gbpD(d.avg_spend)}</div>
        <div class="sub">
          <span class="badge ${spd>=0?'bg':'br'}">${spd>=0?'+':''}${spd}%</span>
          vs £${b.avg_spend} benchmark
        </div>
      </div>
      <div class="kcard" style="--kline:linear-gradient(90deg,${fcOk?'#34d399':'#f87171'},${fcOk?'#60a5fa':'#fbbf24'});animation-delay:.2s">
        <div class="lbl">Food Cost %</div>
        <div class="val" style="color:${fcOk?'var(--text)':'var(--red)'}">${pct(d.food_cost_pct)}</div>
        <div class="sub">
          <span class="badge ${fcOk?'bg':'br'}">${fcOk?'✓ on target':'▲ above target'}</span>
          target ${b.food_cost_pct}%
        </div>
      </div>
      <div class="kcard" style="--kline:linear-gradient(90deg,#34d399,#34d399);animation-delay:.25s">
        <div class="lbl">GP Margin</div>
        <div class="val" style="color:${gpOk?'var(--green)':'var(--red)'}">${pct(d.gp_pct)}</div>
        <div class="sub">
          <span class="badge ${gpOk?'bg':'br'}">${gpOk?'✓ on target':'▼ below target'}</span>
          target ${b.gp_pct}%
        </div>
      </div>
      <div class="kcard" style="--kline:linear-gradient(90deg,#f472b6,#a78bfa);animation-delay:.3s">
        <div class="lbl">Labour %</div>
        <div class="val" style="color:${lbOk?'var(--text)':lbWrn?'var(--amber)':'var(--red)'}">${pct(d.labour_pct)}</div>
        <div class="sub">
          <span class="badge ${lbOk?'bg':lbWrn?'ba':'br'}">${lbOk?'✓ good':lbWrn?'~ watch':'▲ high'}</span>
          target &lt;30–32%
        </div>
      </div>`;
  } catch(e){
    g.innerHTML = '<div class="empty"><strong>📊</strong><p>No data yet — send a voice note to the bot to start tracking.</p></div>';
  }
}

// ── Revenue Trend ─────────────────────────────────────────────────────────────
async function loadTrend(){
  const wks = parseInt(document.getElementById('twks').value)||8;
  const d   = await api('/api/revenue-trend',{restaurant_id:rid,weeks:wks});
  const lbs = d.weeks.map(w=>{
    const dt=new Date(w.week);
    return dt.toLocaleDateString('en-GB',{day:'numeric',month:'short'});
  });
  const ctx = document.getElementById('cRevenue');
  if(cRev) cRev.destroy();
  cRev = new Chart(ctx,{
    type:'line',
    data:{
      labels:lbs,
      datasets:[
        {
          label:'Revenue',
          data:d.weeks.map(w=>w.revenue),
          borderColor:'#60a5fa',backgroundColor:'rgba(96,165,250,0.08)',
          borderWidth:2.5,fill:true,tension:0.4,
          pointBackgroundColor:'#60a5fa',pointRadius:4,pointHoverRadius:7,
        },
        {
          label:'Food Cost',
          data:d.weeks.map(w=>w.food_cost),
          borderColor:'#f87171',backgroundColor:'rgba(248,113,113,0.06)',
          borderWidth:2,fill:true,tension:0.4,
          pointBackgroundColor:'#f87171',pointRadius:3,pointHoverRadius:6,
        },
      ],
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{labels:{color:'#94a3b8',boxWidth:12,font:{size:11}}},
        tooltip:{...ttCfg(),callbacks:{label:c=>` ${c.dataset.label}: ${gbp(c.parsed.y)}`}},
      },
      scales:{
        x:{...scaleCfg().x},
        y:{...scaleCfg().y,ticks:{...scaleCfg().y.ticks,callback:v=>gbp(v)}},
      },
    },
  });
  // Also draw FC% chart with same data
  const b = BENCH[rtype]||BENCH.casual;
  drawFCChart(d.weeks, b.food_cost_pct);
}

// ── Food Cost % chart ─────────────────────────────────────────────────────────
function drawFCChart(weeks, benchPct){
  const lbs    = weeks.map(w=>{const d=new Date(w.week);return d.toLocaleDateString('en-GB',{day:'numeric',month:'short'});});
  const fcPcts = weeks.map(w=>w.food_cost_pct);
  const ctx    = document.getElementById('cFC');
  if(cFC) cFC.destroy();
  cFC = new Chart(ctx,{
    type:'line',
    data:{
      labels:lbs,
      datasets:[
        {
          label:'Your Food Cost %',
          data:fcPcts,
          borderColor:'#f87171',backgroundColor:'rgba(248,113,113,0.07)',
          borderWidth:2.5,fill:true,tension:0.4,
          pointBackgroundColor:'#f87171',pointRadius:4,pointHoverRadius:7,
        },
        {
          label:`Benchmark (${benchPct}%)`,
          data:weeks.map(()=>benchPct),
          borderColor:'rgba(251,191,36,0.55)',borderWidth:1.5,
          borderDash:[6,4],fill:false,pointRadius:0,tension:0,
        },
      ],
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{labels:{color:'#94a3b8',boxWidth:12,font:{size:11}}},
        tooltip:{...ttCfg(),callbacks:{label:c=>` ${c.dataset.label}: ${c.parsed.y.toFixed(1)}%`}},
      },
      scales:{
        x:{...scaleCfg().x},
        y:{...scaleCfg().y,ticks:{...scaleCfg().y.ticks,callback:v=>v+'%'}},
      },
    },
  });
}

// ── Overhead Donut ────────────────────────────────────────────────────────────
async function loadOverhead(){
  const daysDiff = Math.max(1, Math.round((new Date(td)-new Date(fd))/(864e5)));
  const d = await api('/api/overhead',{restaurant_id:rid,days:daysDiff});
  document.getElementById('oh-lbl').textContent =
    `Total: ${gbp(d.total)} · ${d.days} days`;

  const labels = d.categories.map(c=>c.category.charAt(0).toUpperCase()+c.category.slice(1));
  const vals   = d.categories.map(c=>c.total);
  const cols   = d.categories.map(c=>CAT_COLOR[c.category]||'#6b7280');

  // Legend
  const leg = document.getElementById('ohleg');
  leg.innerHTML = d.categories.map((c,i)=>
    `<div class="li"><div class="ld" style="background:${cols[i]}"></div><span>${labels[i]} ${gbp(c.total)}</span></div>`
  ).join('');

  const ctx = document.getElementById('cDonut');
  if(cDonut) cDonut.destroy();
  if(!d.categories.length){
    ctx.parentElement.innerHTML='<div class="empty"><strong>💰</strong><p>No overheads logged yet.</p><p style="font-size:11px;margin-top:6px">Log costs via Telegram: /overhead rent 2000</p></div>';
    return;
  }
  cDonut = new Chart(ctx,{
    type:'doughnut',
    data:{
      labels,
      datasets:[{
        data:vals,
        backgroundColor:cols.map(c=>c+'bb'),
        borderColor:cols,
        borderWidth:1.5,
        hoverOffset:10,
      }],
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      cutout:'62%',
      plugins:{
        legend:{display:false},
        tooltip:{
          ...ttCfg(),
          callbacks:{
            label:(c)=>{
              const cat = d.categories[c.dataIndex];
              const p = d.total>0?(c.parsed/d.total*100).toFixed(1):0;
              const lines = [`  ${gbp(c.parsed)} — ${p}%`];
              cat.subcategories.forEach(s=>lines.push(`    · ${s.name}: ${gbp(s.total)}`));
              return lines;
            },
          },
        },
      },
    },
  });
}

// ── Overhead Bar ──────────────────────────────────────────────────────────────
async function loadOhBar(){
  const d = await api('/api/overhead-trend',{restaurant_id:rid});
  const ctx = document.getElementById('cOhBar');
  if(cOhBar) cOhBar.destroy();
  if(!d.months.some(m=>m.total>0)){
    ctx.parentElement.innerHTML='<div class="empty"><strong>📈</strong><p>No monthly overhead history yet.</p></div>';
    return;
  }
  cOhBar = new Chart(ctx,{
    type:'bar',
    data:{
      labels:d.months.map(m=>m.month),
      datasets:[{
        label:'Overhead Spend',
        data:d.months.map(m=>m.total),
        backgroundColor:'rgba(129,140,248,0.3)',
        borderColor:'#818cf8',borderWidth:1.5,borderRadius:6,
      }],
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{
        legend:{display:false},
        tooltip:{...ttCfg(),callbacks:{label:c=>` ${gbp(c.parsed.y)}`}},
      },
      scales:{
        x:{...scaleCfg().x},
        y:{...scaleCfg().y,ticks:{...scaleCfg().y.ticks,callback:v=>gbp(v)}},
      },
    },
  });
}

// ── Menu Table ────────────────────────────────────────────────────────────────
async function loadMenu(){
  const w = document.getElementById('mwrap');
  const d = await api('/api/menu',{restaurant_id:rid});
  if(!d.items.length){
    w.innerHTML='<div class="empty"><strong>🍽</strong><p>No menu items yet.</p><p style="font-size:11px;margin-top:6px">Add them: /menu add "Beef Burger" 6.50 14.00</p></div>';
    return;
  }
  w.innerHTML=`<table class="tbl">
    <thead><tr><th>Dish</th><th>Cost</th><th>Price</th><th>Margin</th><th>GP%</th></tr></thead>
    <tbody>${d.items.map(it=>{
      const cls = it.gp_pct>=65?'gph':it.gp_pct>=50?'gpm':'gpl';
      return `<tr>
        <td><strong>${it.name}</strong></td>
        <td style="color:var(--red)">${gbpD(it.food_cost)}</td>
        <td>${gbpD(it.selling_price)}</td>
        <td style="color:var(--green)">${gbpD(it.margin)}</td>
        <td><span class="${cls}">${it.gp_pct}%</span></td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

// ── No-shows ──────────────────────────────────────────────────────────────────
async function loadNoshows(){
  const w = document.getElementById('nswrap');
  const d = await api('/api/noshows',{restaurant_id:rid,days:90});
  const s = d.summary;
  if(!s||!s.total_noshows){
    w.innerHTML=`<div class="empty"><strong>📋</strong>
      <p>No no-shows tracked yet.</p>
      <p style="font-size:11px;margin-top:6px">Log with /noshow 3 in Telegram.</p>
      <p style="font-size:11px;color:#475569;margin-top:10px">
        UK average: 5–10% of bookings no-show.<br>
        At 400 covers/week that's £58,000/year lost.
      </p></div>`;
    return;
  }
  const rateCol = s.noshow_rate_pct>10?'var(--red)':s.noshow_rate_pct>5?'var(--amber)':'var(--green)';
  w.innerHTML=`
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px">
      <div style="text-align:center;padding:10px;background:rgba(255,255,255,0.03);border-radius:9px">
        <div style="font-size:20px;font-weight:700;color:${rateCol}">${(s.noshow_rate_pct||0).toFixed(1)}%</div>
        <div style="font-size:10px;color:var(--muted);margin-top:3px">No-show rate</div>
      </div>
      <div style="text-align:center;padding:10px;background:rgba(255,255,255,0.03);border-radius:9px">
        <div style="font-size:20px;font-weight:700;color:var(--red)">${s.total_noshows||0}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:3px">Covers missed</div>
      </div>
      <div style="text-align:center;padding:10px;background:rgba(255,255,255,0.03);border-radius:9px">
        <div style="font-size:20px;font-weight:700;color:var(--purple)">${s.log_days||0}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:3px">Days tracked</div>
      </div>
    </div>
    <table class="tbl">
      <thead><tr><th>Date</th><th>No-shows</th><th>Booked</th><th>Note</th></tr></thead>
      <tbody>${d.logs.slice(0,8).map(l=>`<tr>
        <td>${l.log_date}</td>
        <td style="color:var(--red);font-weight:600">${l.covers_noshow}</td>
        <td style="color:var(--muted)">${l.covers_booked||'—'}</td>
        <td style="color:var(--muted);font-size:11px">${l.note||''}</td>
      </tr>`).join('')}</tbody>
    </table>`;
}

// ── Entry Search ──────────────────────────────────────────────────────────────
let st;
function onSI(){ clearTimeout(st); st=setTimeout(doSearch,320); }
async function doSearch(){
  const q  = document.getElementById('sq').value.trim();
  const sf = document.getElementById('sfd').value||dAgo(90);
  const st2= document.getElementById('std').value||dNow();
  const w  = document.getElementById('sres');
  const rc = document.getElementById('src');
  if(!q){ w.innerHTML=''; rc.textContent=''; return; }

  w.innerHTML='<div class="spin"></div>';
  const d = await api('/api/entries/search',{restaurant_id:rid,q,from:sf,to:st2});
  rc.textContent = `${d.count} result${d.count!==1?'s':''}`;

  if(!d.entries.length){
    w.innerHTML=`<div class="empty"><p>No entries found matching "<strong>${q}</strong>"</p></div>`;
    return;
  }
  const catBadge = cat => {
    const c = (cat||'general').toLowerCase();
    const cl = c==='allergen'?'br':c==='delivery_issue'?'ba':'bg';
    return `<span class="badge ${cl}" style="font-size:10px">${c}</span>`;
  };
  w.innerHTML=`<table class="tbl">
    <thead><tr><th>Date</th><th>Time</th><th>Category</th><th>Revenue</th><th>Food Cost</th><th>Entry</th></tr></thead>
    <tbody>${d.entries.map(e=>`<tr>
      <td style="white-space:nowrap">${e.date}</td>
      <td style="color:var(--muted)">${e.time}</td>
      <td>${catBadge(e.category)}</td>
      <td style="color:var(--blue)">${e.revenue?gbp(e.revenue):'—'}</td>
      <td style="color:var(--red)">${e.food_cost?gbp(e.food_cost):'—'}</td>
      <td style="color:var(--muted);font-size:11px;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${e.text.replace(/"/g,'&quot;')}">${e.text||'—'}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}
</script>
</body>
</html>
"""
