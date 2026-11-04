#!/usr/bin/env python3
"""
What the SDK's CMake has to do differently when building for iOS.

    python3 tools/ios/patch_ios_cmake.py            apply
    python3 tools/ios/patch_ios_cmake.py --status
    python3 tools/ios/patch_ios_cmake.py --revert

Touches CMakeLists.txt and thirdparty/CMakeLists.txt.

With CMAKE_SYSTEM_NAME=iOS, CMake sets both APPLE and IOS. Almost everything
under APPLE applies (SDL with Metal, the OBJC languages), except:

  - The Vulkan loader and MoltenVK from the submodules. On macOS they are
    built and placed next to the executable. Not on iOS: the desktop loader is
    pointless (no ICDs to choose from, MoltenVK is the only driver), and
    MoltenVK builds with its own Xcode project, not add_subdirectory. The app
    ships the MoltenVK.xcframework from Khronos' release of the SAME version
    the submodule pins (v1.4.1), downloaded by tools/ios/prepare_sdk.py and
    packaged by ios/CMakeLists.txt.

  - REX_PLATFORM_IOS=1 on the compiler command line, like the SDK already does
    with REX_PLATFORM_MAC=1. platform.h defines it too (patch_ios_platform),
    but some files test it before including platform.h (memory_posix.cpp).
    And iOS gets its own output folder, out/ios-arm64, apart from macOS's.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import find_sdk, run  # noqa: E402

MVK_ANCHOR = '''    if(APPLE)
        # Build the loader and MoltenVK revisions shipped by the pinned SDK.
'''
MVK_NEW = '''    # LOCAL PATCH - iOS: neither the loader nor MoltenVK from the submodules;
    # the app ships the MoltenVK.xcframework of the same version
    # (tools/ios/prepare_sdk.py).
    if(APPLE AND NOT IOS AND NOT REX_PLATFORM_IOS)
        # Build the loader and MoltenVK revisions shipped by the pinned SDK.
'''

REQ_ANCHOR = '''    if(APPLE)
        list(APPEND REQUIRED_SUBMODULES vulkan-loader moltenvk)
    endif()
'''
REQ_NEW = '''    if(APPLE AND NOT IOS AND NOT REX_PLATFORM_IOS)
        list(APPEND REQUIRED_SUBMODULES vulkan-loader moltenvk)
    endif()
'''

DEF_ANCHOR = '''        set(REX_PLATFORM "mac-${REX_TARGET_PROCESSOR}")
    endif()
    add_compile_definitions(REX_PLATFORM_MAC=1)
'''
DEF_NEW = '''        set(REX_PLATFORM "mac-${REX_TARGET_PROCESSOR}")
    endif()
    add_compile_definitions(REX_PLATFORM_MAC=1)
    # LOCAL PATCH - iOS: REX_PLATFORM_IOS from the command line too, like
    # REX_PLATFORM_MAC. Some files test it BEFORE including rex/platform.h
    # (memory_posix.cpp), and there only what CMake sets exists. Plus its own
    # output folder (out/ios-arm64), apart from macOS's.
    if(IOS OR REX_PLATFORM_IOS)
        add_compile_definitions(REX_PLATFORM_IOS=1)
        set(REX_PLATFORM "ios-${REX_TARGET_PROCESSOR}")
    endif()
'''

BLOCKS = [
    ("thirdparty/CMakeLists.txt", "no loader or MoltenVK in REQUIRED_SUBMODULES", REQ_ANCHOR,
     REQ_NEW),
    ("thirdparty/CMakeLists.txt", "no loader or MoltenVK from the submodules", MVK_ANCHOR,
     MVK_NEW),
    ("CMakeLists.txt", "REX_PLATFORM_IOS=1 and platform ios-arm64", DEF_ANCHOR, DEF_NEW),
]


def safeguard_vulkan_loader(sdk):
    """Extra safeguard: quote ${SYSTEM_PROCESSOR} and ${CMAKE_SYSTEM_PROCESSOR} in vulkan-loader."""
    loader_cmake = sdk / "thirdparty" / "vulkan-loader" / "loader" / "CMakeLists.txt"
    if loader_cmake.exists():
        txt = loader_cmake.read_text(encoding="utf-8")
        orig = txt
        for var in ["${SYSTEM_PROCESSOR}", "${CMAKE_SYSTEM_PROCESSOR}"]:
            if var in txt:
                tmp = f"___TMP_QUOTED_{var[2:-1]}___"
                txt = txt.replace(f'"{var}"', tmp)
                txt = txt.replace(var, f'"{var}"')
                txt = txt.replace(tmp, f'"{var}"')
        if txt != orig:
            loader_cmake.write_text(txt, encoding="utf-8")
            print("  [ok] ios_cmake: safeguarded vulkan-loader/loader/CMakeLists.txt (quoted processor variables)")


def safeguard_rex_version(sdk):
    """Ensure rex_version.cmake cleanly resolves 0.10.0 without warnings on iOS."""
    ver_cmake = sdk / "cmake" / "rex_version.cmake"
    if ver_cmake.exists():
        txt = ver_cmake.read_text(encoding="utf-8")
        old_warn = 'message(WARNING\n            "rex_compute_version: no v* tag reachable from HEAD.'
        if old_warn in txt:
            new_warn = 'set(${out_var} "0.10.0" PARENT_SCOPE)\n        return()\n        message(DEBUG\n            "rex_compute_version: no v* tag reachable from HEAD.'
            txt = txt.replace(old_warn, new_warn)
            ver_cmake.write_text(txt, encoding="utf-8")
            print("  [ok] ios_cmake: safeguarded rex_version.cmake (clean 0.10.0 fallback)")


if __name__ == "__main__":
    ret = run("ios_cmake", BLOCKS)
    if ret == 0 and "--revert" not in sys.argv:
        try:
            sdk = find_sdk("thirdparty/CMakeLists.txt")
            safeguard_vulkan_loader(sdk)
            safeguard_rex_version(sdk)
        except Exception as e:
            print(f"  [WARN] safeguard error: {e}")
    sys.exit(ret)
