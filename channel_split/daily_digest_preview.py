#!/usr/bin/env python3
"""Read-only live preview of the verified AlanChande daily market digest.

No Telegram send, no timer/config change, and no market-history write.
24h changes show as — until the production digest has a prior verified daily
snapshot. The production publisher will later store history only after a
successful VERIFIED Telegram delivery.
"""
from __future__ import annotations

from pathlib import Path

from daily_market_digest import collect_digest


PREVIEW_HISTORY = Path("/tmp/alanchande-daily-digest-preview-no-history.sqlite3")


def main() -> int:
    # Do not let a prior local experiment turn this into a writable history.
    if PREVIEW_HISTORY.exists():
        PREVIEW_HISTORY.unlink()

    result = collect_digest(PREVIEW_HISTORY)

    print("===== SOURCE HEALTH =====")
    for key, error in sorted(result.source_health.items()):
        print(f"{key}: {'HEALTHY' if error is None else 'DEGRADED'}"
              + (f" | {error}" if error else ""))

    print("\n===== 28-LINE SAFETY =====")
    print(
        f"{result.assessment.post_type}: {result.assessment.decision} | "
        f"{result.assessment.reason}"
    )
    for check in result.assessment.checks:
        sources = ", ".join(
            f"{name}={value}"
            for name, value in sorted(check.source_values.items())
        ) or "none"
        print(
            f"{check.market_key}: {check.decision} | "
            f"reference={check.reference_value} | sources=[{sources}]"
        )
        if check.decision != "VERIFIED":
            print(f"  reason: {check.reason}")

    print("\n===== TELEGRAM PREVIEW (NOT SENT) =====")
    print(result.text)
    print(f"\nCHARACTERS: {len(result.text)}/4096")
    print("TELEGRAM SEND: DISABLED")
    print("HISTORY WRITE: DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
