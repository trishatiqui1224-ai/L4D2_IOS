#!/usr/bin/env python3
"""
Ensures module name extraction and matching handle both POSIX (/) and guest (\\)
path separators. On iOS, fs_entry->absolute_path() uses POSIX paths (/), which
caused utf8_find_base_name_from_guest_path to preserve the entire path as name_,
preventing XModule::Matches and KernelState::GetModule from locating preloaded
or active user modules by name (e.g. "engine_360").

Touches:
    src/system/user_module.cpp
    src/system/xmodule.cpp
    src/system/kernel_state.cpp
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run

FILE_USER_MODULE = "src/system/user_module.cpp"
FILE_XMODULE = "src/system/xmodule.cpp"
FILE_KERNEL_STATE = "src/system/kernel_state.cpp"

ANCHOR_USER_MODULE = '''  path_ = fs_entry->absolute_path();
  name_ = rex::string::utf8_find_base_name_from_guest_path(path_);
'''

PATCHED_USER_MODULE = '''  path_ = fs_entry->absolute_path();
  // LOCAL PATCH - iOS: extract stem supporting both POSIX (/) and guest (\\) path separators
  {
    std::string_view abs_path_sv = path_;
    size_t sep_pos = abs_path_sv.find_last_of("/\\\\");
    std::string_view fn = (sep_pos == std::string_view::npos) ? abs_path_sv : abs_path_sv.substr(sep_pos + 1);
    size_t dot_pos = fn.find_last_of('.');
    name_ = std::string((dot_pos == std::string_view::npos) ? fn : fn.substr(0, dot_pos));
  }
'''

ANCHOR_XMODULE = '''bool XModule::Matches(const std::string_view name) const {
  return rex::string::utf8_equal_case(rex::string::utf8_find_name_from_guest_path(path()), name) ||
         rex::string::utf8_equal_case(this->name(), name) ||
         rex::string::utf8_equal_case(path(), name);
}  // namespace system
'''

PATCHED_XMODULE = '''bool XModule::Matches(const std::string_view name) const {
  if (rex::string::utf8_equal_case(this->name(), name) ||
      rex::string::utf8_equal_case(path(), name)) {
    return true;
  }
  // LOCAL PATCH - iOS: match filename and stem across POSIX (/) and guest (\\) path separators
  std::string_view p = path();
  size_t last_sep = p.find_last_of("/\\\\");
  std::string_view filename = (last_sep == std::string_view::npos) ? p : p.substr(last_sep + 1);
  if (rex::string::utf8_equal_case(filename, name)) {
    return true;
  }
  size_t dot = filename.find_last_of('.');
  std::string_view stem = (dot == std::string_view::npos) ? filename : filename.substr(0, dot);
  if (rex::string::utf8_equal_case(stem, name)) {
    return true;
  }

  size_t name_last_sep = name.find_last_of("/\\\\");
  if (name_last_sep != std::string_view::npos) {
    std::string_view name_fn = name.substr(name_last_sep + 1);
    if (rex::string::utf8_equal_case(filename, name_fn) ||
        rex::string::utf8_equal_case(this->name(), name_fn)) {
      return true;
    }
    size_t name_dot = name_fn.find_last_of('.');
    std::string_view name_stem = (name_dot == std::string_view::npos) ? name_fn : name_fn.substr(0, name_dot);
    if (rex::string::utf8_equal_case(stem, name_stem) ||
        rex::string::utf8_equal_case(this->name(), name_stem)) {
      return true;
    }
  }

  return false;
}
'''

ANCHOR_KERNEL_STATE = '''  // Search user modules under lock
  {
    auto global_lock = global_critical_region_.Acquire();
    for (auto user_module : user_modules_) {
      if (user_module->Matches(path)) {
        return retain_object(user_module.get());
      }
    }
  }
  return nullptr;
'''

PATCHED_KERNEL_STATE = '''  // Search user modules under lock
  {
    auto global_lock = global_critical_region_.Acquire();
    for (auto user_module : user_modules_) {
      if (user_module->Matches(name) || user_module->Matches(path)) {
        return retain_object(user_module.get());
      }
    }
  }
  return nullptr;
'''

BLOCKS = [
    (FILE_USER_MODULE, "extract base name supporting / and \\ separators", ANCHOR_USER_MODULE, PATCHED_USER_MODULE),
    (FILE_XMODULE, "match module stem and filename across / and \\ separators", ANCHOR_XMODULE, PATCHED_XMODULE),
    (FILE_KERNEL_STATE, "search user modules by name and path in GetModule", ANCHOR_KERNEL_STATE, PATCHED_KERNEL_STATE),
]

if __name__ == "__main__":
    sys.exit(run("ios_module_matching", BLOCKS))
