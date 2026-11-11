#!/usr/bin/env python3
"""Compare guest startup and graphics milestones from ReXGlue launch logs."""

import argparse
from collections import Counter
from pathlib import Path
import re


BOOT_START = re.compile(r"^.*---- start, build .*argc=", re.MULTILINE)
UNRESOLVED = re.compile(r"\[UNRESOLVED INDIRECT CALL\] Target: (0x[0-9a-f]+).*?Caller LR: (0x[0-9a-f]+)", re.I)
GUEST_FAULT = re.compile(r"Unhandled guest access violation|\[host pc\]|\[contexto ppc\]", re.I)
GRAPHICS = re.compile(r"\bd3d12\b|\bmoltenvk\b|\bvulkan\b|graphics pipeline state|\[ios-resolve\]", re.I)
SHADER_ERROR = re.compile(r"shader|pipeline|spir-?v|dxil|dxc", re.I)
ERROR = re.compile(r"\[(?:error|critical|fatal)\]|\bfailed\b", re.I)


def read_log(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def report(label: str, runtime: Path, boot: Path | None) -> None:
    runtime_text = read_log(runtime)
    boot_text = read_log(boot) if boot else runtime_text
    starts = list(BOOT_START.finditer(boot_text))
    if starts:
        boot_text = boot_text[starts[-1].start():]
    if boot is None:
        runtime_text = boot_text
    lines = runtime_text.splitlines()

    print(f"\n{label} ({runtime.name})")
    if starts:
        print(boot_text.splitlines()[0])
    for name, pattern in (
        ("Graphics milestones", GRAPHICS),
        ("Guest fault", GUEST_FAULT),
    ):
        matches = [line for line in lines if pattern.search(line)]
        print(f"{name} ({len(matches)})")
        for line in matches[-6:]:
            print(f"  {line}")
    shader_errors = [line for line in lines if SHADER_ERROR.search(line) and ERROR.search(line)]
    print(f"Shader or pipeline errors ({len(shader_errors)})")
    for line in shader_errors[-10:]:
        print(f"  {line}")
    calls = Counter((target.upper(), caller.upper()) for target, caller in UNRESOLVED.findall(boot_text))
    print(f"Unresolved calls ({sum(calls.values())} across {len(calls)} target/caller pairs)")
    for (target, caller), count in calls.most_common(15):
        print(f"  {count:5d}  {target}  caller LR {caller}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ios-log", type=Path, required=True)
    parser.add_argument("--ios-boot", type=Path)
    parser.add_argument("--windows-log", type=Path)
    parser.add_argument("--windows-boot", type=Path)
    args = parser.parse_args()
    if args.windows_boot and not args.windows_log:
        parser.error("--windows-boot requires --windows-log")
    report("iOS", args.ios_log, args.ios_boot)
    if args.windows_log:
        report("Windows", args.windows_log, args.windows_boot)


if __name__ == "__main__":
    main()
