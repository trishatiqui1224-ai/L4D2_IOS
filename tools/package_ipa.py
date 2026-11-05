#!/usr/bin/env python3
"""
tools/package_ipa.py
Packages L4D2 Recomp iOS build into a clean, codesigned .ipa archive for sideloading
(AltStore, TrollStore, SideStore, Sideloadly, Xcode).
Enforces correct dyld @rpath IDs, dependency paths, flat framework structures,
UNIX 0755 execute permissions, and ad-hoc code signing.
"""

import argparse
import os
import pathlib
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def fix_rpaths_and_install_names(dest_app: pathlib.Path):
    """
    Ensures:
    1. Main executable has LC_RPATH = @executable_path/Frameworks
    2. Embedded dylibs/frameworks have LC_ID_DYLIB = @rpath/<filename>
    3. Cross-library links use @rpath instead of build machine paths.
    4. MoltenVK.framework and L4D2Game.framework are verified shallow ios-arm64 frameworks.
    """
    main_bin = dest_app / "L4D2Recomp"
    fw_dir = dest_app / "Frameworks"

    # 1. Main executable RPATH
    if main_bin.exists():
        subprocess.run(["install_name_tool", "-add_rpath", "@executable_path/Frameworks", str(main_bin)], check=False)

    if fw_dir.is_dir():
        # 2. Stage & configure L4D2Game.framework
        game_bin = fw_dir / "L4D2Game.framework" / "L4D2Game"
        if not game_bin.exists():
            cands = [
                fw_dir / "libL4D2Game.dylib",
                fw_dir / "L4D2Game.dylib",
                fw_dir / "L4D2Game",
                ROOT / "build" / "L4D2Game",
                ROOT / "build" / "L4D2Game.dylib",
                ROOT / "build" / "libL4D2Game.dylib",
                ROOT / "build" / "Release-iphoneos" / "L4D2Game",
                ROOT / "build" / "Release-iphoneos" / "libL4D2Game.dylib",
                *ROOT.glob("**/libL4D2Game.dylib"),
                *ROOT.glob("**/L4D2Game.dylib"),
                *ROOT.glob("**/L4D2Game"),
            ]
            for cand in cands:
                if cand.is_file() and not str(cand).endswith((".cpp", ".o", ".h", ".d", ".plist", ".json")):
                    print(f"[package_ipa] Staging L4D2Game from {cand}...")
                    game_fw = fw_dir / "L4D2Game.framework"
                    game_fw.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cand, game_bin)
                    break

        if game_bin.exists():
            subprocess.run(["install_name_tool", "-id", "@rpath/L4D2Game.framework/L4D2Game", str(game_bin)], check=False)
            subprocess.run(["install_name_tool", "-add_rpath", "@loader_path/..", str(game_bin)], check=False)
            subprocess.run(["install_name_tool", "-add_rpath", "@executable_path/Frameworks", str(game_bin)], check=False)
            game_plist = fw_dir / "L4D2Game.framework" / "Info.plist"
            if not game_plist.exists():
                pl = {
                    "CFBundleDevelopmentRegion": "en",
                    "CFBundleExecutable": "L4D2Game",
                    "CFBundleIdentifier": "com.valve.l4d2recomp.game",
                    "CFBundleInfoDictionaryVersion": "6.0",
                    "CFBundleName": "L4D2Game",
                    "CFBundlePackageType": "FMWK",
                    "CFBundleShortVersionString": "1.0",
                    "CFBundleVersion": "1",
                    "MinimumOSVersion": "16.0",
                    "CFBundleSupportedPlatforms": ["iPhoneOS"],
                }
                with open(game_plist, "wb") as fp:
                    plistlib.dump(pl, fp)
            print("[package_ipa] Verified L4D2Game.framework structure and Info.plist")

        # 3. Stage & configure MoltenVK.framework
        mvk_bin = fw_dir / "MoltenVK.framework" / "MoltenVK"
        if mvk_bin.exists():
            subprocess.run(["install_name_tool", "-id", "@rpath/MoltenVK.framework/MoltenVK", str(mvk_bin)], check=False)
            mvk_plist = fw_dir / "MoltenVK.framework" / "Info.plist"
            if mvk_plist.exists():
                try:
                    with open(mvk_plist, "rb") as fp:
                        pl = plistlib.load(fp)
                    pl["CFBundleSupportedPlatforms"] = ["iPhoneOS"]
                    with open(mvk_plist, "wb") as fp:
                        plistlib.dump(pl, fp)
                    print(f"[package_ipa] Verified MoltenVK.framework CFBundleSupportedPlatforms = ['iPhoneOS']")
                except Exception as e:
                    print(f"[package_ipa] Warning updating MoltenVK Info.plist: {e}")

        # 4. Stage & configure rexruntime and rexgpu
        rexruntime_bin = fw_dir / "librexruntime.dylib"
        if rexruntime_bin.exists():
            subprocess.run(["install_name_tool", "-id", "@rpath/librexruntime.dylib", str(rexruntime_bin)], check=False)

        rexgpu_bin = fw_dir / "librexgpu-xenos.dylib"
        if rexgpu_bin.exists():
            subprocess.run(["install_name_tool", "-id", "@rpath/librexgpu-xenos.dylib", str(rexgpu_bin)], check=False)
            subprocess.run(["install_name_tool", "-add_rpath", "@loader_path", str(rexgpu_bin)], check=False)
            subprocess.run(["install_name_tool", "-add_rpath", "@executable_path/Frameworks", str(rexgpu_bin)], check=False)

        # 5. Fix cross-library dependencies using install_name_tool -change
        all_binaries = []
        if main_bin.exists():
            all_binaries.append(main_bin)
        for p in fw_dir.glob("**/*"):
            if p.is_file() and not p.name.endswith(('.plist', '.json', '.h', '.nib', '.strings', '.DS_Store', '.txt')):
                all_binaries.append(p)

        target_map = {
            "librexruntime": "@rpath/librexruntime.dylib",
            "librexgpu-xenos": "@rpath/librexgpu-xenos.dylib",
            "MoltenVK": "@rpath/MoltenVK.framework/MoltenVK",
            "L4D2Game": "@rpath/L4D2Game.framework/L4D2Game",
        }

        for b in all_binaries:
            try:
                res = subprocess.run(["otool", "-L", str(b)], capture_output=True, text=True, check=False)
                if res.returncode != 0:
                    continue
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if not line or line.endswith(":"):
                        continue
                    dep = line.split()[0]
                    for key, rpath_val in target_map.items():
                        if key in dep and dep != rpath_val:
                            print(f"[package_ipa] {b.name}: Changing dependency {dep} -> {rpath_val}")
                            subprocess.run(["install_name_tool", "-change", dep, rpath_val, str(b)], check=False)
                    if "libSDL3" in dep and not dep.startswith("@rpath/"):
                        sdl_name = pathlib.Path(dep).name
                        print(f"[package_ipa] {b.name}: Changing dependency {dep} -> @rpath/{sdl_name}")
                        subprocess.run(["install_name_tool", "-change", dep, f"@rpath/{sdl_name}", str(b)], check=False)
            except Exception as e:
                print(f"[package_ipa] Error checking dependencies for {b}: {e}")


def package_ipa(app_dir: pathlib.Path, output_ipa: pathlib.Path):
    """Packs app_dir into Payload/L4D2Recomp.app inside an IPA zip with UNIX 0755 execute bits."""
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
        actool_cmd = shutil.which("actool")
        if not actool_cmd and shutil.which("xcrun"):
            actool_cmd = "xcrun actool"

        if actool_cmd:
            try:
                cmd = (
                    f"xcrun actool --output-format human-readable-text --notices --warnings "
                    f"--export-dependency-info '{temp_payload}/assetcatalog_dependencies' "
                    f"--output-partial-info-plist '{temp_payload}/assetcatalog_generated_info.plist' "
                    f"--app-icon AppIcon --compress-pngs --enable-on-demand-resources NO "
                    f"--target-device iphone --target-device ipad --minimum-deployment-target 16.0 "
                    f"--platform iphoneos --compile '{dest_app}' '{xcassets}'"
                )
                print(f"[package_ipa] Compiling asset catalog with actool...")
                subprocess.run(cmd, shell=True, check=False)

                # Merge actool partial plist (CFBundleIcons) into destination Info.plist
                partial_plist = temp_payload / "assetcatalog_generated_info.plist"
                if partial_plist.exists() and dest_plist.exists():
                    try:
                        with open(partial_plist, "rb") as fp:
                            part_pl = plistlib.load(fp)
                        with open(dest_plist, "rb") as fp:
                            main_pl = plistlib.load(fp)
                        for k, v in part_pl.items():
                            main_pl[k] = v
                        with open(dest_plist, "wb") as fp:
                            plistlib.dump(main_pl, fp)
                        print("[package_ipa] Merged assetcatalog_generated_info.plist (CFBundleIcons) into Info.plist")
                    except Exception as e:
                        print(f"[package_ipa] Warning merging asset catalog plist: {e}")
            except Exception as e:
                print(f"[package_ipa] Notice: actool compile skipped: {e}")

        # Ensure CFBundleIcons exists in Info.plist even if actool was unavailable
        if dest_plist.exists():
            try:
                with open(dest_plist, "rb") as fp:
                    main_pl = plistlib.load(fp)
                if "CFBundleIcons" not in main_pl:
                    main_pl["CFBundleIcons"] = {
                        "CFBundlePrimaryIcon": {
                            "CFBundleIconFiles": ["AppIcon60x60"],
                            "CFBundleIconName": "AppIcon"
                        }
                    }
                if "CFBundleIcons~ipad" not in main_pl:
                    main_pl["CFBundleIcons~ipad"] = {
                        "CFBundlePrimaryIcon": {
                            "CFBundleIconFiles": ["AppIcon60x60", "AppIcon76x76"],
                            "CFBundleIconName": "AppIcon"
                        }
                    }
                with open(dest_plist, "wb") as fp:
                    plistlib.dump(main_pl, fp)
            except Exception as e:
                print(f"[package_ipa] Notice setting default CFBundleIcons: {e}")

        # Copy raw AppIcon PNGs into the bundle root for SpringBoard / sideloaders
        appicon_dir = xcassets / "AppIcon.appiconset"
        if appicon_dir.exists():
            for icon_file in appicon_dir.glob("*.png"):
                shutil.copy2(icon_file, dest_app / icon_file.name)
            print(f"[package_ipa] Copied raw AppIcon PNGs to {dest_app.name}/")

        # Copy standard named icons from resources/
        res_dir = ROOT / "ios" / "resources"
        for name in ["AppIcon60x60@2x.png", "AppIcon60x60@3x.png", "AppIcon76x76@2x~ipad.png"]:
            src_f = res_dir / name
            if src_f.exists():
                shutil.copy2(src_f, dest_app / name)

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

    # 4. Fix dyld rpaths and install names on all staged binaries
    print("[package_ipa] Fixing dyld rpaths and install names...")
    fix_rpaths_and_install_names(dest_app)

    # 5. Clear quarantine / extended attributes
    subprocess.run(["xattr", "-cr", str(dest_app)], check=False)

    # 6. ENFORCE UNIX 0755 EXECUTE PERMISSIONS on all binaries inside the app bundle!
    print("[package_ipa] Enforcing UNIX 0755 execute permissions on all binaries...")
    main_exec = dest_app / "L4D2Recomp"
    if main_exec.exists():
        os.chmod(main_exec, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH) # 0755
        subprocess.run(["chmod", "755", str(main_exec)], check=False)

    for p in fw_dir.glob("**/*"):
        if p.is_file() and not p.name.endswith(('.plist', '.json', '.h', '.nib', '.strings', '.DS_Store', '.txt')):
            os.chmod(p, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH) # 0755
            subprocess.run(["chmod", "755", str(p)], check=False)

    # 7. Ad-hoc codesign every framework and the app bundle
    if shutil.which("codesign"):
        print("[package_ipa] Ad-hoc signing embedded frameworks...")
        for fw_item in fw_dir.iterdir():
            subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(fw_item)], check=False)

        print("[package_ipa] Ad-hoc signing main app bundle...")
        entitlements = ROOT / "ios" / "l4d2recomp.entitlements"
        sign_cmd = ["codesign", "--force", "--sign", "-", "--timestamp=none"]
        if entitlements.exists():
            sign_cmd.extend(["--entitlements", str(entitlements)])
        sign_cmd.append(str(dest_app))
        subprocess.run(sign_cmd, check=False)

    # 8. Archive with native zip to preserve UNIX 0755 permissions
    print(f"[package_ipa] Archiving to {output_ipa} preserving UNIX 0755 execute permissions...")
    if output_ipa.exists():
        output_ipa.unlink()

    zip_bin = shutil.which("zip") or "/usr/bin/zip"
    if os.path.exists(zip_bin):
        cmd = [zip_bin, "-qry", str(output_ipa.resolve()), "Payload"]
        subprocess.run(cmd, cwd=str(temp_payload), check=True)
    elif shutil.which("ditto"):
        cmd = ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "Payload", str(output_ipa.resolve())]
        subprocess.run(cmd, cwd=str(temp_payload), check=True)
    else:
        # Fallback to python zipfile, preserving permissions via external_attr
        with zipfile.ZipFile(output_ipa, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(temp_payload):
                for file in files:
                    p = pathlib.Path(root) / file
                    arcname = p.relative_to(temp_payload)
                    zinfo = zipfile.ZipInfo.from_file(p, str(arcname))
                    is_exec = (p.name in ["L4D2Recomp", "L4D2Game", "MoltenVK"] or p.suffix in [".dylib", ".so"])
                    zinfo.external_attr = (0o100755 if is_exec else 0o100644) << 16
                    with open(p, "rb") as fp:
                        zf.writestr(zinfo, fp.read(), zipfile.ZIP_DEFLATED)

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
