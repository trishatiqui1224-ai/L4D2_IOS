#include "resolution_hooks.h"
#include "logging/logger.h"

#include <mutex>

namespace l4d2 {

ResolutionManager& ResolutionManager::Instance() {
    static ResolutionManager instance;
    return instance;
}

void ResolutionManager::ApplyConfig(const RenderConfig& cfg) {
    config_ = cfg;
    switch (config_.resolution) {
        case ResolutionPreset::Res720p:
            config_.width = 1280;
            config_.height = 720;
            break;
        case ResolutionPreset::Res540p:
            config_.width = 960;
            config_.height = 540;
            break;
        case ResolutionPreset::Res480p:
            config_.width = 854;
            config_.height = 480;
            break;
    }

    uint32_t edram_tiles = CalculateEdramTiles(config_.width, config_.height);
    uint32_t target_fps = (config_.fps_cap == FrameRateCap::Fps30) ? 30 :
                          (config_.fps_cap == FrameRateCap::Fps120) ? 120 : 60;

    L4D2_LOG_INFO("Renderer", "Applied RenderConfig: %ux%u (%u EDRAM tiles), Cap: %u FPS, HalfTex: %d, LowRAMCache: %d, CPUPin: %d",
                  config_.width, config_.height, edram_tiles, target_fps,
                  config_.half_res_textures, config_.low_ram_texture_cache, config_.cpu_boost_pinning);
}

void ResolutionManager::HookXGetVideoMode(void* pVideoMode) {
    if (!pVideoMode) return;
    struct XVIDEO_MODE {
        uint32_t fIsInterlaced;
        uint32_t fIsWideScreen;
        uint32_t fIsHiDef;
        uint32_t RefreshRate;
        uint32_t VideoStandard;
        uint32_t DisplayWidth;
        uint32_t DisplayHeight;
    };
    auto* vm = reinterpret_cast<XVIDEO_MODE*>(pVideoMode);
    vm->fIsInterlaced = 0;
    vm->fIsWideScreen = 1;
    vm->fIsHiDef = 1;
    vm->RefreshRate = (config_.fps_cap == FrameRateCap::Fps30) ? 30 :
                      (config_.fps_cap == FrameRateCap::Fps120) ? 120 : 60;
    vm->DisplayWidth = config_.width;
    vm->DisplayHeight = config_.height;

    L4D2_LOG_DEBUG("Renderer", "XGetVideoMode hook returned %ux%u @ %u Hz (Widescreen=1, HiDef=1)",
                   vm->DisplayWidth, vm->DisplayHeight, vm->RefreshRate);
}

void ResolutionManager::HookShaderApiDimensions(uint32_t& out_w, uint32_t& out_h) {
    out_w = config_.width;
    out_h = config_.height;
}

uint32_t ResolutionManager::CalculateEdramTiles(uint32_t w, uint32_t h) {
    // Exact Xenos EDRAM tile math formula: ((width + 79) / 80) * ((height + 15) / 16)
    return ((w + 79) / 80) * ((h + 15) / 16);
}

void ResolutionManager::LogResolveWarningOnce(uint32_t sample_select, uint32_t msaa_samples, bool is_depth) {
    static std::once_flag s_resolve_warning_flag;
    std::call_once(s_resolve_warning_flag, [=]() {
        L4D2_LOG_WARN("GPU", "MSAA Resolve sample fallback: %u-sample %s: sample_select=%u (Silenced subsequent occurrences)",
                      1 << msaa_samples, is_depth ? "depth" : "color", sample_select);
    });
}

} // namespace l4d2

