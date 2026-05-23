"""One-time scraper for accessbank.az public pages.

Pulls a curated list of EN/AZ pages, strips boilerplate (nav, footer, scripts),
converts the main content to markdown, and writes one .md file per page to
the /knowledge directory.

Usage:
    python -m scripts.scrape_accessbank
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

from src import config

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en;q=0.9,az;q=0.8",
}

# Comprehensive list of AccessBank public pages discovered by
# (a) crawling the EN + AZ homepages and section index pages and
# (b) a `site:accessbank.az` Google query. URL patterns are:
#   /en/our-bank/<page>/         — corporate info
#   /en/private/<category>/...   — retail products
#   /en/biznes/                  — business banking
#   /en/requests/<form>          — online application forms
#   /az/...                      — Azerbaijani mirror of every above
BASE = "https://www.accessbank.az"

_EN_PATHS: list[str] = [
    # Top-level
    "/en/",

    # Our Bank / corporate
    "/en/our-bank/mission/",
    "/en/our-bank/in-figures/",
    "/en/our-bank/history/",
    "/en/our-bank/awards/",
    "/en/our-bank/requisites/",
    "/en/our-bank/tariffs/",
    "/en/our-bank/mgmt/",
    "/en/our-bank/shareholders/",
    "/en/our-bank/corpgov/audit-committee/",
    "/en/our-bank/corpgov/riskmgmt/",
    "/en/our-bank/corpgov/remuneration-policy/",
    "/en/our-bank/corpgov/policies/",
    "/en/our-bank/cpp/",
    "/en/our-bank/contact/",
    "/en/our-bank/service-networks/",
    "/en/our-bank/vacancies/",

    # Loans / credit
    "/en/private/kredit/",
    "/en/private/creditcard/ok-kart/",
    "/en/private/loans/lombard/",
    "/en/kredit-kalkulyatoru",

    # Deposits
    "/en/private/deposits/timed/",
    "/en/private/deposits/mygoal/",
    "/en/private/deposits/elverisli/",
    "/en/private/deposits/serbest/",
    "/en/private/deposits/instaccess/",
    "/en/private/deposits/myaccess-muddetli/",

    # Cards
    "/en/private/cards/mycard/",
    "/en/private/cards/mycard/mycard_junior/",
    "/en/private/cards/mycard/white/",
    "/en/private/cards/mycard/black/",

    # Other retail services
    "/en/private/money-transfer/",
    "/en/private/utility-payments/",
    "/en/private/deposit-boxes/",
    "/en/private/online-queue/",
    "/en/private/emlak-satishi/",

    # Online forms
    "/en/requests/onlayn-kredit",
    "/en/requests/debetcard",
    "/en/requests/loanpayment",

    # Other
    "/en/biznes/",
    "/en/private_banking/",
    "/en/g/faq/",
    "/en/private/news/",
    "/en/private/announcements/",
    "/en/investors/ataglance/",
]

# Azerbaijani mirror — same paths, just /az/ prefix.
_AZ_PATHS: list[str] = [p.replace("/en/", "/az/", 1) if p.startswith("/en/") else p for p in _EN_PATHS]
_AZ_PATHS = [p for p in _AZ_PATHS if p.startswith("/az/")] + ["/az/"]

SEED_URLS: list[str] = [f"{BASE}{p}" for p in _EN_PATHS + _AZ_PATHS]


def _slugify(url: str) -> str:
    p = urlparse(url)
    path = p.path.strip("/").replace("/", "_") or "home"
    # Replace anything non-ascii-safe.
    path = re.sub(r"[^a-zA-Z0-9_\-]", "_", path)
    return f"{path}.md"


def _extract_main(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # Drop noisy elements outright.
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "form", "nav", "footer", "header"]):
        tag.decompose()

    # Heuristic: prefer <main>, then <article>, then largest <div> by text length.
    candidates = []
    for selector in ["main", "article", "[role=main]", "section"]:
        for el in soup.select(selector):
            candidates.append(el)
    if not candidates:
        candidates = [soup.body or soup]

    best = max(candidates, key=lambda el: len(el.get_text(" ", strip=True)))
    md = html_to_md(str(best), heading_style="ATX", strip=["a", "img"])
    # Collapse excessive blank lines.
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as exc:
        print(f"  ! fetch failed: {exc}")
        return None
    if resp.status_code != 200:
        print(f"  ! HTTP {resp.status_code}")
        return None
    return resp.text


def main() -> int:
    knowledge_dir: Path = config.KNOWLEDGE_DIR
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    failed = 0
    for url in SEED_URLS:
        print(f"→ {url}")
        html = _fetch(url)
        if html is None:
            failed += 1
            continue
        try:
            md = _extract_main(html)
        except Exception as exc:
            print(f"  ! parse failed: {exc}")
            failed += 1
            continue
        if len(md) < 80:  # Skip near-empty pages (likely SPA shells).
            print(f"  ! content too short ({len(md)} chars), skipping")
            failed += 1
            continue
        out_path = knowledge_dir / _slugify(url)
        header = f"# Source: {url}\n\n"
        out_path.write_text(header + md, encoding="utf-8")
        print(f"  ✓ saved {out_path.name} ({len(md)} chars)")
        saved += 1
        time.sleep(0.6)  # Be polite.

    print()
    print(f"Done: {saved} saved, {failed} skipped.")
    if saved == 0:
        print("WARNING: nothing was saved. The site structure may have changed.")
        print("You can add your own .md files directly to /knowledge and re-run ingest.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
