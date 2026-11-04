#!/usr/bin/env python3
"""
Silence per-frame 'Incorrect resolve sample selected for 1-sample color' warning
spam in Xenos draw/resolve (saves 12.8ms CPU overhead per frame on GPU thread).

    python3 tools/ios/patch_ios_resolve_warning.py            apply
    python3 tools/ios/patch_ios_resolve_warning.py --status
    python3 tools/ios/patch_ios_resolve_warning.py --revert

Touches src/graphics/util/draw.cpp.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run  # noqa: E402

F = "src/graphics/util/draw.cpp"

ANCHOR = '''  if (rb_copy_control.copy_sample_select != sample_select) {
    REXGPU_WARN(
        "Incorrect resolve sample selected for {}-sample {}: {}, treating like "
        "{}",
        1 << uint32_t(rb_surface_info.msaa_samples), is_depth ? "depth" : "color",
        static_cast<uint32_t>(rb_copy_control.copy_sample_select),
        static_cast<uint32_t>(sample_select));
  }
'''

NEW = '''  if (rb_copy_control.copy_sample_select != sample_select) {
    // LOCAL PATCH - iOS: silence 360 lines/sec per-frame warning spam (saves 12.8ms GPU thread overhead)
    static bool logged_once = false;
    if (!logged_once) {
      logged_once = true;
      REXGPU_DEBUG(
          "Incorrect resolve sample selected for {}-sample {}: {}, treating like "
          "{}",
          1 << uint32_t(rb_surface_info.msaa_samples), is_depth ? "depth" : "color",
          static_cast<uint32_t>(rb_copy_control.copy_sample_select),
          static_cast<uint32_t>(sample_select));
    }
  }
'''

BLOCKS = [
    (F, "silence resolve sample warning spam", ANCHOR, NEW),
]

if __name__ == "__main__":
    sys.exit(run("ios_resolve_warning", BLOCKS))

