#!/usr/bin/env python3
"""
tools/patch_cross_dll_thunks.py
Scans generated recompilation C++ files for cross-DLL import thunk patterns
(direct bl targets that call mtctr r11; bctr or jump to uninitialized r11)
and replaces them with dynamic dispatch through LookupGlobalFunction.
Also validates that src/guest_stubs.cpp contains valid dispatching stubs.
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"
STUBS_FILE = ROOT / "src" / "guest_stubs.cpp"

def patch_generated_recomp_thunks(dry_run=False):
    patched_count = 0
    if not GEN_DIR.exists():
        return 0

    thunk_re = re.compile(
        r'DEFINE_REX_FUNC\((sub_([0-9a-fA-F]+))\)\s*\{([^}]+)\}',
        re.MULTILINE
    )

    for cpp in sorted(GEN_DIR.glob("*/*recomp*.cpp")):
        content = cpp.read_text(encoding="utf-8")
        modified = False

        def replace_thunk(match):
            nonlocal modified, patched_count
            full_fn = match.group(0)
            fn_name = match.group(1)
            hex_addr = match.group(2).upper()
            body = match.group(3)

            # Check if this is an unpatched raw XEX2 thunk (mtctr r11 without r11 assignment, or subfic import descriptor)
            if 'r11.u64' in body and ('ctx.ctr.u64 = ctx.r11.u64' in body or 'mtctr r11' in body):
                # Check if r11 was assigned before ctr
                before_ctr = body.split('ctx.ctr.u64')[0] if 'ctx.ctr.u64' in body else body
                if not re.search(r'ctx\.r11\.[su]64\s*=', before_ctr) or 'subfic' in body or '~ctx.r0' in body:
                    new_body = (
                        f"DEFINE_REX_FUNC({fn_name}) {{\n"
                        f"\tREX_FUNC_PROLOGUE();\n"
                        f"\tPPCFunc* wired = LookupGlobalFunction(base, 0x{hex_addr}u);\n"
                        f"\tif (__builtin_expect(wired != nullptr && wired != &{fn_name}, 1)) {{\n"
                        f"\t\twired(ctx, base);\n"
                        f"\t\treturn;\n"
                        f"\t}}\n"
                        f"\tSafeDispatchIndirect(ctx, base, 0x{hex_addr}u, static_cast<uint32_t>(ctx.lr));\n"
                        f"}}"
                    )
                    modified = True
                    patched_count += 1
                    return new_body
            return full_fn

        new_content = thunk_re.sub(replace_thunk, content)
        if modified and not dry_run:
            cpp.write_text(new_content, encoding="utf-8", newline="\n")

    return patched_count

def check_stubs_file():
    if not STUBS_FILE.exists():
        return False
    content = STUBS_FILE.read_text(encoding="utf-8")
    return "LookupGlobalFunction" in content and "DEFINE_REX_STUB" in content

def main():
    parser = argparse.ArgumentParser(description="Patch and verify cross-DLL import thunk dispatch")
    parser.add_argument("--apply", action="store_true", help="Apply patches to generated sources")
    parser.add_argument("--status", action="store_true", help="Report status of import thunk patching")
    args = parser.parse_args()

    stubs_ok = check_stubs_file()
    patched = patch_generated_recomp_thunks(dry_run=not args.apply)

    if args.status:
        print(f"[cross_dll_thunks] guest_stubs.cpp dispatching: {'OK' if stubs_ok else 'MISSING'}")
        print(f"[cross_dll_thunks] Recomp C++ thunks patched/detected: {patched}")
        return 0

    if args.apply:
        print(f"[cross_dll_thunks] Patched {patched} inlined recomp thunks.")
        print(f"[cross_dll_thunks] guest_stubs.cpp dispatching: {'OK' if stubs_ok else 'MISSING'}")
        return 0

    print("Use --apply to patch or --status to check.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
