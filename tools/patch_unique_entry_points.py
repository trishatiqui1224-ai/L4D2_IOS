#!/usr/bin/env python3
"""
tools/patch_unique_entry_points.py
Renames each recompiled module's entry point from 'xstart' to 'sub_<ENTRY_ADDR>'
(e.g., sub_82C246E0 for tier0_360, sub_82E21480 for vstdlib_360, sub_836A2B40 for launcher_360,
and sub_82010CB8 for default.xex).

This prevents Apple Clang ld64 from coalescing all 22 recompiled modules' entry points to
default.xex's xstart (0x82010CB8) inside L4D2Game.framework, ensuring each module's real
DllMainCRTStartup / entry point is registered and executed during LoadUserModule.
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"

KNOWN_ENTRIES = {
    "client_360": 0x886A6EF0,
    "datacache_360": 0x832C7980,
    "default": 0x82010CB8,
    "engine_360": 0x86EBDDF0,
    "FileSystem_Stdio_360": 0x8304FB20,
    "GameUI_360": 0x84131310,
    "inputsystem_360": 0x83517740,
    "launcher_360": 0x836A2B40,
    "matchmaking_360": 0x8B0CB8D0,
    "MaterialSystem_360": 0x84993E30,
    "SceneFileCache_360": 0x83A93870,
    "server_360": 0x89DED900,
    "shaderapidx9_360": 0x8538A1C0,
    "SoundEmitterSystem_360": 0x838A3E90,
    "stdshader_dx9_360": 0x85F62D30,
    "StudioRender_360": 0x863DF940,
    "tier0_360": 0x82C246E0,
    "vgui2_360": 0x83C32B20,
    "vguimatsurface_360": 0x84EB3040,
    "vphysics_360": 0x822D7CE0,
    "vscript_360": 0x8484DC60,
    "vstdlib_360": 0x82E21480,
}

def get_module_entry_addr(mod_dir: pathlib.Path) -> int:
    mod_name = mod_dir.name
    if mod_name in KNOWN_ENTRIES:
        return KNOWN_ENTRIES[mod_name]

    init_files = list(mod_dir.glob("*_init.cpp"))
    for init in init_files:
        content = init.read_text(encoding="utf-8")
        m = re.search(r'\{\s*(0x[0-9a-fA-F]{8})\s*,\s*xstart\s*\}', content)
        if m:
            return int(m.group(1), 16)
        m2 = re.search(r'\{\s*(0x[0-9a-fA-F]{8})\s*,\s*sub_([0-9a-fA-F]{8})\s*\}', content)
        if m2 and m2.group(1).upper() == f"0X{m2.group(2).upper()}":
            return int(m2.group(1), 16)
    return 0

def patch_module_entry_points(dry_run: bool = False):
    total_patched_files = 0
    total_replacements = 0
    results = {}

    if not GEN_DIR.exists():
        print(f"[unique_entry_points] generated directory not found: {GEN_DIR}")
        return 0, 0, results

    for mod_name, entry_addr in sorted(KNOWN_ENTRIES.items()):
        mod_dir = GEN_DIR / mod_name
        if not mod_dir.is_dir():
            continue

        hex_str = f"{entry_addr:08X}"
        sub_name = f"sub_{hex_str}"
        mod_replacements = 0
        mod_files_changed = 0

        # Scan all .h and .cpp files in module directory
        for f in sorted(mod_dir.glob("*")):
            if not f.is_file() or f.suffix not in [".h", ".cpp"]:
                continue

            content = f.read_text(encoding="utf-8")
            if "xstart" not in content:
                continue

            new_content, count = re.subn(r'\bxstart\b', sub_name, content)
            if count > 0:
                mod_replacements += count
                mod_files_changed += 1
                if not dry_run:
                    f.write_text(new_content, encoding="utf-8", newline="\n")

        total_replacements += mod_replacements
        total_patched_files += mod_files_changed
        results[mod_name] = (sub_name, mod_replacements, mod_files_changed)

    return total_replacements, total_patched_files, results

def check_status() -> int:
    if not GEN_DIR.exists():
        print(f"[unique_entry_points] generated directory not found: {GEN_DIR}")
        return 1

    all_ok = True
    print("[unique_entry_points] Checking module entry point symbol uniqueness:")
    for mod_name, entry_addr in sorted(KNOWN_ENTRIES.items()):
        mod_dir = GEN_DIR / mod_name
        hex_str = f"{entry_addr:08X}"
        sub_name = f"sub_{hex_str}"

        if not mod_dir.is_dir():
            print(f"  [-] {mod_name:24s}: directory missing")
            all_ok = False
            continue

        # Check for remaining xstart
        has_xstart = False
        has_sub = False
        for f in mod_dir.glob("*"):
            if not f.is_file() or f.suffix not in [".h", ".cpp"]:
                continue
            content = f.read_text(encoding="utf-8")
            if re.search(r'\bxstart\b', content):
                has_xstart = True
            if sub_name in content:
                has_sub = True

        if has_xstart:
            print(f"  [X] {mod_name:24s}: entry STILL contains generic 'xstart' (target 0x{hex_str} -> {sub_name})")
            all_ok = False
        elif has_sub:
            print(f"  [+] {mod_name:24s}: unique entry symbol OK ({sub_name})")
        else:
            print(f"  [?] {mod_name:24s}: neither xstart nor {sub_name} detected")
            all_ok = False

    if all_ok:
        print("[unique_entry_points] ALL 22 modules have unique entry point symbols. No symbol collisions.")
        return 0
    else:
        print("[unique_entry_points] Some modules still have colliding entry points. Run with --apply.")
        return 1

def main():
    parser = argparse.ArgumentParser(description="Rename xstart to unique sub_<ENTRY_ADDR> per module")
    parser.add_argument("--apply", action="store_true", help="Apply unique entry point renaming")
    parser.add_argument("--status", action="store_true", help="Check status of entry point symbols")
    args = parser.parse_args()

    if args.status:
        return check_status()

    if args.apply:
        replacements, files_changed, results = patch_module_entry_points(dry_run=False)
        print(f"[unique_entry_points] Applied patches: {replacements} occurrences replaced across {files_changed} files.")
        for mod, (sub_name, reps, fcount) in results.items():
            if reps > 0:
                print(f"  - {mod:24s} -> {sub_name} ({reps} occurrences in {fcount} files)")
        return check_status()

    # Default to status if neither flag provided
    return check_status()

if __name__ == "__main__":
    sys.exit(main())
