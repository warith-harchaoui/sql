"""Capture the GUI screenshots used in the docs, bilingual + both themes.

Module summary
--------------
Drives the running FastAPI app with a headless Chromium to produce the doc
figures under ``docs/screenshots/``. Language (fr/en) and theme (light/dark)
are seeded via ``localStorage`` before the page boots.

Shots (static — no Ollama needed)
----------------------------------
* ``01-accueil`` — landing page, light mode, FR + EN.
* ``02-accueil-sombre`` — landing page, dark mode, FR + EN.
* ``03-schema`` — schema panel expanded, FR + EN.

Shots (dynamic — needs Ollama + qwen2.5-coder)
-----------------------------------------------
* ``04-resultat-sql`` — a query run through the default approach, FR + EN.
* ``05-figure-vega`` — the Vega chart for that same result, FR + EN.
* ``06-comparaison`` — all approaches compared on the same question, FR + EN.

Usage
-----
    python scripts/screenshots.py --base-url http://localhost:8001
    python scripts/screenshots.py --dynamic          # static + 1 query result
    python scripts/screenshots.py --comparaison      # static + full comparison
    python scripts/screenshots.py --all              # everything

Author
------
Project maintainers.
"""

from __future__ import annotations

import argparse
from pathlib import Path

_SHOTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
_LANG_KEY = "text2sql.lang"
_THEME_KEY = "theme"

_QUERY_FR = "Combien de patients sont suivis au total ?"
_QUERY_EN = "How many patients are being followed in total?"


def _new_page(pw, lang: str, dark: bool, width: int = 1360, height: int = 900):
    """Open a browser page pre-seeded with the requested language and theme."""
    browser = pw.chromium.launch()
    page = browser.new_page(
        viewport={"width": width, "height": height}, device_scale_factor=2.0
    )
    theme = "dark" if dark else "light"
    page.add_init_script(
        f"localStorage.setItem('{_LANG_KEY}', '{lang}');"
        f"localStorage.setItem('{_THEME_KEY}', '{theme}');"
    )
    return browser, page


def _settle(page, base_url: str, lang: str) -> None:
    """Navigate and wait until the app has rendered its initial state."""
    page.goto(base_url, wait_until="networkidle")
    # Wait for i18n to apply (the <html lang> attribute is set by initI18n).
    page.wait_for_function(
        f"document.documentElement.getAttribute('lang') === '{lang}'",
        timeout=10_000,
    )
    page.wait_for_timeout(400)


def shoot_static(base_url: str) -> list[Path]:
    """Capture landing and schema shots (no Ollama call needed)."""
    from playwright.sync_api import sync_playwright

    _SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (_SHOTS_DIR / "fr").mkdir(exist_ok=True)
    (_SHOTS_DIR / "en").mkdir(exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as pw:
        # Landing — light, FR.
        browser, page = _new_page(pw, "fr", dark=False)
        _settle(page, base_url, "fr")
        out = _SHOTS_DIR / "01-accueil-clair.png"
        page.screenshot(path=str(out))
        written.append(out)
        (_SHOTS_DIR / "fr" / "01-accueil-clair.png").write_bytes(out.read_bytes())
        browser.close()

        # Landing — light, EN.
        browser, page = _new_page(pw, "en", dark=False)
        _settle(page, base_url, "en")
        out = _SHOTS_DIR / "en" / "01-accueil-light.png"
        page.screenshot(path=str(out))
        written.append(out)
        browser.close()

        # Landing — dark, FR.
        browser, page = _new_page(pw, "fr", dark=True)
        _settle(page, base_url, "fr")
        out = _SHOTS_DIR / "02-accueil-sombre.png"
        page.screenshot(path=str(out))
        written.append(out)
        (_SHOTS_DIR / "fr" / "02-accueil-sombre.png").write_bytes(out.read_bytes())
        browser.close()

        # Landing — dark, EN.
        browser, page = _new_page(pw, "en", dark=True)
        _settle(page, base_url, "en")
        out = _SHOTS_DIR / "en" / "02-accueil-dark.png"
        page.screenshot(path=str(out))
        written.append(out)
        browser.close()

        # Schema panel — FR.
        browser, page = _new_page(pw, "fr", dark=False, height=1100)
        _settle(page, base_url, "fr")
        schema = page.query_selector("details")
        if schema:
            page.evaluate("document.querySelector('details').open = true")
            page.wait_for_timeout(300)
            schema.scroll_into_view_if_needed()
            out = _SHOTS_DIR / "03-schema.png"
            schema.screenshot(path=str(out))
            written.append(out)
            (_SHOTS_DIR / "fr" / "03-schema.png").write_bytes(out.read_bytes())
        browser.close()

        # Schema panel — EN.
        browser, page = _new_page(pw, "en", dark=False, height=1100)
        _settle(page, base_url, "en")
        schema = page.query_selector("details")
        if schema:
            page.evaluate("document.querySelector('details').open = true")
            page.wait_for_timeout(300)
            schema.scroll_into_view_if_needed()
            out = _SHOTS_DIR / "en" / "03-schema.png"
            schema.screenshot(path=str(out))
            written.append(out)
        browser.close()

    return written


def shoot_result(base_url: str) -> list[Path]:
    """Submit a simple query and capture the SQL result (needs Ollama)."""
    from playwright.sync_api import sync_playwright

    _SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (_SHOTS_DIR / "fr").mkdir(exist_ok=True)
    (_SHOTS_DIR / "en").mkdir(exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as pw:
        for lang, query, stem in (
            ("fr", _QUERY_FR, "04-resultat-sql"),
            ("en", _QUERY_EN, "en/04-result-sql"),
        ):
            browser, page = _new_page(pw, lang, dark=False, height=1000)
            _settle(page, base_url, lang)
            page.fill("#question", query)
            page.click("#run-btn")
            # Wait for at least one result card (not the loading spinner).
            _sel = (
                "#results .result-card,"
                " #results article:not(.animate-pulse)"
            )
            page.wait_for_function(
                f"document.querySelectorAll('{_sel}').length >= 1",
                timeout=90_000,
            )
            page.wait_for_timeout(600)
            out = _SHOTS_DIR / f"{stem}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out))
            written.append(out)
            browser.close()

    return written


def shoot_comparaison(base_url: str) -> list[Path]:
    """Run the same query on all three approaches and capture the comparison."""
    from playwright.sync_api import sync_playwright

    _SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (_SHOTS_DIR / "fr").mkdir(exist_ok=True)
    (_SHOTS_DIR / "en").mkdir(exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as pw:
        for lang, query, stem in (
            ("fr", _QUERY_FR, "06-comparaison"),
            ("en", _QUERY_EN, "en/06-comparison"),
        ):
            browser, page = _new_page(pw, lang, dark=False, height=1100)
            _settle(page, base_url, lang)
            page.fill("#question", query)
            page.click("#run-btn")
            # Wait for all approach cards.
            _sel3 = (
                "#results .result-card,"
                " #results article:not(.animate-pulse)"
            )
            page.wait_for_function(
                f"document.querySelectorAll('{_sel3}').length >= 3",
                timeout=120_000,
            )
            page.wait_for_timeout(700)
            page.evaluate("window.scrollTo(0, document.querySelector('#results').offsetTop - 60)")
            out = _SHOTS_DIR / f"{stem}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out))
            written.append(out)
            browser.close()

    return written


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the screenshot pipeline.

    Parameters
    ----------
    argv : list[str] | None, optional
        Argument vector; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        0 on success, 1 if no files were written.
    """
    parser = argparse.ArgumentParser(prog="screenshots")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--dynamic", action="store_true", help="Static + 1 query result.")
    parser.add_argument("--comparaison", action="store_true", help="Static + full comparison.")
    parser.add_argument("--all", action="store_true", help="Everything.")
    args = parser.parse_args(argv)

    written: list[Path] = shoot_static(args.base_url)
    if args.dynamic or args.all:
        written += shoot_result(args.base_url)
    if args.comparaison or args.all:
        written += shoot_comparaison(args.base_url)

    for path in written:
        print(f"Capture : {path}")
    return 0 if written else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
