#pragma once

#include <cstdint>
#include <string>

namespace l4d2 {

struct GuestRegisters {
    uint32_t pc = 0;
    uint32_t lr = 0;
    uint32_t ctr = 0;
    uint32_t cr = 0;
    uint32_t xer = 0;
    uint32_t r[32] = {0};
};

class CrashHandler {
public:
    static void Install();
    static void SetBootFilePath(const std::string& path);
    static void RecordIndirectCall(uint32_t target_pc, const char* hint);
    static void DumpCrashState(int sig, const GuestRegisters* regs, const char* reason);
};

} // namespace l4d2
