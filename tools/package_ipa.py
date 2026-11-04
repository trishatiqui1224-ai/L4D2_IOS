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

    # 1. Ensure Info.plist is present in the app bundle
    dest_plist = dest_app / "Info.plist"
    if not dest_plist.exists():
        plist_candidates = [
            ROOT / "build" / "Info.plist",
            ROOT / "build" / "ios" / "Info.plist",
            ROOT / "ios" / "Info.plist",
        ]
        for p in plist_candidates:
            if p.exists():
                print(f"[package_ipa] Copying missing Info.plist from {p}...")
                shutil.copy2(p, dest_plist)
                break

    # 2. Compile Assets.xcassets or copy AppIcons into the bundle
    xcassets = ROOT / "ios" / "resources" / "Assets.xcassets"
    if xcassets.exists():
        # Try compiling with actool if available
        actool_cmd = shutil.which("actool")
        if not actool_cmd and shutil.which("xcrun"):
            actool_cmd = "xcrun actool"
        
        if actool_cmd:
            try:
                cmd = f"xcrun actool --output-format human-readable-text --notices --warnings --export-dependency-info {temp_payload}/assetcatalog_dependencies --output-partial-info-plist {temp_payload}/assetcatalog_generated_info.plist --app-icon AppIcon --compress-pngs --enable-on-demand-resources NO --target-device iphone --target-device ipad --minimum-deployment-target 16.0 --platform iphoneos --compile '{dest_app}' '{xcassets}'"
                print(f"[package_ipa] Compiling asset catalog with actool...")
                subprocess.run(cmd, shell=True, check=False)
            except Exception as e:
                print(f"[package_ipa] Notice: actool compile skipped: {e}")

        # Also copy raw AppIcon PNGs into the bundle root for sideloaders (TrollStore, AltStore, Sideloadly)
        appicon_dir = xcassets / "AppIcon.appiconset"
        if appicon_dir.exists():
            for icon_file in appicon_dir.glob("*.png"):
                shutil.copy2(icon_file, dest_app / icon_file.name)
            print(f"[package_ipa] Copied raw AppIcon PNGs to {dest_app.name}/")

    # 3. Ensure Frameworks are fully populated with dereferenced binaries
    fw_dir = dest_app / "Frameworks"
    fw_dir.mkdir(parents=True, exist_ok=True)

    # Search for MoltenVK.framework
    mvk_dest = fw_dir / "MoltenVK.framework"
    if not (mvk_dest / "MoltenVK").exists():
        mvk_candidates = [
            ROOT / "build" / "Frameworks" / "MoltenVK.framework",
            ROOT.parent / "rexglue-sdk-ios" / ".nfsc-ios" / "MoltenVK" / "v1.4.1" / "ios-arm64" / "MoltenVK.framework",
            ROOT.parent / "rexglue-sdk-ios" / ".nfsmw-ios" / "MoltenVK" / "v1.4.1" / "ios-arm64" / "MoltenVK.framework",
        ]
        mvk_candidates.extend(ROOT.parent.glob("**/ios-arm64/MoltenVK.framework"))
        for mc in mvk_candidates:
            if (mc / "MoltenVK").exists():
                print(f"[package_ipa] Staging MoltenVK.framework from {mc}...")
                if mvk_dest.exists():
                    shutil.rmtree(mvk_dest)
                shutil.copytree(mc, mvk_dest, symlinks=False)
                break

    # Search for librexruntime.dylib & librexgpu-xenos.dylib
    for dylib_name in ["librexruntime.dylib", "librexgpu-xenos.dylib"]:
        dest_dylib = fw_dir / dylib_name
        if not dest_dylib.exists():
            for f in ROOT.glob(f"**/{dylib_name}"):
                if f.is_file():
                    print(f"[package_ipa] Staging {dylib_name} from {f}...")
                    shutil.copy2(f, dest_dylib)
                    break

    # 4. Ad-hoc codesign every framework and the app bundle
    if shutil.which("codesign"):
        print("[package_ipa] Ad-hoc signing embedded frameworks...")
        for fw_item in fw_dir.iterdir():
            subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(fw_item)], check=False)
        entitlements = ROOT / "ios" / "l4d2recomp.entitlements"
        sign_cmd = ["codesign", "--force", "--sign", "-", "--timestamp=none"]
        if entitlements.exists():
            sign_cmd.extend(["--entitlements", str(entitlements)])
        sign_cmd.append(str(dest_app))
        subprocess.run(sign_cmd, check=False)

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
    parser.add_argument("--app", type=pathlib.Path, default=None, help="Path to .app bundle")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "L4D2Recomp.ipa", help="Output .ipa path")
    args = parser.parse_args()

    app_path = args.app
    if app_path is None or not app_path.is_dir():
        # Auto-detect candidates
        candidates = [
            ROOT / "build" / "L4D2Recomp.app",
            ROOT / "build" / "Release" / "L4D2Recomp.app",
            ROOT / "build" / "Release-iphoneos" / "L4D2Recomp.app",
            ROOT / "build" / "ios" / "L4D2Recomp.app",
            ROOT / "ios" / "build" / "L4D2Recomp.app",
        ]
        for c in candidates:
            if c.is_dir():
                app_path = c
                break

        if app_path is None or not app_path.is_dir():
            for found in (ROOT / "build").glob("**/*.app"):
                if found.is_dir():
                    app_path = found
                    print(f"[package_ipa] Discovered app bundle via glob: {app_path}")
                    break

    if app_path is None or not app_path.is_dir():
        print(f"[ERROR] App bundle L4D2Recomp.app not found in candidates or build tree.")
        sys.exit(1)

    success = package_ipa(app_path, args.out)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()

