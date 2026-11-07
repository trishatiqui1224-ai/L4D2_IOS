#!/usr/bin/env python3
"""Fail CI if a required XEX has no compiled dispatcher mappings."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "generated"

# Keep in sync with L4D2_MODULE_SPECS in ios/CMakeLists.txt.
MODULE_DIRS = (
    "default", "engine_360", "client_360", "server_360",
    "MaterialSystem_360", "shaderapidx9_360", "stdshader_dx9_360",
    "StudioRender_360", "vphysics_360", "SoundEmitterSystem_360",
    "datacache_360", "SceneFileCache_360", "vgui2_360",
    "vguimatsurface_360", "inputsystem_360", "FileSystem_Stdio_360",
    "vstdlib_360", "tier0_360", "launcher_360", "GameUI_360",
    "vscript_360", "matchmaking_360",
)

REQUIRED_FUNCTIONS = {
    "default": (0x82010CB8,),
    "tier0_360": (0x82C246E0,),
    "vstdlib_360": (0x82E21480,),
    "launcher_360": (0x836A2B40, 0x836940A0),
}


def main() -> int:
    errors = []
    cmake = (ROOT / "ios" / "CMakeLists.txt").read_text(encoding="utf-8")
    for module in MODULE_DIRS:
        spec_dir = f":{module}:"
        if spec_dir not in cmake:
            errors.append(f"{module}: missing from ios/CMakeLists.txt module specs")
        module_dir = GENERATED / module
        if not (module_dir / "sources.cmake").is_file():
            errors.append(f"{module}: generated sources are missing ({module_dir.relative_to(ROOT)})")

    # Verify that every module defines its unique l4d2_<prefix>_PPCImageConfig
    for spec in re.findall(r'"([a-zA-Z0-9_]+:[a-zA-Z0-9_]+:[a-zA-Z0-9_]+)"', cmake):
        _, dir_name, prefix = spec.split(":")
        init_file = GENERATED / dir_name / f"l4d2_{prefix}_init.cpp"
        if init_file.is_file():
            content = init_file.read_text(encoding="utf-8")
            if f"l4d2_{prefix}_PPCImageConfig" not in content:
                errors.append(f"{dir_name}: missing symbol l4d2_{prefix}_PPCImageConfig in {init_file.name}")
        else:
            errors.append(f"{dir_name}: missing init file {init_file.name}")

    for module, addresses in REQUIRED_FUNCTIONS.items():
        # The generated prefixes don't always match the module directory name.
        prefix = {
            "default": "default", "tier0_360": "tier0", "vstdlib_360": "vstdlib",
            "launcher_360": "launcher",
        }[module]
        init_file = GENERATED / module / f"l4d2_{prefix}_init.cpp"
        source = init_file.read_text(encoding="utf-8") if init_file.is_file() else ""
        for address in addresses:
            pattern = rf"\{{\s*0x{address:08X}\s*,"
            if not re.search(pattern, source, re.IGNORECASE):
                errors.append(f"{module}: no compiled PPC mapping for 0x{address:08X}")

    game_entry = (ROOT / "ios" / "src" / "game_entry.mm").read_text(encoding="utf-8")
    if "config.register_modules = &RegisterL4D2StaticModules" not in game_entry:
        errors.append("entrypoint PPCImageInfo does not register the static module callback")
    ios_main = (ROOT / "ios" / "src" / "ios_main.mm").read_text(encoding="utf-8")
    if '"--ios_iso_stream=true"' not in ios_main:
        errors.append("iOS launch arguments omit --ios_iso_stream=true")
    if '"--resolution=1280x720"' not in ios_main:
        errors.append("iOS launch arguments do not specify WxH resolution")
    stack_patch = (ROOT / "tools" / "ios" / "patch_ios_host_stack.py").read_text(encoding="utf-8")
    sdk_prep = (ROOT / "tools" / "ios" / "prepare_sdk.py").read_text(encoding="utf-8")
    if "8 * 1024 * 1024" not in stack_patch or '"patch_ios_host_stack"' not in sdk_prep:
        errors.append("8 MiB host thread stack patch is missing or not applied by SDK preparation")
    if '"patch_ios_relative_paths"' not in sdk_prep:
        errors.append("relative-path VFS patch is not applied by SDK preparation")

    if errors:
        print("[dispatch-check] Required static dispatcher coverage is incomplete:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("[dispatch-check] All 22 XEX module source sets and required startup mappings are present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
