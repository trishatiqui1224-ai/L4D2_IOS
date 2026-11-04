#!/usr/bin/env python3
"""
Enforce 8 MiB host stack size for all POSIX threads and 256 KB minimum guest stack.

    python3 tools/ios/patch_ios_host_stack.py            apply
    python3 tools/ios/patch_ios_host_stack.py --status
    python3 tools/ios/patch_ios_host_stack.py --revert

Touches src/core/threading_posix.cpp and src/system/xthread.cpp.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run  # noqa: E402

TP = "src/core/threading_posix.cpp"
XT = "src/system/xthread.cpp"

TP_ANCHOR = '''    pthread_attr_t attr;
    if (pthread_attr_init(&attr) != 0)
      return false;
    if (pthread_attr_setstacksize(&attr, params.stack_size) != 0) {
      pthread_attr_destroy(&attr);
      return false;
    }
'''

TP_NEW = '''    pthread_attr_t attr;
    if (pthread_attr_init(&attr) != 0)
      return false;
    // LOCAL PATCH - iOS: 8 MiB minimum host stack for deep recompiled PPC call frames
    // (tools/ios/patch_ios_host_stack.py). iOS defaults to 512 KB, which overflows.
    size_t host_stack = params.stack_size;
    constexpr size_t kMinHostStack = 8 * 1024 * 1024;  // 8 MiB
    if (host_stack < kMinHostStack) {
      host_stack = kMinHostStack;
    }
    if (pthread_attr_setstacksize(&attr, host_stack) != 0) {
      pthread_attr_setstacksize(&attr, kMinHostStack);
    }
'''

XT_ANCHOR = '''  // Adjust stack size - min of 16k.
  if (creation_params_.stack_size < 16 * 1024) {
    creation_params_.stack_size = 16 * 1024;
  }
'''

XT_NEW = '''  // LOCAL PATCH - iOS: enforce 256 KB minimum guest virtual stack
  // (tools/ios/patch_ios_host_stack.py).
  if (creation_params_.stack_size < 256 * 1024) {
    creation_params_.stack_size = 256 * 1024;
  }
'''

BLOCKS = [
    (TP, "enforce 8 MiB host stack in threading_posix", TP_ANCHOR, TP_NEW),
    (XT, "enforce 256 KB minimum guest stack in xthread", XT_ANCHOR, XT_NEW),
]

if __name__ == "__main__":
    sys.exit(run("ios_host_stack", BLOCKS))
