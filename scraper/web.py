"""A small, no-login web panel for browsing scraped prices.

Run it with:
    python -m scraper.web

Then open http://127.0.0.1:5000 in your browser. The panel lets you:
  * search collected part numbers / prices,
  * pick a site config and kick off a scrape with a button,
  * download everything as CSV.

It's deliberately simple -- single file, templates inline, no auth. Intended
for running locally on your own machine.
"""

from __future__ import annotations

import threading
from pathlib import Path

from flask import Flask, Response, redirect, render_template_string, request, url_for

from .config import load_site_config
from .pipeline import run_site
from .storage import Storage

DB_PATH = "output/prices.sqlite"
SITES_DIR = Path("config/sites")

app = Flask(__name__)

# Track a single background scrape so the UI can show "running".
_run_lock = threading.Lock()
_run_state = {"running": False, "site": None, "message": ""}


PAGE = """
<!doctype html>
<title>Part Price Panel</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; color: #222; }
  h1 { margin-bottom: .25rem; }
  .bar { display: flex; gap: 1rem; flex-wrap: wrap; align-items: center;
         margin: 1rem 0; }
  input, select, button { font-size: 1rem; padding: .4rem .6rem; }
  table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
  th, td { border-bottom: 1px solid #ddd; padding: .45rem .6rem; text-align: left; }
  th { background: #f5f5f5; }
  .price { text-align: right; font-variant-numeric: tabular-nums; }
  .muted { color: #777; font-size: .9rem; }
  .status { padding: .5rem .8rem; border-radius: 6px; background: #eef; }
  a.btn { text-decoration: none; }
</style>

<h1>Part Price Panel</h1>
<p class="muted">{{ total }} price record(s) in the database.</p>

{% if state.message %}
  <p class="status">{{ state.message }}</p>
{% endif %}

<form class="bar" method="post" action="{{ url_for('start') }}">
  <select name="site">
    {% for s in sites %}<option value="{{ s }}">{{ s }}</option>{% endfor %}
  </select>
  <button {% if state.running %}disabled{% endif %}>
    {% if state.running %}Running {{ state.site }}…{% else %}Run scrape{% endif %}
  </button>
  {% if not sites %}<span class="muted">No site configs in config/sites/</span>{% endif %}
</form>

<form class="bar" method="get" action="{{ url_for('index') }}">
  <input type="search" name="q" value="{{ q }}" placeholder="Search part number or site…">
  <button>Search</button>
  <a class="btn" href="{{ url_for('download') }}"><button type="button">Download CSV</button></a>
</form>

<table>
  <thead>
    <tr><th>Site</th><th>Part #</th><th class="price">Price</th>
        <th>Source</th><th>Scraped</th></tr>
  </thead>
  <tbody>
    {% for r in rows %}
    <tr>
      <td>{{ r.site }}</td>
      <td>{{ r.part_number }}</td>
      <td class="price">{{ "%.2f"|format(r.price) }} {{ r.currency }}</td>
      <td><a href="{{ r.url }}" target="_blank" rel="noopener">link</a></td>
      <td class="muted">{{ r.scraped_at }}</td>
    </tr>
    {% else %}
    <tr><td colspan="5" class="muted">No results yet. Run a scrape to populate.</td></tr>
    {% endfor %}
  </tbody>
</table>
"""


def _filtered_rows(storage: Storage, q: str) -> list[dict]:
    rows = [dict(r) for r in storage.all_rows()]
    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if ql in r["part_number"].lower() or ql in r["site"].lower()
        ]
    return rows


@app.route("/")
def index() -> str:
    q = request.args.get("q", "").strip()
    with Storage(DB_PATH) as storage:
        rows = _filtered_rows(storage, q)
        total = len(storage.all_rows())
    sites = sorted(p.name for p in SITES_DIR.glob("*.y*ml")) if SITES_DIR.exists() else []
    return render_template_string(
        PAGE, rows=rows, total=total, q=q, sites=sites, state=_run_state
    )


def _background_scrape(site_file: Path) -> None:
    try:
        config = load_site_config(site_file)
        with Storage(DB_PATH) as storage:
            saved = run_site(config, storage)
        _run_state["message"] = f"Finished {config.name}: {saved} record(s) saved."
    except Exception as exc:  # surface errors to the panel instead of crashing
        _run_state["message"] = f"Scrape failed: {exc}"
    finally:
        _run_state["running"] = False
        _run_state["site"] = None
        _run_lock.release()


@app.route("/run", methods=["POST"])
def start() -> Response:
    site = request.form.get("site", "")
    site_file = SITES_DIR / site
    if not site_file.exists():
        _run_state["message"] = f"Unknown site config: {site}"
        return redirect(url_for("index"))
    if not _run_lock.acquire(blocking=False):
        _run_state["message"] = "A scrape is already running; please wait."
        return redirect(url_for("index"))
    _run_state.update(running=True, site=site, message=f"Started {site}…")
    threading.Thread(target=_background_scrape, args=(site_file,), daemon=True).start()
    return redirect(url_for("index"))


@app.route("/download")
def download() -> Response:
    with Storage(DB_PATH) as storage:
        out = Path("output/prices.csv")
        storage.export_csv(out)
    return Response(
        out.read_text(encoding="utf-8"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=prices.csv"},
    )


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
