#!/usr/bin/env python3
"""
Applies host display preset (720p, 900p, 1080p, retina) to CAMetalLayer
before swapchain creation, and updates WindowSDL actual dimensions to match.

    python3 tools/ios/patch_ios_preset_layer.py            apply
    python3 tools/ios/patch_ios_preset_layer.py --status
    python3 tools/ios/patch_ios_preset_layer.py --revert

Touches src/ui/window_sdl.cpp.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from patch_engine import run  # noqa: E402

W = "src/ui/window_sdl.cpp"

GLOBAL_ANCHOR = '''namespace rex::ui {

namespace {
'''

GLOBAL_NEW = '''#if REX_PLATFORM_IOS
extern "C" {
typedef void (*MetalLayerPresetFn)(void* layer);
typedef uint32_t (*MetalLayerDimFn)();
__attribute__((visibility("default"))) MetalLayerPresetFn g_apply_metal_preset = nullptr;
__attribute__((visibility("default"))) MetalLayerDimFn g_get_drawable_w = nullptr;
__attribute__((visibility("default"))) MetalLayerDimFn g_get_drawable_h = nullptr;
}
#endif

namespace rex::ui {

namespace {
'''

LAYER_ANCHOR = '''#elif REX_PLATFORM_MAC
  if (allowed_types & Surface::kTypeFlag_CAMetalLayer) {
    SDL_MetalView metal_view = SDL_Metal_CreateView(sdl_window_);
    if (metal_view) {
      void* layer = SDL_Metal_GetLayer(metal_view);
      if (layer) {
        return std::make_unique<CAMetalLayerSurface>(sdl_window_, metal_view, layer);
      }
      SDL_Metal_DestroyView(metal_view);
    }
  }
'''

LAYER_NEW = '''#elif REX_PLATFORM_MAC
  if (allowed_types & Surface::kTypeFlag_CAMetalLayer) {
    SDL_MetalView metal_view = SDL_Metal_CreateView(sdl_window_);
    if (metal_view) {
      void* layer = SDL_Metal_GetLayer(metal_view);
      if (layer) {
#if REX_PLATFORM_IOS
        // LOCAL PATCH - iOS: configure preset on CAMetalLayer before swapchain creation
        // and update actual window dimensions so VulkanPresenter matches drawable size.
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
  }
'''

SIZE_ANCHOR = '''  int pixel_width = 0;
  int pixel_height = 0;
  SDL_GetWindowSizeInPixels(sdl_window_, &pixel_width, &pixel_height);
  WindowDestructionReceiver destruction_receiver(this);
  OnActualSizeUpdate(uint32_t(pixel_width), uint32_t(pixel_height), destruction_receiver);
'''

SIZE_NEW = '''  int pixel_width = 0;
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
  OnActualSizeUpdate(uint32_t(pixel_width), uint32_t(pixel_height), destruction_receiver);
'''

BLOCKS = [
    (W, "export metal preset function pointer hooks", GLOBAL_ANCHOR, GLOBAL_NEW),
    (W, "apply preset to CAMetalLayer on creation", LAYER_ANCHOR, LAYER_NEW),
    (W, "update initial actual size for iOS preset", SIZE_ANCHOR, SIZE_NEW),
]

if __name__ == "__main__":
    sys.exit(run("ios_preset_layer", BLOCKS))
