#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from notion_http import load_env_file, notion_request

REPO_DIR = Path(__file__).resolve().parents[1]
NOTION_DATA_SOURCE_ID = "30355347-e6e0-81e2-a2a5-000ba0c84f02"
NOTION_API_URL = f"https://api.notion.com/v1/data_sources/{NOTION_DATA_SOURCE_ID}/query"
NOTION_PAGE_URL = "https://api.notion.com/v1/pages/{page_id}"


def today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get_title(page: Dict[str, Any]) -> str:
    title_parts = page.get("properties", {}).get("Post", {}).get("title", [])
    return "".join(part.get("plain_text", "") for part in title_parts).strip()


def get_page_summary(page: Dict[str, Any]) -> Dict[str, Any]:
    props = page.get("properties", {})
    platform = [item.get("name") for item in props.get("Platform", {}).get("multi_select", []) if item.get("name")]
    date = props.get("Date", {}).get("date", {}) or {}
    return {
        "id": page.get("id"),
        "date": date.get("start"),
        "approved": props.get("Approved", {}).get("checkbox"),
        "published": props.get("Published", {}).get("checkbox"),
        "platform": platform,
        "post": get_title(page),
    }


def query_today_posts() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    start_cursor: str | None = None

    while True:
        payload: Dict[str, Any] = {
            "page_size": 100,
            "filter": {
                "and": [
                    {"property": "Date", "date": {"equals": today_utc()}},
                    {"property": "Approved", "checkbox": {"equals": True}},
                    {"property": "Published Nostr", "checkbox": {"equals": False}},
                    {"property": "Platform", "multi_select": {"contains": "Nostr"}},
                ]
            },
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor

        try:
            response = notion_request("POST", NOTION_API_URL, payload)
        except Exception as exc:
            raise RuntimeError(
                "Failed to query Notion for approved Nostr posts "
                f"(date={today_utc()}, cursor={start_cursor!r}, data_source_id={NOTION_DATA_SOURCE_ID})"
            ) from exc
        results.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        start_cursor = response.get("next_cursor")

    return results


def parse_hora_utc(value: Any) -> dt.datetime:
    """Parse Notion's decimal hour encoding as a UTC datetime for today.

    The workspace uses values like 12, 12.06, or 12.55 where the digits after the
    decimal point represent minutes, not fractional hours.
    """
    if value is None:
        raise ValueError("Hora UTC is missing")

    raw = str(value).strip()
    if not raw:
        raise ValueError("Hora UTC is empty")

    if "." in raw:
        hour_str, minute_str = raw.split(".", 1)
        minute_str = minute_str.rstrip("0") or "0"
        if len(minute_str) == 1:
            minute = int(minute_str) * 10
        else:
            minute = int(minute_str[:2])
    else:
        hour_str, minute = raw, 0

    hour = int(hour_str)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid Hora UTC value: {value!r}")

    now = dt.datetime.now(dt.timezone.utc)
    return dt.datetime(now.year, now.month, now.day, hour, minute, tzinfo=dt.timezone.utc)


def publish_to_nostr(content: str) -> str:
    env = os.environ.copy()
    env.pop("NOTION_API_KEY", None)
    result = subprocess.run(
        ["cargo", "run", "--quiet", "--", "--content", content],
        cwd=str(REPO_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Nostr publisher command failed "
            f"(cwd={REPO_DIR}, exit_code={result.returncode}, content_len={len(content)}):\n"
            f"STDOUT:\n{result.stdout or '<empty>'}\n"
            f"STDERR:\n{result.stderr or '<empty>'}"
        )

    event_id = ""
    for line in result.stdout.splitlines():
        if line.startswith("event_id:"):
            event_id = line.split(":", 1)[1].strip()
            break
    if not event_id:
        raise RuntimeError(
            "Nostr publisher command succeeded but event_id was not found in stdout: "
            f"{result.stdout or '<empty>'}"
        )
    return event_id


def mark_published(page_id: str, page: Dict[str, Any], event_id: str) -> None:
    props = page.get("properties", {})
    published_x = props.get("Published X", {}).get("checkbox", False)
    published_nostr = props.get("Published Nostr", {}).get("checkbox", False)
    updates: Dict[str, Any] = {
        "Published Nostr": {"checkbox": True},
        "published_at Nostr": {"date": {"start": now_utc_iso()}},
        "nostr_event_id": {"rich_text": [{"text": {"content": event_id}}]},
    }

    if published_x:
        updates["Published"] = {"checkbox": True}
        updates["published_at"] = {"date": {"start": now_utc_iso()}}
    elif not published_nostr:
        # Defensive fallback: if the network-specific checkbox is unexpectedly empty,
        # keep the global flag aligned with actual state.
        updates["Published"] = {"checkbox": False}

    notion_request(
        "PATCH",
        NOTION_PAGE_URL.format(page_id=page_id),
        {"properties": updates},
    )


def main() -> int:
    load_env_file(REPO_DIR / ".env")

    now = dt.datetime.now(dt.timezone.utc)
    posts = []
    try:
        pages = query_today_posts()
    except Exception as exc:
        print(f"[mostro-publish-nostr-from-notion] ERROR: {exc}", file=sys.stderr)
        return 1

    for page in pages:
        summary = get_page_summary(page)
        try:
            scheduled_at = parse_hora_utc(page.get("properties", {}).get("Hora UTC", {}).get("number"))
        except Exception as exc:
            print(
                "[mostro-publish-nostr-from-notion] WARN: skipping page "
                f"{summary.get('id')} because Hora UTC is invalid: {exc}",
                file=sys.stderr,
            )
            continue
        if scheduled_at <= now:
            posts.append((page, summary, scheduled_at))

    if not posts:
        return 0

    posts.sort(key=lambda item: item[2])
    for page, summary, scheduled_at in posts:
        page_id = summary["id"]
        content = summary["post"]

        try:
            event_id = publish_to_nostr(content)
            mark_published(page_id, page, event_id)
        except Exception as exc:
            print(
                "[mostro-publish-nostr-from-notion] ERROR: failed to publish page "
                f"{page_id} scheduled_at={scheduled_at.isoformat()}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(f"page_id: {page_id} scheduled_at: {scheduled_at.isoformat()} event_id: {event_id}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[publish_today_from_notion] FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1)
