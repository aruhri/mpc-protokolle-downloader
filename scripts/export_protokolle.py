#!/usr/bin/env python3
"""Export medi-learn Facharztprotokolle as one structured Markdown file.

Workflow:
1. Use a stored Playwright session (or perform one interactive login).
2. Crawl all list pages and collect detail URLs.
3. Extract only the protocol text from each detail page.
4. Write one Markdown file with sections "## Protokoll N".
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from playwright.sync_api import BrowserContext, Page, TimeoutError, sync_playwright


DETAIL_ID_RE = re.compile(r"/details/(\d+)")
ROW_SELECTOR = "table.clubtabelle tbody tr"
LIST_LINK_SELECTOR = "td[data-dyn='Details'] a.aktions-btn--details"
CONTENT_SELECTOR = ".proto-content .ql-editor, #editor .ql-editor, .proto-content"


@dataclass(frozen=True)
class ProtocolLink:
    id: str
    url: str
    date: str
    examiners: str


@dataclass(frozen=True)
class ExtractedProtocol:
    id: str
    date: str
    examiners: str
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export all protocol texts from medi-learn list pages into one Markdown file."
    )
    parser.add_argument(
        "--list-url",
        default=None,
        help=(
            "Basis-URL der Protokollliste. Nur fuer den ersten Lauf (oder mit --force-login) noetig; "
            "danach wird die tatsaechlich genutzte, gefilterte URL automatisch in --list-url-file "
            "gespeichert und wiederverwendet."
        ),
    )
    parser.add_argument(
        "--output",
        default="protokolle_gesamt.md",
        help="Output Markdown file.",
    )
    parser.add_argument(
        "--session-file",
        default="session/storage_state.json",
        help="Playwright storage state path.",
    )
    parser.add_argument(
        "--ids-file",
        default="protokolle_ids.txt",
        help="Datei mit IDs bereits geladener Protokolle (wird gelesen und aktualisiert).",
    )
    parser.add_argument(
        "--list-url-file",
        default="session/list_url.txt",
        help="Datei mit der zuletzt genutzten, gefilterten Listen-URL (wird gelesen und aktualisiert).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=12,
        help="Maximum number of list pages to crawl.",
    )
    parser.add_argument(
        "--min-date",
        default=None,
        help=(
            "Nur Protokolle ab diesem Datum laden (Format TT.MM.JJJJ). "
            "Hat Vorrang vor --max-pages: der Crawl stoppt, sobald aeltere Protokolle gefunden werden."
        ),
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in visible mode (useful for debugging).",
    )
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="Ignore stored session and perform interactive login.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.35,
        help="Delay between detail page requests.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Playwright timeout in milliseconds.",
    )
    parser.add_argument(
        "--max-protocols",
        type=int,
        default=0,
        help="Optional limit for detail pages (0 = no limit).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-page and per-protocol progress.",
    )
    return parser.parse_args()


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def maybe_login_required(page: Page) -> bool:
    url = page.url.lower()
    if "login" in url or "anmeldung" in url:
        return True
    return page.locator("input[type='password']").count() > 0


BASE_LIST_URL = "https://medi-pro-club.de/club/wegweiser/facharztprotokolle"


def load_stored_list_url(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def save_list_url(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url.strip() + "\n", encoding="utf-8")


def apply_filters_from_url(page: Page, list_url: str, timeout_ms: int) -> str:
    """Fill and submit the real filter form with the values from list_url.

    GET query params alone are not reliably honoured by the server (pagination
    links only ever carry seitenNr/fachrichtung/ort), so passing --list-url with
    query params and just navigating to it can silently show an empty list."""
    query = parse_qs(urlparse(list_url).query, keep_blank_values=True)

    page.goto(list_url, wait_until="domcontentloaded")
    if maybe_login_required(page):
        raise RuntimeError("Session abgelaufen vor Anwenden der Filter. Bitte mit --force-login neu starten.")

    if page.locator("#formular").count() == 0:
        log("[filter] Filterformular nicht gefunden, verwende die URL direkt.")
        return page.url

    fachrichtung = (query.get("fachrichtung") or [""])[0]
    if fachrichtung:
        page.locator("#fachrichtung").select_option(value=fachrichtung)

    ort = (query.get("ort") or [""])[0]
    page.locator("#ort").fill(ort)

    pruefer = (query.get("pruefer") or [""])[0]
    page.locator("#pruefer").fill(pruefer)

    search_term = (query.get("search_term") or [""])[0]
    page.locator("#search_term").fill(search_term)

    page.locator("#formular button[name='aktion'][value='search']").first.click()
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    if maybe_login_required(page):
        raise RuntimeError("Session abgelaufen nach Anwenden der Filter. Bitte mit --force-login neu starten.")

    log(
        f"[filter] Filter angewendet: fachrichtung={fachrichtung!r} ort={ort!r} "
        f"pruefer={pruefer!r} search_term={search_term!r}"
    )
    return page.url


def ensure_session(context: BrowserContext, args: argparse.Namespace, list_url_path: Path) -> str:
    """Login (if needed) and determine the real, filtered list URL.

    If --list-url is given, its filter values are applied through the real
    filter form (see apply_filters_from_url). Otherwise, on the first run (or
    with --force-login) the user sets the desired filter directly in the
    browser; the resulting URL is captured and stored in list_url_path so
    later runs can reuse it without --list-url."""
    stored_url = load_stored_list_url(list_url_path)
    start_url = args.list_url or stored_url or BASE_LIST_URL

    page = context.new_page()
    page.set_default_timeout(args.timeout_ms)
    page.goto(start_url, wait_until="domcontentloaded")

    if args.force_login or maybe_login_required(page):
        log("[auth] Interaktive Anmeldung erforderlich.")
        log("[auth] Bitte im Browser einloggen, dann im Terminal Enter druecken.")
        input("Weiter mit Enter, sobald du eingeloggt bist... ")

        page.goto(start_url, wait_until="domcontentloaded")
        if maybe_login_required(page):
            raise RuntimeError("Login nicht erfolgreich. Bitte erneut ausfuehren.")

    if args.list_url:
        resolved_list_url = apply_filters_from_url(page, args.list_url, args.timeout_ms)
    elif stored_url is None:
        log("[filter] Keine gespeicherte Filter-URL gefunden.")
        log("[filter] Bitte jetzt im Browser die gewuenschte Protokoll-Liste filtern.")
        input("Weiter mit Enter, sobald die gefilterte Liste sichtbar ist... ")
        resolved_list_url = page.url
    else:
        resolved_list_url = stored_url

    session_path = Path(args.session_file)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(session_path))
    save_list_url(list_url_path, resolved_list_url)
    log(f"[list] Listen-URL gespeichert: {resolved_list_url}")
    page.close()
    return resolved_list_url


def extract_detail_id(url: str) -> str | None:
    match = DETAIL_ID_RE.search(url)
    return match.group(1) if match else None


def increment_page_url(url: str, next_page_nr: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["seitenNr"] = [str(next_page_nr)]
    rebuilt_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=rebuilt_query))


def parse_list_date(date_str: str) -> date | None:
    try:
        return datetime.strptime(date_str, "%d.%m.%Y").date()
    except (ValueError, TypeError):
        return None


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(", ").strip()
    return text


def collect_links_from_page(page: Page, verbose: bool = False) -> list[ProtocolLink]:
    rows = page.locator(ROW_SELECTOR)
    count = rows.count()
    items: list[ProtocolLink] = []

    for idx in range(count):
        row = rows.nth(idx)
        link = row.locator(LIST_LINK_SELECTOR).first
        if link.count() == 0:
            continue
        href = link.get_attribute("href")
        if not href:
            continue
        abs_url = urljoin(page.url, href)
        protocol_id = extract_detail_id(abs_url)
        if not protocol_id:
            continue

        date_cell = row.locator("td[data-dyn='Geschrieben am']").first
        date = clean_text(date_cell.inner_text()) if date_cell.count() > 0 else ""

        examiners_cell = row.locator("td[data-dyn='Prüfer']").first
        examiners = clean_text(examiners_cell.inner_text()) if examiners_cell.count() > 0 else ""

        items.append(ProtocolLink(id=protocol_id, url=abs_url, date=date, examiners=examiners))

    if verbose:
        log(f"[crawl] {page.url} -> {len(items)} Detail-Links")
    return items


def collect_all_protocol_links(
    page: Page,
    args: argparse.Namespace,
    downloaded_ids: set[str],
    list_url: str,
    min_date: date | None = None,
) -> list[ProtocolLink]:
    seen_ids: set[str] = set()
    collected: list[ProtocolLink] = []

    for page_nr in range(1, args.max_pages + 1):
        current_url = increment_page_url(list_url, page_nr)
        page.goto(current_url, wait_until="domcontentloaded")
        if maybe_login_required(page):
            raise RuntimeError("Session abgelaufen waehrend Listen-Crawl. Bitte mit --force-login neu starten.")

        page_links = collect_links_from_page(page, verbose=args.verbose)

        older_than_min_date = False
        if min_date is not None:
            in_range_links = []
            for item in page_links:
                item_date = parse_list_date(item.date)
                if item_date is not None and item_date < min_date:
                    older_than_min_date = True
                    continue
                in_range_links.append(item)
            page_links = in_range_links

        new_count = 0
        for item in page_links:
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            collected.append(item)
            new_count += 1

        if args.verbose:
            log(
                f"[crawl] Seite {page_nr}: {len(page_links)} gefunden, {new_count} neu, {len(collected)} gesamt"
            )

        if older_than_min_date:
            log(f"[crawl] Protokolle vor {min_date.strftime('%d.%m.%Y')} gefunden, stoppe (Vorrang vor --max-pages).")
            break

        if not page_links:
            log(f"[crawl] Keine Eintraege auf Seite {page_nr}, stoppe.")
            break

        if new_count == 0 and page_nr > 1:
            log(f"[crawl] Keine neuen IDs auf Seite {page_nr}, stoppe.")
            break

        if page_links and all(item.id in downloaded_ids for item in page_links):
            log(f"[crawl] Seite {page_nr} enthaelt nur bereits geladene Protokolle, stoppe.")
            break

    return collected


def normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def quill_html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for span in soup.select("span.ql-ui"):
        span.decompose()

    for para in soup.find_all("p"):
        children = [c for c in para.contents if str(c).strip()]
        if len(children) == 1 and getattr(children[0], "name", None) == "strong":
            heading = soup.new_tag("h3")
            heading.string = children[0].get_text(" ", strip=True)
            para.replace_with(heading)

    markdown = md(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["span"],
    )
    return normalize_markdown(markdown)


def proto_content_html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for node in soup.select(
        "script, style, form, iframe, svg, .proto-meta-entity, .proto-legende, "
        "#CookiebotWidget, #CookiebotWidgetUnderlay, .CybotCookiebotHiddenIframe, .CybotCookiebotOffscreenIframe"
    ):
        node.decompose()

    for node in soup.select(".ql-ui"):
        node.decompose()

    for span in soup.select("span[contenteditable='false']"):
        span.decompose()

    markdown = md(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["span"],
    )
    return normalize_markdown(markdown)


def extract_protocol_markdown(page: Page, detail_url: str, timeout_ms: int) -> str:
    page.goto(detail_url, wait_until="domcontentloaded")
    if maybe_login_required(page):
        raise RuntimeError("Session abgelaufen waehrend Detail-Extraktion.")

    locator = page.locator(CONTENT_SELECTOR).first
    locator.wait_for(state="visible", timeout=timeout_ms)

    matched_class = locator.get_attribute("class") or ""
    html = locator.inner_html()

    if "ql-editor" in matched_class:
        markdown = quill_html_to_markdown(html)
    else:
        markdown = proto_content_html_to_markdown(html)

    if not markdown:
        raise RuntimeError("Leerer Protokollinhalt nach Extraktion.")
    return markdown


PROTOCOL_HEADING_RE = re.compile(r"^## Protokoll (\d+)\s*$", re.MULTILINE)


def load_downloaded_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.add(line)
    return ids


def save_downloaded_ids(path: Path, ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(ids, key=int)) + "\n", encoding="utf-8")


def next_protocol_index(path: Path) -> int:
    if not path.exists():
        return 1
    numbers = [int(m.group(1)) for m in PROTOCOL_HEADING_RE.finditer(path.read_text(encoding="utf-8"))]
    return max(numbers, default=0) + 1


def write_output(path: Path, protocols: Iterable[ExtractedProtocol]) -> None:
    start_index = next_protocol_index(path)
    blocks = []
    for offset, proto in enumerate(protocols):
        blocks.append(
            f"## Protokoll {start_index + offset}\n\n"
            f"**Datum:** {proto.date or 'unbekannt'}\n"
            f"**Prüfer:** {proto.examiners or 'unbekannt'}\n\n"
            f"{proto.text}\n"
        )

    if not blocks:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    new_content = "\n".join(blocks).strip() + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip("\n")
        path.write_text(existing + "\n\n" + new_content, encoding="utf-8")
    else:
        path.write_text(new_content, encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    session_path = Path(args.session_file)
    ids_path = Path(args.ids_file)
    list_url_path = Path(args.list_url_file)

    min_date = None
    if args.min_date:
        min_date = parse_list_date(args.min_date)
        if min_date is None:
            raise SystemExit(f"Ungueltiges --min-date '{args.min_date}', erwartet Format TT.MM.JJJJ.")

    downloaded_ids = load_downloaded_ids(ids_path)
    log(f"[ids] {len(downloaded_ids)} bereits geladene Protokoll-IDs aus {ids_path} eingelesen.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        state = str(session_path) if session_path.exists() and not args.force_login else None
        context = browser.new_context(storage_state=state, locale="de-DE")

        try:
            list_url = ensure_session(context, args, list_url_path)

            page = context.new_page()
            page.set_default_timeout(args.timeout_ms)

            protocol_links = collect_all_protocol_links(page, args, downloaded_ids, list_url, min_date)

            skipped_ids = [item.id for item in protocol_links if item.id in downloaded_ids]
            protocol_links = [item for item in protocol_links if item.id not in downloaded_ids]
            if skipped_ids:
                log(f"[crawl] {len(skipped_ids)} bereits geladene Protokolle uebersprungen.")

            if args.max_protocols > 0:
                protocol_links = protocol_links[: args.max_protocols]

            if not protocol_links:
                log("[done] Keine neuen Protokolle gefunden, nichts zu tun.")
                return 0

            log(f"[crawl] Insgesamt {len(protocol_links)} neue Protokolle gefunden.")

            extracted: list[ExtractedProtocol] = []
            failed: list[tuple[str, str]] = []

            for idx, item in enumerate(protocol_links, start=1):
                try:
                    md_text = extract_protocol_markdown(page, item.url, args.timeout_ms)
                    extracted.append(
                        ExtractedProtocol(id=item.id, date=item.date, examiners=item.examiners, text=md_text)
                    )
                    if args.verbose:
                        log(f"[extract] {idx}/{len(protocol_links)} OK (ID {item.id})")
                except Exception as exc:  # noqa: BLE001
                    failed.append((item.id, str(exc)))
                    log(f"[extract] FEHLER bei ID {item.id}: {exc}")
                time.sleep(max(0.0, args.delay_seconds))

            if not extracted:
                raise RuntimeError("Keine Protokolle erfolgreich extrahiert.")

            write_output(output_path, extracted)

            downloaded_ids.update(proto.id for proto in extracted)
            save_downloaded_ids(ids_path, downloaded_ids)

            log(f"[done] Markdown geschrieben: {output_path}")
            log(f"[done] Erfolgreich: {len(extracted)} | Fehler: {len(failed)}")
            log(f"[done] IDs-Datei aktualisiert: {ids_path} ({len(downloaded_ids)} gesamt)")
            if failed:
                log("[done] Fehlerhafte IDs:")
                for pid, err in failed:
                    log(f"  - {pid}: {err}")
        finally:
            context.close()
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
