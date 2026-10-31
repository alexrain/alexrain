#!/usr/bin/env python3
"""Generate assets/stats.svg for the alexrain GitHub profile README."""

from __future__ import annotations

import datetime as dt
import html
import base64
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import requests

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
LOGIN = os.environ.get("GITHUB_LOGIN", "alexrain")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = Path(__file__).resolve().parent.parent / "assets" / "stats.svg"

PURPLE = "#7C3AED"
INK = "#111827"
MUTED = "#6B7280"
LINE = "#E5E7EB"
CARD = "#FFFFFF"


def _headers() -> dict[str, str]:
    if not TOKEN:
        raise SystemExit("GITHUB_TOKEN is required")
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "alexrain-profile-stats",
    }


def _get(url: str, **params):
    response = requests.get(url, headers=_headers(), params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _prs(state: str) -> tuple[int, Counter[str]]:
    counts: Counter[str] = Counter()
    total = 0
    page = 1
    while True:
        payload = _get(
            f"{API}/search/issues",
            q=f"is:pr author:{LOGIN} is:{state}",
            per_page=100,
            page=page,
        )
        total = payload.get("total_count", 0)
        items = payload.get("items", [])
        if not items:
            break
        for item in items:
            repo = item.get("repository_url", "").rsplit("/repos/", 1)[-1]
            if repo:
                counts[repo] += 1
        if len(items) < 100 or page >= 10:
            break
        page += 1
    return total, counts


def _repo_stars(full_name: str) -> int:
    try:
        repo = _get(f"{API}/repos/{full_name}")
    except requests.HTTPError:
        return 0
    parent = repo.get("parent") or repo.get("source") or {}
    return int(parent.get("stargazers_count") or repo.get("stargazers_count") or 0)


_AVATAR_CACHE: dict[str, str] = {}


def _avatar_data_uri(full_name: str) -> str:
    """Fetch the repository owner's avatar and return a small data URI."""
    owner = full_name.split("/", 1)[0]
    if owner in _AVATAR_CACHE:
        return _AVATAR_CACHE[owner]
    response = requests.get(
        f"https://github.com/{owner}.png",
        params={"size": 64},
        headers={"User-Agent": "alexrain-profile-stats"},
        timeout=20,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "image/png").split(";", 1)[0]
    encoded = base64.b64encode(response.content).decode("ascii")
    uri = f"data:{content_type};base64,{encoded}"
    _AVATAR_CACHE[owner] = uri
    return uri


def _contributions() -> list[tuple[str, int]]:
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            weeks {
              contributionDays { date contributionCount }
            }
          }
        }
      }
    }
    """
    response = requests.post(
        GRAPHQL,
        headers=_headers(),
        json={"query": query, "variables": {"login": LOGIN}},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    days = []
    for week in payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for day in week["contributionDays"]:
            days.append((day["date"], int(day["contributionCount"])))
    return days[-30:]


def _fmt_stars(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _sparkline(days: list[tuple[str, int]], x0: int, y0: int, width: int, height: int) -> tuple[str, int]:
    if not days:
        return "", 0
    max_count = max((count for _, count in days), default=0) or 1
    gap = width / max(len(days) - 1, 1)
    bars = []
    for index, (_, count) in enumerate(days):
        bar_h = max(3, int(count / max_count * height))
        x = x0 + index * gap
        y = y0 + height - bar_h
        opacity = 0.35 if count == 0 else 0.9
        bars.append(
            f'<rect x="{x:.1f}" y="{y}" width="6" height="{bar_h}" rx="3" fill="{PURPLE}" opacity="{opacity}"/>'
        )
    recent = sum(count for _, count in days)
    return "".join(bars), recent


def _svg(
    merged_total: int,
    merged_counts: Counter[str],
    open_total: int,
    open_counts: Counter[str],
    days: list[tuple[str, int]],
) -> str:
    combined = Counter(merged_counts)
    combined.update(open_counts)
    ranked = sorted(
        combined.items(),
        key=lambda item: (item[1], _repo_stars(item[0])),
        reverse=True,
    )
    top = ranked[:6]
    hidden = max(0, len(ranked) - len(top))
    row_h = 32
    height = 300 + (len(top) + (1 if hidden else 0)) * row_h + 40
    width = 860
    chart_x, chart_y, chart_w, chart_h = 40, 176, 780, 48
    bars, recent = _sparkline(days, chart_x, chart_y, chart_w, chart_h)
    start_label = days[0][0][5:] if days else ""
    end_label = days[-1][0][5:] if days else ""
    updated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = []
    defs = []
    y = 302
    for index, (full_name, count) in enumerate(top):
        stars = _repo_stars(full_name)
        merged = merged_counts.get(full_name, 0)
        opened = open_counts.get(full_name, 0)
        if index:
            rows.append(f'<line x1="40" y1="{y - 10}" x2="820" y2="{y - 10}" stroke="{LINE}" stroke-width="1"/>')
        avatar = _avatar_data_uri(full_name)
        defs.append(
            f'<clipPath id="repo-avatar-{index}"><circle cx="52" cy="{y + 1}" r="12"/></clipPath>'
        )
        rows.append(
            f'<image x="40" y="{y - 11}" width="24" height="24" href="{avatar}" '
            f'clip-path="url(#repo-avatar-{index})" preserveAspectRatio="xMidYMid slice"/>'
        )
        rows.append(
            f'<text x="76" y="{y + 6}" font-size="15" font-weight="600" fill="{INK}">{html.escape(full_name)}</text>'
        )
        detail = f"{merged} merged" + (f" · {opened} open" if opened else "")
        rows.append(
            f'<text x="700" y="{y + 6}" font-size="13" fill="{MUTED}" text-anchor="end">{detail}</text>'
        )
        rows.append(
            f'<text x="820" y="{y + 6}" font-size="13" fill="{MUTED}" text-anchor="end">★ {_fmt_stars(stars)}</text>'
        )
        y += row_h

    if hidden:
        rows.append(
            f'<text x="40" y="{y + 6}" font-size="13" fill="{MUTED}">… 另有 {hidden} 个仓库的 PR</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Merged pull requests by {LOGIN}">
  <defs>{''.join(defs)}</defs>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="18" fill="{CARD}" stroke="{LINE}"/>
  <text x="40" y="38" font-size="13" font-weight="700" letter-spacing="2" fill="{PURPLE}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">MERGED PULL REQUESTS</text>
  <text x="820" y="38" font-size="12" fill="#9CA3AF" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">github.com/{html.escape(LOGIN)}</text>
  <text x="40" y="128" font-size="76" font-weight="800" fill="{INK}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{merged_total}</text>
  <text x="40" y="154" font-size="14" fill="{MUTED}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{merged_total} 个 PR 合并 · {open_total} 个待合并 · 近 30 天 +{recent}</text>
  <line x1="40" y1="168" x2="820" y2="168" stroke="{LINE}" stroke-width="1"/>
  {bars}
  <line x1="{chart_x}" y1="{chart_y + chart_h + 8}" x2="{chart_x + chart_w}" y2="{chart_y + chart_h + 8}" stroke="{LINE}" stroke-width="1"/>
  <text x="{chart_x}" y="{chart_y + chart_h + 20}" font-size="11" fill="#9CA3AF" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{html.escape(start_label)}</text>
  <text x="{chart_x + chart_w}" y="{chart_y + chart_h + 20}" font-size="11" fill="#9CA3AF" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{html.escape(end_label)}</text>
  <line x1="40" y1="274" x2="820" y2="274" stroke="{LINE}" stroke-width="1"/>
  {''.join(rows)}
  <line x1="40" y1="{height - 28}" x2="820" y2="{height - 28}" stroke="{LINE}" stroke-width="1"/>
  <text x="40" y="{height - 10}" font-size="11" fill="#9CA3AF" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">数据来源 GitHub REST API · 每日自动刷新</text>
  <text x="820" y="{height - 10}" font-size="11" fill="#9CA3AF" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">更新于 {updated}</text>
</svg>
'''


def main() -> None:
    merged_total, merged_counts = _prs("merged")
    open_total, open_counts = _prs("open")
    days = _contributions()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(_svg(merged_total, merged_counts, open_total, open_counts, days), encoding="utf-8")
    print(f"Wrote {OUT} ({merged_total} merged, {open_total} open, {len(merged_counts)} merged repos)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # keep the action log readable
        print(f"generate_stats failed: {exc}", file=sys.stderr)
        raise
