#!/usr/bin/env python3
"""Refresh the 'Recently shipped' block in the profile README.

Uses only the standard library. Reads:
  - latest commit on each public repo of the profile owner (GitHub API)
  - latest posts from the owner's Medium RSS feed
Replaces the text between ACTIVITY markers. If either source fails, exits
without touching README.md so a bad run never blanks the profile.
"""
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

OWNER = "GreatHavoc"
SKIP_REPOS = {"GreatHavoc"}  # self-referential: the workflow commits to this repo
START = "<!-- activity:start -->"
END = "<!-- activity:end -->"
MAX_ITEMS = 6
MAX_AGE_DAYS = 365
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def get(url, token=None):
    headers = {"User-Agent": "profile-activity-bot", "Accept": "application/json"}
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def isoday(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def recent_code(token):
    repos = json.loads(get(f"https://api.github.com/users/{OWNER}/repos?per_page=100&type=owner", token))
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    for repo in repos:
        name = repo["name"]
        if repo.get("fork") or name in SKIP_REPOS:
            continue
        try:
            branch = repo.get("default_branch", "main")
            commits = json.loads(get(f"https://api.github.com/repos/{OWNER}/{name}/commits?sha={branch}&per_page=1", token))
            if not commits:
                continue
            c = commits[0]
            when = isoday(c["commit"]["committer"]["date"])
            if when < cutoff:
                continue
            message = c["commit"]["message"].splitlines()[0].strip().replace(" — ", ": ")
            items.append((when, f"- [{name}: {message[:80]}]({c['html_url']}) - {when.date()}"))
        except Exception:
            continue  # a single private/deleted repo must not break the whole refresh
    return sorted(items, reverse=True)[:MAX_ITEMS]


def recent_writing():
    xml = get(f"https://medium.com/feed/@{OWNER.lower()}")
    root = ET.fromstring(xml)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        raw = item.findtext("pubDate") or ""
        try:
            when = parsedate_to_datetime(raw).astimezone(timezone.utc)
        except Exception:
            continue
        if title and link:
            items.append((when, f"- [{title}]({link}) - {when.date()}"))
    return sorted(items, reverse=True)[:MAX_ITEMS]


def main():
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit("README is missing activity markers")

    token = os.environ.get("GITHUB_TOKEN")
    try:
        code = recent_code(token)
        writing = recent_writing()
    except Exception as exc:
        raise SystemExit(f"fetch failed, leaving README unchanged: {exc}")

    block = ["**Code**"]
    block += [line for _, line in code] or ["- No public commits in the last year."]
    block += ["", "**Writing**"]
    block += [line for _, line in writing] or ["- No recent posts."]
    new_text = text.split(START)[0] + START + "\n" + "\n".join(block) + "\n" + END + text.split(END)[1]

    if new_text != text:
        README.write_text(new_text, encoding="utf-8")
        print("README activity block refreshed")
    else:
        print("README unchanged")


if __name__ == "__main__":
    main()
