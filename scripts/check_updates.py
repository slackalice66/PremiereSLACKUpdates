#!/usr/bin/env python3
"""
Checks Adobe's release notes for new Premiere Pro versions and updates versions.json.
Exits with code 0 always; prints a summary of what was found/changed.
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

VERSIONS_JSON = Path(__file__).parent.parent / "versions.json"

# Adobe pages to try in order. The year-specific pages are most reliable.
CURRENT_YEAR = date.today().year
ADOBE_URLS = [
    f"https://helpx.adobe.com/premiere-pro/using/whats-new/{CURRENT_YEAR}.html",
    f"https://helpx.adobe.com/premiere-pro/using/whats-new/{CURRENT_YEAR - 1}.html",
    "https://helpx.adobe.com/premiere-pro/using/premiere-pro-release-notes.html",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Matches versions like "26.2", "26.0.2", "25.6.0"
VERSION_RE = re.compile(r"\b(2[0-9]\.\d+(?:\.\d+)?)\b")

# Matches dates like "April 16, 2026" / "16 April 2026" / "2026-04-16"
DATE_RES = [
    re.compile(r"(\d{4}-\d{2}-\d{2})"),
    re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2}),?\s+(\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{4})",
        re.IGNORECASE,
    ),
]

MONTH_MAP = {
    m: str(i + 1).zfill(2)
    for i, m in enumerate(
        "january february march april may june july august september october november december".split()
    )
}


def parse_date(text: str) -> str | None:
    m = DATE_RES[0].search(text)
    if m:
        return m.group(1)
    m = DATE_RES[1].search(text)
    if m:
        month, day, year = m.group(1), m.group(2), m.group(3)
        return f"{year}-{MONTH_MAP[month.lower()]}-{day.zfill(2)}"
    m = DATE_RES[2].search(text)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        return f"{year}-{MONTH_MAP[month.lower()]}-{day.zfill(2)}"
    return None


def fetch_page(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  Could not fetch {url}: {e}")
        return None


def extract_versions(soup: BeautifulSoup, source_url: str) -> list[dict]:
    """
    Walk headings (h1-h4) looking for version numbers.
    For each hit, search the surrounding text (heading + next sibling paragraphs) for a date.
    """
    found = []
    headings = soup.find_all(["h1", "h2", "h3", "h4"])
    for heading in headings:
        text = heading.get_text(" ", strip=True)
        vm = VERSION_RE.search(text)
        if not vm:
            continue
        version = vm.group(1)

        # Search heading text + nearby siblings for a date
        search_text = text
        for sib in heading.find_next_siblings()[:5]:
            search_text += " " + sib.get_text(" ", strip=True)
            if parse_date(search_text):
                break

        release_date = parse_date(search_text)
        if not release_date:
            continue

        year = release_date[:4]
        found.append({
            "version": version,
            "releaseDate": release_date,
            "releaseNotesUrl": f"https://helpx.adobe.com/premiere-pro/using/whats-new/{year}.html",
        })

    # Deduplicate, keeping first occurrence of each version
    seen = set()
    unique = []
    for item in found:
        if item["version"] not in seen:
            seen.add(item["version"])
            unique.append(item)
    return unique


def load_versions_json() -> dict:
    with open(VERSIONS_JSON) as f:
        return json.load(f)


def save_versions_json(data: dict) -> None:
    with open(VERSIONS_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def main() -> None:
    current = load_versions_json()
    known_versions = {v["version"] for v in current["versions"]}

    scraped: list[dict] = []
    for url in ADOBE_URLS:
        print(f"Fetching {url} …")
        soup = fetch_page(url)
        if soup:
            results = extract_versions(soup, url)
            print(f"  Found {len(results)} version(s): {[r['version'] for r in results]}")
            scraped.extend(results)
        if scraped:
            break  # Stop once we have results

    if not scraped:
        print("No versions scraped from any source — versions.json unchanged.")
        return

    # Find genuinely new versions
    new_entries = [r for r in scraped if r["version"] not in known_versions]
    if not new_entries:
        print(f"No new versions found. Latest known: {current['latest']['version']}")
        return

    print(f"New version(s) detected: {[e['version'] for e in new_entries]}")

    # Merge: prepend new entries to the versions list, sorted newest-first
    all_versions = new_entries + current["versions"]
    all_versions.sort(key=lambda v: version_tuple(v["version"]), reverse=True)

    # Remove releaseNotesUrl from per-version entries (it lives on latest only)
    versions_list = [{"version": v["version"], "releaseDate": v["releaseDate"], "knownIssues": v.get("knownIssues", [])} for v in all_versions]

    latest = all_versions[0]
    current["updated"] = date.today().isoformat()
    current["latest"] = {
        "version": latest["version"],
        "releaseDate": latest["releaseDate"],
        "releaseNotesUrl": latest["releaseNotesUrl"],
    }
    current["versions"] = versions_list

    save_versions_json(current)
    print(f"versions.json updated. Latest: {latest['version']} ({latest['releaseDate']})")


if __name__ == "__main__":
    main()
