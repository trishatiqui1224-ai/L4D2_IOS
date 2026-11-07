#!/usr/bin/env python3
"""
Stop storing function tables inside guest RAM (image_end + code_size * 2).
Uses a unified host function table (g_global_func_table) and fixes the
[84800000, 849275F0) overlap error that dropped MaterialSystem_360.dll.
Also skips the {0, nullptr} sentinel in SetFunction cleanly.

Touches:
    src/system/function_dispatcher.cpp
    src/system/xmemory.cpp
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run

FILE_DISPATCHER = "src/system/function_dispatcher.cpp"
FILE_MEMORY = "src/system/xmemory.cpp"

# 1. Global table extern in function_dispatcher.cpp
ANCHOR_DISP_TOP = '''#include <rex/system/function_dispatcher.h>
#include <rex/system/thread_state.h>
'''
NEW_DISP_TOP = '''#include <rex/system/function_dispatcher.h>
#include <rex/system/thread_state.h>

extern "C" ::PPCFunc** g_global_func_table;
static constexpr uint32_t kGlobalFuncBase = 0x82000000u;
static constexpr uint32_t kGlobalFuncEnd  = 0x90000000u;
'''

# 2. Overlap check in FunctionDispatcher::InitializeFunctionTable: check image range ONLY
ANCHOR_OVERLAP = '''  uint32_t new_table_end = image_base + image_size + (code_size + kThunkReserveSize) * 2;
  uint32_t new_code_end = code_base + code_size + kThunkReserveSize;
  for (const auto& existing : module_tables_) {
    uint32_t existing_table_end =
        existing.image_base + existing.image_size + (existing.code_size + kThunkReserveSize) * 2;
    uint32_t existing_code_end = existing.code_base + existing.code_size + kThunkReserveSize;
    if (image_base < existing_table_end && new_table_end > existing.image_base) {
      REXLOG_ERROR("Module image range [{:08X}, {:08X}) overlaps existing [{:08X}, {:08X})",
                   image_base, new_table_end, existing.image_base, existing_table_end);
      return false;
    }
    if (code_base < existing_code_end && new_code_end > existing.code_base) {
      REXLOG_ERROR("Module code range [{:08X}, {:08X}) overlaps existing [{:08X}, {:08X})",
                   code_base, new_code_end, existing.code_base, existing_code_end);
      return false;
    }
  }
'''
NEW_OVERLAP = '''  // LOCAL PATCH - iOS: check actual image range [image_base, image_base + image_size)
  // without in-arena function table inflation, avoiding false collision at 0x84800000 / 0x84900000.
  uint32_t new_image_end = image_base + image_size;
  uint32_t new_code_end = code_base + code_size + kThunkReserveSize;
  for (const auto& existing : module_tables_) {
    uint32_t existing_image_end = existing.image_base + existing.image_size;
    uint32_t existing_code_end = existing.code_base + existing.code_size + kThunkReserveSize;
    if (image_base < existing_image_end && new_image_end > existing.image_base) {
      REXLOG_ERROR("Module image range [{:08X}, {:08X}) overlaps existing [{:08X}, {:08X})",
                   image_base, new_image_end, existing.image_base, existing_image_end);
      return false;
    }
    if (code_base < existing_code_end && new_code_end > existing.code_base) {
      REXLOG_ERROR("Module code range [{:08X}, {:08X}) overlaps existing [{:08X}, {:08X})",
                   code_base, new_code_end, existing.code_base, existing_code_end);
      return false;
    }
  }
'''

# 3. Skip sentinel 0 and update g_global_func_table in FunctionDispatcher::SetFunction
ANCHOR_SETFUNC = '''bool FunctionDispatcher::SetFunction(uint32_t guest_address, ::PPCFunc* func) {
  std::lock_guard<std::recursive_mutex> lock(dispatch_mutex_);
  assert_true(!module_tables_.empty());

  if (!FindModuleByAddress(guest_address)) {
    REXLOG_ERROR("SetFunction: address {:08X} outside all registered module ranges", guest_address);
    return false;
  }

  function_table_[guest_address] = func;
'''
NEW_SETFUNC = '''bool FunctionDispatcher::SetFunction(uint32_t guest_address, ::PPCFunc* func) {
  if (guest_address == 0) {
    return true; // Skip {0, nullptr} sentinel quietly
  }
  std::lock_guard<std::recursive_mutex> lock(dispatch_mutex_);
  assert_true(!module_tables_.empty());

  if (!FindModuleByAddress(guest_address)) {
    REXLOG_ERROR("SetFunction: address {:08X} outside all registered module ranges", guest_address);
    return false;
  }

  function_table_[guest_address] = func;
  if (g_global_func_table && guest_address >= kGlobalFuncBase && guest_address < kGlobalFuncEnd) {
    g_global_func_table[(guest_address - kGlobalFuncBase) >> 2] = func;
  }
'''

# 4. Check g_global_func_table in FunctionDispatcher::GetFunction
ANCHOR_GETFUNC = '''::PPCFunc* FunctionDispatcher::GetFunction(uint32_t guest_address) {
  std::lock_guard<std::recursive_mutex> lock(dispatch_mutex_);
  auto it = function_table_.find(guest_address);
  if (it != function_table_.end()) {
    return it->second;
  }
  return nullptr;
}
'''
NEW_GETFUNC = '''::PPCFunc* FunctionDispatcher::GetFunction(uint32_t guest_address) {
  if (g_global_func_table && guest_address >= kGlobalFuncBase && guest_address < kGlobalFuncEnd) {
    PPCFunc* fn = g_global_func_table[(guest_address - kGlobalFuncBase) >> 2];
    if (fn) {
      return fn;
    }
  }
  std::lock_guard<std::recursive_mutex> lock(dispatch_mutex_);
  auto it = function_table_.find(guest_address);
  if (it != function_table_.end()) {
    return it->second;
  }
  return nullptr;
}
'''

# 5. Global table extern in xmemory.cpp
ANCHOR_MEM_TOP = '''#include <rex/system/mmio_handler.h>
#include <rex/system/xmemory.h>
'''
NEW_MEM_TOP = '''#include <rex/system/mmio_handler.h>
#include <rex/system/xmemory.h>

extern "C" ::PPCFunc** g_global_func_table;
'''

# 6. Stop in-arena AllocFixed in Memory::InitializeFunctionTable
ANCHOR_MEM_ALLOC = '''  if (!heaps_.v80000000.AllocFixed(
          table_base, table_size, 0x10000,
          memory::kMemoryAllocationReserve | memory::kMemoryAllocationCommit,
          memory::kMemoryProtectRead | memory::kMemoryProtectWrite)) {
    REXSYS_ERROR("Failed to allocate function table at {:08X}", table_base);
    return false;
  }

  Zero(table_base, table_size);
'''
NEW_MEM_ALLOC = '''  // LOCAL PATCH - iOS: function tables are stored outside the 4 GB guest arena.
  // We do not allocate in heaps_.v80000000, avoiding virtual address overlap.
'''

# 7. Stop Release in Memory::DestroyFunctionTable
ANCHOR_MEM_REL = '''  REXSYS_DEBUG("Destroying function table at {:08X}, size {:08X} for code {:08X}-{:08X}",
               table_base, table_size, logged_code_base, logged_code_base + logged_code_size);

  heaps_.v80000000.Release(table_base);
  return true;
'''
NEW_MEM_REL = '''  REXSYS_DEBUG("Destroying function table at {:08X}, size {:08X} for code {:08X}-{:08X}",
               table_base, table_size, logged_code_base, logged_code_base + logged_code_size);

  return true;
'''

# 8. Skip 0 and update g_global_func_table in Memory::SetFunction
ANCHOR_MEM_SET = '''bool Memory::SetFunction(uint32_t guest_address, PPCFunc* host_function) {
  uint32_t table_address = 0;
'''
NEW_MEM_SET = '''bool Memory::SetFunction(uint32_t guest_address, PPCFunc* host_function) {
  if (guest_address == 0) {
    return true;
  }
  if (guest_address >= 0x82000000u && guest_address < 0x90000000u) {
    if (g_global_func_table) {
      g_global_func_table[(guest_address - 0x82000000u) >> 2] = host_function;
    }
  }
  uint32_t table_address = 0;
'''

BLOCKS = [
    (FILE_DISPATCHER, "dispatcher global table extern", ANCHOR_DISP_TOP, NEW_DISP_TOP),
    (FILE_DISPATCHER, "image overlap check fix", ANCHOR_OVERLAP, NEW_OVERLAP),
    (FILE_DISPATCHER, "skip sentinel 0 and update global table", ANCHOR_SETFUNC, NEW_SETFUNC),
    (FILE_DISPATCHER, "global table fast path in GetFunction", ANCHOR_GETFUNC, NEW_GETFUNC),
    (FILE_MEMORY, "memory global table extern", ANCHOR_MEM_TOP, NEW_MEM_TOP),
    (FILE_MEMORY, "stop guest heap allocation for function tables", ANCHOR_MEM_ALLOC, NEW_MEM_ALLOC),
    (FILE_MEMORY, "stop guest heap release for function tables", ANCHOR_MEM_REL, NEW_MEM_REL),
    (FILE_MEMORY, "skip sentinel 0 and update global table in Memory", ANCHOR_MEM_SET, NEW_MEM_SET),
]

if __name__ == "__main__":
    sys.exit(run("ios_function_table", BLOCKS))
