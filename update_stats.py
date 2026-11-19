#!/usr/bin/env python3
"""Refresh frags-stats.svg, hero-banner.svg, and frags-contri.svg with live numbers from GitHub (stdlib only)."""
import json
import os
import re
import textwrap
import urllib.request
from datetime import datetime, timezone
from xml.sax.saxutils import escape

USER = os.environ.get("GH_USER", "FrndlyFrags")
TOKEN = os.environ["GITHUB_TOKEN"]
STATS_SVG_PATH = os.environ.get("SVG_PATH", "frags-stats.svg")
HERO_SVG_PATH = "hero-banner.svg"
CONTRI_SVG_PATH = "frags-contri.svg"
REPO_SLOTS = 3  # tiles in the SVG: r1, r2, r3

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
    pullRequests(states: MERGED) { totalCount }
    issues(states: CLOSED) { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100,
                 orderBy: {field: STARGAZERS, direction: DESC}) {
      nodes {
        name
        description
        stargazerCount
        pushedAt
        primaryLanguage { name color }
      }
    }
  }
}
"""


def fetch():
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise SystemExit(payload["errors"])
    return payload["data"]["user"]


def streak_from(weeks):
    days = [d for w in weeks for d in w["contributionDays"]]
    today = datetime.now(timezone.utc).date().isoformat()
    streak = 0
    for d in reversed(days):
        if d["date"] == today and d["contributionCount"] == 0:
            continue  # today isn't over yet
        if d["contributionCount"] > 0:
            streak += 1
        else:
            break
    return streak


def contribution_stats(weeks):
    """Calculate real stats from contribution calendar weeks."""
    days = [d for w in weeks for d in w["contributionDays"]]
    today = datetime.now(timezone.utc).date().isoformat()

    # Filter to this year
    year = datetime.now(timezone.utc).year
    year_start = f"{year}-01-01"
    year_days = [d for d in days if d["date"] >= year_start]

    # Active days this year
    active_days = sum(1 for d in year_days if d["contributionCount"] > 0)
    total_days = len(year_days) if year_days else 1

    # Last 12 weeks for charge history (84 days)
    recent_days = days[-84:] if len(days) >= 84 else days
    # Group by week (7 days each)
    weekly_totals = []
    for i in range(0, len(recent_days), 7):
        week = recent_days[i:i+7]
        weekly_totals.append(sum(d["contributionCount"] for d in week))
    # Take last 12 weeks
    weekly_totals = weekly_totals[-12:]

    # Last 7 days for 7-day charge
    last_7 = recent_days[-7:] if len(recent_days) >= 7 else recent_days
    last_7_counts = [d["contributionCount"] for d in last_7]

    # Longest streak
    longest_streak = 0
    current = 0
    for d in year_days:
        if d["contributionCount"] > 0:
            current += 1
            longest_streak = max(longest_streak, current)
        else:
            current = 0

    # Peak week
    peak_week = max(weekly_totals) if weekly_totals else 0

    # Total contributions this year
    total_contribs = sum(d["contributionCount"] for d in year_days)

    return {
        "weekly_totals": weekly_totals,
        "last_7": last_7_counts,
        "longest_streak": longest_streak,
        "active_days": active_days,
        "total_days": total_days,
        "peak_week": peak_week,
        "total_contribs": total_contribs,
    }


def set_text(svg, el_id, value):
    value = escape(str(value))
    return re.sub(rf'(id="{el_id}"[^>]*>)[^<]*(<)', lambda m: m.group(1) + value + m.group(2), svg, count=1)


def set_attr(svg, el_id, attr, value):
    return re.sub(rf'(id="{el_id}"[^>]*? {attr}=")[^"]*(")', lambda m: m.group(1) + str(value) + m.group(2), svg, count=1)


def set_bar(svg, el_id, width):
    pattern = rf'(<rect id="{el_id}"[^>]*? width=")\d+(".*?\bto=")\d+(")'
    return re.sub(pattern, lambda m: f"{m.group(1)}{width}{m.group(2)}{width}{m.group(3)}", svg, count=1, flags=re.S)


def bar_width(value, cap, full):
    if value <= 0:
        return 0
    return max(6, round(full * min(1, value / cap)))


def short(text, limit):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def desc_lines(desc, lang):
    text = (desc or "").strip().strip('"').strip()
    if not text:
        text = f"{lang or 'Code'} project"
    lines = textwrap.wrap(text, 34, max_lines=2, placeholder="…")
    return lines + [""] * (2 - len(lines))


def ago(iso):
    days = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    if days < 1:
        return "today"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def top_repos(nodes):
    pool = [n for n in nodes if n["name"].lower() != USER.lower()]
    pool.sort(key=lambda n: (n["stargazerCount"], n["pushedAt"]), reverse=True)
    return pool[:REPO_SLOTS]


def update_frags_contri(svg, stats, power_level):
    """Update frags-contri.svg with real contribution data."""
    # Update sample data text
    svg = re.sub(r'frndlyfrags · sample data', f'frndlyfrags · {stats["total_contribs"]} contribs this year', svg)

    # Update CHARGE HISTORY bars (12 weeks)
    weekly = stats["weekly_totals"]
    max_weekly = max(weekly) if weekly else 1
    # Heights are scaled to max 78px (from y=112 to y=190)
    # The SVG has 12 rects at x positions: 30, 39.5, 49, 58.5, 68, 77.5, 87, 96.5, 106, 115.5, 125, 134.5
    # We'll replace each rect's height and y position
    weekly_heights = [round(78 * w / max_weekly) if max_weekly > 0 else 0 for w in weekly]

    # Find and replace the CHARGE HISTORY bar group
    # Pattern: <rect x="30.0" y="112.0" width="7" height="78.0" rx="2" fill="#ff7b00"/>
    # We need to update each of the 12 bars
    x_positions = [30.0, 39.5, 49.0, 58.5, 68.0, 77.5, 87.0, 96.5, 106.0, 115.5, 125.0, 134.5]
    for i, (x, h) in enumerate(zip(x_positions, weekly_heights)):
        y = 190 - h  # bottom at y=190
        pattern = rf'(<rect x="{x}" y=")[^"]*(" width="7" height=")[^"]*(" rx="2" fill="#[^"]*"/>)'
        svg = re.sub(pattern, lambda m: f'{m.group(1)}{y}{m.group(2)}{h}{m.group(3)}', svg, count=1)

    # Update 7-DAY CHARGE (7 blocks)
    last_7 = stats["last_7"]
    # The 7-day blocks are at x: 30, 46.5, 63, 79.5, 96, 112.5, 129
    # Active days get #ff3700, inactive get #1f1f23
    seven_x = [30.0, 46.5, 63.0, 79.5, 96.0, 112.5, 129.0]
    for i, (x, count) in enumerate(zip(seven_x, last_7)):
        fill = "#ff3700" if count > 0 else "#1f1f23"
        pattern = rf'(<rect x="{x}" y="236" width="13" height="14" rx="3" fill=")[^"]*("/?>)'
        svg = re.sub(pattern, lambda m: f'{m.group(1)}{fill}{m.group(2)}', svg, count=1)

    # Update POWER LEVEL - use the computed XP-based level
    # There are multiple animated text elements cycling through numbers
    # Replace the final stable value (the one with longest duration)
    # The last one (765) has keyTimes 0;0.1417;0.9667 - it shows the longest
    # We'll replace all of them with the real power level
    power_values = [power_level] * 13  # 13 animated values
    for i, val in enumerate(power_values):
        # Each animated text has a different opacity keyTimes pattern
        # We'll replace the text content of each
        pass  # Skip for now - the animation cycles through, we could set one representative

    # Better: just replace the final displayed value (the one that stays visible longest)
    # The last animated text with fill="#ff7b00" has the longest visibility
    # Find and replace its content
    svg = re.sub(
        r'(<text x="566" y="182" font-size="56" font-weight="800" fill="#ff7b00" opacity="0" filter="url\(#xglow\)"><animate attributeName="opacity" calcMode="discrete" values="0;1;0" keyTimes="0;0\.1417;0\.9667" dur="12\.0s" repeatCount="indefinite"/>)',
        lambda m: m.group(1) + str(power_level),
        svg
    )

    # Update KI · LONGEST STREAK
    svg = re.sub(
        r'(<text x="820" y="240" text-anchor="end" font-size="12" font-weight="800" fill="#fafafa">)\d+ days(</text>)',
        lambda m: f'{m.group(1)}{stats["longest_streak"]} days{m.group(2)}',
        svg
    )
    # Update streak progress bar (max ~365 days, width 254)
    streak_width = max(6, round(254 * min(1, stats["longest_streak"] / 365)))
    svg = re.sub(
        r'(<rect x="566" y="248" width=")110(" height="8" rx="4" fill="url\(#xog\)"><animate attributeName="width" values="0;0;110;110" keyTimes="0;0\.1833;0\.2583;1" dur="12\.0s" repeatCount="indefinite"/>)(</rect>)',
        lambda m: f'{m.group(1)}{streak_width}{m.group(2).replace("110", str(streak_width))}{m.group(3)}',
        svg
    )

    # Update STAMINA · ACTIVE DAYS
    svg = re.sub(
        r'(<text x="820" y="286" text-anchor="end" font-size="12" font-weight="800" fill="#fafafa">)\d+/\d+(</text>)',
        lambda m: f'{m.group(1)}{stats["active_days"]}/{stats["total_days"]}{m.group(2)}',
        svg
    )
    # Update active days progress bar
    active_width = max(6, round(254 * min(1, stats["active_days"] / stats["total_days"])))
    svg = re.sub(
        r'(<rect x="566" y="294" width=")139(" height="8" rx="4" fill="url\(#xog\)"><animate attributeName="width" values="0;0;139;139" keyTimes="0;0\.2125;0\.2875;1" dur="12\.0s" repeatCount="indefinite"/>)(</rect>)',
        lambda m: f'{m.group(1)}{active_width}{m.group(2).replace("139", str(active_width))}{m.group(3)}',
        svg
    )

    # Update BURST · PEAK WEEK
    svg = re.sub(
        r'(<text x="820" y="332" text-anchor="end" font-size="12" font-weight="800" fill="#fafafa">)\d+(</text>)',
        lambda m: f'{m.group(1)}{stats["peak_week"]}{m.group(2)}',
        svg
    )
    # Update peak week progress bar (cap at ~50 contribs/week)
    peak_width = max(6, round(254 * min(1, stats["peak_week"] / 50)))
    svg = re.sub(
        r'(<rect x="566" y="340" width=")203(" height="8" rx="4" fill="url\(#xog\)"><animate attributeName="width" values="0;0;203;203" keyTimes="0;0\.2417;0\.3167;1" dur="12\.0s" repeatCount="indefinite"/>)(</rect>)',
        lambda m: f'{m.group(1)}{peak_width}{m.group(2).replace("203", str(peak_width))}{m.group(3)}',
        svg
    )

    # Update THREAT level based on total contributions
    threat = "SSS" if stats["total_contribs"] > 1000 else "SS" if stats["total_contribs"] > 500 else "S" if stats["total_contribs"] > 100 else "A"
    svg = re.sub(
        r'(<text x="820" y="390" text-anchor="end" font-size="26" font-weight="800" fill="#ff7b00" filter="url\(#xglow\)">)[A-Z]+(</text>)',
        lambda m: f'{m.group(1)}{threat}{m.group(2)}',
        svg
    )

    # Update footer note
    svg = re.sub(
        r'orbs = last 12 weeks · aura = this week\'s charge · numbers are sample data',
        f'orbs = last 12 weeks · aura = this week\'s charge · {stats["total_contribs"]} total contributions',
        svg
    )

    return svg


def main():
    u = fetch()
    cc = u["contributionsCollection"]
    commits = cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
    prs = u["pullRequests"]["totalCount"]
    issues = u["issues"]["totalCount"]
    nodes = u["repositories"]["nodes"]
    stars = sum(n["stargazerCount"] for n in nodes)
    streak = streak_from(cc["contributionCalendar"]["weeks"])

    xp = commits * 10 + prs * 50 + stars * 20 + issues * 30
    level, xp_in = xp // 1000 + 1, xp % 1000

    with open(STATS_SVG_PATH, encoding="utf-8") as f:
        svg = f.read()

    for el_id, val in [("v-commits", f"{commits:,}"), ("v-stars", stars),
                       ("v-issues", issues), ("streak", streak), ("lvl", level),
                       ("xp", xp_in), ("next", f"next: LVL {level + 1}")]:
        svg = set_text(svg, el_id, val)

    svg = set_bar(svg, "bar-commits", bar_width(commits, 1500, 230))
    svg = set_bar(svg, "bar-prs", bar_width(prs, 100, 230))
    svg = set_bar(svg, "bar-stars", bar_width(stars, 200, 230))
    svg = set_bar(svg, "bar-issues", bar_width(issues, 100, 230))
    svg = set_bar(svg, "bar-xp", bar_width(xp_in, 1000, 440))

    repos = top_repos(nodes)
    for i in range(1, REPO_SLOTS + 1):
        r = repos[i - 1] if i <= len(repos) else None
        lang = (r or {}).get("primaryLanguage") or {}
        d1, d2 = desc_lines(r["description"], lang.get("name")) if r else ("", "")
        svg = set_text(svg, f"r{i}-name", short(r["name"], 24) if r else "—")
        svg = set_text(svg, f"r{i}-d1", d1)
        svg = set_text(svg, f"r{i}-d2", d2)
        svg = set_attr(svg, f"r{i}-dot", "fill", lang.get("color") or "#52525b")
        svg = set_text(svg, f"r{i}-lang", lang.get("name") or "—")
        svg = set_text(svg, f"r{i}-meta", f"★ {r['stargazerCount']} · {ago(r['pushedAt'])}" if r else "")

    with open(STATS_SVG_PATH, "w", encoding="utf-8") as f:
        f.write(svg)

    # Update hero-banner.svg
    update_hero_banner(commits, streak, len([n for n in nodes if n["name"].lower() != USER.lower()]), stars)

    # Update frags-contri.svg with real contribution data
    stats = contribution_stats(cc["contributionCalendar"]["weeks"])
    power_level = commits + prs * 5 + stars * 2  # Simple power level formula

    with open(CONTRI_SVG_PATH, encoding="utf-8") as f:
        contri_svg = f.read()

    contri_svg = update_frags_contri(contri_svg, stats, power_level)

    with open(CONTRI_SVG_PATH, "w", encoding="utf-8") as f:
        f.write(contri_svg)

    print(f"{USER}: commits={commits} prs={prs} stars={stars} issues={issues} streak={streak} "
          f"lvl={level} repos={[r['name'] for r in repos]}")
    print(f"  contrib stats: active={stats['active_days']}/{stats['total_days']} streak={stats['longest_streak']} peak_week={stats['peak_week']} power={power_level}")


def update_hero_banner(commits, streak, repo_count, stars):
    """Update the hero-banner.svg with real-time stats."""
    with open(HERO_SVG_PATH, encoding="utf-8") as f:
        svg = f.read()

    # Update hero-banner.svg via id-targeted text injection (same helper as stats card)
    svg = set_text(svg, "v-commits-hero", f"{commits:,}")
    svg = set_text(svg, "v-streak-hero", str(streak))
    svg = set_text(svg, "v-repos-hero", str(repo_count))
    svg = set_text(svg, "v-stars-hero", str(stars))

    with open(HERO_SVG_PATH, "w", encoding="utf-8") as f:
        f.write(svg)


if __name__ == "__main__":
    main()
