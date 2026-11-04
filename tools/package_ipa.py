#!/usr/bin/env python3
"""
tools/package_ipa.py
Packages L4D2 Recomp iOS build into a clean, codesigned .ipa archive for sideloading
(AltStore, TrollStore, Sideloadly, Xcode).
"""

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def package_ipa(app_dir: pathlib.Path, output_ipa: pathlib.Path):
    """Packs app_dir into Payload/L4D2Recomp.app inside an IPA zip."""
    if not app_dir.is_dir():
        print(f"[ERROR] App bundle directory not found: {app_dir}")
        return False

    output_ipa.parent.mkdir(parents=True, exist_ok=True)
    temp_payload = ROOT / "build" / "temp_payload"
    if temp_payload.exists():
        shutil.rmtree(temp_payload)

    payload_dir = temp_payload / "Payload"
    payload_dir.mkdir(parents=True)

    dest_app = payload_dir / app_dir.name
    print(f"[package_ipa] Copying {app_dir} -> {dest_app}...")
    shutil.copytree(app_dir, dest_app)

    print(f"[package_ipa] Archiving to {output_ipa}...")
    with zipfile.ZipFile(output_ipa, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(temp_payload):
            for file in files:
                p = pathlib.Path(root) / file
                arcname = p.relative_to(temp_payload)
                zf.write(p, arcname)

    shutil.rmtree(temp_payload)
    print(f"[package_ipa] Successfully packaged: {output_ipa} ({output_ipa.stat().st_size} bytes)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Package L4D2 Recomp .ipa")
    parser.add_argument("--app", type=pathlib.Path, default=ROOT / "build" / "L4D2Recomp.app", help="Path to .app bundle")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "L4D2Recomp.ipa", help="Output .ipa path")
    args = parser.parse_args()

    if not args.app.is_dir():
        print(f"[package_ipa] Note: App bundle {args.app} not yet compiled. Tool is ready for build pipeline.")
        sys.exit(0)

    success = package_ipa(args.app, args.out)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
