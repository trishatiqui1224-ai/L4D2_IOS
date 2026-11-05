#pragma once

#include <string>
#include <cstdint>

namespace l4d2::boot {

// Opens the trace file (e.g. Documents/boot.txt) and installs crash hooks.
void Open(const std::string& path);

// Registers the main log file path so crash dumps are written to both files.
void SetLogFilePath(const std::string& path);

// One line, written and flushed to disk immediately via raw POSIX write().
void Trace(const std::string& line);

// Enable or disable boot tracing.
void SetEnabled(bool enabled);

// Allocate and register an alternate signal stack via sigaltstack()
void SetupAltStack();

// Thread-local PPC execution breadcrumb for crash reporting
void SetLastPPCBreadcrumb(uint32_t fn_addr, uint32_t lr, uint32_t r3);

// Formatted ring buffer of last 16 PPC breadcrumbs
size_t FormatLastPPCBreadcrumbs(char* buf, size_t buf_size);

}  // namespace l4d2::boot
