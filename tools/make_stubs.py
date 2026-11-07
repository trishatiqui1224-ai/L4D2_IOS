#!/usr/bin/env python3
"""
tools/make_stubs.py
1. Patches recompiled module PCH headers so that Mach-O / ld64 marks all
   runtime helper symbols (__imp__##name) as weak, allowing ld64 to coalesce
   compiler register save/restore helpers (__restvmx_*, __savevmx_*, etc.)
   across static libraries.
2. Scans recompiled modules for uncompiled guest function entry points and
   cross-module import trampolines, and generates weak fallback stubs in
   src/guest_stubs.cpp to satisfy link-time references on Darwin / iOS (ld64).
"""

import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"
OUT_FILE = ROOT / "src" / "guest_stubs.cpp"

def patch_apple_weak_pch():
    """
    On Apple / Darwin (Mach-O ld64), multiple static recompilation libraries contain
    compiler runtime helpers (such as __restvmx_*, __savevmx_*, __restfpr_*, etc.).
    While the wrapper 'name' function is marked weak, __imp__##name must also be marked
    weak so that ld64 can coalesce them across libraries without duplicate symbol errors.
    """
    patched = 0
    old_decl = 'extern "C" void __imp__##name(PPCContext& __restrict, uint8_t*);'
    new_decl = '__attribute__((weak)) extern "C" void __imp__##name(PPCContext& __restrict, uint8_t*);'
    old_def = 'extern "C" void __imp__##name([[maybe_unused]] PPCContext& __restrict ctx, uint8_t* base)'
    new_def = '__attribute__((weak)) extern "C" void __imp__##name([[maybe_unused]] PPCContext& __restrict ctx, uint8_t* base)'

    for pch in GEN_DIR.glob("*/*_pch.h"):
        content = pch.read_text(encoding="utf-8")
        if old_decl in content or old_def in content:
            content = content.replace(old_decl, new_decl).replace(old_def, new_def)
            pch.write_text(content, encoding="utf-8", newline="\n")
            patched += 1
    print(f"[make_stubs] Patched {patched} module PCH files for Darwin weak __imp__ linkage.")

def main():
    if not GEN_DIR.exists():
        print(f"[make_stubs] {GEN_DIR} does not exist. Run tools/generate_code.py first.")
        return 0

    patch_apple_weak_pch()
    try:
        from patch_module_prefixes import patch_module_symbol_prefixes
        patch_module_symbol_prefixes()
    except Exception as e:
        print(f"[make_stubs] Warning: patch_module_symbol_prefixes failed: {e}")

    all_defined = set()
    all_referenced = set()

    for root, dirs, files in os.walk(GEN_DIR):
        for f in files:
            p = os.path.join(root, f)
            if f.endswith('.cpp') and 'recomp' in f:
                with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                    for line in fp:
                        m = re.search(r'DEFINE_REX_FUNC\((sub_[0-9a-fA-F]+)\)', line)
                        if m:
                            all_defined.add(m.group(1))
                        else:
                            for m in re.finditer(r'\b(sub_[0-9a-fA-F]+)\b', line):
                                all_referenced.add(m.group(1))
            elif f.endswith(('.h', '.cpp')):
                with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                    for line in fp:
                        for m in re.finditer(r'\b(sub_[0-9a-fA-F]+)\b', line):
                            all_referenced.add(m.group(1))

    missing = sorted(all_referenced - all_defined)
    print(f"[make_stubs] Found {len(all_defined)} defined guest functions, {len(missing)} uncompiled stubs.")

    lines = [
        "// Auto-generated stubs for uncompiled PowerPC guest function entry points and DLL import thunks.",
        "// These symbols are referenced by PPCFuncMappings and cross-module dispatch tables in Left 4 Dead 2.",
        "#include <cstdint>",
        "",
        "struct PPCContext;",
        "",
        "#if defined(__clang__)",
        "#define DEFINE_REX_STUB(name) \\",
        '    extern "C" __attribute__((weak, noinline)) void __imp__##name([[maybe_unused]] PPCContext& __restrict ctx, [[maybe_unused]] uint8_t* base) {} \\',
        '    extern "C" __attribute__((weak, noinline)) void name([[maybe_unused]] PPCContext& __restrict ctx, [[maybe_unused]] uint8_t* base) { \\',
        "        [[clang::musttail]] return __imp__##name(ctx, base); \\",
        "    }",
        "#elif defined(__GNUC__)",
        "#define DEFINE_REX_STUB(name) \\",
        '    extern "C" __attribute__((weak, noinline)) void __imp__##name([[maybe_unused]] PPCContext& __restrict ctx, [[maybe_unused]] uint8_t* base) {} \\',
        '    extern "C" __attribute__((weak, noinline)) void name([[maybe_unused]] PPCContext& __restrict ctx, [[maybe_unused]] uint8_t* base) { \\',
        "        __imp__##name(ctx, base); \\",
        "    }",
        "#else",
        "#define DEFINE_REX_STUB(name) \\",
        '    extern "C" inline void __imp__##name([[maybe_unused]] PPCContext& __restrict ctx, [[maybe_unused]] uint8_t* base) {} \\',
        '    extern "C" inline void name([[maybe_unused]] PPCContext& __restrict ctx, [[maybe_unused]] uint8_t* base) { \\',
        "        __imp__##name(ctx, base); \\",
        "    }",
        "#endif",
        "",
    ]

    for s in missing:
        lines.append(f"DEFINE_REX_STUB({s})")

    lines.append("")

    with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(lines))

    print(f"[make_stubs] Wrote {len(missing)} stubs to {OUT_FILE}.")

if __name__ == "__main__":
    main()
