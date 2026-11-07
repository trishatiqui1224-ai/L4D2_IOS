#!/usr/bin/env python3
"""Forward unhandled Darwin faults and log detailed crash reports (symbolicated PC/LR + guest regs) to boot.txt."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run

FILE = "src/core/exception_handler_posix.cpp"

ANCHOR = '''static void ExceptionHandlerCallback(int signal_number, siginfo_t* signal_info,
                                     void* signal_context) {
'''
ANCHOR_NEW = '''extern "C" uintptr_t g_last_host_fault_pc;
uintptr_t g_last_host_fault_pc = 0;

static void ExceptionHandlerCallback(int signal_number, siginfo_t* signal_info,
                                     void* signal_context) {
#if REX_PLATFORM_MAC && REX_ARCH_ARM64
  if (signal_context) {
    auto mc = reinterpret_cast<ucontext_t*>(signal_context)->uc_mcontext;
#if __DARWIN_OPAQUE_ARM_THREAD_STATE64
    g_last_host_fault_pc = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_pc);
#else
    g_last_host_fault_pc = mc->__ss.__pc;
#endif
  }
#endif
'''

FORWARD = '''#if REX_PLATFORM_MAC
// Guest MMIO/write-watch faults are handled first. Other faults must reach
// the handler installed before ours (for example Metal's capture layer), or
// the process's default disposition. Returning silently retries the fault.
static void ForwardUnhandledSignal(int number, siginfo_t* info, void* context) {
  struct sigaction* previous = nullptr;
  switch (number) {
    case SIGILL:  previous = &original_sigill_handler_; break;
    case SIGSEGV: previous = &original_sigsegv_handler_; break;
    case SIGBUS:  previous = &original_sigbus_handler_; break;
    case SIGABRT: previous = &original_sigabrt_handler_; break;
    case SIGTRAP: previous = &original_sigtrap_handler_; break;
    default: return;
  }
  ReportUnhandledSignal(number, info, context);
  const struct sigaction action = *previous;
  if (action.sa_handler == SIG_DFL || action.sa_handler == SIG_IGN) {
    // Ignoring a synchronous hardware fault cannot make the instruction
    // succeed. Restore default termination rather than creating a retry loop.
    struct sigaction fatal = {};
    fatal.sa_handler = SIG_DFL;
    sigemptyset(&fatal.sa_mask);
    sigaction(number, &fatal, nullptr);
    raise(number);
    return;
  }
  if (action.sa_flags & SA_RESETHAND) {
    previous->sa_handler = SIG_DFL;
    previous->sa_flags = 0;
    sigemptyset(&previous->sa_mask);
  }
  // Invoke with the original fault context so a handler can repair it.
  // Keep ReXGlue installed for subsequent guest faults.
  sigset_t old_mask;
  sigprocmask(SIG_BLOCK, &action.sa_mask, &old_mask);
  if (action.sa_flags & SA_NODEFER) {
    sigset_t current;
    sigprocmask(SIG_BLOCK, nullptr, &current);
    if (!sigismember(&action.sa_mask, number)) sigdelset(&current, number);
    sigprocmask(SIG_SETMASK, &current, nullptr);
  }
  if (action.sa_flags & SA_SIGINFO) action.sa_sigaction(number, info, context);
  else action.sa_handler(number);
  sigprocmask(SIG_SETMASK, &old_mask, nullptr);
}
#endif

'''

REPORT = '''// Opened outside signal context; only write() and stack formatting on fault.
static int signal_report_fd = -1;
static struct sigaction original_sigabrt_handler_;
static struct sigaction original_sigtrap_handler_;

static void ReportUnhandledSignal(int number, siginfo_t* info, void* context) {
  int boot_fd = -1;
  const char* bp = std::getenv("L4D2_BOOT_PATH");
  if (!bp) bp = std::getenv("NFSMW_SIGNAL_REPORT");
  if (bp) {
    boot_fd = open(bp, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
  } else {
    boot_fd = open("boot.txt", O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
  }

  char text[4096];
  size_t used = 0;
  auto append = [&](const char* s) {
    while (*s && used < sizeof(text) - 1) text[used++] = *s++;
  };
  auto field = [&](const char* name, uint64_t value) {
    append(name);
    append("=0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
      if (used < sizeof(text) - 1) text[used++] = "0123456789abcdef"[(value >> shift) & 15];
    }
    append("\\n");
  };

  append("\\n================================================================================\\n");
  append("  [CRASH] FATAL HOST EXCEPTION / UNHANDLED SIGNAL REPORT\\n");
  append("================================================================================\\n");
  field("signal", number);
  if (info) {
    field("code", info->si_code);
    field("fault_address", reinterpret_cast<uintptr_t>(info->si_addr));
  }
#if REX_ARCH_ARM64
  if (context) {
    auto mc = reinterpret_cast<ucontext_t*>(context)->uc_mcontext;
#if __DARWIN_OPAQUE_ARM_THREAD_STATE64
    uintptr_t host_pc = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_pc);
    uintptr_t host_lr = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_lr);
    uintptr_t host_sp = reinterpret_cast<uintptr_t>(mc->__ss.__opaque_sp);
#else
    uintptr_t host_pc = mc->__ss.__pc;
    uintptr_t host_lr = mc->__ss.__lr;
    uintptr_t host_sp = mc->__ss.__sp;
#endif
    field("pc", host_pc);
    Dl_info dli_pc{};
    if (dladdr(reinterpret_cast<void*>(host_pc), &dli_pc) && dli_pc.dli_sname) {
      append("pc_symbol=");
      append(dli_pc.dli_sname);
      append("\\n");
    }
    field("lr", host_lr);
    Dl_info dli_lr{};
    if (dladdr(reinterpret_cast<void*>(host_lr), &dli_lr) && dli_lr.dli_sname) {
      append("lr_caller_symbol=");
      append(dli_lr.dli_sname);
      append("\\n");
    }
    field("sp", host_sp);
    field("esr", mc->__es.__esr);
    for (int i = 0; i < 29; ++i) {
      char name[] = {'x', char('0' + i / 10), char('0' + i % 10), 0};
      field(name, mc->__ss.__x[i]);
    }
  }
#endif

  auto* ts = rex::runtime::ThreadState::Get();
  if (ts && ts->context()) {
    auto* ctx = ts->context();
    append("\\n--- Guest Thread State ---\\n");
    field("guest_lr", ctx->lr);
    field("guest_ctr", ctx->ctr.u64);
    field("guest_r1", ctx->r1.u32);
    field("guest_r3", ctx->r3.u32);
    field("guest_r4", ctx->r4.u32);
    field("guest_r5", ctx->r5.u32);
    field("guest_r6", ctx->r6.u32);
    field("guest_r7", ctx->r7.u32);
    field("guest_r8", ctx->r8.u32);
    field("guest_r9", ctx->r9.u32);
    field("guest_r10", ctx->r10.u32);
    field("guest_r11", ctx->r11.u32);
    field("guest_r12", ctx->r12.u32);
  }
  append("================================================================================\\n\\n");

  if (signal_report_fd >= 0) {
    (void)write(signal_report_fd, text, used);
    (void)fsync(signal_report_fd);
  }
  if (boot_fd >= 0) {
    (void)write(boot_fd, text, used);
    (void)fsync(boot_fd);
    close(boot_fd);
  }
  (void)write(2, text, used);
}

'''

FULL_FORWARD = REPORT + FORWARD

TAIL = '''      return;
    }
  }
}

void ExceptionHandler::Install(Handler fn, void* data) {
'''
TAIL_NEW = '''      return;
    }
  }
#if REX_PLATFORM_MAC
  ForwardUnhandledSignal(signal_number, signal_info, signal_context);
#endif
}

void ExceptionHandler::Install(Handler fn, void* data) {
'''

ANCHOR_INSTALL = '''    if (sigaction(SIGSEGV, &signal_handler, &original_sigsegv_handler_) != 0) {
      assert_always("Failed to install new SIGSEGV handler");
    }
'''

NEW_INSTALL = '''    if (sigaction(SIGSEGV, &signal_handler, &original_sigsegv_handler_) != 0) {
      assert_always("Failed to install new SIGSEGV handler");
    }
#if REX_PLATFORM_MAC
    sigaction(SIGABRT, &signal_handler, &original_sigabrt_handler_);
    sigaction(SIGTRAP, &signal_handler, &original_sigtrap_handler_);
#endif
'''

BLOCKS = [
    (FILE, "signal report system headers", "#include <signal.h>\n",
     "#ifndef _DARWIN_C_SOURCE\n#define _DARWIN_C_SOURCE 1\n#endif\n#include <signal.h>\n#include <fcntl.h>\n#include <unistd.h>\n#include <cstdlib>\n#include <dlfcn.h>\n#include <rex/system/thread_state.h>\n#include <rex/ppc/context.h>\n"),
    (FILE, "Darwin unhandled signal forwarding", ANCHOR, FULL_FORWARD + ANCHOR_NEW),
    (FILE, "forward only faults unclaimed by guest handlers", TAIL, TAIL_NEW),
    (FILE, "install SIGABRT and SIGTRAP handlers", ANCHOR_INSTALL, NEW_INSTALL),
    (FILE, "open optional fault report outside signal context",
     "  if (!signal_handlers_installed_) {\n    struct sigaction signal_handler;",
     '''  if (!signal_handlers_installed_) {
#if REX_PLATFORM_MAC
    const char* rpath = std::getenv("L4D2_BOOT_PATH");
    if (!rpath) rpath = std::getenv("NFSMW_SIGNAL_REPORT");
    if (rpath) {
      signal_report_fd = open(rpath, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    }
#endif
    struct sigaction signal_handler;'''),
]

if __name__ == "__main__":
    sys.exit(run("ios_signal_forwarding", BLOCKS))
