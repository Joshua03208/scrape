"""Page fetchers.

Two backends share one interface so the crawler doesn't care which is used:

* ``RequestsFetcher`` -- fast, lightweight, for static HTML.
* ``PlaywrightFetcher`` -- a real browser, for JavaScript-rendered pages and
  login-gated sites. Created lazily so that ``playwright`` only needs to be
  installed when a site actually requires it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import SiteConfig


@dataclass
class FetchResult:
    url: str            # final URL after redirects
    status: int
    html: str
    ok: bool


class Fetcher:
    """Common fetcher interface."""

    def fetch(self, url: str) -> FetchResult:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - default no-op
        pass

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class RequestsFetcher(Fetcher):
    """Static HTML fetcher built on the ``requests`` library."""

    def __init__(self, config: SiteConfig) -> None:
        import requests

        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})

    def fetch(self, url: str) -> FetchResult:
        try:
            resp = self.session.get(
                url, timeout=self.config.timeout_seconds, allow_redirects=True
            )
        except Exception as exc:  # network error, timeout, etc.
            return FetchResult(url=url, status=0, html="", ok=False)
        ok = resp.status_code == 200 and "text/html" in resp.headers.get(
            "Content-Type", "text/html"
        )
        return FetchResult(
            url=str(resp.url), status=resp.status_code, html=resp.text, ok=ok
        )

    def close(self) -> None:
        self.session.close()


class PlaywrightFetcher(Fetcher):
    """Browser-based fetcher for JS-heavy and login-gated sites."""

    def __init__(self, config: SiteConfig, headless: bool = True) -> None:
        from playwright.sync_api import sync_playwright

        self.config = config
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._context = self._browser.new_context(user_agent=config.user_agent)
        self._page = self._context.new_page()
        if config.login.enabled:
            self._do_login()

    def _do_login(self) -> None:
        login = self.config.login
        if not login.url:
            raise ValueError(f"{self.config.name}: login.enabled but no login.url set.")
        self._page.goto(login.url, timeout=self.config.timeout_seconds * 1000)
        for step in login.steps:
            if step.action == "fill":
                self._page.fill(step.selector, step.resolved_value() or "")
            elif step.action == "click":
                self._page.click(step.selector)
            elif step.action == "wait":
                self._page.wait_for_selector(step.selector)
            else:
                raise ValueError(f"Unknown login step action: {step.action!r}")
        if login.success_selector:
            # Raises if login didn't land us where we expect.
            self._page.wait_for_selector(
                login.success_selector, timeout=self.config.timeout_seconds * 1000
            )

    def fetch(self, url: str) -> FetchResult:
        try:
            resp = self._page.goto(
                url, timeout=self.config.timeout_seconds * 1000, wait_until="domcontentloaded"
            )
            # Give late-loading prices a moment to appear.
            self._page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            return FetchResult(url=url, status=0, html="", ok=False)
        status = resp.status if resp else 0
        html = self._page.content()
        ok = bool(resp and resp.ok)
        return FetchResult(url=self._page.url, status=status, html=html, ok=ok)

    def close(self) -> None:
        try:
            self._context.close()
            self._browser.close()
        finally:
            self._pw.stop()


def build_fetcher(config: SiteConfig) -> Fetcher:
    """Instantiate the fetcher named in the site config."""
    if config.fetcher == "requests":
        return RequestsFetcher(config)
    if config.fetcher == "playwright":
        return PlaywrightFetcher(config)
    raise ValueError(
        f"Unknown fetcher {config.fetcher!r}. Use 'requests' or 'playwright'."
    )
