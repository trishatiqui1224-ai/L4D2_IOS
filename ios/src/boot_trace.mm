#include "boot_trace.h"

#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>

#if defined(__APPLE__) && defined(__arm64__)
#include <sys/ucontext.h>
#endif

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <exception>
#include <initializer_list>
#include <string>
#include <utility>

namespace l4d2::boot {

namespace {

std::atomic<int> g_boot_fd{-1};
std::atomic<int> g_log_fd{-1};
struct sigaction g_previous[32];

thread_local uint32_t tl_last_ppc_fn = 0;
thread_local uint32_t tl_last_ppc_lr = 0;
thread_local uint32_t tl_last_ppc_r3 = 0;

struct PPCBreadcrumb {
    uint32_t fn;
    uint32_t lr;
    uint32_t r3;
    uint32_t count;
};
constexpr size_t kMaxBreadcrumbs = 16;
thread_local PPCBreadcrumb tl_breadcrumbs[kMaxBreadcrumbs] = {};
thread_local size_t tl_breadcrumb_head = 0;
thread_local size_t tl_breadcrumb_count = 0;

void WriteFdRaw(int fd, const char* text, size_t length) {
    if (fd < 0 || !text || length == 0) return;
    while (length > 0) {
        const ssize_t n = write(fd, text, length);
        if (n <= 0) {
            if (n < 0 && errno == EINTR) continue;
            return;
        }
        text += n;
        length -= size_t(n);
    }
}

void WriteBothRaw(const char* text, size_t length) {
    WriteFdRaw(g_boot_fd.load(std::memory_order_acquire), text, length);
    WriteFdRaw(g_log_fd.load(std::memory_order_acquire), text, length);
}

void OnSignal(int sig, siginfo_t* info, void* context) {
    char buf[2048];
    int len = 0;

    const char* sig_name = "?";
    switch (sig) {
        case SIGSEGV: sig_name = "SIGSEGV"; break;
        case SIGBUS:  sig_name = "SIGBUS"; break;
        case SIGABRT: sig_name = "SIGABRT"; break;
        case SIGILL:  sig_name = "SIGILL"; break;
        case SIGFPE:  sig_name = "SIGFPE"; break;
        case SIGTRAP: sig_name = "SIGTRAP"; break;
        default: break;
    }

    len += snprintf(buf + len, sizeof(buf) - len,
                    "\n==================== FATAL SIGNAL %d (%s) ====================\n"
                    "si_signo: %d, si_code: %d, faulting address: %p\n",
                    sig, sig_name, sig, info ? info->si_code : 0, info ? info->si_addr : nullptr);

#if defined(__APPLE__) && defined(__arm64__)
    if (context) {
        auto uctx = reinterpret_cast<ucontext_t*>(context);
        if (uctx && uctx->uc_mcontext) {
            auto mc = uctx->uc_mcontext;
            uintptr_t pc = 0, lr = 0, sp = 0, fp = 0;
#if defined(__DARWIN_OPAQUE_ARM_THREAD_STATE64) && __DARWIN_OPAQUE_ARM_THREAD_STATE64
            pc = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_pc);
            lr = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_lr);
            sp = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_sp);
            fp = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_fp);
#else
            pc = static_cast<uintptr_t>(mc->__ss.__pc);
            lr = static_cast<uintptr_t>(mc->__ss.__lr);
            sp = static_cast<uintptr_t>(mc->__ss.__sp);
            fp = static_cast<uintptr_t>(mc->__ss.__fp);
#endif
            Dl_info pc_info{};
            const char* pc_img = "unknown";
            const char* pc_sym = "?";
            uintptr_t pc_base = 0;
            uintptr_t pc_saddr = 0;
            if (dladdr(reinterpret_cast<void*>(pc), &pc_info)) {
                if (pc_info.dli_fname) pc_img = pc_info.dli_fname;
                pc_base = reinterpret_cast<uintptr_t>(pc_info.dli_fbase);
                if (pc_info.dli_sname) pc_sym = pc_info.dli_sname;
                pc_saddr = reinterpret_cast<uintptr_t>(pc_info.dli_saddr);
            }
            Dl_info lr_info{};
            const char* lr_img = "unknown";
            const char* lr_sym = "?";
            uintptr_t lr_base = 0;
            uintptr_t lr_saddr = 0;
            if (dladdr(reinterpret_cast<void*>(lr), &lr_info)) {
                if (lr_info.dli_fname) lr_img = lr_info.dli_fname;
                lr_base = reinterpret_cast<uintptr_t>(lr_info.dli_fbase);
                if (lr_info.dli_sname) lr_sym = lr_info.dli_sname;
                lr_saddr = reinterpret_cast<uintptr_t>(lr_info.dli_saddr);
            }
            intptr_t slide = _dyld_get_image_vmaddr_slide(0);
            len += snprintf(buf + len, sizeof(buf) - len,
                            "ARM64 Registers:\n"
                            "  pc: 0x%016llX (%s + 0x%llX [%s + 0x%llX], slide=0x%llX)\n"
                            "  lr: 0x%016llX (%s + 0x%llX [%s + 0x%llX])\n"
                            "  sp: 0x%016llX\n"
                            "  fp: 0x%016llX\n",
                            static_cast<unsigned long long>(pc), pc_img,
                            static_cast<unsigned long long>(pc - pc_base),
                            pc_sym, static_cast<unsigned long long>(pc_saddr ? (pc - pc_saddr) : 0),
                            static_cast<unsigned long long>(slide),
                            static_cast<unsigned long long>(lr), lr_img,
                            static_cast<unsigned long long>(lr - lr_base),
                            lr_sym, static_cast<unsigned long long>(lr_saddr ? (lr - lr_saddr) : 0),
                            static_cast<unsigned long long>(sp),
                            static_cast<unsigned long long>(fp));
        }
    }
#endif

    len += snprintf(buf + len, sizeof(buf) - len,
                    "PPC Guest Breadcrumbs:\n"
                    "  last_ppc_fn:  0x%08X\n"
                    "  last_ppc_lr:  0x%08X\n"
                    "  last_ppc_r3:  0x%08X\n",
                    tl_last_ppc_fn, tl_last_ppc_lr, tl_last_ppc_r3);
    len += FormatLastPPCBreadcrumbs(buf + len, sizeof(buf) - len);
    len += snprintf(buf + len, sizeof(buf) - len,
                    "==============================================================\n");

    if (len > 0) {
        WriteBothRaw(buf, size_t(len));
    }

    const struct sigaction& prev = g_previous[sig];
    if (prev.sa_flags & SA_SIGINFO) {
        if (prev.sa_sigaction) {
            prev.sa_sigaction(sig, info, context);
            return;
        }
    } else if (prev.sa_handler != SIG_DFL && prev.sa_handler != SIG_IGN && prev.sa_handler) {
        prev.sa_handler(sig);
        return;
    }
    signal(sig, SIG_DFL);
    raise(sig);
}

void OnTerminate() {
    std::string line = "FATAL std::terminate";
    if (auto e = std::current_exception()) {
        try {
            std::rethrow_exception(e);
        } catch (const std::exception& ex) {
            line += std::string(": uncaught exception: ") + ex.what();
        } catch (...) {
            line += ": uncaught exception of unknown type";
        }
    }
    line += "\n";
    WriteBothRaw(line.data(), line.size());
    std::abort();
}

std::atomic<bool> g_enabled{true};

} // namespace

void SetupAltStack() {
    stack_t ss{};
    void* stack_mem = std::malloc(65536);
    if (!stack_mem) return;
    ss.ss_sp = stack_mem;
    ss.ss_size = 65536;
    ss.ss_flags = 0;
    sigaltstack(&ss, nullptr);
}

void SetLastPPCBreadcrumb(uint32_t fn_addr, uint32_t lr, uint32_t r3) {
    tl_last_ppc_fn = fn_addr;
    if (lr != 0 || tl_last_ppc_lr == 0) tl_last_ppc_lr = lr;
    if (r3 != 0 || tl_last_ppc_r3 == 0) tl_last_ppc_r3 = r3;

    if (tl_breadcrumb_count > 0) {
        const size_t last_idx = (tl_breadcrumb_head + kMaxBreadcrumbs - 1) % kMaxBreadcrumbs;
        if (tl_breadcrumbs[last_idx].fn == fn_addr) {
            if (tl_breadcrumbs[last_idx].lr == 0 && lr != 0) {
                tl_breadcrumbs[last_idx].lr = lr;
                tl_breadcrumbs[last_idx].r3 = r3;
                return;
            }
            if (tl_breadcrumbs[last_idx].lr == lr) {
                tl_breadcrumbs[last_idx].r3 = r3;
                tl_breadcrumbs[last_idx].count++;
                return;
            }
        }
    }

    tl_breadcrumbs[tl_breadcrumb_head] = {fn_addr, lr, r3, 1};
    tl_breadcrumb_head = (tl_breadcrumb_head + 1) % kMaxBreadcrumbs;
    if (tl_breadcrumb_count < kMaxBreadcrumbs) {
        ++tl_breadcrumb_count;
    }
}

size_t FormatLastPPCBreadcrumbs(char* buf, size_t buf_size) {
    if (!buf || buf_size == 0) return 0;
    size_t written = 0;
    written += snprintf(buf + written, buf_size - written, "Last 16 PPC Guest Breadcrumbs:\n");
    if (tl_breadcrumb_count == 0) {
        written += snprintf(buf + written, buf_size - written, "  (none)\n");
        return written;
    }
    const size_t start = (tl_breadcrumb_head + kMaxBreadcrumbs - tl_breadcrumb_count) % kMaxBreadcrumbs;
    for (size_t i = 0; i < tl_breadcrumb_count && written < buf_size; ++i) {
        const size_t idx = (start + i) % kMaxBreadcrumbs;
        const auto& b = tl_breadcrumbs[idx];
        if (b.count > 1) {
            written += snprintf(buf + written, buf_size - written,
                                "  [%zu] fn=0x%08X lr=0x%08X r3=0x%08X (x%u)\n",
                                i, b.fn, b.lr, b.r3, b.count);
        } else {
            written += snprintf(buf + written, buf_size - written,
                                "  [%zu] fn=0x%08X lr=0x%08X r3=0x%08X\n",
                                i, b.fn, b.lr, b.r3);
        }
    }
    return written;
}

void SetLogFilePath(const std::string& path) {
    const int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if (fd >= 0) {
        g_log_fd.store(fd, std::memory_order_release);
    }
}

void Open(const std::string& path) {
    const int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if (fd < 0) {
        return;
    }
    g_boot_fd.store(fd, std::memory_order_release);
    SetupAltStack();
    std::set_terminate(OnTerminate);
    const int sigs[] = {SIGSEGV, SIGBUS, SIGABRT, SIGILL, SIGFPE, SIGTRAP};
    for (int sig : sigs) {
        struct sigaction sa{};
        sa.sa_sigaction = OnSignal;
        sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
        sigemptyset(&sa.sa_mask);
        sigaction(sig, &sa, &g_previous[sig]);
    }
}

void SetEnabled(bool enabled) {
    g_enabled.store(enabled, std::memory_order_relaxed);
}

void Trace(const std::string& line) {
    if (!g_enabled.load(std::memory_order_relaxed)) {
        return;
    }
    const auto now = std::chrono::system_clock::now();
    const std::time_t t = std::chrono::system_clock::to_time_t(now);
    const int ms = int(std::chrono::duration_cast<std::chrono::milliseconds>(
                           now.time_since_epoch()).count() % 1000);
    std::tm tm{};
    localtime_r(&t, &tm);
    char stamp[32];
    const size_t n = std::strftime(stamp, sizeof(stamp), "[%Y-%m-%d %H:%M:%S", &tm);
    std::string text(stamp, n);
    char tail[8];
    snprintf(tail, sizeof(tail), ".%03d] ", ms);
    text += tail;
    text += line;
    text += '\n';
    WriteFdRaw(g_boot_fd.load(std::memory_order_acquire), text.data(), text.size());
}

} // namespace l4d2::boot
