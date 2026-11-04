#!/usr/bin/env python3
"""
Where the SDK looks for its libraries on iOS: the GPU plugin and MoltenVK.

    python3 tools/ios/patch_ios_paths.py            apply
    python3 tools/ios/patch_ios_paths.py --status
    python3 tools/ios/patch_ios_paths.py --revert

Touches two SDK files:
    src/core/filesystem_posix.cpp     GetExecutableFolder() on iOS
    src/ui/vulkan/vulkan_instance.cpp MoltenVK.framework as the first candidate


THE PROBLEM: LIVECONTAINER
==========================

The SDK looks for the GPU plugin (librexgpu-xenos.dylib) in
GetExecutableFolder(), which on Apple is the folder of _NSGetExecutablePath().
In a normal app that is the .app. But the app runs inside LiveContainer, which
loads the app's executable INTO ITS OWN PROCESS: _NSGetExecutablePath()
returns LiveContainer's executable, and the plugin would be looked for in ITS
bundle.

Same problem as Android, where /proc/self/exe is app_process, and the same fix
as android_main.cpp (CarpetaDeLasLibrerias): ask dladdr() where THIS library
is loaded. This function lives in librexruntime.dylib, which sits in
<app>.app/Frameworks/, and librexgpu-xenos.dylib and MoltenVK.framework are
right there too (see ios/CMakeLists.txt). So GetExecutableFolder() becomes
that folder, and the plugin loader finds the plugin with no further changes.
It works the same without LiveContainer.

Anything else that uses GetExecutableFolder() (looking for an ISO next to the
executable, say) will look in Frameworks/ and find nothing; on iOS the app
always passes explicit paths (--game_data_root, --user_data_root).


MOLTENVK
========

On macOS the SDK looks for a Vulkan loader (libvulkan) or libMoltenVK.dylib in
an installed Vulkan SDK. On iOS nothing is installed: MoltenVK ships inside the
app as MoltenVK.framework and is loader and driver at once (it exports
vkGetInstanceProcAddr). It goes first in the list, by absolute path.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run  # noqa: E402

# ---------------------------------------------------------------------------
#  src/core/filesystem_posix.cpp
# ---------------------------------------------------------------------------
DLFCN_ANCHOR = '''#if defined(__APPLE__)
#include <mach-o/dyld.h>
#endif
'''
DLFCN_NEW = '''#if defined(__APPLE__)
#include <mach-o/dyld.h>
#endif
// LOCAL PATCH - iOS: GetExecutableFolder() through dladdr (see below).
// Unconditional: rex/platform.h is not included yet here (REX_PLATFORM_IOS
// would read 0), and dlfcn.h exists on every POSIX system.
#include <dlfcn.h>
'''

FOLDER_ANCHOR = '''std::filesystem::path GetExecutableFolder() {
#if REX_PLATFORM_ANDROID
'''
FOLDER_NEW = '''std::filesystem::path GetExecutableFolder() {
#if REX_PLATFORM_IOS
  // LOCAL PATCH - iOS: the folder of THIS library (<app>.app/Frameworks), not
  // the executable's. Inside LiveContainer the process executable is
  // LiveContainer's, not the app's. librexgpu-xenos.dylib and
  // MoltenVK.framework are there too (ios/CMakeLists.txt).
  Dl_info info{};
  if (dladdr(reinterpret_cast<const void*>(&GetExecutableFolder), &info) && info.dli_fname) {
    return std::filesystem::path(info.dli_fname).parent_path();
  }
#endif
#if REX_PLATFORM_ANDROID
'''

USER_FOLDER_ANCHOR = '''std::filesystem::path GetUserFolder() {
  // get preferred data home'''
USER_FOLDER_NEW = '''std::filesystem::path GetUserFolder() {
#if REX_PLATFORM_IOS
  // LOCAL PATCH - iOS: never use ~/.local or ~/.cache; root of sandbox is strictly read-only.
  if (auto xdg = rex::platform::env::get("XDG_DATA_HOME")) {
    return std::filesystem::path(*xdg);
  }
  if (auto home = rex::platform::env::get("HOME")) {
    return std::filesystem::path(*home) / "Documents" / "rex_data";
  }
  return "/private/var/mobile/Documents/rex_data";
#endif
  // get preferred data home'''

# ---------------------------------------------------------------------------
#  src/ui/vulkan/vulkan_instance.cpp
# ---------------------------------------------------------------------------
# After parche_turnip's block, not before it: Turnip anchors on the
# vulkan_moltenvk.h include. With this block between that include and
# Turnip's, re-running the Android patches made Turnip miss its own block and
# insert it again, then this one did too: both ended up duplicated.
INCLUDE_ANCHOR = '''#if REX_PLATFORM_ANDROID && defined(REX_HAS_ADRENOTOOLS)
#include <dlfcn.h>
#include <adrenotools/driver.h>
#endif
'''
INCLUDE_NEW = '''#if REX_PLATFORM_ANDROID && defined(REX_HAS_ADRENOTOOLS)
#include <dlfcn.h>
#include <adrenotools/driver.h>
#endif
// LOCAL PATCH - iOS: GetExecutableFolder()
#if REX_PLATFORM_IOS
#include <rex/filesystem.h>
#endif
'''

MVK_ANCHOR = '''  std::vector<std::filesystem::path> loader_candidates = macos_runtime_paths.loader_candidates;
'''
MVK_NEW = '''  std::vector<std::filesystem::path> loader_candidates = macos_runtime_paths.loader_candidates;
#if REX_PLATFORM_IOS
  // LOCAL PATCH - iOS: MoltenVK ships inside the app, next to librexruntime
  // (GetExecutableFolder() is <app>.app/Frameworks on iOS). Before anything.
  loader_candidates.insert(loader_candidates.begin(),
                           rex::filesystem::GetExecutableFolder() / "MoltenVK.framework" /
                               "MoltenVK");
#endif
'''

# ---------------------------------------------------------------------------
#  src/graphics/vulkan/pipeline_cache.cpp
# ---------------------------------------------------------------------------
SHADER_STORAGE_ANCHOR = '''  auto shader_storage_root = cache_root / "shaders";
  auto shader_storage_shareable_root = shader_storage_root / "shareable";
  if (!std::filesystem::exists(shader_storage_shareable_root)) {
    if (!std::filesystem::create_directories(shader_storage_shareable_root)) {
      REXGPU_ERROR(
          "Failed to create the shareable shader storage directory, persistent "
          "shader storage will be disabled: {}",
          rex::path_to_utf8(shader_storage_shareable_root));
      return;
    }
  }'''
SHADER_STORAGE_NEW = '''  auto shader_storage_root = cache_root / "shaders";
  auto shader_storage_shareable_root = shader_storage_root / "shareable";
  std::error_code storage_ec;
  if (!std::filesystem::exists(shader_storage_shareable_root, storage_ec)) {
    storage_ec.clear();
    if (!std::filesystem::create_directories(shader_storage_shareable_root, storage_ec) && storage_ec) {
      REXGPU_ERROR(
          "Failed to create the shareable shader storage directory ({}), persistent "
          "shader storage will be disabled: {}",
          storage_ec.message(), rex::path_to_utf8(shader_storage_shareable_root));
      return;
    }
  }'''

# ---------------------------------------------------------------------------
#  src/core/filesystem.cpp
# ---------------------------------------------------------------------------
PARENT_FOLDER_ANCHOR = '''bool CreateParentFolder(const std::filesystem::path& path) {
  if (path.has_parent_path()) {
    auto parent_path = path.parent_path();
    if (!std::filesystem::exists(parent_path)) {
      return std::filesystem::create_directories(parent_path);
    }
  }
  return true;
}'''
PARENT_FOLDER_NEW = '''bool CreateParentFolder(const std::filesystem::path& path) {
  if (path.has_parent_path()) {
    auto parent_path = path.parent_path();
    std::error_code ec;
    if (!std::filesystem::exists(parent_path, ec)) {
      ec.clear();
      return std::filesystem::create_directories(parent_path, ec);
    }
  }
  return true;
}'''

# ---------------------------------------------------------------------------
#  src/system/xam/content_manager.cpp
# ---------------------------------------------------------------------------
CONTENT_HEADER_ANCHOR = '''  auto parent_path = header_path.parent_path();

  if (!std::filesystem::exists(parent_path)) {
    if (!std::filesystem::create_directories(parent_path)) {
      return X_ERROR_ACCESS_DENIED;
    }
  }'''
CONTENT_HEADER_NEW = '''  auto parent_path = header_path.parent_path();

  std::error_code parent_ec;
  if (!std::filesystem::exists(parent_path, parent_ec)) {
    parent_ec.clear();
    if (!std::filesystem::create_directories(parent_path, parent_ec) && parent_ec) {
      return X_ERROR_ACCESS_DENIED;
    }
  }'''

CONTENT_PKG1_ANCHOR = '''  if (!std::filesystem::create_directories(package_path)) {'''
CONTENT_PKG1_NEW = '''  std::error_code pkg_ec;
  if (!std::filesystem::create_directories(package_path, pkg_ec) && pkg_ec) {'''

CONTENT_PKG2_ANCHOR = '''  std::filesystem::create_directories(package_path);
'''
CONTENT_PKG2_NEW = '''  std::error_code pkg2_ec;
  std::filesystem::create_directories(package_path, pkg2_ec);
'''

# ---------------------------------------------------------------------------
#  src/system/xam/user_profile.cpp
# ---------------------------------------------------------------------------
USER_PROF_ANCHOR = '''    auto content_dir = kernel_state_->content_manager()->ResolveGameUserContentPath();
    std::filesystem::create_directories(content_dir);'''
USER_PROF_NEW = '''    auto content_dir = kernel_state_->content_manager()->ResolveGameUserContentPath();
    std::error_code prof_ec;
    std::filesystem::create_directories(content_dir, prof_ec);'''

# ---------------------------------------------------------------------------
#  src/filesystem/devices/host_path_entry.cpp
# ---------------------------------------------------------------------------
HOST_PATH_ANCHOR = '''  if (attributes & kFileAttributeDirectory) {
    if (!std::filesystem::create_directories(full_path)) {
      return nullptr;
    }
  }'''
HOST_PATH_NEW = '''  if (attributes & kFileAttributeDirectory) {
    std::error_code dir_ec;
    if (!std::filesystem::create_directories(full_path, dir_ec) && dir_ec) {
      return nullptr;
    }
  }'''

# ---------------------------------------------------------------------------
#  src/core/logging.cpp
# ---------------------------------------------------------------------------
LOG_PATH_ANCHOR = '''std::filesystem::path NextSequentialLogPath(const std::filesystem::path& logs_dir,
                                            std::string_view app_name) {
  std::filesystem::create_directories(logs_dir);'''
LOG_PATH_NEW = '''std::filesystem::path NextSequentialLogPath(const std::filesystem::path& logs_dir,
                                            std::string_view app_name) {
  std::error_code log_ec;
  std::filesystem::create_directories(logs_dir, log_ec);'''

BLOCKS = [
    ("src/core/filesystem_posix.cpp", "include dlfcn.h", DLFCN_ANCHOR, DLFCN_NEW),
    ("src/core/filesystem_posix.cpp", "GetExecutableFolder() is Frameworks/", FOLDER_ANCHOR,
     FOLDER_NEW),
    ("src/core/filesystem_posix.cpp", "GetUserFolder() uses Documents/rex_data on iOS",
     USER_FOLDER_ANCHOR, USER_FOLDER_NEW),
    ("src/ui/vulkan/vulkan_instance.cpp", "include rex/filesystem.h", INCLUDE_ANCHOR,
     INCLUDE_NEW),
    ("src/ui/vulkan/vulkan_instance.cpp", "MoltenVK.framework first", MVK_ANCHOR, MVK_NEW),
    ("src/graphics/vulkan/pipeline_cache.cpp", "exception-safe shader storage create_directories",
     SHADER_STORAGE_ANCHOR, SHADER_STORAGE_NEW),
    ("src/core/filesystem.cpp", "exception-safe CreateParentFolder create_directories",
     PARENT_FOLDER_ANCHOR, PARENT_FOLDER_NEW),
    ("src/system/xam/content_manager.cpp", "exception-safe content header create_directories",
     CONTENT_HEADER_ANCHOR, CONTENT_HEADER_NEW),
    ("src/system/xam/content_manager.cpp", "exception-safe content package create_directories 1",
     CONTENT_PKG1_ANCHOR, CONTENT_PKG1_NEW),
    ("src/system/xam/content_manager.cpp", "exception-safe content package create_directories 2",
     CONTENT_PKG2_ANCHOR, CONTENT_PKG2_NEW),
    ("src/system/xam/user_profile.cpp", "exception-safe user profile create_directories",
     USER_PROF_ANCHOR, USER_PROF_NEW),
    ("src/filesystem/devices/host_path_entry.cpp", "exception-safe host path entry create_directories",
     HOST_PATH_ANCHOR, HOST_PATH_NEW),
    ("src/core/logging.cpp", "exception-safe logging create_directories",
     LOG_PATH_ANCHOR, LOG_PATH_NEW),
]

if __name__ == "__main__":
    sys.exit(run("ios_paths", BLOCKS))
