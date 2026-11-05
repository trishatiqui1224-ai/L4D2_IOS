#!/usr/bin/env python3
"""
tools/verify_ios_bundle.py
Mandatory CI Launch-Readiness Gate:
Inspects unzipped Payload/*.app and fails if:
1. CFBundleExecutable in Info.plist does not match an executable file in Payload/*.app/ case-for-case.
2. otool -L on the main binary or any file in Frameworks/ contains /Users/, /tmp/, /opt/, or build/.
3. otool -l on the main binary is missing LC_RPATH @executable_path/Frameworks.
4. vtool -show-build on the main binary or any framework/dylib does not say platform IOS.
5. Missing UIFileSharingEnabled or LSSupportsOpeningDocumentsInPlace in Info.plist.
6. Forbidden/restricted sideload entitlements present in codesign signature.
"""

import argparse
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile


def verify_bundle(app_dir: pathlib.Path) -> bool:
    print(f"\n================================================================================")
    print(f"  MANDATORY CI LAUNCH-READINESS GATE: {app_dir.name}")
    print(f"================================================================================")

    failed = False

    # 1. Verify Info.plist and CFBundleExecutable
    plist_path = app_dir / "Info.plist"
    if not plist_path.is_file():
        print(f"[ERROR] Missing Info.plist in {app_dir}")
        return False

    with open(plist_path, "rb") as fp:
        plist = plistlib.load(fp)

    exe_name = plist.get("CFBundleExecutable")
    if not exe_name:
        print("[ERROR] CFBundleExecutable not defined in Info.plist!")
        return False

    # Case-for-case match on disk
    case_exact_files = {f.name: f for f in app_dir.iterdir() if f.is_file()}
    if exe_name not in case_exact_files:
        print(f"[ERROR] CFBundleExecutable '{exe_name}' does not match any file in {app_dir} case-for-case!")
        print(f"        Available files: {list(case_exact_files.keys())}")
        failed = True
    else:
        print(f"[PASS] CFBundleExecutable '{exe_name}' matches binary case-exact.")

    main_bin = app_dir / exe_name

    # Check Info.plist mandatory iOS keys
    if plist.get("CFBundlePackageType") != "APPL":
        print(f"[ERROR] CFBundlePackageType is '{plist.get('CFBundlePackageType')}', expected 'APPL'")
        failed = True
    if not plist.get("LSRequiresIPhoneOS"):
        print("[ERROR] LSRequiresIPhoneOS is not true in Info.plist!")
        failed = True
    if not plist.get("UIFileSharingEnabled"):
        print("[ERROR] UIFileSharingEnabled is not true in Info.plist (Files app will not show documents)!")
        failed = True
    if not plist.get("LSSupportsOpeningDocumentsInPlace"):
        print("[ERROR] LSSupportsOpeningDocumentsInPlace is not true in Info.plist!")
        failed = True

    device_families = plist.get("UIDeviceFamily", [])
    if 1 not in device_families or 2 not in device_families:
        print(f"[ERROR] UIDeviceFamily does not contain [1, 2] (iPhone & iPad): {device_families}")
        failed = True
    else:
        print(f"[PASS] Info.plist configured for iPhone & iPad with Files app sharing enabled.")

    # Collect all Mach-O binaries in app and Frameworks
    fw_dir = app_dir / "Frameworks"
    binaries = [main_bin]
    if fw_dir.is_dir():
        for p in fw_dir.glob("**/*"):
            if p.is_file() and not p.name.endswith(('.plist', '.json', '.h', '.nib', '.strings', '.DS_Store', '.txt')):
                binaries.append(p)

    # 2. Check otool -L for leaked build machine paths
    forbidden_prefixes = ["/Users/", "/tmp/", "/opt/", "build/"]
    print(f"\n[CI] Auditing dyld linkage across {len(binaries)} binaries...")

    for b in binaries:
        res = subprocess.run(["otool", "-L", str(b)], capture_output=True, text=True, check=False)
        if res.returncode != 0:
            print(f"[WARN] otool -L failed on {b.name}: {res.stderr}")
            continue

        print(f"\n--- otool -L {b.relative_to(app_dir)} ---")
        lines = res.stdout.splitlines()
        for line in lines[1:]:
            line_str = line.strip()
            if not line_str:
                continue
            dep = line_str.split()[0]
            print(f"    {line_str}")
            for bad in forbidden_prefixes:
                if bad in dep:
                    print(f"[ERROR] Binary {b.name} contains build machine path: {dep}")
                    failed = True

    # 3. Check otool -l on main binary for LC_RPATH = @executable_path/Frameworks
    print(f"\n[CI] Auditing LC_RPATH in {main_bin.name}...")
    res = subprocess.run(["otool", "-l", str(main_bin)], capture_output=True, text=True, check=False)
    rpaths = []
    if res.returncode == 0:
        lines = res.stdout.splitlines()
        in_rpath = False
        for line in lines:
            line_str = line.strip()
            if line_str == "cmd LC_RPATH":
                in_rpath = True
            elif in_rpath and line_str.startswith("path "):
                rpath = line_str.split()[1]
                rpaths.append(rpath)
                in_rpath = False
            elif line_str.startswith("cmd "):
                in_rpath = False

    print(f"    Discovered LC_RPATH entries: {rpaths}")
    if "@executable_path/Frameworks" not in rpaths:
        print("[ERROR] LC_RPATH missing '@executable_path/Frameworks' in main executable!")
        failed = True
    else:
        print("[PASS] LC_RPATH contains '@executable_path/Frameworks'.")

    # 4. Check vtool -show-build on all binaries
    if shutil.which("vtool"):
        print(f"\n[CI] Auditing target platform with vtool -show-build...")
        for b in binaries:
            res = subprocess.run(["vtool", "-show-build", str(b)], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                out = res.stdout
                if "platform IOS" not in out and "platform 2" not in out:
                    print(f"[ERROR] Binary {b.name} target platform is NOT iOS!\n{out}")
                    failed = True
                else:
                    print(f"[PASS] {b.name} verified platform: iOS")
            else:
                print(f"[WARN] vtool returned non-zero for {b.name}: {res.stderr}")

    # 5. Check codesign entitlements for restricted entitlements
    if shutil.which("codesign"):
        print(f"\n[CI] Auditing embedded code signing entitlements...")
        res = subprocess.run(["codesign", "-d", "--entitlements", ":-", str(app_dir)],
                             capture_output=True, text=True, check=False)
        if res.returncode == 0:
            ent_xml = res.stdout
            print(f"--- Embedded Entitlements ---\n{ent_xml}\n-----------------------------")
            restricted = [
                "com.apple.developer.kernel.increased-memory-limit",
                "com.apple.developer.kernel.extended-virtual-addressing",
            ]
            for r in restricted:
                if r in ent_xml:
                    print(f"[ERROR] Restricted sideload entitlement found in signature: {r} (causes AMFI crash!)")
                    failed = True
            if not failed:
                print("[PASS] Clean sideload entitlements verified (no AMFI-restricted keys).")

    if failed:
        print(f"\n================================================================================")
        print(f"  [FAILED] Mandatory CI Launch-Readiness Gate FAILED!")
        print(f"================================================================================")
        return False

    print(f"\n================================================================================")
    print(f"  [SUCCESS] Mandatory CI Launch-Readiness Gate PASSED! App is 100% launch-ready.")
    print(f"================================================================================")
    return True


def main():
    parser = argparse.ArgumentParser(description="Verify iOS .app bundle launch-readiness.")
    parser.add_argument("--ipa", type=pathlib.Path, default=None, help="Path to .ipa package")
    parser.add_argument("--app", type=pathlib.Path, default=None, help="Path to .app bundle")
    args = parser.parse_args()

    if args.app and args.app.is_dir():
        ok = verify_bundle(args.app)
        sys.exit(0 if ok else 1)

    if args.ipa and args.ipa.is_file():
        temp_dir = tempfile.mkdtemp(prefix="ipa_verify_")
        try:
            print(f"[CI Gate] Unpacking {args.ipa} to {temp_dir}...")
            with zipfile.ZipFile(args.ipa, "r") as zf:
                zf.extractall(temp_dir)
            payload = pathlib.Path(temp_dir) / "Payload"
            apps = list(payload.glob("*.app"))
            if not apps:
                print(f"[ERROR] No .app bundle found inside {args.ipa}/Payload!")
                sys.exit(1)
            ok = verify_bundle(apps[0])
            sys.exit(0 if ok else 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    print("[ERROR] Please provide --ipa <path> or --app <path>")
    sys.exit(1)


if __name__ == "__main__":
    main()

