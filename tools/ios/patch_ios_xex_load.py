#!/usr/bin/env python3
"""
tools/ios/patch_ios_xex_load.py
Ensures XexLoadImage_entry invokes LoadUserModule(..., call_entry=true) on the active
guest thread, so that recompiled modules preloaded during OnPreLaunchModule execute
their DllMain(DLL_PROCESS_ATTACH) when the guest thread requests them.

Touches:
    src/kernel/xboxkrnl/xboxkrnl_modules.cpp
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run

FILE = "src/kernel/xboxkrnl/xboxkrnl_modules.cpp"

ANCHOR = '''u32 XexLoadImage_entry(mapped_string module_name, u32 module_flags, u32 min_version,
                       mapped_u32 hmodule_ptr) {
  X_STATUS result = X_STATUS_NO_SUCH_FILE;

  uint32_t hmodule = 0;
  {
    // Lookup + load_count++ must be atomic vs XexUnloadImage to prevent
    // resurrecting a module between the read of hmodule and the increment.
    // The fresh-load path can't share this lock: LoadUserModule runs
    // DllMain ATTACH outside the global lock by design.
    auto lock = rex::thread::global_critical_region::AcquireDirect();
    auto module = REX_KERNEL_STATE()->GetModule(module_name.value());
    if (module) {
      hmodule = module->hmodule_ptr();
      auto ldr_data = REX_KERNEL_MEMORY()->TranslateVirtual<X_LDR_DATA_TABLE_ENTRY*>(hmodule);
      ldr_data->load_count++;
      result = X_STATUS_SUCCESS;
    }
  }

  if (!hmodule) {
    auto user_module = REX_KERNEL_STATE()->LoadUserModule(module_name.value());
'''

PATCHED = '''u32 XexLoadImage_entry(mapped_string module_name, u32 module_flags, u32 min_version,
                       mapped_u32 hmodule_ptr) {
  X_STATUS result = X_STATUS_NO_SUCH_FILE;

  uint32_t hmodule = 0;
  // LOCAL PATCH - iOS: Always invoke LoadUserModule with call_entry=true on active guest thread
  // so that preloaded modules execute their deferred DllMain on this thread.
  auto user_module = REX_KERNEL_STATE()->LoadUserModule(module_name.value(), /*call_entry=*/true);
  if (!user_module) {
    auto lock = rex::thread::global_critical_region::AcquireDirect();
    auto existing = REX_KERNEL_STATE()->GetModule(module_name.value());
    if (existing) {
      user_module = REX_KERNEL_STATE()->LoadUserModule(existing->path(), /*call_entry=*/true);
    }
  }

  if (user_module) {
    auto user_module_raw = user_module.release();
    hmodule = user_module_raw->hmodule_ptr();
    auto lock = rex::thread::global_critical_region::AcquireDirect();
    auto ldr_data = REX_KERNEL_MEMORY()->TranslateVirtual<X_LDR_DATA_TABLE_ENTRY*>(hmodule);
    ldr_data->load_count++;
    result = X_STATUS_SUCCESS;
  } else {
    auto lock = rex::thread::global_critical_region::AcquireDirect();
    auto module = REX_KERNEL_STATE()->GetModule(module_name.value());
    if (module) {
      hmodule = module->hmodule_ptr();
      auto ldr_data = REX_KERNEL_MEMORY()->TranslateVirtual<X_LDR_DATA_TABLE_ENTRY*>(hmodule);
      ldr_data->load_count++;
      result = X_STATUS_SUCCESS;
    }
  }
'''

BLOCKS = [
    (FILE, "invoke LoadUserModule with call_entry=true for preloaded modules", ANCHOR, PATCHED),
]

if __name__ == "__main__":
    sys.exit(run("ios_xex_load", BLOCKS))
