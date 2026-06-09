# Part Price Scraper

A configurable tool for crawling manufacturer/supplier websites, finding
**prices** and associating them with **part numbers**, then storing everything
in a single-file database with CSV/JSON export and a small web panel.

Built for collecting your own catalog/pricing data. **Scrape responsibly** —
see [Legal & etiquette](#legal--etiquette) below.

## How it works

```
config (YAML)  ->  fetcher  ->  crawler  ->  extractor  ->  storage
 per-site          requests/     follow      part # +       SQLite file
 settings          Playwright    in-domain   price          + CSV/JSON
                                  links
```

- **Fetchers** — `requests` for static HTML (fast); **Playwright** (a real
  browser) for JavaScript-heavy pages and **login-gated** dealer portals.
- **Crawler** — breadth-first over every in-domain link, honouring
  `robots.txt`, a politeness delay, link include/exclude patterns, and a page
  cap.
- **Extractor** — finds the part number and price via CSS selectors first,
  then regexes, then a generic fallback. Two strategies: `product_page`
  (one part per page) and `price_table` (many rows per page).
- **Storage** — one `output/prices.sqlite` file (no database server to run).
  Export to CSV/JSON for Excel/Sheets.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Only needed if any site uses fetcher: playwright
python -m playwright install chromium
```

## Adding a site

Drop a YAML file in `config/sites/`. Two worked examples are included:

- `config/sites/example.yaml` — a public, static site (`requests`).
- `config/sites/example_login.yaml` — a JS dealer portal behind a login
  (`playwright`), with credentials read from environment variables.

For login sites, copy `.env.example` to `.env` and fill in the credentials
referenced by `value_env:` in the config. The `.env` file is git-ignored.

The key fields to tune per site are the CSS **selectors** and **regexes** under
`extract:` — open a product page, inspect where the part number and price live,
and point the selectors at them.

## Running

```bash
# Crawl one site, or a whole folder of site configs:
python -m scraper.cli run config/sites/example.yaml
python -m scraper.cli run config/sites/

# Export collected data:
python -m scraper.cli export --format csv  --out output/prices.csv
python -m scraper.cli export --format json --out output/prices.json

# Verbose logging:
python -m scraper.cli -v run config/sites/example.yaml
```

## Web panel

A simple, no-login local panel to browse/search results and start scrapes:

```bash
python -m scraper.web
# open http://127.0.0.1:5000
```

It lists every collected price, lets you search by part number or site, run a
configured site with a button, and download a CSV.

## Tests

```bash
pip install pytest
pytest
```

The extractor is covered by offline tests (no network needed).

## Legal & etiquette

Scraping other companies' sites carries legal and ethical responsibilities.
Before pointing this at a real site:

- Read the site's **Terms of Service** — some prohibit automated access.
- The crawler respects **`robots.txt`** by default (`respect_robots: true`).
  Don't disable it without good reason.
- Keep `delay_seconds` reasonable so you don't hammer their servers.
- Identify yourself honestly in `user_agent` with real contact info.
- For dealer portals you have a legitimate account on, make sure automated
  access doesn't violate your dealer agreement.

This tool is provided for collecting data you're permitted to access.
