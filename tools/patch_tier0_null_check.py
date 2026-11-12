#!/usr/bin/env python3
"""
tools/patch_tier0_null_check.py
Adds a defensive NULL check in tier0_360's generated sub_82C34E00 function immediately
after the call at 0x82C34E04 (LR = 0x82C34E08). If ctx.r3 is NULL (e.g. uninitialized CRT
thread data), it redirects to a safe zeroed scratch buffer (0x3005D000) near the TLS arena
to prevent Signal 10 (SIGBUS) at 0x7000000014 (r3 + 0x14).
"""

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TIER0_RECOMP = ROOT / "generated" / "tier0_360" / "l4d2_tier0_recomp.1.cpp"

ANCHOR = """\t// bl 0x82c24710
\tctx.lr = 0x82C34E08;
\t__savegprlr_22(ctx, base);"""

PATCHED = """\t// bl 0x82c24710
\tctx.lr = 0x82C34E08;
\t__savegprlr_22(ctx, base);
\tif (__builtin_expect(ctx.r3.u32 == 0, 0)) {
\t\tREXLOG_WARN("[tier0] sub_82C34E00 got r3=0 at LR=0x82C34E08; returning NULL");
\t\tctx.r3.u64 = 0;
\t\treturn;
\t}"""

def check_status() -> int:
    if not TIER0_RECOMP.exists():
        print(f"[tier0_null_check] File not found: {TIER0_RECOMP}")
        return 1

    content = TIER0_RECOMP.read_text(encoding="utf-8")
    if "ctx.r3.u64 = 0;\n\t\treturn;" in content:
        print("[tier0_null_check] Fallback NULL check in sub_82C34E00: APPLIED (OK)")
        return 0
    elif ANCHOR in content:
        print("[tier0_null_check] Fallback NULL check in sub_82C34E00: NOT APPLIED (Clean)")
        return 1
    else:
        print("[tier0_null_check] Anchor not found in sub_82C34E00!")
        return 1

def apply_patch() -> int:
    if not TIER0_RECOMP.exists():
        print(f"[tier0_null_check] File not found: {TIER0_RECOMP}")
        return 1

    content = TIER0_RECOMP.read_text(encoding="utf-8")
    if "ctx.r3.u64 = 0;\n\t\treturn;" in content:
        print("[tier0_null_check] Patch already applied.")
        return 0

    if "ctx.r3.u32 = 0x3005D000;" in content:
        # Replace old scratch buffer patch with clean NULL return
        old_patch = """\tif (__builtin_expect(ctx.r3.u32 == 0, 0)) {
\t\tREXLOG_WARN("[tier0] sub_82C34E00 got r3=0 at LR=0x82C34E08; using scratch buffer");
\t\tctx.r3.u32 = 0x3005D000; // Valid zeroed guest address near TLS arena (0x3005E000)
\t}"""
        new_patch = """\tif (__builtin_expect(ctx.r3.u32 == 0, 0)) {
\t\tREXLOG_WARN("[tier0] sub_82C34E00 got r3=0 at LR=0x82C34E08; returning NULL");
\t\tctx.r3.u64 = 0;
\t\treturn;
\t}"""
        new_content = content.replace(old_patch, new_patch, 1)
        TIER0_RECOMP.write_text(new_content, encoding="utf-8", newline="\n")
        print("[tier0_null_check] Successfully updated NULL check in sub_82C34E00 to return NULL.")
        return 0

    if ANCHOR not in content:
        print("[tier0_null_check] ERROR: Anchor pattern not found in file!")
        return 1

    new_content = content.replace(ANCHOR, PATCHED, 1)
    TIER0_RECOMP.write_text(new_content, encoding="utf-8", newline="\n")
    print("[tier0_null_check] Successfully applied fallback NULL check to sub_82C34E00.")
    return 0

def main():
    parser = argparse.ArgumentParser(description="Patch fallback null check in sub_82C34E00")
    parser.add_argument("--apply", action="store_true", help="Apply null check patch")
    parser.add_argument("--status", action="store_true", help="Check patch status")
    args = parser.parse_args()

    if args.apply:
        ret = apply_patch()
        if ret != 0:
            return ret
        return check_status()

    return check_status()

if __name__ == "__main__":
    sys.exit(main())
