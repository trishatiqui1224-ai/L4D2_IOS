#!/usr/bin/env python3
"""
Log step-by-step Calling DllMain(0x...) and DllMain(0x...) returned 0x... with flush.

Touches:
    src/system/kernel_state.cpp
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run

FILE = "src/system/kernel_state.cpp"

ANCHOR = '''      auto* thread = XThread::GetCurrentThread();
      uint64_t args[] = {module->hmodule_ptr(), 1 /* DLL_PROCESS_ATTACH */, 0};
      uint64_t dllmain_ret =
          function_dispatcher_->Execute(thread->thread_state(), module->entry_point(), args, 3);
      if (static_cast<uint32_t>(dllmain_ret) == 0) {
'''

NEW = '''      auto* thread = XThread::GetCurrentThread();
      uint64_t args[] = {module->hmodule_ptr(), 1 /* DLL_PROCESS_ATTACH */, 0};
      REXSYS_INFO("Calling DllMain(0x{:08X}) for {}...", module->entry_point(), module->name());
      fflush(stdout);
      fflush(stderr);
      uint64_t dllmain_ret =
          function_dispatcher_->Execute(thread->thread_state(), module->entry_point(), args, 3);
      REXSYS_INFO("DllMain(0x{:08X}) returned 0x{:08X}", module->entry_point(), static_cast<uint32_t>(dllmain_ret));
      fflush(stdout);
      fflush(stderr);
      if (static_cast<uint32_t>(dllmain_ret) == 0) {
'''

BLOCKS = [
    (FILE, "log Calling DllMain and returned with flush", ANCHOR, NEW),
]

if __name__ == "__main__":
    sys.exit(run("ios_dllmain_log", BLOCKS))

