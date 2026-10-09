"""Nightly leaderboard check: re-run every submitted Daily Outage design with the engine.

Scores on the leaderboard are sent by the browser, so they are claims. The engine is
deterministic (the day number is the seed), so re-running the stored design must give
the same grade and total. Matching rows are marked verified; anything else is hidden.

Runs in GitHub Actions every night. Needs three environment variables:
  CF_ACCOUNT_ID, CF_API_TOKEN (D1 edit permission), D1_DATABASE_ID
Use --dry-run to print the verdicts without writing anything.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.web_api import run  # noqa: E402

ROTATION = json.loads((ROOT / "incidents" / "rotation.json").read_text())["eras"]  # shared with the web app
SEED_LINE = re.compile(r"^seed:.*$", re.MULTILINE)


def incident_for_daily(number: int) -> str:
    era = [e for e in ROTATION if e["from_daily"] <= number][-1]
    return era["incidents"][(number - era["from_daily"]) % len(era["incidents"])]


def scenario_for_daily(number: int) -> tuple[str, str]:
    """The incident name and scenario YAML everyone played on Daily Outage #number."""
    name = incident_for_daily(number)
    path = ROOT / "incidents" / name / "scenario.yaml"
    text = path.read_text()
    text = SEED_LINE.sub(f"seed: {number}", text) if SEED_LINE.search(text) else f"{text}\nseed: {number}\n"
    return name, text


def check(row: dict) -> tuple[bool, str]:
    """Re-run one submission. Returns (verified, reason)."""
    if not row.get("design_yaml"):
        return False, "no design"
    _, scenario_yaml = scenario_for_daily(int(row["daily"]))
    out = json.loads(run(row["design_yaml"], scenario_yaml))
    if not out["ok"]:
        return False, f"design does not load: {out['error'][:80]}"
    grade, total = out["score"]["grade"], out["score"]["total"]
    if grade == row["grade"] and abs(total - int(row["total"])) <= 1:
        return True, f"{grade} {total}"
    return False, f"claimed {row['grade']} {row['total']}, engine says {grade} {total}"


def d1(sql: str, params: list | None = None) -> list[dict]:
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CF_ACCOUNT_ID']}"
        f"/d1/database/{os.environ['D1_DATABASE_ID']}/query"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps({"sql": sql, "params": params or []}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['CF_API_TOKEN'].strip()}",
            "Content-Type": "application/json",
            "User-Agent": "scale-or-fail-verify/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Cloudflare said HTTP {exc.code}: {exc.read().decode()[:500]}") from None
    if not body.get("success"):
        raise RuntimeError(body.get("errors"))
    return body["result"][0].get("results", [])


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    rows = d1(
        "SELECT id, daily, name, grade, total, design_yaml FROM daily_results "
        "WHERE verified = 0 AND hidden = 0 ORDER BY id LIMIT 500"
    )
    print(f"{len(rows)} unverified submission(s)")
    passed = failed = 0
    for row in rows:
        ok, reason = check(row)
        print(f"  #{row['daily']} {row['name']!r}: {'verified' if ok else 'HIDDEN'} ({reason})")
        if ok:
            passed += 1
        else:
            failed += 1
        if not dry_run:
            column = "verified" if ok else "hidden"
            d1(f"UPDATE daily_results SET {column} = 1 WHERE id = ?", [row["id"]])
    print(f"done: {passed} verified, {failed} hidden{' (dry run, nothing written)' if dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
