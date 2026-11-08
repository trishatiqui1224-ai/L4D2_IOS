#!/usr/bin/env python3
"""
Resolve cross-DLL XEX2 imports across all loaded modules.
Wires function import thunks to target PPCFunc* and patches variable imports
(like g_pMemAlloc in vstdlib_360.dll / launcher_360.dll).
CRITICAL: Never touches xboxkrnl.exe or xam.xex imports (those are handled natively).

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
      // CRITICAL: NEVER run on xboxkrnl or xam; they are kernel modules handled natively above!
      std::string_view base_sv(base_name);
      const bool is_kernel = (base_sv.find("xboxkrnl") != std::string_view::npos ||
                              base_sv.find("xam") != std::string_view::npos);
      if (!is_kernel && !patched && kernel_state_) {
        auto target_mod = kernel_state_->GetModule(base_name);
        if (!target_mod) {
          std::string mod_with_ext = std::string(base_name) + ".dll";
          target_mod = kernel_state_->GetModule(mod_with_ext);
        }
        if (target_mod) {
          uint32_t export_addr = target_mod->GetProcAddressByOrdinal(ordinal);
          if (export_addr) {
            *record_slot = export_addr;
            patched = true;
            REXLOG_DEBUG("Patched cross-DLL variable import {}:{:#x} -> {:#x}", base_name, ordinal,
                         export_addr);
          }
        }
      }
    } else if (record_type == 1) {
      // Thunk import - thunk_address is the function pointer location
      // This is the address we need for function table registration
      import_info.thunk_address = record_addr;

      // LOCAL PATCH - iOS: wire cross-DLL function import thunk to target host PPCFunc*
      // CRITICAL: NEVER run on xboxkrnl or xam; they are kernel modules handled natively!
      std::string_view base_sv(base_name);
      const bool is_kernel = (base_sv.find("xboxkrnl") != std::string_view::npos ||
                              base_sv.find("xam") != std::string_view::npos);
      if (!is_kernel && kernel_state_) {
        auto target_mod = kernel_state_->GetModule(base_name);
        if (!target_mod) {
          std::string mod_with_ext = std::string(base_name) + ".dll";
          target_mod = kernel_state_->GetModule(mod_with_ext);
        }
        if (target_mod) {
          uint32_t export_addr = target_mod->GetProcAddressByOrdinal(ordinal);
          if (export_addr && function_dispatcher_) {
            // Always patch guest memory thunk with direct PPC trampoline so guest PPC code and stubs know the target:
            if (record_slot) {
              auto* raw_words = reinterpret_cast<rex::be<uint32_t>*>(record_slot);
              raw_words[0] = 0x3D600000u | ((export_addr >> 16) & 0xFFFFu);
              raw_words[1] = 0x616B0000u | (export_addr & 0xFFFFu);
              raw_words[2] = 0x7D6903A6u;
              raw_words[3] = 0x4E800420u;
            }
            auto host_fn = function_dispatcher_->GetFunction(export_addr);
            if (host_fn) {
              function_dispatcher_->SetFunction(record_addr, host_fn);
              REXLOG_DEBUG("Wired cross-DLL import thunk {}:{:#x} (thunk={:#x} -> {:#x})",
                           base_name, ordinal, record_addr, export_addr);
            } else {
              REXLOG_WARN("Cross-DLL import thunk {}:{:#x} (thunk={:#x}) has no host function at target {:#x}",
                          base_name, ordinal, record_addr, export_addr);
            }
          }
        }
      }
    }
'''

ANCHOR_SUMMARY = '''  import_libs_.push_back(library_info);
  REXLOG_DEBUG("created symbols for import library {} with {} imports", base_name,
               library_info.imports.size());

  return true;
'''

NEW_SUMMARY = '''  import_libs_.push_back(library_info);
  std::string_view base_sv_sum(base_name);
  if (base_sv_sum.find("xboxkrnl") == std::string_view::npos &&
      base_sv_sum.find("xam") == std::string_view::npos) {
    REXLOG_INFO("Wired cross-DLL imports for {} ({} total imports)",
                base_name, library_info.imports.size());
  } else {
    REXLOG_DEBUG("created symbols for import library {} with {} imports", base_name,
                 library_info.imports.size());
  }

  return true;
'''

ANCHOR_RELOC = '''  // Setup memory protection.
  for (uint32_t i = 0, page = 0; i < sec_header->page_descriptor_count; i++) {
    // Byteswap the bitfield manually.
    xex2_page_descriptor desc;
'''

NEW_RELOC = '''  // LOCAL PATCH - iOS: apply base relocations to data sections of rebased modules
  const uint32_t orig_base = sec_header->load_address;
  if (base_address_ != orig_base && orig_base != 0) {
    const uint32_t delta = base_address_ - orig_base;
    const uint32_t image_span = sec_header->image_size;
    uint32_t relocated_count = 0;
    for (uint32_t i = 0, page = 0; i < sec_header->page_descriptor_count; i++) {
      xex2_page_descriptor desc;
      desc.value = rex::byte_swap(sec_header->page_descriptors[i].value);
      if (desc.info == XEX_SECTION_READONLY_DATA || desc.info == XEX_SECTION_DATA) {
        uint32_t page_addr = base_address_ + (page * page_size);
        uint32_t page_bytes = desc.page_count * page_size;
        uint8_t* mem_ptr = memory()->TranslateVirtual(page_addr);
        if (mem_ptr) {
          auto* words = reinterpret_cast<rex::be<uint32_t>*>(mem_ptr);
          size_t word_count = page_bytes / 4;
          for (size_t w = 0; w < word_count; ++w) {
            uint32_t val = words[w];
            if (val >= orig_base && val < orig_base + image_span) {
              words[w] = val + delta;
              ++relocated_count;
            }
          }
        }
      }
      page += desc.page_count;
    }
    REXLOG_INFO("Applied base relocations for {} (orig=0x{:08X}, new=0x{:08X}, delta=+0x{:08X}): {} pointers updated",
                name_, orig_base, base_address_, delta, relocated_count);
  }

  // Setup memory protection.
  for (uint32_t i = 0, page = 0; i < sec_header->page_descriptor_count; i++) {
    // Byteswap the bitfield manually.
    xex2_page_descriptor desc;
'''

BLOCKS = [
    (FILE, "cross-DLL and kernel import thunk & variable resolution", ANCHOR, NEW),
    (FILE, "summary log for cross-DLL imports", ANCHOR_SUMMARY, NEW_SUMMARY),
    (FILE, "apply base relocations to data sections of rebased modules", ANCHOR_RELOC, NEW_RELOC),
]

if __name__ == "__main__":
    sys.exit(run("ios_import_resolution", BLOCKS))
