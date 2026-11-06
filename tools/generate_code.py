#!/usr/bin/env python3
"""Restore the checked-in cache of generated C++ recompilation sources."""

import argparse
import os
import pathlib
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"
TAR_FILE = ROOT / "gen.tar.gz"

MODULES = (
    "default", "engine_360", "client_360", "server_360",
    "MaterialSystem_360", "shaderapidx9_360", "stdshader_dx9_360",
    "StudioRender_360", "vphysics_360", "SoundEmitterSystem_360",
    "datacache_360", "SceneFileCache_360", "vgui2_360",
    "vguimatsurface_360", "inputsystem_360", "FileSystem_Stdio_360",
    "vstdlib_360", "tier0_360", "launcher_360", "GameUI_360",
    "vscript_360", "matchmaking_360",
)

def unpack_cache():
    if not TAR_FILE.exists():
        print(f"[ERROR] Cache archive not found: {TAR_FILE}")
        return False
        
    print(f"[generate_code] Unpacking {TAR_FILE} ({TAR_FILE.stat().st_size} bytes) -> {GEN_DIR}...")
    with tarfile.open(TAR_FILE, "r:gz") as tar:
        if hasattr(tarfile, 'data_filter'):
            tar.extractall(ROOT, filter='data')
        else:
            tar.extractall(ROOT)
            
    for m in MODULES:
        p = GEN_DIR / m / "sources.cmake"
        if not p.exists():
            print(f"[ERROR] Expected module source list missing: {p}")
            return False
            
    print(f"[generate_code] Successfully restored all {len(MODULES)} recompiled Source Engine modules into {GEN_DIR}!")
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--unpack-cache", action="store_true", help="Unpack pre-generated gen.tar.gz")
    args = parser.parse_args()
    
    if args.unpack_cache or not (GEN_DIR / "engine_360" / "sources.cmake").exists():
        if not unpack_cache():
            sys.exit(1)
    else:
        print("[generate_code] Generated sources already present.")

if __name__ == "__main__":
    main()

