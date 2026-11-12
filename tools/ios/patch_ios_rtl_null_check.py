#!/usr/bin/env python3
"""
tools/ios/patch_ios_rtl_null_check.py
Adds defensive NULL checks to RtlEnterCriticalSection, RtlTryEnterCriticalSection,
and RtlLeaveCriticalSection to prevent SIGSEGV / host crashes when guest code passes
uninitialized or NULL critical section pointers.

Touches:
    src/kernel/xboxkrnl/xboxkrnl_rtl.cpp
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run

FILE = "src/kernel/xboxkrnl/xboxkrnl_rtl.cpp"

ANCHOR_ENTER = '''void RtlEnterCriticalSection_entry(ppc_ptr_t<X_RTL_CRITICAL_SECTION> cs) {
  uint32_t cur_thread = XThread::GetCurrentThread()->guest_object();
'''

PATCHED_ENTER = '''void RtlEnterCriticalSection_entry(ppc_ptr_t<X_RTL_CRITICAL_SECTION> cs) {
  if (!cs || !cs.guest_address()) {
    return;
  }
  uint32_t cur_thread = XThread::GetCurrentThread()->guest_object();
'''

ANCHOR_TRY_ENTER = '''u32 RtlTryEnterCriticalSection_entry(ppc_ptr_t<X_RTL_CRITICAL_SECTION> cs) {
  uint32_t thread = XThread::GetCurrentThread()->guest_object();
'''

PATCHED_TRY_ENTER = '''u32 RtlTryEnterCriticalSection_entry(ppc_ptr_t<X_RTL_CRITICAL_SECTION> cs) {
  if (!cs || !cs.guest_address()) {
    return 0;
  }
  uint32_t thread = XThread::GetCurrentThread()->guest_object();
'''

ANCHOR_LEAVE = '''void RtlLeaveCriticalSection_entry(ppc_ptr_t<X_RTL_CRITICAL_SECTION> cs) {
  assert_true(cs->owning_thread == XThread::GetCurrentThread()->guest_object());
'''

PATCHED_LEAVE = '''void RtlLeaveCriticalSection_entry(ppc_ptr_t<X_RTL_CRITICAL_SECTION> cs) {
  if (!cs || !cs.guest_address()) {
    return;
  }
  assert_true(cs->owning_thread == XThread::GetCurrentThread()->guest_object());
'''

BLOCKS = [
    (FILE, "defensive null check in RtlEnterCriticalSection_entry", ANCHOR_ENTER, PATCHED_ENTER),
    (FILE, "defensive null check in RtlTryEnterCriticalSection_entry", ANCHOR_TRY_ENTER, PATCHED_TRY_ENTER),
    (FILE, "defensive null check in RtlLeaveCriticalSection_entry", ANCHOR_LEAVE, PATCHED_LEAVE),
]

if __name__ == "__main__":
    sys.exit(run("ios_rtl_null_check", BLOCKS))
