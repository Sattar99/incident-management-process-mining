"""
make_fixture.py : generate a small synthetic dataset for CI.

The real Incident_Management_CSV.csv is 28 MB and git-ignored, so it is not
available on GitHub Actions runners. This script produces a miniature dataset
with the identical schema and delimiter so the pipeline and its tests can be
exercised end to end without it.

The fixture deliberately includes the awkward cases the real data contains, so
the edge-case handling is actually covered rather than assumed:

  * a NULL event name        (mirrors INC0305 in the real data)
  * NULL resolvers on system transitions (Ticket created / closed)
  * an escalated case that reaches level 3
  * a repeated event within one case (rework loop)
  * a Bug with a capped satisfaction score
  * DD/MM/YYYY timestamps, semicolon-delimited

Usage:
    python tests/make_fixture.py [--out PATH] [--cases N]
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd

RAW_COLUMNS = [
    "Case ID",
    "Variant",
    "Priority",
    "Reporter",
    "Timestamp",
    "Event",
    "Issue Type",
    "Resolver",
    "Report Channel",
    "Short Description",
    "Customer Satisfaction",
]

BASE = pd.Timestamp("2023-06-01 08:00:00")

# A simple happy path: create -> assign -> WIP -> solve -> feedback -> closed
HAPPY_PATH = [
    ("Ticket created", None),
    ("Ticket assigned to level 1 support", "alice"),
    ("WIP - level 1 support", "alice"),
    ("Ticket solved by level 1 support", "alice"),
    ("Customer feedback received", None),
    ("Ticket closed", None),
]

# Escalated path with the L3 rework loop seen in Variant 7
ESCALATED_PATH = [
    ("Ticket created", None),
    ("Ticket assigned to level 1 support", "alice"),
    ("WIP - level 1 support", "alice"),
    ("Level 1 escalates to level 2 support", "bob"),
    ("WIP - level 2 support", "bob"),
    ("Level 2 escalates to level 3 support", "carol"),
    ("WIP - level 3 support", "carol"),
    ("Ticket assigned to level 2 support", "bob"),
    ("WIP - level 2 support", "bob"),
    ("Level 2 escalates to level 3 support", "carol"),
    ("WIP - level 3 support", "carol"),
    ("Ticket assigned to level 2 support", "bob"),
    ("WIP - level 2 support", "bob"),
    ("Ticket solved by level 2 support", "bob"),
    ("Customer feedback received", None),
    ("Ticket closed", None),
]

ISSUE_TYPES = ["Bug", "Incident", "Service Request", "Feature Request"]
CHANNELS = ["Email", "Website", "Phone", "App"]
PRIORITIES = ["Low", "Medium", "High"]
REPORTERS = ["dana", "eli", "fern", "gus"]

# Variant 2/4/7/10 have satisfaction capped at 3 in the real data
CAPPED_VARIANTS = {"Variant 2", "Variant 4", "Variant 7", "Variant 10"}


def build(cases: int, seed: int = 7) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []

    for i in range(cases):
        case_id = f"INC{i + 1:04d}"
        variant = f"Variant {rng.randint(1, 13)}"
        priority = rng.choice(PRIORITIES)
        reporter = rng.choice(REPORTERS)
        issue_type = rng.choice(ISSUE_TYPES)
        channel = rng.choice(CHANNELS)

        path = ESCALATED_PATH if (i % 4 == 0) else HAPPY_PATH
        clock = BASE + pd.Timedelta(hours=6 * i)

        # Satisfaction is constant within a case in the real dataset (verified:
        # 0 of 31,588 cases have more than one value). v_case_metrics groups by
        # it, so a per-row score would split one case into several rows.
        satisfaction = rng.randint(1, 3 if variant in CAPPED_VARIANTS else 5)

        for event, resolver in path:
            clock = clock + pd.Timedelta(minutes=rng.randint(20, 240))
            rows.append({
                "Case ID": case_id,
                "Variant": variant,
                "Priority": priority,
                "Reporter": reporter,
                # Source format is DD/MM/YYYY HH:MM
                "Timestamp": clock.strftime("%d/%m/%Y %H:%M"),
                "Event": event,
                "Issue Type": issue_type,
                "Resolver": resolver,
                "Report Channel": channel,
                "Short Description": f"{issue_type} reported by {reporter}",
                "Customer Satisfaction": satisfaction,
            })

        # One case carries a NULL event name, mirroring INC0305 in the real data.
        if i == 1:
            rows.append({
                "Case ID": case_id,
                "Variant": variant,
                "Priority": priority,
                "Reporter": reporter,
                "Timestamp": (clock + pd.Timedelta(minutes=30)).strftime("%d/%m/%Y %H:%M"),
                "Event": None,
                "Issue Type": issue_type,
                "Resolver": "alice",
                "Report Channel": channel,
                "Short Description": "Row with a missing event label",
                "Customer Satisfaction": satisfaction,
            })

    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the CI test fixture")
    parser.add_argument("--out", default=str(Path(__file__).parent / "fixtures" / "sample_incidents.csv"))
    parser.add_argument("--cases", type=int, default=60)
    args = parser.parse_args()

    df = build(args.cases)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Semicolon-delimited, matching the real file.
    df.to_csv(out, sep=";", index=False)

    print(f"Wrote {out}")
    print(f"  {len(df):,} events | {df['Case ID'].nunique()} cases | {df['Variant'].nunique()} variants")
    print(f"  null events: {int(df['Event'].isna().sum())} | null resolvers: {int(df['Resolver'].isna().sum())}")


if __name__ == "__main__":
    main()