#!/usr/bin/env python3
"""Resolve device-less Xbox paths against game:\\, like a disc launch."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run  # noqa: E402

VFS = "src/filesystem/virtual_file_system.cpp"
ANCHOR = '  auto normalized_path(rex::string::utf8_canonicalize_guest_path(path));'
PATCHED = '''  // LOCAL PATCH - iOS: resolve device-less paths from the disc launch directory
  // and map d: / D: to game: (Xbox 360 DVD drive alias).
  std::string launch_relative_path;
  std::string_view path_to_resolve = path;
  if (path_to_resolve.size() >= 2 && (path_to_resolve[0] == 'd' || path_to_resolve[0] == 'D') && path_to_resolve[1] == ':') {
    launch_relative_path = "game:";
    launch_relative_path.append(path_to_resolve.substr(2));
    path_to_resolve = launch_relative_path;
  } else {
    const bool has_device = path.find(':') != std::string_view::npos;
    if (!has_device) {
      if (!path.empty() && (path.front() == '\\\\' || path.front() == '/')) {
        launch_relative_path = "game:";
        launch_relative_path.append(path);
      } else {
        launch_relative_path = "game:\\\\";
        launch_relative_path.append(path);
      }
      path_to_resolve = launch_relative_path;
    }
  }
  auto normalized_path(rex::string::utf8_canonicalize_guest_path(path_to_resolve));'''

BLOCKS = [(VFS, "resolve relative paths from the game device", ANCHOR, PATCHED)]

if __name__ == "__main__":
    sys.exit(run("ios_relative_paths", BLOCKS))
