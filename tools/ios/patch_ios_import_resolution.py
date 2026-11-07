#!/usr/bin/env python3
"""
Resolve cross-DLL and kernel XEX2 imports across all loaded modules.
Wires function import thunks to target PPCFunc* and patches variable imports
(like g_pMemAlloc in vstdlib_360.dll / launcher_360.dll).

Touches:
    src/system/xex_module.cpp
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run

FILE = "src/system/xex_module.cpp"

ANCHOR = '''    if (record_type == 0) {
      // Variable import - value_address is where the variable value is stored
      import_info.value_address = record_addr;

      // Patch variable imports in guest memory with the actual address
      if (export_resolver) {
        auto kernel_export = export_resolver->GetExportByOrdinal(base_name, ordinal);
        if (kernel_export && kernel_export->type == runtime::Export::Type::kVariable) {
          if (kernel_export->is_implemented() && kernel_export->variable_ptr) {
            // Write the variable address to guest memory
            *record_slot = kernel_export->variable_ptr;
            REXLOG_DEBUG("Patched variable import {}:{:#x} ({}) -> {:#x}", base_name, ordinal,
                         kernel_export->name, kernel_export->variable_ptr);
          } else {
            // write garbage value if we don't have it implemented
            *record_slot = 0xD000BEEF | (kernel_export->ordinal & 0xFFF) << 16;
            REXLOG_WARN("Variable import {}:{:#x} ({}) not implemented", base_name, ordinal,
                        kernel_export->name);
          }
        }
      }
    } else if (record_type == 1) {
      // Thunk import - thunk_address is the function pointer location
      // This is the address we need for function table registration
      import_info.thunk_address = record_addr;
    }
'''

NEW = '''    if (record_type == 0) {
      // Variable import - value_address is where the variable value is stored
      import_info.value_address = record_addr;

      bool patched = false;
      // Patch variable imports in guest memory with the actual address
      if (export_resolver) {
        auto kernel_export = export_resolver->GetExportByOrdinal(base_name, ordinal);
        if (kernel_export && kernel_export->type == runtime::Export::Type::kVariable) {
          if (kernel_export->is_implemented() && kernel_export->variable_ptr) {
            // Write the variable address to guest memory
            *record_slot = kernel_export->variable_ptr;
            patched = true;
            REXLOG_DEBUG("Patched variable import {}:{:#x} ({}) -> {:#x}", base_name, ordinal,
                         kernel_export->name, kernel_export->variable_ptr);
          } else {
            // write garbage value if we don't have it implemented
            *record_slot = 0xD000BEEF | (kernel_export->ordinal & 0xFFF) << 16;
            patched = true;
            REXLOG_WARN("Variable import {}:{:#x} ({}) not implemented", base_name, ordinal,
                        kernel_export->name);
          }
        }
      }

      // LOCAL PATCH - iOS: resolve cross-DLL variable imports from loaded UserModules (e.g. tier0 -> vstdlib)
      if (!patched && kernel_state_) {
        auto target_mod = kernel_state_->GetModule(base_name);
        if (!target_mod) {
          std::string mod_with_ext = std::string(base_name) + ".dll";
          target_mod = kernel_state_->GetModule(mod_with_ext);
        }
        if (target_mod && target_mod->xex_module()) {
          uint32_t export_addr = target_mod->xex_module()->GetProcAddress(ordinal);
          if (export_addr) {
            *record_slot = export_addr;
            patched = true;
            REXLOG_INFO("Patched cross-DLL variable import {}:{:#x} -> {:#x}", base_name, ordinal,
                        export_addr);
          }
        }
      }
    } else if (record_type == 1) {
      // Thunk import - thunk_address is the function pointer location
      // This is the address we need for function table registration
      import_info.thunk_address = record_addr;

      // LOCAL PATCH - iOS: wire function import thunk to target host PPCFunc*
      if (export_resolver) {
        auto kernel_export = export_resolver->GetExportByOrdinal(base_name, ordinal);
        if (kernel_export && kernel_export->type == runtime::Export::Type::kFunction) {
          if (kernel_export->is_implemented() && kernel_export->function_data.function_info) {
            auto host_fn = reinterpret_cast<::PPCFunc*>(
                kernel_export->function_data.function_info->host_function);
            if (host_fn && function_dispatcher_) {
              function_dispatcher_->SetFunction(record_addr, host_fn);
            }
          }
        }
      }
      if (kernel_state_) {
        auto target_mod = kernel_state_->GetModule(base_name);
        if (!target_mod) {
          std::string mod_with_ext = std::string(base_name) + ".dll";
          target_mod = kernel_state_->GetModule(mod_with_ext);
        }
        if (target_mod && target_mod->xex_module()) {
          uint32_t export_addr = target_mod->xex_module()->GetProcAddress(ordinal);
          if (export_addr && function_dispatcher_) {
            auto host_fn = function_dispatcher_->GetFunction(export_addr);
            if (host_fn) {
              function_dispatcher_->SetFunction(record_addr, host_fn);
              REXLOG_INFO("Wired cross-DLL import thunk {}:{:#x} (thunk={:#x} -> {:#x})",
                          base_name, ordinal, record_addr, export_addr);
            }
          }
        }
      }
    }
'''

BLOCKS = [
    (FILE, "cross-DLL and kernel import thunk & variable resolution", ANCHOR, NEW),
]

if __name__ == "__main__":
    sys.exit(run("ios_import_resolution", BLOCKS))
