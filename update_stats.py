#!/usr/bin/env python3
"""Refresh frags-stats.svg with live numbers and top repos from GitHub (stdlib only)."""
import json
import os
import re
import textwrap
import urllib.request
from datetime import datetime, timezone
from xml.sax.saxutils import escape

USER = os.environ.get("GH_USER", "FrndlyFrags")
TOKEN = os.environ["GITHUB_TOKEN"]
SVG_PATH = os.environ.get("SVG_PATH", "frags-stats.svg")
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
    # public, non-fork repos come from the query; drop the profile repo itself
    pool = [n for n in nodes if n["name"].lower() != USER.lower()]
    pool.sort(key=lambda n: (n["stargazerCount"], n["pushedAt"]), reverse=True)
    return pool[:REPO_SLOTS]


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

    with open(SVG_PATH, encoding="utf-8") as f:
        svg = f.read()

    for el_id, val in [("v-commits", f"{commits:,}"), ("v-prs", prs), ("v-stars", stars),
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

    with open(SVG_PATH, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"{USER}: commits={commits} prs={prs} stars={stars} issues={issues} streak={streak} "
          f"lvl={level} repos={[r['name'] for r in repos]}")


if __name__ == "__main__":
    main()
