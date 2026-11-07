#!/usr/bin/env python3
"""
Prepares the ReXGlue SDK tree for building the Left 4 Dead 2 iOS port.

    python3 tools/ios/prepare_sdk.py
    python3 tools/ios/prepare_sdk.py --sdk /path/to/rexglue-sdk-ios
    python3 tools/ios/prepare_sdk.py --status

Leaves an SDK v0.10.0 in ../rexglue-sdk-ios, SEPARATE from the Windows and
Android ones. Safe to run as often as needed: every step checks whether it is
already done before touching anything.
"""

import argparse
import importlib.util
import os
import pathlib
import subprocess
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _android():
    """tools/preparar_sdk.py as a module, untouched."""
    path = ROOT / "tools" / "preparar_sdk.py"
    if not path.exists():
        sys.exit(f"[ERROR] Cannot find {path}")
    spec = importlib.util.spec_from_file_location("preparar_sdk_android", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ANDROID = _android()

MOLTENVK_VERSION = "v1.4.1"  # = commit db445ff of the thirdparty/moltenvk submodule
MOLTENVK_URL = (
    f"https://github.com/KhronosGroup/MoltenVK/releases/download/"
    f"{MOLTENVK_VERSION}/MoltenVK-ios.tar"
)

# Order matters: each one anchors on what the earlier ones left.
IOS_PATCHES = [
    "patch_ios_platform",
    "patch_ios_signal_forwarding",
    "patch_ios_cmake",
    "patch_ios_paths",
    "patch_ios_relative_paths",
    "patch_ios_memory",
    "patch_ios_function_table",
    "patch_ios_import_resolution",
    "patch_ios_dllmain_log",
    "patch_ios_waits",
    "patch_ios_pause",
    "patch_ios_sdl",
    "patch_ios_timing",
    "patch_ios_ui_tick",
    "patch_ios_aspect",
    "patch_ios_retina",
    "patch_ios_preset_layer",
    "patch_ios_qos",
    "patch_ios_fault_log",
    "patch_ios_save_log",
    "patch_ios_touch_pad",
    "patch_ios_dump_image",
    "patch_ios_upload_batch",
    "patch_ios_vblank_grid",
    "patch_ios_shader_contraction",
    "patch_ios_occlusion_async",
    "patch_ios_fps_cap",
    "patch_ios_present_pacing",
    "patch_ios_vblank_display",
    "patch_ios_ui_tick_cap",
    "patch_ios_register_check",
    "patch_ios_texture_descriptors",
    "patch_ios_readback_limit",
    "patch_ios_suboptimal",
    "patch_ios_surface_reattach",
    "patch_ios_paint_suspend",
    "patch_ios_texture_stats",
    "patch_ios_narrow_invalidation",
    "patch_ios_occlusion_batch",
    "patch_ios_dispatch_stats",
    "patch_ios_shared_stats",
    "patch_ios_hot_pages",
    "patch_ios_async_copies",
    "patch_ios_type0_ranges",
    "patch_ios_resolve_stats",
    "patch_ios_resolve_warning",
    "patch_ios_iso_stream",
    "patch_ios_native_only",
    "patch_ios_semaphore_trace",
    "patch_ios_xma_canary",
    "patch_ios_mnk_modifiers",
    "patch_ios_native_present_skip",
    "patch_ios_suboptimal_limit",
    "patch_ios_native_occlusion",
    "patch_ios_xma_starve_switch",
    "patch_ios_invalid_call_log",
    "patch_ios_read_timing",
    "patch_ios_xma_reset_stats",
    "patch_ios_xma_voice_log",
    "patch_ios_xma_direct_output",
    "patch_ios_shader_disasm_log",
    "patch_ios_small_shared_memory",
    "patch_ios_native_backend",
    "patch_ios_timer_queue_block",
    "patch_ios_cheap_sleep",
    "patch_ios_sdl_display_link",
    "patch_ios_stack_top",
    "patch_ios_save_hook",
    "patch_ios_sdl_scene",
    "patch_ios_retire_qos",
    "patch_ios_battery_group",
    "patch_ios_utility_qos",
    "patch_ios_packet_census",
    "patch_ios_cp_fast_runs",
    "patch_ios_cp_idle_wait",
    "patch_ios_vblank_realtime",
    "patch_ios_cap_30_at_120",
    "patch_ios_host_stack",
]


def step(n, text):
    print(f"\n== {n}. {text}")


def ensure_git_tags(sdk):
    """Ensure v* git tag is reachable so rex_compute_version resolves cleanly."""
    chk = subprocess.run(
        ["git", "describe", "--tags", "--match", "v*"],
        cwd=sdk,
        capture_output=True,
        text=True,
    )
    if chk.returncode != 0:
        subprocess.run(["git", "fetch", "--tags", "--depth=1"], cwd=sdk, capture_output=True)
        chk2 = subprocess.run(
            ["git", "describe", "--tags", "--match", "v*"],
            cwd=sdk,
            capture_output=True,
            text=True,
        )
        if chk2.returncode != 0:
            subprocess.run(["git", "tag", "-f", "v0.10.0", "HEAD"], cwd=sdk, capture_output=True)
            print("  [ok] Tagged v0.10.0 on HEAD for rex_compute_version")


def safeguard_vulkan_loader(sdk):
    """Extra safeguard: quote ${SYSTEM_PROCESSOR} and ${CMAKE_SYSTEM_PROCESSOR} in vulkan-loader."""
    loader_cmake = sdk / "thirdparty" / "vulkan-loader" / "loader" / "CMakeLists.txt"
    if loader_cmake.exists():
        txt = loader_cmake.read_text(encoding="utf-8")
        orig = txt
        for var in ["${SYSTEM_PROCESSOR}", "${CMAKE_SYSTEM_PROCESSOR}"]:
            if var in txt:
                tmp = f"___TMP_QUOTED_{var[2:-1]}___"
                txt = txt.replace(f'"{var}"', tmp)
                txt = txt.replace(var, f'"{var}"')
                txt = txt.replace(tmp, f'"{var}"')
        if txt != orig:
            loader_cmake.write_text(txt, encoding="utf-8")
            print("  [ok] Safeguarded vulkan-loader/loader/CMakeLists.txt (quoted processor variables)")


def safeguard_rex_version(sdk):
    """Ensure rex_version.cmake cleanly resolves 0.10.0 without warnings on iOS."""
    ver_cmake = sdk / "cmake" / "rex_version.cmake"
    if ver_cmake.exists():
        txt = ver_cmake.read_text(encoding="utf-8")
        old_warn = 'message(WARNING\n            "rex_compute_version: no v* tag reachable from HEAD.'
        if old_warn in txt:
            new_warn = 'set(${out_var} "0.10.0" PARENT_SCOPE)\n        return()\n        message(DEBUG\n            "rex_compute_version: no v* tag reachable from HEAD.'
            txt = txt.replace(old_warn, new_warn)
            ver_cmake.write_text(txt, encoding="utf-8")
            print("  [ok] Safeguarded rex_version.cmake (clean 0.10.0 fallback)")


def safeguard_fpscr(sdk):
    """Fix ARM64 inline-asm operand width warning in rex/platform/fpscr.h (cast csr to uint64_t)."""
    for sub in [
        sdk / "include" / "rex" / "platform" / "fpscr.h",
        sdk / "src" / "rex" / "platform" / "fpscr.h",
    ]:
        if sub.exists():
            txt = sub.read_text(encoding="utf-8")
            orig = txt
            old_setcsr = 'static inline void setcsr(u32 csr) noexcept {\n  __asm__ __volatile__("msr fpcr, %0" : : "r"(csr));\n}'
            new_setcsr = 'static inline void setcsr(u32 csr) noexcept {\n  uint64_t v = csr;\n  __asm__ __volatile__("msr fpcr, %0" : : "r"(v));\n}'
            if old_setcsr in txt:
                txt = txt.replace(old_setcsr, new_setcsr)
            elif '__asm__ __volatile__("msr fpcr, %0" : : "r"(csr));' in txt:
                txt = txt.replace(
                    '__asm__ __volatile__("msr fpcr, %0" : : "r"(csr));',
                    'uint64_t v = csr; __asm__ __volatile__("msr fpcr, %0" : : "r"(v));'
                )
            elif 'msr fpcr, %0' in txt and 'uint64_t v = csr' not in txt:
                import re
                txt = re.sub(
                    r'(static\s+inline\s+void\s+setcsr\s*\([^)]*\)\s*(?:noexcept)?\s*\{)([^}]*__asm__\s*__volatile__\s*\(\s*"msr\s+fpcr,\s*%0"\s*:\s*:\s*"r"\()(\w+)(\)\s*\);)',
                    r'\1 uint64_t v = \3; \2v\4',
                    txt
                )
            if txt != orig:
                sub.write_text(txt, encoding="utf-8")
                print(f"  [ok] Safeguarded {sub.relative_to(sdk)} (msr fpcr uint64_t operand)")


def safeguard_resolve_warning(sdk):
    """Silence per-frame 'Incorrect resolve sample selected' warning spam (saves 12.8ms GPU thread overhead)."""
    p = sdk / "src" / "graphics" / "util" / "draw.cpp"
    if p.exists():
        txt = p.read_text(encoding="utf-8")
        if "Incorrect resolve sample selected" in txt and "static bool logged_once" not in txt:
            old = '''  if (rb_copy_control.copy_sample_select != sample_select) {
    REXGPU_WARN(
        "Incorrect resolve sample selected for {}-sample {}: {}, treating like "
        "{}",
        1 << uint32_t(rb_surface_info.msaa_samples), is_depth ? "depth" : "color",
        static_cast<uint32_t>(rb_copy_control.copy_sample_select),
        static_cast<uint32_t>(sample_select));
  }'''
            new = '''  if (rb_copy_control.copy_sample_select != sample_select) {
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
  }'''
            if old in txt:
                txt = txt.replace(old, new)
                p.write_text(txt, encoding="utf-8")
                print("  [ok] Safeguarded draw.cpp (silenced resolve sample warning spam)")


def safeguard_preset_layer(sdk):
    """Ensure CAMetalLayer drawableSize & contentsScale match preset before swapchain creation."""
    p = sdk / "src" / "ui" / "window_sdl.cpp"
    if p.exists():
        txt = p.read_text(encoding="utf-8")
        if "g_apply_metal_preset" not in txt:
            # Revert any previous non-pointer version if present
            if "extern void ApplyMetalLayerPreset" in txt:
                txt = txt.replace(
                    '''#if REX_PLATFORM_IOS
        extern void ApplyMetalLayerPreset(void* layer);
        extern uint32_t GetMetalLayerDrawableWidth();
        extern uint32_t GetMetalLayerDrawableHeight();
        ApplyMetalLayerPreset(layer);
        if (uint32_t dw = GetMetalLayerDrawableWidth()) {
          uint32_t dh = GetMetalLayerDrawableHeight();
          WindowDestructionReceiver destruction_receiver(this);
          OnActualSizeUpdate(dw, dh, destruction_receiver);
        }
#endif''',
                    '''#if REX_PLATFORM_IOS
        if (g_apply_metal_preset) {
          g_apply_metal_preset(layer);
        }
        if (g_get_drawable_w && g_get_drawable_h) {
          uint32_t dw = g_get_drawable_w();
          uint32_t dh = g_get_drawable_h();
          if (dw > 0 && dh > 0) {
            WindowDestructionReceiver destruction_receiver(this);
            OnActualSizeUpdate(dw, dh, destruction_receiver);
          }
        }
#endif'''
                )
            # Add global pointer definitions
            anchor_global = '''namespace rex::ui {

namespace {'''
            new_global = '''#if REX_PLATFORM_IOS
extern "C" {
typedef void (*MetalLayerPresetFn)(void* layer);
typedef uint32_t (*MetalLayerDimFn)();
__attribute__((visibility("default"))) MetalLayerPresetFn g_apply_metal_preset = nullptr;
__attribute__((visibility("default"))) MetalLayerDimFn g_get_drawable_w = nullptr;
__attribute__((visibility("default"))) MetalLayerDimFn g_get_drawable_h = nullptr;
}
#endif

namespace rex::ui {

namespace {'''
            if anchor_global in txt and "g_apply_metal_preset" not in txt:
                txt = txt.replace(anchor_global, new_global)

            old_layer = '''#elif REX_PLATFORM_MAC
  if (allowed_types & Surface::kTypeFlag_CAMetalLayer) {
    SDL_MetalView metal_view = SDL_Metal_CreateView(sdl_window_);
    if (metal_view) {
      void* layer = SDL_Metal_GetLayer(metal_view);
      if (layer) {
        return std::make_unique<CAMetalLayerSurface>(sdl_window_, metal_view, layer);
      }
      SDL_Metal_DestroyView(metal_view);
    }
  }'''
            new_layer = '''#elif REX_PLATFORM_MAC
  if (allowed_types & Surface::kTypeFlag_CAMetalLayer) {
    SDL_MetalView metal_view = SDL_Metal_CreateView(sdl_window_);
    if (metal_view) {
      void* layer = SDL_Metal_GetLayer(metal_view);
      if (layer) {
#if REX_PLATFORM_IOS
        if (g_apply_metal_preset) {
          g_apply_metal_preset(layer);
        }
        if (g_get_drawable_w && g_get_drawable_h) {
          uint32_t dw = g_get_drawable_w();
          uint32_t dh = g_get_drawable_h();
          if (dw > 0 && dh > 0) {
            WindowDestructionReceiver destruction_receiver(this);
            OnActualSizeUpdate(dw, dh, destruction_receiver);
          }
        }
#endif
        return std::make_unique<CAMetalLayerSurface>(sdl_window_, metal_view, layer);
      }
      SDL_Metal_DestroyView(metal_view);
    }
  }'''
            if old_layer in txt:
                txt = txt.replace(old_layer, new_layer)

            old_size = '''  int pixel_width = 0;
  int pixel_height = 0;
  SDL_GetWindowSizeInPixels(sdl_window_, &pixel_width, &pixel_height);
  WindowDestructionReceiver destruction_receiver(this);
  OnActualSizeUpdate(uint32_t(pixel_width), uint32_t(pixel_height), destruction_receiver);'''
            new_size = '''  int pixel_width = 0;
  int pixel_height = 0;
  SDL_GetWindowSizeInPixels(sdl_window_, &pixel_width, &pixel_height);
#if REX_PLATFORM_IOS
  if (g_get_drawable_w && g_get_drawable_h) {
    uint32_t dw = g_get_drawable_w();
    uint32_t dh = g_get_drawable_h();
    if (dw > 0 && dh > 0) {
      pixel_width = int(dw);
      pixel_height = int(dh);
    }
  }
#endif
  WindowDestructionReceiver destruction_receiver(this);
  OnActualSizeUpdate(uint32_t(pixel_width), uint32_t(pixel_height), destruction_receiver);'''
            if old_size in txt:
                txt = txt.replace(old_size, new_size)

            p.write_text(txt, encoding="utf-8")
            print("  [ok] Safeguarded window_sdl.cpp (CAMetalLayer preset function pointers)")


def moltenvk(sdk):
    dest = sdk / ".nfsc-ios" / "MoltenVK"
    marker = dest / (MOLTENVK_VERSION + ".ready")
    if marker.exists():
        print(f"[ok] MoltenVK {MOLTENVK_VERSION} already there")
        return
    dest.mkdir(parents=True, exist_ok=True)
    tar = dest.parent / "MoltenVK-ios.tar"
    if not tar.exists():
        print(f"[..] Downloading MoltenVK {MOLTENVK_VERSION} for iOS")
        with urllib.request.urlopen(MOLTENVK_URL, timeout=300) as resp:
            tar.write_bytes(resp.read())
    with tarfile.open(tar) as t:
        if hasattr(tarfile, 'data_filter'):
            t.extractall(dest, filter='data')
        else:
            t.extractall(dest)
    xcf = list(dest.rglob("dynamic/MoltenVK.xcframework"))
    if not xcf:
        sys.exit(f"[ERROR] The MoltenVK tar has no dynamic/MoltenVK.xcframework ({dest})")
    marker.write_text(str(xcf[0].relative_to(dest)) + "\n", encoding="utf-8")
    # Also write marker to .nfsmw-ios for compatibility
    alt_marker = sdk / ".nfsmw-ios" / "MoltenVK"
    alt_marker.mkdir(parents=True, exist_ok=True)
    (alt_marker / (MOLTENVK_VERSION + ".ready")).write_text(
        str(xcf[0].relative_to(dest)) + "\n", encoding="utf-8"
    )
    tar.unlink(missing_ok=True)
    print(f"[ok] MoltenVK in {xcf[0]}")


def project_patches(sdk):
    """The project patches still missing, each one only once."""
    marker = sdk / ".nfsc-ios" / "project-patches.applied"
    if not marker.exists():
        marker = sdk / ".nfsmw-ios" / "project-patches.applied"
    done = marker.read_text(encoding="utf-8").split() if marker.exists() else []
    full = ANDROID.PARCHES_PROYECTO
    pending = [p for p in full if p not in done]
    if not pending:
        print(f"[ok] All {len(full)} project patches already applied")
        return
    last = max((full.index(d) for d in done if d in full), default=-1)
    for p in pending:
        if full.index(p) < last:
            print(f"[!!] {p} sits in the middle of list and is applied after the "
                  f"ones that follow it: if it fails, prepare the SDK from scratch")

    marker.parent.mkdir(parents=True, exist_ok=True)
    original = ANDROID.PARCHES_PROYECTO
    try:
        for p in pending:
            ANDROID.PARCHES_PROYECTO = [p]
            ANDROID.parches_proyecto(sdk)
            done.append(p)
            marker.write_text("\n".join(done) + "\n", encoding="utf-8")
    finally:
        ANDROID.PARCHES_PROYECTO = original


def ios_patches(sdk, status=False):
    env = dict(
        os.environ,
        L4D2_SDK=str(sdk),
        NFSCARBON_SDK=str(sdk),
        NFSC_SDK=str(sdk),
        NFSMW_SDK=str(sdk),
    )
    for p in IOS_PATCHES:
        cmd = [sys.executable, str(ROOT / "tools" / "ios" / f"{p}.py")]
        if status:
            cmd.append("--status")
        r = subprocess.run(cmd, env=env, text=True, capture_output=True)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            print(out)
            sys.exit(f"[ERROR] {p} failed. The earlier ones are already applied; "
                     f"re-running this script is safe.")
        if status:
            print(out)
        else:
            first = next((l for l in out.splitlines() if l.startswith("[")), "")
            print(f"  {p:30s} {first}")


def main():
    ap = argparse.ArgumentParser(description="Prepares the ReXGlue SDK for iOS.")
    ap.add_argument("--sdk", default=str(ROOT.parent / "rexglue-sdk-ios"),
                    help="iOS SDK folder (default ../rexglue-sdk-ios)")
    ap.add_argument("--status", action="store_true", help="only report which patches are in")
    args = ap.parse_args()
    sdk = pathlib.Path(args.sdk).resolve()

    if args.status:
        if not (sdk / "CMakeLists.txt").exists():
            sys.exit(f"[ERROR] No SDK in {sdk}")
        marker = sdk / ".nfsc-ios" / "project-patches.applied"
        if not marker.exists():
            marker = sdk / ".nfsmw-ios" / "project-patches.applied"
        done = marker.read_text(encoding="utf-8").split() if marker.exists() else []
        full = ANDROID.PARCHES_PROYECTO
        print(f"  project patches: {sum(p in done for p in full)} of {len(full)} applied (recorded)")
        for p in full:
            print(f"      {'yes' if p in done else 'NO':>3}  {p}")
        ios_patches(sdk, status=True)
        return 0

    step(1, f"SDK {ANDROID.SDK_TAG}")
    ANDROID.clonar(sdk)
    ensure_git_tags(sdk)
    ANDROID.reparar_symlinks(sdk)

    step(2, "hells-gate's Android SDK patch: ARM64 barriers")
    ANDROID.aplicar_parches_ref(sdk)

    step(3, "Project patches (Android base, once each)")
    project_patches(sdk)

    step(4, f"MoltenVK {MOLTENVK_VERSION} for iOS")
    moltenvk(sdk)

    step(5, "iOS platform patches")
    ios_patches(sdk)

    step(6, "Extra safeguards")
    safeguard_vulkan_loader(sdk)
    safeguard_rex_version(sdk)
    safeguard_fpscr(sdk)
    safeguard_resolve_warning(sdk)
    safeguard_preset_layer(sdk)
    ensure_git_tags(sdk)

    print(f"\n[ok] SDK ready in {sdk}")
    print("     Next: build from ios/ (cmake --preset ios).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
