#!/usr/bin/env python3
"""
Patch generated PCH headers to use LookupGlobalFunction and SafeDispatchIndirect.
Prevents uncompiled callback or unresolved import jumps to host NULL (PC = 0x0).
"""

import argparse
import glob
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"

TARGET_BLOCK = """#define REX_LOOKUP_FUNC(x, y) \\
  (*(PPCFunc**)(x + REX_IMAGE_BASE + REX_IMAGE_SIZE + (u64(u32(y) - REX_CODE_BASE) * 2)))

#define REX_CALL_INDIRECT_FUNC(x)                                                          \\
  do {                                                                                     \\
    REX_PROFILE_INDIRECT_DISPATCH();                                                       \\
    uint32_t rex_indirect_target_ = (uint32_t)(x);                                         \\
    PPCFunc* rex_indirect_func_;                                                           \\
    if ((uint32_t)(rex_indirect_target_ - REX_CODE_BASE) <                                 \\
        REX_CODE_SIZE + REX_THUNK_RESERVE_SIZE) [[likely]] {                               \\
      rex_indirect_func_ = REX_LOOKUP_FUNC(base, rex_indirect_target_);                    \\
    } else {                                                                               \\
      rex_indirect_func_ = nullptr;                                                        \\
    }                                                                                      \\
    if (!rex_indirect_func_) [[unlikely]] {                                                \\
      ctx.last_indirect_target = rex_indirect_target_;                                     \\
      rex_indirect_func_ = rex::runtime::ResolveIndirectFunction(rex_indirect_target_);    \\
    }                                                                                      \\
    rex_indirect_func_(ctx, base);                                                         \\
  } while (0)"""

REPLACEMENT_BLOCK = """extern "C" {
PPCFunc* LookupGlobalFunction(uint8_t* base, uint32_t guest_addr);
void SafeDispatchIndirect(PPCContext& ctx, uint8_t* base, uint32_t target_addr, uint32_t caller_lr);
}

#define REX_LOOKUP_FUNC(x, y) LookupGlobalFunction((x), (uint32_t)(y))

#define REX_CALL_INDIRECT_FUNC(x)                                                          \\
  do {                                                                                     \\
    REX_PROFILE_INDIRECT_DISPATCH();                                                       \\
    SafeDispatchIndirect(ctx, base, (uint32_t)(x), (uint32_t)ctx.lr);                      \\
  } while (0)"""

def normalize(text: str) -> str:
    return text.replace("\r\n", "\n")

def get_pch_files():
    return sorted(GEN_DIR.glob("*/*_pch.h"))

def status():
    files = get_pch_files()
    applied = 0
    clean = 0
    unknown = 0
    for f in files:
        content = normalize(f.read_text(encoding="utf-8"))
        if normalize(REPLACEMENT_BLOCK) in content:
            applied += 1
        elif normalize(TARGET_BLOCK) in content:
            clean += 1
        else:
            unknown += 1
            print(f"Unknown state: {f}")
    print(f"[pch status] Total: {len(files)}, Applied: {applied}, Clean: {clean}, Unknown: {unknown}")
    return 0 if unknown == 0 else 1

def apply_patch():
    files = get_pch_files()
    count = 0
    for f in files:
        raw = f.read_bytes()
        is_crlf = b"\r\n" in raw
        text = raw.decode("utf-8").replace("\r\n", "\n")
        if REPLACEMENT_BLOCK in text:
            continue
        if TARGET_BLOCK in text:
            new_text = text.replace(TARGET_BLOCK, REPLACEMENT_BLOCK)
            if is_crlf:
                new_text = new_text.replace("\n", "\r\n")
            f.write_bytes(new_text.encode("utf-8"))
            count += 1
        else:
            print(f"Could not find TARGET_BLOCK in {f}")
            return 1
    print(f"[pch apply] Successfully updated {count} files (already applied: {len(files) - count})")
    return 0

def revert_patch():
    files = get_pch_files()
    count = 0
    for f in files:
        raw = f.read_bytes()
        is_crlf = b"\r\n" in raw
        text = raw.decode("utf-8").replace("\r\n", "\n")
        if TARGET_BLOCK in text:
            continue
        if REPLACEMENT_BLOCK in text:
            new_text = text.replace(REPLACEMENT_BLOCK, TARGET_BLOCK)
            if is_crlf:
                new_text = new_text.replace("\n", "\r\n")
            f.write_bytes(new_text.encode("utf-8"))
            count += 1
        else:
            print(f"Could not find REPLACEMENT_BLOCK in {f}")
            return 1
    print(f"[pch revert] Successfully reverted {count} files (already clean: {len(files) - count})")
    return 0

def main():
    parser = argparse.ArgumentParser(description="Patch generated PCH headers for safe indirect dispatch")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Report patch status")
    group.add_argument("--apply", action="store_true", default=True, help="Apply patch (default)")
    group.add_argument("--revert", action="store_true", help="Revert patch")
    args = parser.parse_args()

    if args.status:
        return status()
    elif args.revert:
        return revert_patch()
    else:
        return apply_patch()

if __name__ == "__main__":
    sys.exit(main())

