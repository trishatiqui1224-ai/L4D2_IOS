#include "crash_handler.h"
#include "logging/logger.h"
#include "module_loader.h"

#include <cstdio>
#include <cstdlib>
#include <sstream>
#include <iomanip>

#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
#include <signal.h>
#include <unistd.h>
#include <dlfcn.h>
#include <execinfo.h>
#endif

#if defined(_WIN32)
#include <windows.h>
#include <dbghelp.h>
#endif

namespace l4d2 {

static GuestRegisters s_last_regs;
static bool s_has_regs = false;
static std::string s_boot_path = "boot.txt";

void CrashHandler::SetBootFilePath(const std::string& path) {
    if (!path.empty()) {
        s_boot_path = path;
    }
}

void CrashHandler::RecordIndirectCall(uint32_t target_pc, const char* hint) {
    char buf[128];
    snprintf(buf, sizeof(buf), "Call -> 0x%08X [%s]", target_pc, hint ? hint : "unknown");
    log::Logger::Instance().RecordBreadcrumb(buf);
}

void CrashHandler::DumpCrashState(int sig, const GuestRegisters* regs, const char* reason) {
    FILE* boot_file = fopen(s_boot_path.c_str(), "a");

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
        fclose(boot_file);
    }
}

#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
static uint8_t s_alt_stack[SIGSTKSZ * 4];

static void PosixSignalHandler(int sig, siginfo_t* info, void* ctx) {
    CrashHandler::DumpCrashState(sig, nullptr, "POSIX Signal Fault");
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
    L4D2_LOG_INFO("CrashHandler", "Installed POSIX sigaltstack crash handler");
}
#else
void CrashHandler::Install() {
    L4D2_LOG_INFO("CrashHandler", "Crash handler initialized");
}
#endif

} // namespace l4d2
