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

ANCHOR_TOP = '''#include <rex/system/xtimer.h>

namespace rex::system {
'''

NEW_TOP = '''#include <rex/system/xtimer.h>

#if defined(__GNUC__) || defined(__clang__)
#define REX_CALLBACK_EXPORT __attribute__((visibility("default")))
#elif defined(_MSC_VER)
#define REX_CALLBACK_EXPORT __declspec(dllexport)
#else
#define REX_CALLBACK_EXPORT
#endif

typedef void (*RexDumpRingBufferFn)();
static RexDumpRingBufferFn s_dump_ring_buffer_fn = nullptr;

extern "C" REX_CALLBACK_EXPORT void RexRegisterDumpRingBufferCallback(RexDumpRingBufferFn fn) {
  s_dump_ring_buffer_fn = fn;
}

namespace rex::system {
'''

ANCHOR_EXEC = '''      auto* thread = XThread::GetCurrentThread();
      uint64_t args[] = {module->hmodule_ptr(), 1 /* DLL_PROCESS_ATTACH */, 0};
      uint64_t dllmain_ret =
          function_dispatcher_->Execute(thread->thread_state(), module->entry_point(), args, 3);
      if (static_cast<uint32_t>(dllmain_ret) == 0) {
'''

NEW_EXEC = '''      auto* thread = XThread::GetCurrentThread();
      uint64_t args[] = {module->hmodule_ptr(), 1 /* DLL_PROCESS_ATTACH */, 0};
      REXSYS_INFO("Calling DllMain(0x{:08X}) for {}...", module->entry_point(), module->name());
      fflush(stdout);
      fflush(stderr);
      rex::FlushLogging();

      std::atomic<bool> watchdog_done{false};
      std::thread watchdog([&]() {
        for (int sec = 1; sec <= 10; ++sec) {
          std::this_thread::sleep_for(std::chrono::milliseconds(1000));
          if (watchdog_done.load(std::memory_order_relaxed)) {
            return;
          }
          REXSYS_WARN("[WATCHDOG] DllMain(0x{:08X}) for {} still running after {}s...",
                      module->entry_point(), module->name(), sec);
          if (s_dump_ring_buffer_fn) {
            s_dump_ring_buffer_fn();
          }
          fflush(stdout);
          fflush(stderr);
          rex::FlushLogging();
        }
      });

      uint64_t dllmain_ret =
          function_dispatcher_->Execute(thread->thread_state(), module->entry_point(), args, 3);
      watchdog_done.store(true, std::memory_order_relaxed);
      if (watchdog.joinable()) {
        watchdog.join();
      }

      REXSYS_INFO("DllMain(0x{:08X}) returned 0x{:08X}", module->entry_point(), static_cast<uint32_t>(dllmain_ret));
      fflush(stdout);
      fflush(stderr);
      rex::FlushLogging();
      if (static_cast<uint32_t>(dllmain_ret) == 0) {
'''

BLOCKS = [
    (FILE, "define RexRegisterDumpRingBufferCallback at file scope", ANCHOR_TOP, NEW_TOP),
    (FILE, "log Calling DllMain with watchdog and returned with flush", ANCHOR_EXEC, NEW_EXEC),
]

if __name__ == "__main__":
    sys.exit(run("ios_dllmain_log", BLOCKS))
