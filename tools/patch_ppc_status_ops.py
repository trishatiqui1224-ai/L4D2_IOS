#!/usr/bin/env python3
"""Implement the PPC status-register instructions used by the generated modules.

The cached ReXGlue output marks these four instructions unimplemented. They are
reached during early Source Engine initialization, so leaving the generated
throw in place aborts the whole iOS app before the title can start.
"""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]

PATCHES = {
    ROOT / "generated/tier0_360/l4d2_tier0_recomp.1.cpp": {
        "0x82C19750": (
            "mtfsfi",
            "\tctx.fpscr.storeFromGuest(0);",
        ),
        "0x82C19770": (
            "mtvscr",
            "\tctx.vscr_sat = static_cast<uint8_t>(ctx.v0.u32[0] & 1u);",
        ),
    },
    ROOT / "generated/engine_360/l4d2_engine_recomp.0.cpp": {
        "0x86C820B8": (
            "mtfsfi",
            "\tctx.fpscr.storeFromGuest(0);",
        ),
        "0x86C820D8": (
            "mtvscr",
            "\tctx.vscr_sat = static_cast<uint8_t>(ctx.v0.u32[0] & 1u);",
        ),
    },
}


def patch_file(path: Path, entries: dict[str, tuple[str, str]]) -> bool:
    if not path.exists():
        raise FileNotFoundError(f"Generated source not found: {path}")

    text = path.read_text(encoding="utf-8")
    original = text
    for address, (opcode, replacement) in entries.items():
        marker = f'REX_UNIMPLEMENTED({address}, "{opcode}");'
        if marker not in text:
            if replacement not in text:
                raise RuntimeError(f"Expected {marker} or its implementation in {path}")
            continue

        pattern = re.compile(
            rf"(?m)^[ \t]*// UNIMPLEMENTED: {re.escape(opcode)}\r?\n"
            rf"[ \t]*{re.escape(marker)}[ \t]*$"
        )
        text, count = pattern.subn(replacement, text, count=1)
        if count != 1:
            raise RuntimeError(f"Could not replace {marker} in {path}")

    # The cache already includes the opcode comments immediately above the
    # unimplemented markers, so keep those comments and remove any duplicate
    # comment left by a previous run of this patch.
    text = re.sub(
        r"(?m)^([ \t]*// (?:mtfsfi 7,0|mtvscr v0)\r?\n)\1",
        r"\1",
        text,
    )

    if text != original:
        path.write_bytes(text.encode("utf-8"))
    return text != original


def main() -> int:
    try:
        changed = [path for path, entries in PATCHES.items() if patch_file(path, entries)]
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[patch_ppc_status_ops] ERROR: {exc}", file=sys.stderr)
        return 1

    if changed:
        for path in changed:
            print(f"[patch_ppc_status_ops] Implemented PPC status ops in {path.relative_to(ROOT)}")
    else:
        print("[patch_ppc_status_ops] PPC status ops already implemented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
