#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app import run_offline_demo


def main() -> None:
    controller = run_offline_demo(seconds=4.0)
    print("OK: offline demo completed")
    print(f"state={controller.state.value} angle={controller.servo.get_angle():.1f}")
    print(f"events={len(controller.logs)}")
    for row in controller.logs[:12]:
        print(f"  [{row.t:4.2f}s] {row.state}: {row.note}")
    if len(controller.logs) > 12:
        print(f"  ... ({len(controller.logs) - 12} more)")


if __name__ == "__main__":
    main()
