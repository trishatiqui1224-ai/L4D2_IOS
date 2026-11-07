#!/usr/bin/env python3
"""Patch symbol prefixes for static recompilation modules."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"

TARGETS = [
    ("launcher_360", "launcher"),
    ("GameUI_360", "gameui"),
    ("vscript_360", "vscript"),
]

def patch_module_symbol_prefixes():
    patched_count = 0
    for mod_dir, prefix in TARGETS:
        init_cpp = GEN_DIR / mod_dir / f"l4d2_{prefix}_init.cpp"
        pch_h = GEN_DIR / mod_dir / f"l4d2_{prefix}_pch.h"

        if init_cpp.exists():
            content = init_cpp.read_text(encoding="utf-8")
            orig = content
            content = content.replace("const rex::PPCImageInfo PPCImageConfig =", f"const rex::PPCImageInfo l4d2_{prefix}_PPCImageConfig =")
            content = content.replace(".func_mappings = PPCFuncMappings,", f".func_mappings = l4d2_{prefix}_PPCFuncMappings,")
            content = content.replace("PPCFuncMapping PPCFuncMappings[] =", f"PPCFuncMapping l4d2_{prefix}_PPCFuncMappings[] =")
            if content != orig:
                init_cpp.write_text(content, encoding="utf-8", newline="\n")
                patched_count += 1
                print(f"[patch_prefixes] Patched {init_cpp}")

        if pch_h.exists():
            content = pch_h.read_text(encoding="utf-8")
            orig = content
            content = content.replace("extern const rex::PPCImageInfo PPCImageConfig;", f"extern const rex::PPCImageInfo l4d2_{prefix}_PPCImageConfig;")
            content = content.replace("extern PPCFuncMapping PPCFuncMappings[];", f"extern PPCFuncMapping l4d2_{prefix}_PPCFuncMappings[];")
            if content != orig:
                pch_h.write_text(content, encoding="utf-8", newline="\n")
                patched_count += 1
                print(f"[patch_prefixes] Patched {pch_h}")

    print(f"[patch_prefixes] Finished. Patched {patched_count} files.")
    return patched_count

if __name__ == "__main__":
    patch_module_symbol_prefixes()
