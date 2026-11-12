#!/usr/bin/env python3
"""
Log step-by-step Calling DllMain(0x...) and DllMain(0x...) returned 0x... with flush.
Also tracks executed DllMains and triggers deferred DllMain on active guest threads
for modules that were preloaded in OnPreLaunchModule (call_entry=false).

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
#include <condition_variable>
#include <mutex>
#include <unordered_set>

#if defined(_WIN32)
#define REX_CALLBACK_EXPORT __declspec(dllexport)
#elif defined(__GNUC__) || defined(__clang__)
#define REX_CALLBACK_EXPORT __attribute__((visibility("default")))
#else
#define REX_CALLBACK_EXPORT
#endif

typedef void (*RexDumpRingBufferFn)();
static RexDumpRingBufferFn s_dump_ring_buffer_fn = nullptr;

extern "C" REX_CALLBACK_EXPORT void RexRegisterDumpRingBufferCallback(RexDumpRingBufferFn fn) {
  s_dump_ring_buffer_fn = fn;
}

namespace rex::system {
static std::unordered_set<std::string> s_dllmain_called_modules;
static std::unordered_set<uint32_t> s_dllmain_called_entrypoints;
'''

ANCHOR_PRELOAD = '''  {
    auto global_lock = global_critical_region_.Acquire();
    for (auto& existing_module : user_modules_) {
      if (existing_module->path() == path) {
        return existing_module;
      }
    }
    auto [it, inserted] = loading_paths_.emplace(path);
    (void)it;
    if (!inserted) {
      REXSYS_WARN("LoadUserModule: '{}' already being loaded by another thread", path);
      return nullptr;
    }
  }
'''

NEW_PRELOAD = '''  // LOCAL PATCH - iOS: track executed DllMains and execute DllMain on active guest thread for preloaded modules
  object_ref<UserModule> existing_to_call;
  {
    auto global_lock = global_critical_region_.Acquire();
    for (auto& existing_module : user_modules_) {
      if (existing_module->path() == path ||
          existing_module->Matches(raw_name) ||
          existing_module->Matches(path) ||
          existing_module->Matches(name) ||
          existing_module->name() == name) {
        if (call_entry && existing_module->is_dll_module() && existing_module->entry_point()) {
          if (!s_dllmain_called_entrypoints.count(existing_module->entry_point()) &&
              !s_dllmain_called_modules.count(existing_module->path())) {
            s_dllmain_called_entrypoints.insert(existing_module->entry_point());
            s_dllmain_called_modules.insert(existing_module->path());
            existing_to_call = existing_module;
          }
        }
        if (!existing_to_call) {
          return existing_module;
        }
        break;
      }
    }
    if (!existing_to_call) {
      auto [it, inserted] = loading_paths_.emplace(path);
      (void)it;
      if (!inserted) {
        REXSYS_WARN("LoadUserModule: '{}' already being loaded by another thread", path);
        return nullptr;
      }
    }
  }

  if (existing_to_call) {
    if (XThread::IsInThread()) {
      auto* thread = XThread::GetCurrentThread();
      uint64_t args[] = {existing_to_call->hmodule_ptr(), 1 /* DLL_PROCESS_ATTACH */, 0};
      REXSYS_INFO("Calling DllMain(0x{:08X}) for {}...", existing_to_call->entry_point(), existing_to_call->name());
      fflush(stdout);
      fflush(stderr);
      rex::FlushLogging();

      auto watchdog_done = std::make_shared<std::atomic<bool>>(false);
      auto watchdog_mutex = std::make_shared<std::mutex>();
      auto watchdog_cv = std::make_shared<std::condition_variable>();
      std::thread watchdog([watchdog_done, watchdog_mutex, watchdog_cv,
                            entry = existing_to_call->entry_point(), name = existing_to_call->name()]() {
        std::unique_lock<std::mutex> lock(*watchdog_mutex);
        for (int sec = 1; sec <= 10; ++sec) {
          if (watchdog_cv->wait_for(lock, std::chrono::seconds(1), [&] {
                return watchdog_done->load(std::memory_order_acquire);
              })) {
            return;
          }
          REXSYS_WARN("[WATCHDOG] DllMain(0x{:08X}) for {} still running after {}s...",
                      entry, name, sec);
          if (s_dump_ring_buffer_fn) {
            s_dump_ring_buffer_fn();
          }
          fflush(stdout);
          fflush(stderr);
          rex::FlushLogging();
        }
      });

      uint64_t dllmain_ret =
          function_dispatcher_->Execute(thread->thread_state(), existing_to_call->entry_point(), args, 3);
      {
        std::lock_guard<std::mutex> lock(*watchdog_mutex);
        watchdog_done->store(true, std::memory_order_release);
      }
      watchdog_cv->notify_one();
      if (watchdog.joinable()) {
        watchdog.join();
      }

      REXSYS_INFO("DllMain(0x{:08X}) returned 0x{:08X}", existing_to_call->entry_point(), static_cast<uint32_t>(dllmain_ret));
      fflush(stdout);
      fflush(stderr);
      rex::FlushLogging();
      if (static_cast<uint32_t>(dllmain_ret) == 0) {
        REXSYS_ERROR("DllMain(DLL_PROCESS_ATTACH) returned FALSE for '{}'; rolling back load",
                     existing_to_call->name());
        UnloadUserModule(existing_to_call, /*call_entry=*/false);
        return nullptr;
      }
    } else {
      REXSYS_WARN("DllMain(DLL_PROCESS_ATTACH) deferred for '{}': not on a guest thread", existing_to_call->name());
      auto lock = global_critical_region_.Acquire();
      s_dllmain_called_modules.erase(existing_to_call->path());
      s_dllmain_called_entrypoints.erase(existing_to_call->entry_point());
    }
    return existing_to_call;
  }
'''

ANCHOR_EXEC = '''      auto* thread = XThread::GetCurrentThread();
      uint64_t args[] = {module->hmodule_ptr(), 1 /* DLL_PROCESS_ATTACH */, 0};
      uint64_t dllmain_ret =
          function_dispatcher_->Execute(thread->thread_state(), module->entry_point(), args, 3);
      if (static_cast<uint32_t>(dllmain_ret) == 0) {
'''

NEW_EXEC = '''      auto* thread = XThread::GetCurrentThread();
      uint64_t args[] = {module->hmodule_ptr(), 1 /* DLL_PROCESS_ATTACH */, 0};
      s_dllmain_called_modules.insert(module->path());
      s_dllmain_called_entrypoints.insert(module->entry_point());
      REXSYS_INFO("Calling DllMain(0x{:08X}) for {}...", module->entry_point(), module->name());
      fflush(stdout);
      fflush(stderr);
      rex::FlushLogging();

      auto watchdog_done = std::make_shared<std::atomic<bool>>(false);
      auto watchdog_mutex = std::make_shared<std::mutex>();
      auto watchdog_cv = std::make_shared<std::condition_variable>();
      std::thread watchdog([watchdog_done, watchdog_mutex, watchdog_cv,
                            entry = module->entry_point(), name = module->name()]() {
        std::unique_lock<std::mutex> lock(*watchdog_mutex);
        for (int sec = 1; sec <= 10; ++sec) {
          if (watchdog_cv->wait_for(lock, std::chrono::seconds(1), [&] {
                return watchdog_done->load(std::memory_order_acquire);
              })) {
            return;
          }
          REXSYS_WARN("[WATCHDOG] DllMain(0x{:08X}) for {} still running after {}s...",
                      entry, name, sec);
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
      {
        std::lock_guard<std::mutex> lock(*watchdog_mutex);
        watchdog_done->store(true, std::memory_order_release);
      }
      watchdog_cv->notify_one();
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
    (FILE, "execute deferred DllMain for preloaded modules on guest thread", ANCHOR_PRELOAD, NEW_PRELOAD),
    (FILE, "log Calling DllMain with watchdog and returned with flush", ANCHOR_EXEC, NEW_EXEC),
]

if __name__ == "__main__":
    sys.exit(run("ios_dllmain_log", BLOCKS))
