#include "crash_handler.h"
#include "logging/logger.h"
#include "module_loader.h"

#include <rex/system/thread_state.h>
#include <rex/ppc/context.h>

#include <cstdio>
#include <cstdlib>
#include <sstream>
#include <iomanip>

#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE 1
#endif
#include <signal.h>
#include <unistd.h>
#include <dlfcn.h>
#include <execinfo.h>
#endif

#if defined(_WIN32)
#include <windows.h>
#include <dbghelp.h>
#include <cstdlib>
#endif

namespace l4d2 {

static GuestRegisters s_last_regs;
static bool s_has_regs = false;
static std::string s_boot_path = "boot.txt";

void CrashHandler::SetBootFilePath(const std::string& path) {
    if (!path.empty()) {
        s_boot_path = path;
#if defined(_WIN32)
        _putenv_s("L4D2_BOOT_PATH", path.c_str());
        _putenv_s("NFSMW_SIGNAL_REPORT", path.c_str());
#else
        setenv("L4D2_BOOT_PATH", path.c_str(), 1);
        setenv("NFSMW_SIGNAL_REPORT", path.c_str(), 1);
#endif
    }
}

void CrashHandler::RecordIndirectCall(uint32_t target_pc, const char* hint) {
    char buf[128];
    snprintf(buf, sizeof(buf), "Call -> 0x%08X [%s]", target_pc, hint ? hint : "unknown");
    log::Logger::Instance().RecordBreadcrumb(buf);
}

void CrashHandler::DumpCrashState(int sig, const GuestRegisters* regs, const char* reason,
                                   void* siginfo_ptr, void* ucontext_ptr) {
    const char* bp = std::getenv("L4D2_BOOT_PATH");
    if (!bp) bp = std::getenv("NFSMW_SIGNAL_REPORT");
    std::string path_to_open = (bp && *bp) ? std::string(bp) : s_boot_path;
    FILE* boot_file = fopen(path_to_open.c_str(), "a");
    if (!boot_file) boot_file = fopen(s_boot_path.c_str(), "a");

    auto write_out = [&](const std::string& line) {
        L4D2_LOG_FATAL("CRASH", "%s", line.c_str());
        if (boot_file) {
            fprintf(boot_file, "[CRASH] %s\n", line.c_str());
            fflush(boot_file);
        }
    };

    write_out("================================================================================");
    write_out("  L4D2 RECOMP FATAL GUEST EXCEPTION REPORT");
    write_out("================================================================================");

    char sig_buf[128];
    snprintf(sig_buf, sizeof(sig_buf), "Signal: %d, Reason: %s", sig, reason ? reason : "Unknown");
    write_out(sig_buf);

#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
    if (siginfo_ptr) {
        siginfo_t* si = reinterpret_cast<siginfo_t*>(siginfo_ptr);
        char si_buf[256];
        snprintf(si_buf, sizeof(si_buf), "Faulting si_addr: %p (si_code: 0x%X)", si->si_addr, si->si_code);
        write_out(si_buf);
    }
#if defined(__APPLE__) && defined(__aarch64__)
    if (ucontext_ptr) {
        ucontext_t* uc = reinterpret_cast<ucontext_t*>(ucontext_ptr);
        auto mc = uc->uc_mcontext;
#if __DARWIN_OPAQUE_ARM_THREAD_STATE64
        uintptr_t host_pc = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_pc);
        uintptr_t host_lr = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_lr);
        uintptr_t host_sp = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_sp);
#else
        uintptr_t host_pc = mc->__ss.__pc;
        uintptr_t host_lr = mc->__ss.__lr;
        uintptr_t host_sp = mc->__ss.__sp;
#endif
        Dl_info dli_pc{};
        const char* pc_sym = (dladdr(reinterpret_cast<void*>(host_pc), &dli_pc) && dli_pc.dli_sname)
                                 ? dli_pc.dli_sname : "unknown";
        char pc_buf[256];
        snprintf(pc_buf, sizeof(pc_buf), "Host PC: 0x%016lX [%s]", (unsigned long)host_pc, pc_sym);
        write_out(pc_buf);

        Dl_info dli_lr{};
        const char* lr_sym = (dladdr(reinterpret_cast<void*>(host_lr), &dli_lr) && dli_lr.dli_sname)
                                 ? dli_lr.dli_sname : "unknown";
        char lr_buf[256];
        snprintf(lr_buf, sizeof(lr_buf), "Host LR (Caller): 0x%016lX [%s]", (unsigned long)host_lr, lr_sym);
        write_out(lr_buf);

        char sp_buf[128];
        snprintf(sp_buf, sizeof(sp_buf), "Host SP: 0x%016lX", (unsigned long)host_sp);
        write_out(sp_buf);
    }
#endif
#endif

    // Dump active guest thread registers from ReXGlue ThreadState if available
    auto* ts = rex::runtime::ThreadState::Get();
    if (ts && ts->context()) {
        auto* ctx = ts->context();
        char gr_buf[256];
        snprintf(gr_buf, sizeof(gr_buf), "Active Guest Thread Registers:\n  LR:  0x%08X  CTR: 0x%08X  R1: 0x%08X",
                 (uint32_t)ctx->lr, ctx->ctr.u32, ctx->r1.u32);
        write_out(gr_buf);

        snprintf(gr_buf, sizeof(gr_buf), "  r3:  0x%08X  r4:  0x%08X  r5:  0x%08X  r6: 0x%08X",
                 ctx->r3.u32, ctx->r4.u32, ctx->r5.u32, ctx->r6.u32);
        write_out(gr_buf);

        snprintf(gr_buf, sizeof(gr_buf), "  r7:  0x%08X  r8:  0x%08X  r9:  0x%08X  r10: 0x%08X  r11: 0x%08X  r12: 0x%08X",
                 ctx->r7.u32, ctx->r8.u32, ctx->r9.u32, ctx->r10.u32, ctx->r11.u32, ctx->r12.u32);
        write_out(gr_buf);
    }

    const GuestRegisters* r = regs ? regs : (s_has_regs ? &s_last_regs : nullptr);
    if (r) {
        std::string mod_sym = ModuleLoader::Instance().SymbolicateAddress(r->pc);
        char pc_buf[256];
        snprintf(pc_buf, sizeof(pc_buf), "Faulting Guest PC: 0x%08X in %s", r->pc, mod_sym.c_str());
        write_out(pc_buf);

        char reg_head[128];
        snprintf(reg_head, sizeof(reg_head), "LR: 0x%08X  CTR: 0x%08X  CR: 0x%08X  XER: 0x%08X",
                 r->lr, r->ctr, r->cr, r->xer);
        write_out(reg_head);

        for (int i = 0; i < 32; i += 4) {
            char r_line[128];
            snprintf(r_line, sizeof(r_line), "r%-2d: 0x%08X  r%-2d: 0x%08X  r%-2d: 0x%08X  r%-2d: 0x%08X",
                     i, r->r[i], i+1, r->r[i+1], i+2, r->r[i+2], i+3, r->r[i+3]);
            write_out(r_line);
        }
    }

    write_out("Recent Call Breadcrumbs (Last 16):");
    auto crumbs = log::Logger::Instance().GetRecentBreadcrumbs(16);
    for (size_t i = 0; i < crumbs.size(); ++i) {
        char c_buf[256];
        snprintf(c_buf, sizeof(c_buf), "  [%02zu] %s", i, crumbs[i].c_str());
        write_out(c_buf);
    }

#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
    write_out("Host Native Stack Trace (dladdr symbolicated):");
    void* callstack[64];
    int frames = backtrace(callstack, 64);
    for (int i = 0; i < frames; ++i) {
        Dl_info info;
        if (dladdr(callstack[i], &info) && info.dli_sname) {
            ptrdiff_t offset = (char*)callstack[i] - (char*)info.dli_saddr;
            char frame_buf[512];
            snprintf(frame_buf, sizeof(frame_buf), "  [%02d] %s + 0x%lx (%s)",
                     i, info.dli_sname, (unsigned long)offset, info.dli_fname ? info.dli_fname : "?");
            write_out(frame_buf);
        } else {
            char frame_buf[128];
            snprintf(frame_buf, sizeof(frame_buf), "  [%02d] %p", i, callstack[i]);
            write_out(frame_buf);
        }
    }
#endif

    write_out("================================================================================");
    log::Logger::Instance().Flush();
    if (boot_file) {
        fflush(boot_file);
#if !defined(_WIN32)
        fsync(fileno(boot_file));
#endif
        fclose(boot_file);
    }
}

#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
static uint8_t s_alt_stack[SIGSTKSZ * 4];

static void PosixSignalHandler(int sig, siginfo_t* info, void* ctx) {
    CrashHandler::DumpCrashState(sig, nullptr, "POSIX Signal Fault", info, ctx);
    _exit(128 + sig);
}

void CrashHandler::Install() {
    stack_t ss;
    ss.ss_sp = s_alt_stack;
    ss.ss_size = sizeof(s_alt_stack);
    ss.ss_flags = 0;
    sigaltstack(&ss, nullptr);

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = PosixSignalHandler;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);

    sigaction(SIGSEGV, &sa, nullptr);
    sigaction(SIGBUS,  &sa, nullptr);
    sigaction(SIGILL,  &sa, nullptr);
    sigaction(SIGFPE,  &sa, nullptr);
    sigaction(SIGABRT, &sa, nullptr);
#if defined(SIGTRAP)
    sigaction(SIGTRAP, &sa, nullptr);
#endif
    L4D2_LOG_INFO("CrashHandler", "Installed POSIX sigaltstack crash handler");
}
#else
void CrashHandler::Install() {
    L4D2_LOG_INFO("CrashHandler", "Crash handler initialized");
}
#endif

} // namespace l4d2
