"""
dashboard.py — lightweight HTTP dashboard server for Restaurant-IQ.

Runs in a daemon thread alongside the Telegram bot.
Exposes:
  GET /                        → landing page
  GET /dashboard/<token>       → full HTML dashboard
  GET /api/<token>             → JSON data (used by auto-refresh JS)
"""

import json
import threading
import logging
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── Data builder ───────────────────────────────────────────────────────────────

def _week_bounds(ref: date, offset: int = 0):
    monday = ref - timedelta(days=ref.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def _week_label(ws: str, we: str) -> str:
    try:
        s = datetime.strptime(ws, "%Y-%m-%d")
        e = datetime.strptime(we, "%Y-%m-%d")
        return f"Mon {s.day} {s.strftime('%b')} – Sun {e.day} {e.strftime('%b %Y')}"
    except ValueError:
        return f"{ws} to {we}"


def _fmt_t(t: str) -> str:
    if not t:
        return ""
    try:
        h, m = t.split(":")
        return f"{int(h)}:{m}"
    except ValueError:
        return t


def build_dashboard_data(restaurant) -> dict:
    """Gather all data for the dashboard JSON payload."""
    from database import (
        get_rota_for_week,
        get_stock_status,
        get_low_stock_items,
        get_outstanding_invoices,
        get_financial_summary,
        get_entries_with_staff,
        get_eightysix_trends,
        get_allergen_alerts,
    )

    rid = restaurant["id"]
    today = date.today()
    this_start, this_end = _week_bounds(today)
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    month_end = today.strftime("%Y-%m-%d")

    # Rota — current week
    raw_rota = get_rota_for_week(rid, this_start, this_end)
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    rota_by_day = []
    monday = datetime.strptime(this_start, "%Y-%m-%d")
    for i in range(7):
        day_date = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        day_label = (monday + timedelta(days=i)).strftime(f"%-d %b")
        shifts = [
            {
                "id": s["id"],
                "name": s["staff_name"],
                "start": _fmt_t(s["start_time"]),
                "end": _fmt_t(s["end_time"]),
                "role": s["role"] or "",
            }
            for s in raw_rota if s["shift_date"] == day_date
        ]
        rota_by_day.append({"day": DAY_NAMES[i], "date": day_label, "shifts": shifts})

    # Stock
    stock_items = get_stock_status(rid)
    low_items = get_low_stock_items(rid)
    stock_data = [
        {
            "name": s["item_name"],
            "par": s["par_level"],
            "current": s["current_level"],
            "unit": s["unit"] or "",
            "low": s["current_level"] is not None and s["current_level"] < s["par_level"],
        }
        for s in stock_items
    ]

    # Outstanding invoices
    invoices = get_outstanding_invoices(rid)
    invoice_total = sum(float(i["amount"] or 0) for i in invoices)
    invoice_list = [
        {
            "id": i["id"],
            "supplier": i["supplier_name"],
            "amount": float(i["amount"] or 0),
            "due": i["due_date"] or "",
            "overdue": bool(i["due_date"] and i["due_date"] < today.strftime("%Y-%m-%d")),
        }
        for i in invoices
    ]

    # Financial summary — this month
    fin = get_financial_summary(rid, month_start, month_end)

    # Recent entries — last 10
    entries_raw = get_entries_with_staff(rid, this_start, this_end)
    recent_entries = [
        {
            "date": e["entry_date"],
            "staff": e["staff_name"] if "staff_name" in e.keys() else "—",
            "category": e["category"] or "general",
            "summary": (e["raw_text"] or "")[:120],
        }
        for e in entries_raw[-10:]
    ][::-1]  # newest first

    # 86 trends — this month
    eightysix = get_eightysix_trends(rid, month_start, month_end)
    eightysix_list = [
        {"item": t["item_name"], "count": t["mention_count"]}
        for t in eightysix[:10]
    ]

    # Unresolved allergen alerts — last 90 days
    allergens = [a for a in get_allergen_alerts(rid, days_back=90) if not a["resolved_at"]]
    allergen_list = [
        {
            "id": a["id"],
            "date": a["alert_date"],
            "description": (a["description"] or "")[:100],
            "severity": a["severity"] or "medium",
        }
        for a in allergens[:5]
    ]

    return {
        "restaurant": {
            "name": restaurant["name"],
            "id": rid,
        },
        "week": {
            "start": this_start,
            "end": this_end,
            "label": _week_label(this_start, this_end),
        },
        "rota": rota_by_day,
        "rota_total": len(raw_rota),
        "stock": stock_data,
        "stock_low_count": len(low_items),
        "invoices": invoice_list,
        "invoice_total": round(invoice_total, 2),
        "financials": {
            "revenue": round(float(fin.get("total_revenue", 0) or 0), 2),
            "costs": round(float(fin.get("total_costs", 0) or 0), 2),
            "gross_profit": round(float(fin.get("gross_profit", 0) or 0), 2),
        },
        "recent_entries": recent_entries,
        "eightysix": eightysix_list,
        "allergens": allergen_list,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── HTML template ──────────────────────────────────────────────────────────────

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Restaurant-IQ</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{margin:0;font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh}
  .box{text-align:center;padding:2rem}
  h1{font-size:2rem;color:#f97316;margin-bottom:.5rem}
  p{color:#94a3b8;margin-bottom:1.5rem}
  a{color:#f97316;text-decoration:none}
</style>
</head>
<body>
<div class="box">
  <h1>Restaurant-IQ</h1>
  <p>Your AI-powered restaurant manager.</p>
  <p>To access your dashboard, use <strong>/dashboard</strong> in your Telegram group.</p>
</div>
</body>
</html>"""

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Restaurant-IQ — {name}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{
  --bg: #0f172a; --card: #1e293b; --border: #334155;
  --text: #e2e8f0; --muted: #94a3b8; --accent: #f97316;
  --green: #22c55e; --red: #ef4444; --yellow: #eab308;
  --blue: #3b82f6;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.5}}
.topbar{{background:var(--card);border-bottom:1px solid var(--border);padding:.75rem 1.5rem;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}}
.topbar h1{{font-size:1.1rem;font-weight:700;color:var(--accent)}}
.topbar .meta{{color:var(--muted);font-size:.8rem}}
.refresh-btn{{background:transparent;border:1px solid var(--border);color:var(--muted);padding:.3rem .8rem;border-radius:.4rem;cursor:pointer;font-size:.8rem}}
.refresh-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:1rem;padding:1rem 1.5rem;max-width:1400px;margin:0 auto}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:.75rem;padding:1.25rem}}
.card.wide{{grid-column:1/-1}}
.card h2{{font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:1rem}}
.badge{{display:inline-block;padding:.15rem .5rem;border-radius:9999px;font-size:.75rem;font-weight:600}}
.badge.green{{background:#14532d;color:var(--green)}}
.badge.red{{background:#450a0a;color:var(--red)}}
.badge.yellow{{background:#422006;color:var(--yellow)}}
.badge.blue{{background:#1e3a5f;color:var(--blue)}}
.badge.grey{{background:#1e293b;color:var(--muted)}}

/* KPI row */
.kpi-row{{display:flex;gap:1rem;flex-wrap:wrap}}
.kpi{{flex:1;min-width:120px;background:#0f172a;border-radius:.5rem;padding:.9rem;text-align:center}}
.kpi .val{{font-size:1.5rem;font-weight:700;color:var(--accent)}}
.kpi .lbl{{color:var(--muted);font-size:.75rem;margin-top:.2rem}}

/* Rota */
.rota-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:.5rem;overflow-x:auto}}
.rota-col .day-name{{font-size:.7rem;font-weight:600;color:var(--muted);text-transform:uppercase;margin-bottom:.4rem}}
.rota-col .day-date{{font-size:.8rem;color:var(--muted);margin-bottom:.6rem}}
.shift-chip{{background:#0f172a;border:1px solid var(--border);border-radius:.4rem;padding:.4rem .5rem;margin-bottom:.4rem;font-size:.75rem}}
.shift-chip .sname{{font-weight:600;color:var(--text)}}
.shift-chip .stime{{color:var(--muted)}}
.empty-day{{color:var(--border);font-size:.75rem;padding:.4rem 0}}

/* Tables */
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;color:var(--muted);font-size:.75rem;font-weight:600;padding:.4rem .6rem;border-bottom:1px solid var(--border)}}
td{{padding:.55rem .6rem;border-bottom:1px solid #1e293b;font-size:.82rem}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#1a2436}}

/* Stock */
.stock-bar-wrap{{background:#0f172a;border-radius:9999px;height:6px;width:100%;margin-top:.3rem}}
.stock-bar{{background:var(--green);height:6px;border-radius:9999px;transition:width .4s}}
.stock-bar.low{{background:var(--red)}}

/* Entries */
.entry-cat{{font-size:.7rem;padding:.1rem .4rem;border-radius:.3rem;background:#1e293b;color:var(--muted)}}
.allergen-row td:first-child{{color:var(--red)}}

/* Refresh pulse */
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
.pulsing{{animation:pulse 1s infinite}}

/* Mobile */
@media(max-width:600px){{
  .grid{{padding:.75rem}}
  .rota-grid{{grid-template-columns:repeat(4,minmax(80px,1fr))}}
  .kpi .val{{font-size:1.2rem}}
}}
</style>
</head>
<body>

<div class="topbar">
  <div>
    <h1 id="rest-name">{name}</h1>
    <div class="meta" id="week-label">{week_label}</div>
  </div>
  <div style="display:flex;align-items:center;gap:.75rem">
    <span class="meta" id="updated-at">Loading…</span>
    <button class="refresh-btn" onclick="loadData()">Refresh</button>
  </div>
</div>

<div class="grid" id="dashboard-grid">

  <!-- KPIs -->
  <div class="card wide" id="kpi-card">
    <h2>This month at a glance</h2>
    <div class="kpi-row">
      <div class="kpi"><div class="val" id="kpi-revenue">—</div><div class="lbl">Revenue</div></div>
      <div class="kpi"><div class="val" id="kpi-costs">—</div><div class="lbl">Costs</div></div>
      <div class="kpi"><div class="val" id="kpi-gp">—</div><div class="lbl">Gross Profit</div></div>
      <div class="kpi"><div class="val" id="kpi-invoices">—</div><div class="lbl">Outstanding invoices</div></div>
      <div class="kpi"><div class="val" id="kpi-low-stock">—</div><div class="lbl">Low stock items</div></div>
      <div class="kpi"><div class="val" id="kpi-shifts">—</div><div class="lbl">Shifts this week</div></div>
    </div>
  </div>

  <!-- Rota -->
  <div class="card wide" id="rota-card">
    <h2>Staff rota — <span id="rota-week-label">this week</span></h2>
    <div class="rota-grid" id="rota-grid"></div>
  </div>

  <!-- Stock -->
  <div class="card" id="stock-card">
    <h2>Stock levels</h2>
    <table id="stock-table">
      <thead><tr><th>Item</th><th>Current</th><th>Par</th><th></th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Invoices -->
  <div class="card" id="invoices-card">
    <h2>Outstanding invoices</h2>
    <table id="invoices-table">
      <thead><tr><th>Supplier</th><th>Amount</th><th>Due</th><th></th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Recent activity -->
  <div class="card" id="entries-card">
    <h2>Recent activity — this week</h2>
    <table id="entries-table">
      <thead><tr><th>Date</th><th>By</th><th>Type</th><th>Note</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- 86 list -->
  <div class="card" id="eightysix-card">
    <h2>86'd this month</h2>
    <table id="eightysix-table">
      <thead><tr><th>Item</th><th>Times</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Allergens -->
  <div class="card" id="allergen-card">
    <h2>Open allergen alerts</h2>
    <table id="allergen-table">
      <thead><tr><th>Date</th><th>Severity</th><th>Description</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

</div>

<script>
const TOKEN = "{token}";
const API_URL = "/api/" + TOKEN;
let refreshTimer;

function fmt(v) {{
  if (v === undefined || v === null) return "—";
  return v;
}}
function fmtCurrency(v) {{
  if (!v && v !== 0) return "—";
  return "£" + Number(v).toLocaleString("en-GB", {{minimumFractionDigits:2, maximumFractionDigits:2}});
}}
function fmtDate(d) {{
  if (!d) return "—";
  try {{
    const [y,m,dy] = d.split("-");
    const months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return dy + " " + months[parseInt(m)];
  }} catch(e) {{ return d; }}
}}

function renderRota(days) {{
  const grid = document.getElementById("rota-grid");
  grid.innerHTML = days.map(day => {{
    const shifts = day.shifts.length
      ? day.shifts.map(s => {{
          const time = (s.start && s.end) ? s.start + "–" + s.end : (s.start || "");
          return `<div class="shift-chip"><div class="sname">${{s.name}}</div><div class="stime">${{time}}</div></div>`;
        }}).join("")
      : `<div class="empty-day">—</div>`;
    return `<div class="rota-col">
      <div class="day-name">${{day.day.slice(0,3)}}</div>
      <div class="day-date">${{day.date}}</div>
      ${{shifts}}
    </div>`;
  }}).join("");
}}

function renderStock(items) {{
  const tbody = document.querySelector("#stock-table tbody");
  if (!items.length) {{
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted)">No stock items set up. Use /stock set in Telegram.</td></tr>`;
    return;
  }}
  tbody.innerHTML = items.map(s => {{
    const cur = s.current !== null ? s.current : null;
    const pct = (cur !== null && s.par) ? Math.min(100, Math.round(cur / s.par * 100)) : null;
    const barClass = s.low ? "stock-bar low" : "stock-bar";
    const bar = pct !== null ? `<div class="stock-bar-wrap"><div class="${{barClass}}" style="width:${{pct}}%"></div></div>` : "";
    const badge = s.low
      ? `<span class="badge red">Low</span>`
      : (cur !== null ? `<span class="badge green">OK</span>` : `<span class="badge grey">?</span>`);
    return `<tr>
      <td>${{s.name}}</td>
      <td>${{cur !== null ? cur + " " + s.unit : "—"}}</td>
      <td>${{s.par}} ${{s.unit}}</td>
      <td>${{badge}}${{bar}}</td>
    </tr>`;
  }}).join("");
}}

function renderInvoices(invoices, total) {{
  const tbody = document.querySelector("#invoices-table tbody");
  if (!invoices.length) {{
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted)">No outstanding invoices.</td></tr>`;
    return;
  }}
  tbody.innerHTML = invoices.map(inv => {{
    const badge = inv.overdue
      ? `<span class="badge red">Overdue</span>`
      : `<span class="badge yellow">Due ${{fmtDate(inv.due)}}</span>`;
    return `<tr>
      <td>${{inv.supplier}}</td>
      <td>${{fmtCurrency(inv.amount)}}</td>
      <td>${{inv.due ? fmtDate(inv.due) : "—"}}</td>
      <td>${{badge}}</td>
    </tr>`;
  }}).join("") + `<tr style="font-weight:600"><td colspan="2">Total</td><td colspan="2">${{fmtCurrency(total)}}</td></tr>`;
}}

function renderEntries(entries) {{
  const tbody = document.querySelector("#entries-table tbody");
  if (!entries.length) {{
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted)">No entries this week yet.</td></tr>`;
    return;
  }}
  tbody.innerHTML = entries.map(e => `<tr>
    <td>${{fmtDate(e.date)}}</td>
    <td>${{e.staff}}</td>
    <td><span class="entry-cat">${{e.category}}</span></td>
    <td style="max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${{e.summary}}</td>
  </tr>`).join("");
}}

function renderEightySix(items) {{
  const tbody = document.querySelector("#eightysix-table tbody");
  if (!items.length) {{
    tbody.innerHTML = `<tr><td colspan="2" style="color:var(--muted)">None recorded this month.</td></tr>`;
    return;
  }}
  tbody.innerHTML = items.map(i => `<tr>
    <td>${{i.item}}</td>
    <td><span class="badge red">${{i.count}}×</span></td>
  </tr>`).join("");
}}

function renderAllergens(items) {{
  const tbody = document.querySelector("#allergen-table tbody");
  if (!items.length) {{
    tbody.innerHTML = `<tr><td colspan="3" style="color:var(--muted)">No open allergen alerts.</td></tr>`;
    return;
  }}
  const sev = {{high:"red", medium:"yellow", low:"blue"}};
  tbody.innerHTML = items.map(a => `<tr class="allergen-row">
    <td>${{fmtDate(a.date)}}</td>
    <td><span class="badge ${{sev[a.severity]||"grey"}}">${{a.severity}}</span></td>
    <td>${{a.description}}</td>
  </tr>`).join("");
}}

async function loadData() {{
  const btn = document.querySelector(".refresh-btn");
  btn.classList.add("pulsing");
  btn.textContent = "Loading…";
  try {{
    const resp = await fetch(API_URL);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const d = await resp.json();

    // KPIs
    document.getElementById("kpi-revenue").textContent = fmtCurrency(d.financials.revenue);
    document.getElementById("kpi-costs").textContent = fmtCurrency(d.financials.costs);
    const gp = d.financials.gross_profit;
    const gpEl = document.getElementById("kpi-gp");
    gpEl.textContent = fmtCurrency(gp);
    gpEl.style.color = gp >= 0 ? "var(--green)" : "var(--red)";
    document.getElementById("kpi-invoices").textContent = d.invoices.length || "0";
    const lowEl = document.getElementById("kpi-low-stock");
    lowEl.textContent = d.stock_low_count;
    lowEl.style.color = d.stock_low_count > 0 ? "var(--red)" : "var(--green)";
    document.getElementById("kpi-shifts").textContent = d.rota_total;

    // Header
    document.getElementById("rest-name").textContent = d.restaurant.name;
    document.getElementById("week-label").textContent = d.week.label;
    document.getElementById("rota-week-label").textContent = d.week.label;

    renderRota(d.rota);
    renderStock(d.stock);
    renderInvoices(d.invoices, d.invoice_total);
    renderEntries(d.recent_entries);
    renderEightySix(d.eightysix);
    renderAllergens(d.allergens);

    const ts = new Date(d.generated_at);
    document.getElementById("updated-at").textContent = "Updated " + ts.toLocaleTimeString("en-GB");
  }} catch(err) {{
    document.getElementById("updated-at").textContent = "Error: " + err.message;
  }}
  btn.classList.remove("pulsing");
  btn.textContent = "Refresh";
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(loadData, 60000);
}}

window.addEventListener("DOMContentLoaded", loadData);
</script>
</body>
</html>"""


# ── HTTP handler ───────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silence default access log

    def _send(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self._send(200, "text/html; charset=utf-8", _LANDING_HTML.encode())
            return

        parts = [p for p in path.split("/") if p]

        # /api/<token>
        if len(parts) == 2 and parts[0] == "api":
            self._serve_api(parts[1])
            return

        # /dashboard/<token>
        if len(parts) == 2 and parts[0] == "dashboard":
            self._serve_dashboard(parts[1])
            return

        self._send(404, "text/plain", b"Not found")

    def _get_restaurant(self, token: str):
        from database import get_restaurant_by_dashboard_token
        try:
            return get_restaurant_by_dashboard_token(token)
        except Exception as e:
            logger.error("Dashboard DB error: %s", e)
            return None

    def _serve_dashboard(self, token: str):
        restaurant = self._get_restaurant(token)
        if not restaurant:
            self._send(404, "text/html; charset=utf-8",
                       b"<h1>Dashboard not found</h1><p>Use /dashboard in Telegram to get your link.</p>")
            return
        html = _DASHBOARD_HTML.format(
            name=restaurant["name"],
            week_label="Loading…",
            token=token,
        )
        self._send(200, "text/html; charset=utf-8", html.encode())

    def _serve_api(self, token: str):
        restaurant = self._get_restaurant(token)
        if not restaurant:
            body = json.dumps({"error": "not found"}).encode()
            self._send(404, "application/json", body)
            return
        try:
            data = build_dashboard_data(restaurant)
            body = json.dumps(data).encode()
            self._send(200, "application/json", body)
        except Exception as e:
            logger.error("Dashboard API error: %s", e)
            body = json.dumps({"error": str(e)}).encode()
            self._send(500, "application/json", body)


# ── Public interface ───────────────────────────────────────────────────────────

def start_dashboard_server(port: int = 8080):
    """Start the HTTP server in a background daemon thread."""
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Dashboard server running on port %d", port)
    return server
