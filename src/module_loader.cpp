#include "module_loader.h"
#include "logging/logger.h"

#include <rex/logging.h>
#include <rex/types.h>
#include <rex/image_info.h>
#include <rex/runtime.h>
#include <rex/system/function_dispatcher.h>
#include <rex/system/kernel_state.h>
#include <rex/system/user_module.h>

#include <algorithm>
#include <atomic>
#include <bit>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <sstream>

#if defined(_WIN32)
#include <windows.h>
#else
#include <sys/mman.h>
#include <unistd.h>
#endif

constexpr uint32_t kGlobalFuncTableBase = 0x82000000u;
constexpr uint32_t kGlobalFuncTableEnd  = 0x90000000u;
constexpr size_t   kGlobalFuncTableEntries = (kGlobalFuncTableEnd - kGlobalFuncTableBase) >> 2;
constexpr size_t   kGlobalFuncTableBytes = kGlobalFuncTableEntries * sizeof(PPCFunc*);

// g_global_func_table is defined in function_dispatcher.cpp

static void InitializeGlobalFunctionTable() {
    if (g_global_func_table != nullptr) {
        return;
    }
#if defined(_WIN32)
    g_global_func_table = static_cast<PPCFunc**>(
        VirtualAlloc(nullptr, kGlobalFuncTableBytes, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
#else
    void* ptr = mmap(nullptr, kGlobalFuncTableBytes, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    if (ptr != MAP_FAILED) {
        g_global_func_table = static_cast<PPCFunc**>(ptr);
    }
#endif
    if (g_global_func_table) {
        L4D2_LOG_INFO("ModuleLoader", "Allocated unified global function table: %zu MB (0x%08X..0x%08X)",
                      kGlobalFuncTableBytes / (1024 * 1024), kGlobalFuncTableBase, kGlobalFuncTableEnd);
    } else {
        L4D2_LOG_ERROR("ModuleLoader", "Failed to allocate unified global function table");
    }
}

extern "C" PPCFunc* LookupGlobalFunction(uint8_t* base, uint32_t guest_addr) {
    if (__builtin_expect(guest_addr >= kGlobalFuncTableBase && guest_addr < kGlobalFuncTableEnd, 1)) {
        if (g_global_func_table) {
            PPCFunc* fn = g_global_func_table[(guest_addr - kGlobalFuncTableBase) >> 2];
            if (fn) return fn;
        }
    }
    return nullptr;
}

extern "C" void LogUnresolvedIndirectCall(uint32_t target_addr, uint32_t caller_lr, uint32_t r3) {
    static std::unordered_set<uint64_t> s_logged_calls;
    static std::mutex s_log_mutex;
    uint64_t key = (static_cast<uint64_t>(target_addr) << 32) | caller_lr;
    {
        std::lock_guard<std::mutex> lock(s_log_mutex);
        if (s_logged_calls.size() > 1024) s_logged_calls.clear();
        if (!s_logged_calls.insert(key).second) {
            return;
        }
    }

    std::string mod_target = l4d2::ModuleLoader::Instance().SymbolicateAddress(target_addr);
    std::string mod_caller = l4d2::ModuleLoader::Instance().SymbolicateAddress(caller_lr);

    char buf[512];
    snprintf(buf, sizeof(buf),
             "[UNRESOLVED INDIRECT CALL] Target: 0x%08X (%s), Caller LR: 0x%08X (%s), r3: 0x%08X",
             target_addr, mod_target.c_str(), caller_lr, mod_caller.c_str(), r3);

    L4D2_LOG_ERROR("CRASH", "%s", buf);

    FILE* bf = nullptr;
    const char* bp = std::getenv("L4D2_BOOT_PATH");
    if (!bp) bp = std::getenv("NFSMW_SIGNAL_REPORT");
    if (bp) bf = fopen(bp, "a");
    if (!bf) bf = fopen("boot.txt", "a");
    if (bf) {
        fprintf(bf, "%s\n", buf);
        fflush(bf);
        fclose(bf);
    }
    l4d2::log::Logger::Instance().Flush();
    rex::FlushLogging();
}

extern "C" {
__attribute__((visibility("default"))) std::atomic<uint32_t> g_current_ppc_fn{0};
__attribute__((visibility("default"))) std::atomic<uint32_t> g_current_ppc_lr{0};
__attribute__((visibility("default"))) std::atomic<uint64_t> g_ppc_call_count{0};
__attribute__((visibility("default"))) std::atomic<uint32_t> g_ppc_ring_idx{0};
__attribute__((visibility("default"))) uint32_t g_ppc_call_ring[32] = {0};
__attribute__((visibility("default"))) uint32_t g_ppc_lr_ring[32] = {0};

__attribute__((visibility("default"))) void RecordDispatchBreadcrumb(uint32_t target_addr, uint32_t caller_lr) {
    g_current_ppc_fn.store(target_addr, std::memory_order_relaxed);
    g_current_ppc_lr.store(caller_lr, std::memory_order_relaxed);
    g_ppc_call_count.fetch_add(1, std::memory_order_relaxed);
    uint32_t idx = g_ppc_ring_idx.fetch_add(1, std::memory_order_relaxed) & 31;
    g_ppc_call_ring[idx] = target_addr;
    g_ppc_lr_ring[idx] = caller_lr;
}

__attribute__((visibility("default"))) void DumpDispatchRingBuffer() {
    uint32_t cur_fn = g_current_ppc_fn.load(std::memory_order_relaxed);
    uint32_t cur_lr = g_current_ppc_lr.load(std::memory_order_relaxed);
    uint64_t count  = g_ppc_call_count.load(std::memory_order_relaxed);
    uint32_t head   = g_ppc_ring_idx.load(std::memory_order_relaxed);

    std::string mod_fn = l4d2::ModuleLoader::Instance().SymbolicateAddress(cur_fn);
    std::string mod_lr = l4d2::ModuleLoader::Instance().SymbolicateAddress(cur_lr);

    char buf[1024];
    snprintf(buf, sizeof(buf),
             "[WATCHDOG] Total PPC calls: %llu | Last Target: 0x%08X (%s) | Last LR: 0x%08X (%s)",
             (unsigned long long)count, cur_fn, mod_fn.c_str(), cur_lr, mod_lr.c_str());
    L4D2_LOG_WARN("WATCHDOG", "%s", buf);

    FILE* bf = nullptr;
    const char* bp = std::getenv("L4D2_BOOT_PATH");
    if (!bp) bp = std::getenv("NFSMW_SIGNAL_REPORT");
    if (bp) bf = fopen(bp, "a");
    if (!bf) bf = fopen("boot.txt", "a");
    if (bf) {
        fprintf(bf, "%s\n", buf);
        fprintf(bf, "[WATCHDOG] Ring buffer of last 32 indirect calls (newest to oldest):\n");
        for (uint32_t i = 0; i < 32; ++i) {
            uint32_t ring_idx = (head - 1 - i) & 31;
            uint32_t target = g_ppc_call_ring[ring_idx];
            uint32_t lr = g_ppc_lr_ring[ring_idx];
            if (target != 0) {
                std::string s_t = l4d2::ModuleLoader::Instance().SymbolicateAddress(target);
                std::string s_lr = l4d2::ModuleLoader::Instance().SymbolicateAddress(lr);
                fprintf(bf, "  [%02u] Target: 0x%08X (%s), LR: 0x%08X (%s)\n",
                        i, target, s_t.c_str(), lr, s_lr.c_str());
            }
        }
        fflush(bf);
#if !defined(_WIN32)
        fsync(fileno(bf));
#endif
        fclose(bf);
    }
    l4d2::log::Logger::Instance().Flush();
    rex::FlushLogging();
}
}

static inline PPCRegister& GetGPR(PPCContext& ctx, uint32_t r) {
    switch (r & 31) {
        case 0: return ctx.r0;  case 1: return ctx.r1;  case 2: return ctx.r2;  case 3: return ctx.r3;
        case 4: return ctx.r4;  case 5: return ctx.r5;  case 6: return ctx.r6;  case 7: return ctx.r7;
        case 8: return ctx.r8;  case 9: return ctx.r9;  case 10: return ctx.r10; case 11: return ctx.r11;
        case 12: return ctx.r12; case 13: return ctx.r13; case 14: return ctx.r14; case 15: return ctx.r15;
        case 16: return ctx.r16; case 17: return ctx.r17; case 18: return ctx.r18; case 19: return ctx.r19;
        case 20: return ctx.r20; case 21: return ctx.r21; case 22: return ctx.r22; case 23: return ctx.r23;
        case 24: return ctx.r24; case 25: return ctx.r25; case 26: return ctx.r26; case 27: return ctx.r27;
        case 28: return ctx.r28; case 29: return ctx.r29; case 30: return ctx.r30; default: return ctx.r31;
    }
}

static inline PPCCRRegister& GetCRField(PPCContext& ctx, uint32_t crf) {
    switch (crf & 7) {
        case 0: return ctx.cr0; case 1: return ctx.cr1; case 2: return ctx.cr2; case 3: return ctx.cr3;
        case 4: return ctx.cr4; case 5: return ctx.cr5; case 6: return ctx.cr6; default: return ctx.cr7;
    }
}

static inline PPCRegister& GetFPR(PPCContext& ctx, uint32_t f) {
    switch (f & 31) {
        case 0: return ctx.f0;  case 1: return ctx.f1;  case 2: return ctx.f2;  case 3: return ctx.f3;
        case 4: return ctx.f4;  case 5: return ctx.f5;  case 6: return ctx.f6;  case 7: return ctx.f7;
        case 8: return ctx.f8;  case 9: return ctx.f9;  case 10: return ctx.f10; case 11: return ctx.f11;
        case 12: return ctx.f12; case 13: return ctx.f13; case 14: return ctx.f14; case 15: return ctx.f15;
        case 16: return ctx.f16; case 17: return ctx.f17; case 18: return ctx.f18; case 19: return ctx.f19;
        case 20: return ctx.f20; case 21: return ctx.f21; case 22: return ctx.f22; case 23: return ctx.f23;
        case 24: return ctx.f24; case 25: return ctx.f25; case 26: return ctx.f26; case 27: return ctx.f27;
        case 28: return ctx.f28; case 29: return ctx.f29; case 30: return ctx.f30; default: return ctx.f31;
    }
}

static inline uint32_t PPC_Mask(uint32_t mb, uint32_t me) {
    uint32_t mask_mb = (mb <= 31) ? (~0u >> mb) : 0u;
    uint32_t mask_me = (me <= 31) ? (~0u << (31 - me)) : 0u;
    return (mb <= me) ? (mask_mb & mask_me) : (mask_mb | mask_me);
}

static inline void UpdateCR0(PPCContext& ctx, uint32_t result) {
    ctx.cr0.lt = (static_cast<int32_t>(result) < 0) ? 1 : 0;
    ctx.cr0.gt = (static_cast<int32_t>(result) > 0) ? 1 : 0;
    ctx.cr0.eq = (result == 0) ? 1 : 0;
    ctx.cr0.so = ctx.xer.so;
}

static inline bool CheckCRBit(PPCContext& ctx, uint32_t bi) {
    const PPCCRRegister& cr = GetCRField(ctx, bi >> 2);
    switch (bi & 3) {
        case 0: return cr.lt != 0;
        case 1: return cr.gt != 0;
        case 2: return cr.eq != 0;
        default: return cr.so != 0;
    }
}

static inline bool IsValidGuestPtr(uint32_t ea) {
    return ea >= 0x00010000u && ea < 0x90000000u;
}

static inline uint32_t ReadGuestU32(uint8_t* base, uint32_t ea) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        return __builtin_bswap32(*reinterpret_cast<const uint32_t*>(base + ea));
    }
    return 0;
}

static inline uint16_t ReadGuestU16(uint8_t* base, uint32_t ea) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        return __builtin_bswap16(*reinterpret_cast<const uint16_t*>(base + ea));
    }
    return 0;
}

static inline uint8_t ReadGuestU8(uint8_t* base, uint32_t ea) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        return *reinterpret_cast<const uint8_t*>(base + ea);
    }
    return 0;
}

static inline uint64_t ReadGuestU64(uint8_t* base, uint32_t ea) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        return __builtin_bswap64(*reinterpret_cast<const uint64_t*>(base + ea));
    }
    return 0;
}

static inline void WriteGuestU32(uint8_t* base, uint32_t ea, uint32_t val) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        *reinterpret_cast<uint32_t*>(base + ea) = __builtin_bswap32(val);
    }
}

static inline void WriteGuestU16(uint8_t* base, uint32_t ea, uint16_t val) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        *reinterpret_cast<uint16_t*>(base + ea) = __builtin_bswap16(val);
    }
}

static inline void WriteGuestU8(uint8_t* base, uint32_t ea, uint8_t val) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        *reinterpret_cast<uint8_t*>(base + ea) = val;
    }
}

static inline void WriteGuestU64(uint8_t* base, uint32_t ea, uint64_t val) {
    if (__builtin_expect(IsValidGuestPtr(ea), 1)) {
        *reinterpret_cast<uint64_t*>(base + ea) = __builtin_bswap64(val);
    }
}

extern "C" void SafeDispatchIndirect(PPCContext& ctx, uint8_t* base, uint32_t target_addr, uint32_t caller_lr);

static bool ExecutePPCLeaf(PPCContext& ctx, uint8_t* base, uint32_t target_addr, uint32_t caller_lr) {
    if (!base || (target_addr & 3) != 0 || target_addr < 0x82000000 || target_addr >= 0x90000000) {
        return false;
    }

    uint32_t pc = target_addr;
    constexpr uint32_t kMaxInstructions = 256;

    for (uint32_t step = 0; step < kMaxInstructions; ++step) {
        if ((pc & 3) != 0 || pc < 0x82000000 || pc >= 0x90000000) {
            return false;
        }

        uint32_t instr = ReadGuestU32(base, pc);
        uint32_t op = instr >> 26;
        uint32_t d = (instr >> 21) & 0x1F;
        uint32_t a = (instr >> 16) & 0x1F;
        uint32_t b = (instr >> 11) & 0x1F;
        uint32_t s = d;
        int16_t simm = static_cast<int16_t>(instr & 0xFFFFu);
        uint16_t uimm = static_cast<uint16_t>(instr & 0xFFFFu);

        // Quick path: blr (0x4E800020)
        if (instr == 0x4E800020u) {
            return true;
        }
        // Quick path: bctr (0x4E800420)
        if (instr == 0x4E800420u) {
            SafeDispatchIndirect(ctx, base, ctx.ctr.u32, caller_lr);
            return true;
        }

        switch (op) {
            case 14: { // addi rD, rA, SIMM
                int64_t a_val = (a == 0) ? 0 : GetGPR(ctx, a).s64;
                GetGPR(ctx, d).s64 = a_val + simm;
                pc += 4;
                break;
            }
            case 15: { // addis rD, rA, SIMM
                int64_t a_val = (a == 0) ? 0 : GetGPR(ctx, a).s64;
                GetGPR(ctx, d).s64 = a_val + (static_cast<int32_t>(simm) << 16);
                pc += 4;
                break;
            }
            case 7: { // mulli rD, rA, SIMM
                GetGPR(ctx, d).s64 = GetGPR(ctx, a).s64 * simm;
                pc += 4;
                break;
            }
            case 10: { // cmpli crfD, L, rA, UIMM
                uint32_t crf = (instr >> 23) & 7;
                uint32_t l = (instr >> 21) & 1;
                uint64_t a_val = l ? GetGPR(ctx, a).u64 : GetGPR(ctx, a).u32;
                GetCRField(ctx, crf).compare(a_val, static_cast<uint64_t>(uimm), ctx.xer);
                pc += 4;
                break;
            }
            case 11: { // cmpi crfD, L, rA, SIMM
                uint32_t crf = (instr >> 23) & 7;
                uint32_t l = (instr >> 21) & 1;
                int64_t a_val = l ? GetGPR(ctx, a).s64 : GetGPR(ctx, a).s32;
                GetCRField(ctx, crf).compare(a_val, static_cast<int64_t>(simm), ctx.xer);
                pc += 4;
                break;
            }
            case 12: { // addic rD, rA, SIMM
                uint64_t a_val = GetGPR(ctx, a).u32;
                uint64_t sum = a_val + static_cast<int32_t>(simm);
                ctx.xer.ca = (sum >> 32) & 1;
                GetGPR(ctx, d).s64 = static_cast<int32_t>(sum);
                pc += 4;
                break;
            }
            case 16: { // bc BO, BI, BD
                uint32_t bo = (instr >> 21) & 0x1F;
                uint32_t bi = (instr >> 16) & 0x1F;
                int16_t bd = static_cast<int16_t>(instr & 0xFFFCu);
                uint32_t target = (instr & 2) ? static_cast<uint32_t>(bd) : (pc + bd);

                bool ctr_ok = (bo & 0x04) != 0;
                if (!ctr_ok) {
                    ctx.ctr.u64--;
                    ctr_ok = (ctx.ctr.u32 != 0) == ((bo & 0x02) == 0);
                }
                bool cond_ok = (bo & 0x10) != 0;
                if (!cond_ok) {
                    cond_ok = CheckCRBit(ctx, bi) == ((bo & 0x08) != 0);
                }
                if (ctr_ok && cond_ok) {
                    pc = target;
                } else {
                    pc += 4;
                }
                break;
            }
            case 18: { // b / ba / bl / bla
                int32_t li = static_cast<int32_t>((instr & 0x03FFFFFCu) << 6) >> 6;
                uint32_t target = (instr & 2) ? static_cast<uint32_t>(li) : (pc + li);
                if (instr & 1) { // bl
                    ctx.lr = pc + 4;
                    SafeDispatchIndirect(ctx, base, target, static_cast<uint32_t>(ctx.lr));
                    return true;
                }
                // Unconditional branch
                int32_t diff = static_cast<int32_t>(target - target_addr);
                if (diff >= -4096 && diff <= 4096) {
                    pc = target;
                } else {
                    SafeDispatchIndirect(ctx, base, target, caller_lr);
                    return true;
                }
                break;
            }
            case 19: { // Condition register / return instructions
                uint32_t xo = (instr >> 1) & 0x3FFu;
                uint32_t bo = (instr >> 21) & 0x1F;
                uint32_t bi = (instr >> 16) & 0x1F;
                if (xo == 16) { // bclr / blr
                    bool ctr_ok = (bo & 0x04) != 0;
                    if (!ctr_ok) {
                        ctx.ctr.u64--;
                        ctr_ok = (ctx.ctr.u32 != 0) == ((bo & 0x02) == 0);
                    }
                    bool cond_ok = (bo & 0x10) != 0;
                    if (!cond_ok) {
                        cond_ok = CheckCRBit(ctx, bi) == ((bo & 0x08) != 0);
                    }
                    if (ctr_ok && cond_ok) {
                        return true;
                    }
                    pc += 4;
                    break;
                } else if (xo == 528) { // bcctr / bctr
                    bool cond_ok = (bo & 0x10) != 0;
                    if (!cond_ok) {
                        cond_ok = CheckCRBit(ctx, bi) == ((bo & 0x08) != 0);
                    }
                    if (cond_ok) {
                        SafeDispatchIndirect(ctx, base, ctx.ctr.u32, caller_lr);
                        return true;
                    }
                    pc += 4;
                    break;
                } else {
                    return false;
                }
            }
            case 20: { // rlwimi rA, rS, SH, MB, ME
                uint32_t sh = (instr >> 11) & 0x1F;
                uint32_t mb = (instr >> 6) & 0x1F;
                uint32_t me = (instr >> 1) & 0x1F;
                uint32_t mask = PPC_Mask(mb, me);
                uint32_t rotated = std::rotl(GetGPR(ctx, s).u32, sh);
                uint32_t res = (rotated & mask) | (GetGPR(ctx, a).u32 & ~mask);
                GetGPR(ctx, a).u64 = res;
                if (instr & 1) UpdateCR0(ctx, res);
                pc += 4;
                break;
            }
            case 21: { // rlwinm rA, rS, SH, MB, ME
                uint32_t sh = (instr >> 11) & 0x1F;
                uint32_t mb = (instr >> 6) & 0x1F;
                uint32_t me = (instr >> 1) & 0x1F;
                uint32_t mask = PPC_Mask(mb, me);
                uint32_t rotated = std::rotl(GetGPR(ctx, s).u32, sh);
                uint32_t res = rotated & mask;
                GetGPR(ctx, a).u64 = res;
                if (instr & 1) UpdateCR0(ctx, res);
                pc += 4;
                break;
            }
            case 24: { // ori rA, rS, UIMM (includes nop: ori 0, 0, 0)
                GetGPR(ctx, a).u64 = GetGPR(ctx, s).u64 | uimm;
                pc += 4;
                break;
            }
            case 25: { // oris rA, rS, UIMM
                GetGPR(ctx, a).u64 = GetGPR(ctx, s).u64 | (static_cast<uint64_t>(uimm) << 16);
                pc += 4;
                break;
            }
            case 26: { // xori rA, rS, UIMM
                GetGPR(ctx, a).u64 = GetGPR(ctx, s).u64 ^ uimm;
                pc += 4;
                break;
            }
            case 27: { // xoris rA, rS, UIMM
                GetGPR(ctx, a).u64 = GetGPR(ctx, s).u64 ^ (static_cast<uint64_t>(uimm) << 16);
                pc += 4;
                break;
            }
            case 28: { // andi. rA, rS, UIMM
                uint32_t res = GetGPR(ctx, s).u32 & uimm;
                GetGPR(ctx, a).u64 = res;
                UpdateCR0(ctx, res);
                pc += 4;
                break;
            }
            case 29: { // andis. rA, rS, UIMM
                uint32_t res = GetGPR(ctx, s).u32 & (static_cast<uint32_t>(uimm) << 16);
                GetGPR(ctx, a).u64 = res;
                UpdateCR0(ctx, res);
                pc += 4;
                break;
            }
            case 31: { // Extended opcode 31
                uint32_t xo = (instr >> 1) & 0x3FFu;
                uint32_t rc = instr & 1u;
                switch (xo) {
                    case 0: { // cmp crfD, L, rA, rB
                        uint32_t crf = (instr >> 23) & 7;
                        uint32_t l = (instr >> 21) & 1;
                        int64_t a_val = l ? GetGPR(ctx, a).s64 : GetGPR(ctx, a).s32;
                        int64_t b_val = l ? GetGPR(ctx, b).s64 : GetGPR(ctx, b).s32;
                        GetCRField(ctx, crf).compare(a_val, b_val, ctx.xer);
                        break;
                    }
                    case 32: { // cmpl crfD, L, rA, rB
                        uint32_t crf = (instr >> 23) & 7;
                        uint32_t l = (instr >> 21) & 1;
                        uint64_t a_val = l ? GetGPR(ctx, a).u64 : GetGPR(ctx, a).u32;
                        uint64_t b_val = l ? GetGPR(ctx, b).u64 : GetGPR(ctx, b).u32;
                        GetCRField(ctx, crf).compare(a_val, b_val, ctx.xer);
                        break;
                    }
                    case 8: { // subfc rD, rA, rB (rD = ~rA + rB + 1 = rB - rA)
                        uint32_t a_val = GetGPR(ctx, a).u32;
                        uint32_t b_val = GetGPR(ctx, b).u32;
                        uint32_t res = b_val - a_val;
                        ctx.xer.ca = (b_val >= a_val) ? 1 : 0;
                        GetGPR(ctx, d).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 10: { // addc rD, rA, rB
                        uint32_t a_val = GetGPR(ctx, a).u32;
                        uint32_t b_val = GetGPR(ctx, b).u32;
                        uint64_t sum = static_cast<uint64_t>(a_val) + b_val;
                        ctx.xer.ca = (sum > 0xFFFFFFFFULL) ? 1 : 0;
                        GetGPR(ctx, d).u64 = static_cast<uint32_t>(sum);
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(sum));
                        break;
                    }
                    case 40: { // subf rD, rA, rB (rD = rB - rA)
                        uint32_t res = GetGPR(ctx, b).u32 - GetGPR(ctx, a).u32;
                        GetGPR(ctx, d).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 136: { // subfe rD, rA, rB (rD = ~rA + rB + CA)
                        uint32_t a_val = GetGPR(ctx, a).u32;
                        uint32_t b_val = GetGPR(ctx, b).u32;
                        uint64_t full = static_cast<uint64_t>(~a_val) + b_val + ctx.xer.ca;
                        uint32_t res = static_cast<uint32_t>(full);
                        ctx.xer.ca = (full > 0xFFFFFFFFULL) ? 1 : 0;
                        GetGPR(ctx, d).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 138: { // adde rD, rA, rB (rD = rA + rB + CA)
                        uint32_t a_val = GetGPR(ctx, a).u32;
                        uint32_t b_val = GetGPR(ctx, b).u32;
                        uint64_t full = static_cast<uint64_t>(a_val) + b_val + ctx.xer.ca;
                        uint32_t res = static_cast<uint32_t>(full);
                        ctx.xer.ca = (full > 0xFFFFFFFFULL) ? 1 : 0;
                        GetGPR(ctx, d).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 266: { // add rD, rA, rB
                        uint32_t res = GetGPR(ctx, a).u32 + GetGPR(ctx, b).u32;
                        GetGPR(ctx, d).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 444: { // or rA, rS, rB (includes mr rA, rS: or rA, rS, rS)
                        uint64_t res = GetGPR(ctx, s).u64 | GetGPR(ctx, b).u64;
                        GetGPR(ctx, a).u64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 316: { // xor rA, rS, rB
                        uint64_t res = GetGPR(ctx, s).u64 ^ GetGPR(ctx, b).u64;
                        GetGPR(ctx, a).u64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 28: { // and rA, rS, rB
                        uint64_t res = GetGPR(ctx, s).u64 & GetGPR(ctx, b).u64;
                        GetGPR(ctx, a).u64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 60: { // andc rA, rS, rB (rA = rS & ~rB)
                        uint64_t res = GetGPR(ctx, s).u64 & (~GetGPR(ctx, b).u64);
                        GetGPR(ctx, a).u64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 124: { // nor rA, rS, rB (includes not: nor rA, rS, rS)
                        uint64_t res = ~(GetGPR(ctx, s).u64 | GetGPR(ctx, b).u64);
                        GetGPR(ctx, a).u64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 104: { // neg rD, rA
                        uint32_t res = -GetGPR(ctx, a).u32;
                        GetGPR(ctx, d).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 235: { // mullw rD, rA, rB
                        int32_t res = GetGPR(ctx, a).s32 * GetGPR(ctx, b).s32;
                        GetGPR(ctx, d).s64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 491: { // divw rD, rA, rB
                        int32_t b_val = GetGPR(ctx, b).s32;
                        int32_t res = (b_val != 0) ? (GetGPR(ctx, a).s32 / b_val) : 0;
                        GetGPR(ctx, d).s64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 459: { // divwu rD, rA, rB
                        uint32_t b_val = GetGPR(ctx, b).u32;
                        uint32_t res = (b_val != 0) ? (GetGPR(ctx, a).u32 / b_val) : 0;
                        GetGPR(ctx, d).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 24: { // slw rA, rS, rB
                        uint32_t sh = GetGPR(ctx, b).u32;
                        uint32_t res = (sh & 0x20) ? 0 : (GetGPR(ctx, s).u32 << (sh & 0x1F));
                        GetGPR(ctx, a).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 536: { // srw rA, rS, rB
                        uint32_t sh = GetGPR(ctx, b).u32;
                        uint32_t res = (sh & 0x20) ? 0 : (GetGPR(ctx, s).u32 >> (sh & 0x1F));
                        GetGPR(ctx, a).u64 = res;
                        if (rc) UpdateCR0(ctx, res);
                        break;
                    }
                    case 792: { // sraw rA, rS, rB
                        uint32_t sh = GetGPR(ctx, b).u32;
                        int32_t val = GetGPR(ctx, s).s32;
                        int32_t res = (sh & 0x20) ? ((val < 0) ? -1 : 0) : (val >> (sh & 0x1F));
                        GetGPR(ctx, a).s64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 824: { // srawi rA, rS, SH
                        uint32_t sh = (instr >> 11) & 0x1F;
                        int32_t res = GetGPR(ctx, s).s32 >> sh;
                        GetGPR(ctx, a).s64 = res;
                        if (rc) UpdateCR0(ctx, static_cast<uint32_t>(res));
                        break;
                    }
                    case 922: { // extsh rA, rS
                        GetGPR(ctx, a).s64 = static_cast<int16_t>(GetGPR(ctx, s).u16);
                        if (rc) UpdateCR0(ctx, GetGPR(ctx, a).u32);
                        break;
                    }
                    case 954: { // extsb rA, rS
                        GetGPR(ctx, a).s64 = static_cast<int8_t>(GetGPR(ctx, s).u8);
                        if (rc) UpdateCR0(ctx, GetGPR(ctx, a).u32);
                        break;
                    }
                    case 986: { // extsw rA, rS
                        GetGPR(ctx, a).s64 = GetGPR(ctx, s).s32;
                        if (rc) UpdateCR0(ctx, GetGPR(ctx, a).u32);
                        break;
                    }
                    case 26: { // cntlzw rA, rS
                        GetGPR(ctx, a).u64 = std::countl_zero(GetGPR(ctx, s).u32);
                        if (rc) UpdateCR0(ctx, GetGPR(ctx, a).u32);
                        break;
                    }
                    case 23: { // lwzx rD, rA, rB
                        uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + GetGPR(ctx, b).u32;
                        GetGPR(ctx, d).u64 = ReadGuestU32(base, ea);
                        break;
                    }
                    case 87: { // lbzx rD, rA, rB
                        uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + GetGPR(ctx, b).u32;
                        GetGPR(ctx, d).u64 = ReadGuestU8(base, ea);
                        break;
                    }
                    case 279: { // lhzx rD, rA, rB
                        uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + GetGPR(ctx, b).u32;
                        GetGPR(ctx, d).u64 = ReadGuestU16(base, ea);
                        break;
                    }
                    case 343: { // lhax rD, rA, rB
                        uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + GetGPR(ctx, b).u32;
                        GetGPR(ctx, d).s64 = static_cast<int16_t>(ReadGuestU16(base, ea));
                        break;
                    }
                    case 151: { // stwx rS, rA, rB
                        uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + GetGPR(ctx, b).u32;
                        WriteGuestU32(base, ea, GetGPR(ctx, s).u32);
                        break;
                    }
                    case 215: { // stbx rS, rA, rB
                        uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + GetGPR(ctx, b).u32;
                        WriteGuestU8(base, ea, GetGPR(ctx, s).u8);
                        break;
                    }
                    case 407: { // sthx rS, rA, rB
                        uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + GetGPR(ctx, b).u32;
                        WriteGuestU16(base, ea, GetGPR(ctx, s).u16);
                        break;
                    }
                    case 467: { // mtspr
                        uint32_t spr = (((instr >> 11) & 0x1F) << 5) | ((instr >> 16) & 0x1F);
                        if (spr == 9) { // CTR
                            ctx.ctr.u64 = GetGPR(ctx, s).u64;
                        } else if (spr == 8) { // LR
                            ctx.lr = GetGPR(ctx, s).u64;
                        } else if (spr == 1) { // XER
                            ctx.xer.so = (GetGPR(ctx, s).u32 >> 31) & 1;
                            ctx.xer.ov = (GetGPR(ctx, s).u32 >> 30) & 1;
                            ctx.xer.ca = (GetGPR(ctx, s).u32 >> 29) & 1;
                        }
                        break;
                    }
                    case 339: { // mfspr
                        uint32_t spr = (((instr >> 11) & 0x1F) << 5) | ((instr >> 16) & 0x1F);
                        if (spr == 9) { // CTR
                            GetGPR(ctx, d).u64 = ctx.ctr.u64;
                        } else if (spr == 8) { // LR
                            GetGPR(ctx, d).u64 = ctx.lr;
                        } else if (spr == 1) { // XER
                            GetGPR(ctx, d).u64 = (static_cast<uint32_t>(ctx.xer.so) << 31) |
                                                 (static_cast<uint32_t>(ctx.xer.ov) << 30) |
                                                 (static_cast<uint32_t>(ctx.xer.ca) << 29);
                        }
                        break;
                    }
                    case 144: { // mtcrf FXM, rS
                        uint32_t fxm = (instr >> 12) & 0xFFu;
                        uint32_t val = GetGPR(ctx, s).u32;
                        for (uint32_t i = 0; i < 8; ++i) {
                            if (fxm & (0x80u >> i)) {
                                GetCRField(ctx, i).set_raw((val >> (28 - (i * 4))) & 0xFu);
                            }
                        }
                        break;
                    }
                    case 19: { // mfcr
                        uint32_t cr = 0;
                        for (uint32_t i = 0; i < 8; ++i) {
                            cr |= (GetCRField(ctx, i).raw() & 0xFu) << (28 - (i * 4));
                        }
                        GetGPR(ctx, d).u64 = cr;
                        break;
                    }
                    default:
                        return false; // Unhandled opcode 31
                }
                pc += 4;
                break;
            }
            case 32: { // lwz rD, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                GetGPR(ctx, d).u64 = ReadGuestU32(base, ea);
                pc += 4;
                break;
            }
            case 34: { // lbz rD, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                GetGPR(ctx, d).u64 = ReadGuestU8(base, ea);
                pc += 4;
                break;
            }
            case 35: { // lbzu rD, d(rA)
                uint32_t ea = GetGPR(ctx, a).u32 + simm;
                GetGPR(ctx, d).u64 = ReadGuestU8(base, ea);
                GetGPR(ctx, a).u64 = ea;
                pc += 4;
                break;
            }
            case 36: { // stw rS, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                WriteGuestU32(base, ea, GetGPR(ctx, s).u32);
                pc += 4;
                break;
            }
            case 37: { // stwu rS, d(rA)
                uint32_t ea = GetGPR(ctx, a).u32 + simm;
                WriteGuestU32(base, ea, GetGPR(ctx, s).u32);
                GetGPR(ctx, a).u64 = ea;
                pc += 4;
                break;
            }
            case 38: { // stb rS, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                WriteGuestU8(base, ea, GetGPR(ctx, s).u8);
                pc += 4;
                break;
            }
            case 40: { // lhz rD, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                GetGPR(ctx, d).u64 = ReadGuestU16(base, ea);
                pc += 4;
                break;
            }
            case 42: { // lha rD, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                GetGPR(ctx, d).s64 = static_cast<int16_t>(ReadGuestU16(base, ea));
                pc += 4;
                break;
            }
            case 44: { // sth rS, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                WriteGuestU16(base, ea, GetGPR(ctx, s).u16);
                pc += 4;
                break;
            }
            case 48: { // lfs frD, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                uint32_t val = ReadGuestU32(base, ea);
                GetFPR(ctx, d).f64 = static_cast<double>(std::bit_cast<float>(val));
                pc += 4;
                break;
            }
            case 50: { // lfd frD, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                uint64_t val = ReadGuestU64(base, ea);
                GetFPR(ctx, d).f64 = std::bit_cast<double>(val);
                pc += 4;
                break;
            }
            case 52: { // stfs frS, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                float fval = static_cast<float>(GetFPR(ctx, s).f64);
                WriteGuestU32(base, ea, std::bit_cast<uint32_t>(fval));
                pc += 4;
                break;
            }
            case 54: { // stfd frS, d(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + simm;
                WriteGuestU64(base, ea, std::bit_cast<uint64_t>(GetFPR(ctx, s).f64));
                pc += 4;
                break;
            }
            case 58: { // ld rD, ds(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + static_cast<int16_t>(instr & 0xFFFCu);
                GetGPR(ctx, d).u64 = ReadGuestU64(base, ea);
                pc += 4;
                break;
            }
            case 62: { // std rS, ds(rA)
                uint32_t ea = (a == 0 ? 0 : GetGPR(ctx, a).u32) + static_cast<int16_t>(instr & 0xFFFCu);
                WriteGuestU64(base, ea, GetGPR(ctx, s).u64);
                pc += 4;
                break;
            }
            case 63: { // Floating-point operations
                uint32_t xo = (instr >> 1) & 0x3FFu;
                uint32_t c = (instr >> 6) & 0x1F;
                if (xo == 72) { // fmr frD, frB
                    GetFPR(ctx, d).f64 = GetFPR(ctx, b).f64;
                } else if (xo == 40) { // fneg frD, frB
                    GetFPR(ctx, d).f64 = -GetFPR(ctx, b).f64;
                } else if (xo == 264) { // fabs frD, frB
                    GetFPR(ctx, d).f64 = std::abs(GetFPR(ctx, b).f64);
                } else if (xo == 21) { // fadds frD, frA, frB
                    GetFPR(ctx, d).f64 = static_cast<double>(static_cast<float>(GetFPR(ctx, a).f64 + GetFPR(ctx, b).f64));
                } else if (xo == 20) { // fsubs frD, frA, frB
                    GetFPR(ctx, d).f64 = static_cast<double>(static_cast<float>(GetFPR(ctx, a).f64 - GetFPR(ctx, b).f64));
                } else if (xo == 25) { // fmuls frD, frA, frC
                    GetFPR(ctx, d).f64 = static_cast<double>(static_cast<float>(GetFPR(ctx, a).f64 * GetFPR(ctx, c).f64));
                } else {
                    return false;
                }
                pc += 4;
                break;
            }
            default:
                return false; // Unhandled primary opcode
        }
    }
    return false; // Exceeded kMaxInstructions
}

extern "C" void SafeDispatchIndirect(PPCContext& ctx, uint8_t* base, uint32_t target_addr, uint32_t caller_lr) {
    RecordDispatchBreadcrumb(target_addr, caller_lr);

    if (__builtin_expect(target_addr == 0, 0)) {
        LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
        ctx.r3.u64 = 0;
        return;
    }

    // Allow legitimate recursion while guarding against infinite loops
    thread_local uint32_t tls_dispatch_depth = 0;
    if (__builtin_expect(tls_dispatch_depth >= 128, 0)) {
        LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
        ctx.r3.u64 = 0;
        return;
    }

    thread_local uint32_t tls_target_stack[128];
    uint32_t same_target_count = 0;
    for (uint32_t i = 0; i < tls_dispatch_depth; ++i) {
        if (tls_target_stack[i] == target_addr) {
            if (++same_target_count >= 32) {
                LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
                ctx.r3.u64 = 0;
                return;
            }
        }
    }

    tls_target_stack[tls_dispatch_depth++] = target_addr;
    struct ScopedDepthGuard {
        ~ScopedDepthGuard() { --tls_dispatch_depth; }
    } depth_guard;

    // Safety translation: If a rebased module calls an unrelocated address in 0x82010000..0x8203FFFF
    if (caller_lr >= 0x82C00000 && target_addr >= 0x82010000 && target_addr < 0x82040000) {
        const auto* mod = l4d2::ModuleLoader::Instance().FindModuleByAddress(caller_lr);
        if (mod && mod->image_base > 0x82000000) {
            uint32_t rebased_target = target_addr - 0x82000000 + mod->image_base;
            PPCFunc* rebased_fn = LookupGlobalFunction(base, rebased_target);
            if (rebased_fn) {
                target_addr = rebased_target;
            }
        }
    }

    if (__builtin_expect(target_addr == 0x832ABB08u, 0)) {
        ctx.r11.s64 = -2094071808; // lis r11, 0x832F
        ctx.r3.s64 = ctx.r11.s64 - 16012; // 0x832EC174 (MDLCache / VModelLoader singleton)
        return;
    }

    PPCFunc* fn = LookupGlobalFunction(base, target_addr);
    if (__builtin_expect(fn != nullptr, 1)) {
        fn(ctx, base);
        return;
    }

    // Try fallback in runtime FunctionDispatcher if not yet cached in global table
    rex::runtime::FunctionDispatcher* dispatcher = nullptr;
    if (auto* runtime = rex::Runtime::instance()) {
        dispatcher = runtime->function_dispatcher();
    }
    if (dispatcher) {
        fn = dispatcher->GetFunction(target_addr);
        if (fn) {
            if (g_global_func_table && target_addr >= kGlobalFuncTableBase && target_addr < kGlobalFuncTableEnd) {
                g_global_func_table[(target_addr - kGlobalFuncTableBase) >> 2] = fn;
            }
            fn(ctx, base);
            return;
        }
    }

    // Dynamic PowerPC Leaf Thunk Execution for uncompiled interface/virtual wrappers
    if (base && (target_addr & 3) == 0 && target_addr >= 0x82000000 && target_addr < 0x90000000) {
        const uint32_t* p = reinterpret_cast<const uint32_t*>(base + target_addr);
        uint32_t i0 = __builtin_bswap32(p[0]);
        uint32_t i1 = __builtin_bswap32(p[1]);
        uint32_t i2 = __builtin_bswap32(p[2]);
        uint32_t i3 = __builtin_bswap32(p[3]);

        // Pattern 1: 4-instruction Virtual Call Thunk (C++ interface dispatch)
        // lwz r12, 0(r3)      (0x81830000)
        // lwz r11, offset(r12)(0x816Cxxxx)
        // mtctr r11           (0x7D6903A6)
        // bctr                (0x4E800420)
        if (i0 == 0x81830000u && (i1 & 0xFFFF0000u) == 0x816C0000u &&
            i2 == 0x7D6903A6u && i3 == 0x4E800420u) {
            uint32_t this_ptr = ctx.r3.u32;
            if (this_ptr != 0) {
                uint32_t vtable = __builtin_bswap32(*reinterpret_cast<const uint32_t*>(base + this_ptr));
                int16_t offset = static_cast<int16_t>(i1 & 0xFFFFu);
                uint32_t method = __builtin_bswap32(*reinterpret_cast<const uint32_t*>(base + vtable + offset));
                ctx.r12.u64 = vtable;
                ctx.r11.u64 = method;
                ctx.ctr.u64 = method;
                SafeDispatchIndirect(ctx, base, method, caller_lr);
                return;
            }
        }

        // Pattern 2: Import Trampoline (lis r11, HIGH; ori r11, r11, LOW)
        if ((i0 & 0xFFFF0000u) == 0x3D600000u && (i1 & 0xFFFF0000u) == 0x616B0000u) {
            uint32_t target_guest = ((i0 & 0xFFFFu) << 16) | (i1 & 0xFFFFu);
            if (target_guest != target_addr) {
                ctx.r11.u64 = target_guest;
                ctx.ctr.u64 = target_guest;
                SafeDispatchIndirect(ctx, base, target_guest, caller_lr);
                return;
            }
        }

        // Dynamic PowerPC Leaf Interpreter: executes uncompiled leaf getters, setters,
        // bounds layout methods (e.g. vgui::Panel::SetBounds, GetBounds), visibility controls,
        // hierarchy traversals (HasParent), adjuster thunks, and container comparisons (CDefOps::Less).
        if (ExecutePPCLeaf(ctx, base, target_addr, caller_lr)) {
            return;
        }
    }

    LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
    ctx.r3.u64 = 0;
}

namespace rex::runtime { class IModuleRegistrar; }

#define DECLARE_MODULE_SYMBOLS(name) \
    void l4d2_##name##_RegisterFunctions(rex::runtime::IModuleRegistrar*); \
    extern const rex::PPCImageInfo l4d2_##name##_PPCImageConfig;

DECLARE_MODULE_SYMBOLS(default)
DECLARE_MODULE_SYMBOLS(engine)
DECLARE_MODULE_SYMBOLS(client)
DECLARE_MODULE_SYMBOLS(server)
DECLARE_MODULE_SYMBOLS(materialsystem)
DECLARE_MODULE_SYMBOLS(shaderapidx9)
DECLARE_MODULE_SYMBOLS(stdshader_dx9)
DECLARE_MODULE_SYMBOLS(studiorender)
DECLARE_MODULE_SYMBOLS(vphysics)
DECLARE_MODULE_SYMBOLS(soundemitter)
DECLARE_MODULE_SYMBOLS(datacache)
DECLARE_MODULE_SYMBOLS(scenefilecache)
DECLARE_MODULE_SYMBOLS(vgui2)
DECLARE_MODULE_SYMBOLS(vguimatsurface)
DECLARE_MODULE_SYMBOLS(inputsystem)
DECLARE_MODULE_SYMBOLS(filesystem)
DECLARE_MODULE_SYMBOLS(vstdlib)
DECLARE_MODULE_SYMBOLS(tier0)
DECLARE_MODULE_SYMBOLS(launcher)
DECLARE_MODULE_SYMBOLS(gameui)
DECLARE_MODULE_SYMBOLS(vscript)
DECLARE_MODULE_SYMBOLS(matchmaking)

// Left 4 Dead 2 default.xex entrypoint (0x82010CB8) calls 0x82010AD0 right after startup
// to verify PAL50 / AVPack video settings. On emulation/iOS, XGetAVPack() returns 0,
// which triggers an error dialog and causes default.xex to invoke XamLoaderTerminateTitle (exit code 1).
// Bypassing this check by returning ctx.r3 = 0 ensures the title proceeds directly to loc_82010D0C
// and initializes the Source Engine DLLs.
extern "C" void sub_82010AD0(PPCContext& ctx, [[maybe_unused]] uint8_t* base) {
    L4D2_LOG_INFO("Kernel", "Bypassing PAL50/AVPack video check in default.xex (0x82010AD0 -> r3 = 0)");
    ctx.r3.u64 = 0;
}

extern "C" void __imp__sub_82010AD0(PPCContext& ctx, uint8_t* base) {
    sub_82010AD0(ctx, base);
}

// Left 4 Dead 2 default.xex module listener notifications (0x82011120 and 0x82015D78)
// On retail Xbox 360, default.xex registers notification listeners during startup.
// In the recompiled environment, an uninitialized or circular listener node at 0x8202005C
// causes an unthrottled infinite spin loop at ~85M calls/sec between 0x82011170 and 0x82015D78.
// Short-circuiting both ensures default.xex advances cleanly without starving the main runloop.
extern "C" void sub_82015D78(PPCContext& ctx, [[maybe_unused]] uint8_t* base) {
    ctx.r3.u64 = 1;
}

extern "C" void __imp__sub_82015D78(PPCContext& ctx, uint8_t* base) {
    sub_82015D78(ctx, base);
}

extern "C" void sub_82011120(PPCContext& ctx, [[maybe_unused]] uint8_t* base) {
    L4D2_LOG_INFO("Kernel", "Bypassing NotifyModuleListeners in default.xex (0x82011120)");
    ctx.r3.u64 = 0;
}

extern "C" void __imp__sub_82011120(PPCContext& ctx, uint8_t* base) {
    sub_82011120(ctx, base);
}

// 1. tier0_360:0x1E5 (0x82C18D10) - memalloc setter
// lis r11, 0x82C6 (-2100953088); stw r3, 0x49B8(r11); blr
extern "C" void sub_82C18D10(PPCContext& ctx, uint8_t* base) {
    if (__builtin_expect(base != nullptr, 1)) {
        *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C649B8u) = static_cast<uint32_t>(ctx.r3.u32);
    }
}
extern "C" void __imp__sub_82C18D10(PPCContext& ctx, uint8_t* base) {
    sub_82C18D10(ctx, base);
}

// 2. tier0_360:0x24B (0x82C1AAC8) - leaf wrapper to sub_82C1A478
// li r7, 0; b 0x82C1A478
extern "C" void sub_82C1A478(PPCContext& __restrict ctx, uint8_t* base);
extern "C" void sub_82C1AAC8(PPCContext& ctx, uint8_t* base) {
    ctx.r7.s64 = 0;
    sub_82C1A478(ctx, base);
}
extern "C" void __imp__sub_82C1AAC8(PPCContext& ctx, uint8_t* base) {
    sub_82C1AAC8(ctx, base);
}

// 3. vstdlib_360:0x00F (0x82E1BEF0) - memalloc setter / fallback to sub_82E1BF04
// cmpli cr6, 0, r3, 0; beq cr6, 0x82E1BF04; lis r11, 0x82E3 (-2099052544); stw r3, 0x06D0(r11); blr
extern "C" void sub_82E1BF04(PPCContext& __restrict ctx, uint8_t* base);
extern "C" void sub_82E1BEF0(PPCContext& ctx, uint8_t* base) {
    if (ctx.r3.u32 == 0) {
        sub_82E1BF04(ctx, base);
        return;
    }
    if (__builtin_expect(base != nullptr, 1)) {
        *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E306D0u) = static_cast<uint32_t>(ctx.r3.u32);
    }
}
extern "C" void __imp__sub_82E1BEF0(PPCContext& ctx, uint8_t* base) {
    sub_82E1BEF0(ctx, base);
}

// 4. vstdlib_360:0x012 (0x82E1BF50) - vtable dispatch wrapper
// lis r11, 0x82E3; lwz r3, 0x06D0(r11); lwz r10, 0(r3); lwz r9, 12(r10); mtctr r9; bctr
extern "C" void sub_82E1BF50(PPCContext& ctx, uint8_t* base) {
    if (__builtin_expect(base != nullptr, 1)) {
        uint32_t r3_val = rex::byte_swap(*reinterpret_cast<const uint32_t*>(base + 0x82E306D0u));
        uint32_t r10_val = rex::byte_swap(*reinterpret_cast<const uint32_t*>(base + r3_val));
        uint32_t r9_val = rex::byte_swap(*reinterpret_cast<const uint32_t*>(base + r10_val + 12));
        ctx.r3.u64 = r3_val;
        ctx.r10.u64 = r10_val;
        ctx.r9.u64 = r9_val;
        ctx.ctr.u64 = r9_val;
        SafeDispatchIndirect(ctx, base, r9_val, static_cast<uint32_t>(ctx.lr));
    }
}
extern "C" void __imp__sub_82E1BF50(PPCContext& ctx, uint8_t* base) {
    sub_82E1BF50(ctx, base);
}

// 5. datacache_360:0x832ABB08 - MDLCache / VModelLoader singleton factory thunk
// lis r11, 0x832F (-2094071808); addi r3, r11, -16012 (0x832EC174); blr
extern "C" void sub_832ABB08(PPCContext& ctx, uint8_t* base) {
    ctx.r11.s64 = -2094071808;
    ctx.r3.s64 = ctx.r11.s64 - 16012;
}
extern "C" void __imp__sub_832ABB08(PPCContext& ctx, uint8_t* base) {
    sub_832ABB08(ctx, base);
}

namespace l4d2 {

namespace fs = std::filesystem;

ModuleLoader& ModuleLoader::Instance() {
    static ModuleLoader instance;
    return instance;
}

void ModuleLoader::Init(const std::string& game_root, const std::string& save_root) {
    game_root_ = game_root;
    save_root_ = save_root.empty() ? (game_root + "/SAVE") : save_root;
    cfg_root_  = save_root_ + "/cfg";

    try {
        fs::create_directories(save_root_);
        fs::create_directories(cfg_root_);
    } catch (const std::exception& e) {
        L4D2_LOG_WARN("VFS", "Failed to create save directories: %s", e.what());
    }

    loaded_modules_.clear();
    module_index_by_name_.clear();

    for (const auto& desc : kSourceModules) {
        LoadedModule mod;
        mod.name = desc.module_name;
        mod.path = desc.relative_path;
        mod.image_base = desc.image_base;
        mod.image_end = desc.image_end;
        mod.is_loaded = false;

        size_t idx = loaded_modules_.size();
        loaded_modules_.push_back(mod);

        // Map by name (e.g. "engine_360.dll", "engine_360", "bin\engine_360.dll")
        std::string lower_name = desc.module_name;
        std::transform(lower_name.begin(), lower_name.end(), lower_name.begin(), ::tolower);
        module_index_by_name_[lower_name] = idx;
        module_index_by_name_[lower_name + ".dll"] = idx;

        std::string rel_lower = desc.relative_path;
        std::transform(rel_lower.begin(), rel_lower.end(), rel_lower.begin(), ::tolower);
        module_index_by_name_[rel_lower] = idx;
    }

    L4D2_LOG_INFO("ModuleLoader", "Initialized Source Engine module index with %zu modules", loaded_modules_.size());
}

void ModuleLoader::RegisterRecompiledModules(rex::system::KernelState* kernel_state) {
    if (!kernel_state) {
        L4D2_LOG_ERROR("ModuleLoader", "Cannot register recompiled modules: KernelState is null");
        return;
    }
    auto* dispatcher = kernel_state->function_dispatcher();
    if (!dispatcher) {
        L4D2_LOG_ERROR("ModuleLoader", "Cannot register recompiled modules: FunctionDispatcher is null");
        return;
    }

    // 1. Initialize unified global function table (448 MB virtual memory covering 0x82000000..0x90000000)
    InitializeGlobalFunctionTable();

    // Register watchdog ring buffer dump callback with rexruntime if available
#if defined(_WIN32) && defined(L4D2_USE_REXGLUE)
    RexRegisterDumpRingBufferCallback(&DumpDispatchRingBuffer);
#else
    if (RexRegisterDumpRingBufferCallback) {
        RexRegisterDumpRingBufferCallback(&DumpDispatchRingBuffer);
    }
#endif

#if !defined(_WIN32)
    // 0. Pre-initialize critical cross-DLL variables and default allocator pointers in guest memory
    if (auto* mem = kernel_state->memory()) {
        uint8_t* base = mem->virtual_membase();
        if (base) {
            // tier0_360.dll allocator pointers:
            // 0x82C406CC holds &g_DefaultMemAlloc (0x82C406D0)
            // 0x82C406D0 holds &CStdMemAlloc::vtable (0x82C00BF4)
            // 0x82C00BF4 / 0x82C00BF8 holds CStdMemAlloc::Alloc (0x82C16CD0)
            // 0x82C42EB0 holds fallback allocator function sub_82C13FF0 (0x82C13FF0)
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C406CCu) = 0x82C406D0u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C406D0u) = 0x82C00BF4u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C00BF4u) = 0x82C16CD0u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C00BF8u) = 0x82C16CD0u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C42EB0u) = 0x82C13FF0u;

            // vstdlib_360.dll cross-DLL variable imports from tier0_360.dll:
            // 0x82E0046C (ord 0xEA, g_pMemAlloc) -> 0x82C406CC
            // 0x82E0047C (ord 0x2EA) -> 0x82C64C3C
            // 0x82E00484 (ord 0x78)  -> 0x82C446D8
            // 0x82E004A4 (ord 0x341) -> 0x82C434AC
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E0046Cu) = 0x82C406CCu;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E0047Cu) = 0x82C64C3Cu;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E00484u) = 0x82C446D8u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E004A4u) = 0x82C434ACu;

            // vstdlib_360.dll internal memalloc pointer:
            // 0x82E306D0 holds pointer to IMemAlloc (0x82C406D0)
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E306D0u) = 0x82C406D0u;

            // engine_360.dll's IMemAlloc holder is still null when its first
            // allocation runs during client startup. The crash trace shows the
            // holder at 0x871C0000, reached from the engine allocator thunk.
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x871C0000u) = 0x82C406D0u;

            // Apply guest data relocations across all rebased module ranges
            for (const auto& desc : kSourceModules) {
                if (desc.image_base > 0x82000000 && desc.image_end > desc.image_base) {
                    const uint32_t delta = desc.image_base - 0x82000000;
                    const uint32_t span = desc.image_end - desc.image_base;
                    uint8_t* start = base + desc.image_base;
                    size_t word_count = span / 4;
                    auto* words = reinterpret_cast<rex::be<uint32_t>*>(start);
                    uint32_t count = 0;
                    for (size_t i = 0; i < word_count; ++i) {
                        uint32_t val = words[i];
                        if (val >= 0x82000000 && val < 0x82000000 + span) {
                            words[i] = val + delta;
                            ++count;
                        }
                    }
                    if (count > 0) {
                        L4D2_LOG_INFO("ModuleLoader", "Relocated %u data pointers in guest memory for %s at 0x%08X",
                                      count, desc.module_name, desc.image_base);
                    }
                }
            }

            L4D2_LOG_INFO("ModuleLoader", "Pre-initialized tier0/vstdlib/engine allocator pointers and cross-DLL variables");
        }
    }
#endif

    // Pre-populate default.xex compiled functions into global table
    if (g_global_func_table && l4d2_default_PPCImageConfig.func_mappings) {
        for (const auto* m = l4d2_default_PPCImageConfig.func_mappings; m && m->host != nullptr; ++m) {
            if (m->guest >= kGlobalFuncTableBase && m->guest < kGlobalFuncTableEnd) {
                g_global_func_table[(m->guest - kGlobalFuncTableBase) >> 2] = m->host;
            }
        }
    }

    // Explicitly override 0x82010AD0 (PAL50 / AVPack video check in default.xex)
    // so default.xex proceeds to CRT initialization and LauncherMain without aborting with exit code 1.
    dispatcher->SetFunction(0x82010AD0, &sub_82010AD0);
    if (g_global_func_table) {
        g_global_func_table[(0x82010AD0 - kGlobalFuncTableBase) >> 2] = &sub_82010AD0;
    }

    // 2. Register all 21 compiled non-entrypoint modules into FunctionDispatcher and global table FIRST
    struct RecompModuleBinding {
        const char* module_id;
        const rex::PPCImageInfo* image;
        rex::runtime::FunctionDispatcher::RegisterFn register_fn;
    };

    // Organized in dependency order: tier0, vstdlib, filesystem, launcher first
    static const RecompModuleBinding kBindings[] = {
        {"tier0_360.dll", &l4d2_tier0_PPCImageConfig, l4d2_tier0_RegisterFunctions},
        {"vstdlib_360.dll", &l4d2_vstdlib_PPCImageConfig, l4d2_vstdlib_RegisterFunctions},
        {"FileSystem_Stdio_360.dll", &l4d2_filesystem_PPCImageConfig, l4d2_filesystem_RegisterFunctions},
        {"launcher_360.dll", &l4d2_launcher_PPCImageConfig, l4d2_launcher_RegisterFunctions},
        {"datacache_360.dll", &l4d2_datacache_PPCImageConfig, l4d2_datacache_RegisterFunctions},
        {"vphysics_360.dll", &l4d2_vphysics_PPCImageConfig, l4d2_vphysics_RegisterFunctions},
        {"MaterialSystem_360.dll", &l4d2_materialsystem_PPCImageConfig, l4d2_materialsystem_RegisterFunctions},
        {"shaderapidx9_360.dll", &l4d2_shaderapidx9_PPCImageConfig, l4d2_shaderapidx9_RegisterFunctions},
        {"stdshader_dx9_360.dll", &l4d2_stdshader_dx9_PPCImageConfig, l4d2_stdshader_dx9_RegisterFunctions},
        {"StudioRender_360.dll", &l4d2_studiorender_PPCImageConfig, l4d2_studiorender_RegisterFunctions},
        {"SoundEmitterSystem_360.dll", &l4d2_soundemitter_PPCImageConfig, l4d2_soundemitter_RegisterFunctions},
        {"SceneFileCache_360.dll", &l4d2_scenefilecache_PPCImageConfig, l4d2_scenefilecache_RegisterFunctions},
        {"vgui2_360.dll", &l4d2_vgui2_PPCImageConfig, l4d2_vgui2_RegisterFunctions},
        {"vguimatsurface_360.dll", &l4d2_vguimatsurface_PPCImageConfig, l4d2_vguimatsurface_RegisterFunctions},
        {"inputsystem_360.dll", &l4d2_inputsystem_PPCImageConfig, l4d2_inputsystem_RegisterFunctions},
        {"vscript_360.dll", &l4d2_vscript_PPCImageConfig, l4d2_vscript_RegisterFunctions},
        {"GameUI_360.dll", &l4d2_gameui_PPCImageConfig, l4d2_gameui_RegisterFunctions},
        {"engine_360.dll", &l4d2_engine_PPCImageConfig, l4d2_engine_RegisterFunctions},
        {"client_360.dll", &l4d2_client_PPCImageConfig, l4d2_client_RegisterFunctions},
        {"server_360.dll", &l4d2_server_PPCImageConfig, l4d2_server_RegisterFunctions},
        {"matchmaking_360.dll", &l4d2_matchmaking_PPCImageConfig, l4d2_matchmaking_RegisterFunctions},
    };

    uint32_t registered = 0;
    for (const auto& binding : kBindings) {
        const auto& image = *binding.image;
        if (!dispatcher->InitializeFunctionTable(image.code_base, image.code_size,
                                                 image.image_base, image.image_size)) {
            L4D2_LOG_ERROR("ModuleLoader", "Failed to initialize function table for %s (code=%08X image=%08X)",
                           binding.module_id, image.code_base, image.image_base);
            continue;
        }

        // Populate unified global function table directly from func_mappings
        if (g_global_func_table && image.func_mappings) {
            for (const auto* m = image.func_mappings; m && m->host != nullptr; ++m) {
                if (m->guest >= kGlobalFuncTableBase && m->guest < kGlobalFuncTableEnd) {
                    g_global_func_table[(m->guest - kGlobalFuncTableBase) >> 2] = m->host;
                }
            }
        }

        dispatcher->RegisterModule(binding.module_id, image.code_base, binding.register_fn);
        ++registered;
        L4D2_LOG_INFO("ModuleLoader", "Registered compiled functions for %s: code=%08X-%08X image=%08X+%08X",
                      binding.module_id, image.code_base, image.code_base + image.code_size,
                      image.image_base, image.image_size);
    }
    L4D2_LOG_INFO("ModuleLoader", "Registered %u compiled non-entrypoint modules into unified function table", registered);

    // 3. Register exported leaf functions (tier0_360, vstdlib_360)
    auto register_leaf = [&](uint32_t addr, PPCFunc* fn, const char* name) {
        dispatcher->SetFunction(addr, fn);
        if (g_global_func_table && addr >= kGlobalFuncTableBase && addr < kGlobalFuncTableEnd) {
            g_global_func_table[(addr - kGlobalFuncTableBase) >> 2] = fn;
        }
        L4D2_LOG_INFO("ModuleLoader", "Registered exported leaf function %s at 0x%08X", name, addr);
    };
    register_leaf(0x82C18D10, &sub_82C18D10, "tier0_360:0x1E5 (sub_82C18D10)");
    register_leaf(0x82C1AAC8, &sub_82C1AAC8, "tier0_360:0x24B (sub_82C1AAC8)");
    register_leaf(0x82E1BEF0, &sub_82E1BEF0, "vstdlib_360:0x00F (sub_82E1BEF0)");
    register_leaf(0x82E1BF50, &sub_82E1BF50, "vstdlib_360:0x012 (sub_82E1BF50)");
    register_leaf(0x82015D78, &sub_82015D78, "default:0x82015D78 (sub_82015D78)");
    register_leaf(0x82011120, &sub_82011120, "default:0x82011120 (NotifyModuleListeners)");
    register_leaf(0x832ABB08, &sub_832ABB08, "datacache_360:0x832ABB08 (MDLCacheFactory)");
}

void ModuleLoader::Shutdown() {
    for (auto& mod : loaded_modules_) {
        mod.is_loaded = false;
        mod.create_interface = nullptr;
        mod.named_exports.clear();
        mod.ordinal_exports.clear();
    }
}

void ModuleLoader::PreloadSourceModules(rex::system::KernelState* kernel_state) {
    if (!kernel_state) return;

    L4D2_LOG_INFO("ModuleLoader", "Pass 1: Pre-loading all Source Engine modules and wiring cross-DLL imports...");
    auto preload_one = [&](const ModuleDescriptor& desc) {
        std::string p = desc.relative_path;
        std::replace(p.begin(), p.end(), '/', '\\');
        std::string guest_path = "d:\\" + p;
        auto mod = kernel_state->LoadUserModule(guest_path, /*call_entry=*/false);
        if (!mod) {
            mod = kernel_state->LoadUserModule(desc.relative_path, /*call_entry=*/false);
        }
        if (mod) {
            L4D2_LOG_INFO("ModuleLoader", "Pass 1: Preloaded '%s' (%s) at 0x%08X - imports wired",
                          desc.module_name, guest_path.c_str(), desc.image_base);
        } else {
            L4D2_LOG_DEBUG("ModuleLoader", "Pass 1: Module '%s' will be loaded on demand", desc.module_name);
        }
    };

    // Load dependency roots (tier0_360, then vstdlib_360) before dependents such as vphysics_360.
    for (const char* priority_mod : {"tier0_360", "vstdlib_360"}) {
        for (const auto& desc : kSourceModules) {
            if (strcmp(desc.module_name, priority_mod) == 0) {
                preload_one(desc);
                break;
            }
        }
    }
    for (const auto& desc : kSourceModules) {
        if (strcmp(desc.module_name, "default") == 0 ||
            strcmp(desc.module_name, "tier0_360") == 0 ||
            strcmp(desc.module_name, "vstdlib_360") == 0) {
            continue;
        }
        preload_one(desc);
    }
    L4D2_LOG_INFO("ModuleLoader", "Pass 1 complete: All modules pre-mapped and cross-DLL imports wired");
    // Patch fallback allocator pointers after Pass 1 has mapped each module's pages.
    // On Windows, verify page commit and protection; on POSIX/iOS the arena is already mapped.
    if (auto* mem = kernel_state->memory()) {
        if (uint8_t* base = mem->virtual_membase()) {
            const struct { uint32_t addr; uint32_t fallback; } kFallbackSlots[] = {
                {0x82C406CCu, 0x82C406D0u},
                {0x82C406D0u, 0x82C00BF4u},
                {0x82C00BF4u, 0x82C16CD0u},
                {0x82C00BF8u, 0x82C16CD0u},
                {0x82C42EB0u, 0x82C13FF0u},
                {0x82E0046Cu, 0x82C406CCu},
                {0x82E0047Cu, 0x82C64C3Cu},
                {0x82E00484u, 0x82C446D8u},
                {0x82E004A4u, 0x82C434ACu},
                {0x82E306D0u, 0x82C406D0u},
                {0x871C0000u, 0x82C406D0u},
            };
            for (const auto& s : kFallbackSlots) {
                bool is_committed_and_writable = true;
#if defined(_WIN32)
                MEMORY_BASIC_INFORMATION mbi{};
                if (VirtualQuery(base + s.addr, &mbi, sizeof(mbi)) != sizeof(mbi) ||
                    mbi.State != MEM_COMMIT) {
                    is_committed_and_writable = false;
                } else {
                    const DWORD writable_mask =
                        PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
                    if ((mbi.Protect & writable_mask) == 0) {
                        is_committed_and_writable = false;
                    }
                }
#endif
                if (is_committed_and_writable) {
                    auto* slot = reinterpret_cast<rex::be<uint32_t>*>(base + s.addr);
                    uint32_t cur = static_cast<uint32_t>(*slot);
                    if (cur == 0) {
                        *slot = s.fallback;
                        L4D2_LOG_INFO("ModuleLoader", "Patched null allocator fallback slot 0x%08X -> 0x%08X",
                                      s.addr, s.fallback);
                    } else {
                        L4D2_LOG_INFO("ModuleLoader", "Post-preload slot 0x%08X current=0x%08X",
                                      s.addr, cur);
                    }
                }
            }
        }
    }
    rex::FlushLogging();
}

std::string ModuleLoader::ResolveVFSPath(const std::string& guest_path, bool write_access) {
    std::string p = guest_path;
    std::replace(p.begin(), p.end(), '\\', '/');

    std::string lower = p;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    // 1. Check for expected retail missing directories (cache:, update:)
    if (lower.rfind("cache:/", 0) == 0 || lower == "cache:" ||
        lower.rfind("update:/", 0) == 0 || lower == "update:") {
        // Return empty so callers get STATUS_NO_SUCH_FILE
        return "";
    }

    // 2. Check for debug monitor vxbdm_360.dll
    if (lower.find("vxbdm_360.dll") != std::string::npos) {
        return "";
    }

    // 3. Writable saves & configs (redirect to sandbox Documents/rex_data)
    if (lower.find("/save/") != std::string::npos || lower.rfind("d:/left4dead2/save", 0) == 0) {
        std::string sub = p.substr(p.find("save/") + 5);
        return save_root_ + "/" + sub;
    }
    if (lower.find("/cfg/") != std::string::npos || lower.rfind("d:/left4dead2/cfg", 0) == 0) {
        std::string sub = p.substr(p.find("cfg/") + 4);
        return cfg_root_ + "/" + sub;
    }

    // 4. Strip game: or d: prefixes
    std::string stripped = p;
    if (lower.rfind("game:/", 0) == 0) {
        stripped = p.substr(6);
    } else if (lower.rfind("d:/", 0) == 0) {
        stripped = p.substr(3);
    }

    return game_root_ + "/" + stripped;
}

uint32_t ModuleLoader::XexLoadImage(const char* module_path, uint32_t flags, uint32_t min_version, void** module_handle) {
    if (!module_path || !module_handle) {
        return STATUS_UNSUCCESSFUL;
    }

    std::string mp(module_path);
    std::replace(mp.begin(), mp.end(), '\\', '/');
    std::string lower = mp;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    // Filter out expected retail missing files
    if (lower.find("vxbdm_360.dll") != std::string::npos ||
        lower.rfind("cache:/", 0) == 0 ||
        lower.rfind("update:/", 0) == 0) {
        L4D2_LOG_DEBUG("ModuleLoader", "Gracefully returning STATUS_NO_SUCH_FILE for retail missing module: %s", module_path);
        *module_handle = nullptr;
        return STATUS_NO_SUCH_FILE;
    }

    // Extract filename from path
    std::string filename = mp;
    size_t last_slash = mp.rfind('/');
    if (last_slash != std::string::npos) {
        filename = mp.substr(last_slash + 1);
    }
    std::string fname_lower = filename;
    std::transform(fname_lower.begin(), fname_lower.end(), fname_lower.begin(), ::tolower);

    auto it = module_index_by_name_.find(fname_lower);
    if (it == module_index_by_name_.end()) {
        // Strip .dll and check again
        if (fname_lower.size() > 4 && fname_lower.substr(fname_lower.size() - 4) == ".dll") {
            it = module_index_by_name_.find(fname_lower.substr(0, fname_lower.size() - 4));
        }
    }

    if (it == module_index_by_name_.end()) {
        L4D2_LOG_WARN("ModuleLoader", "XexLoadImage: Unknown module requested '%s'", module_path);
        *module_handle = nullptr;
        return STATUS_NO_SUCH_FILE;
    }

    LoadedModule& mod = loaded_modules_[it->second];
    mod.is_loaded = true;

    L4D2_LOG_INFO("ModuleLoader", "XexLoadImage: Loaded '%s' mapped at [0x%08X - 0x%08X]",
                  mod.name.c_str(), mod.image_base, mod.image_end);
    rex::FlushLogging();

    *module_handle = reinterpret_cast<void*>(static_cast<uintptr_t>(mod.image_base));
    return STATUS_SUCCESS;
}

void* ModuleLoader::XexGetProcedureAddress(void* module_handle, uint32_t ordinal, const char* name) {
    uint32_t base = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(module_handle));
    const ModuleDescriptor* desc = FindModuleByAddress(base);

    if (!desc) {
        L4D2_LOG_WARN("ModuleLoader", "XexGetProcedureAddress: Invalid module handle 0x%08X", base);
        return nullptr;
    }

    // In Source Engine Xbox 360 DLLs, CreateInterface is ordinal 1 or named "CreateInterface"
    if (ordinal == 1 || (name && strcmp(name, "CreateInterface") == 0)) {
        L4D2_LOG_DEBUG("ModuleLoader", "XexGetProcedureAddress: Resolved 'CreateInterface' for %s", desc->module_name);
        // Returns the guest entrypoint for CreateInterface inside the module
        return reinterpret_cast<void*>(static_cast<uintptr_t>(desc->image_base + 0x1000));
    }

    L4D2_LOG_DEBUG("ModuleLoader", "XexGetProcedureAddress: %s lookup ord=%u name=%s",
                   desc->module_name, ordinal, name ? name : "<null>");
    return nullptr;
}

const ModuleDescriptor* ModuleLoader::FindModuleByAddress(uint32_t guest_pc) const {
    for (const auto& desc : kSourceModules) {
        if (guest_pc >= desc.image_base && guest_pc < desc.image_end) {
            return &desc;
        }
    }
    return nullptr;
}

std::string ModuleLoader::SymbolicateAddress(uint32_t guest_pc) const {
    const ModuleDescriptor* desc = FindModuleByAddress(guest_pc);
    std::stringstream ss;
    if (desc) {
        uint32_t offset = guest_pc - desc->image_base;
        ss << desc->module_name << " + 0x" << std::hex << std::uppercase << offset
           << " (Base: 0x" << desc->image_base << ")";
    } else {
        ss << "0x" << std::hex << std::uppercase << guest_pc << " (Unknown guest region)";
    }
    return ss.str();
}

} // namespace l4d2
