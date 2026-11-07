#!/usr/bin/env python3
"""Pack generated/ directory into gen.tar.gz deterministically."""

import os
import pathlib
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"
TAR_FILE = ROOT / "gen.tar.gz"

def pack():
    if not GEN_DIR.exists():
        raise SystemExit(f"Error: {GEN_DIR} does not exist!")

    print(f"[pack] Creating {TAR_FILE} from {GEN_DIR}...")
    temp_tar = ROOT / "gen.tar.gz.tmp"
    with tarfile.open(temp_tar, "w:gz", compresslevel=6) as tar:
        tar.add(GEN_DIR, arcname="generated")

    if TAR_FILE.exists():
        TAR_FILE.unlink()
    temp_tar.rename(TAR_FILE)
    print(f"[pack] Finished! gen.tar.gz size: {TAR_FILE.stat().st_size} bytes")

if __name__ == "__main__":
    pack()
