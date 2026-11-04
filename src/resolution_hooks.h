#pragma once

#include <cstdint>
#include <string>

namespace l4d2 {

enum class ResolutionPreset {
    Res720p,        // 1280x720 (or 1560x720 EDRAM-safe wide)
    Res540p,        // 960x540
    Res480p         // 854x480
};

enum class FrameRateCap {
    Fps30,          // Battery saver (30 Hz lock)
    Fps60,          // Native locked 60 FPS
    Fps120          // Flagship 120 FPS ProMotion
};

struct RenderConfig {
    ResolutionPreset resolution = ResolutionPreset::Res720p;
    uint32_t width = 1280;
    uint32_t height = 720;
    FrameRateCap fps_cap = FrameRateCap::Fps60;
    bool half_res_textures = false;
    bool low_ram_texture_cache = true;
    bool cpu_boost_pinning = true;
};

class ResolutionManager {
public:
    static ResolutionManager& Instance();

    void ApplyConfig(const RenderConfig& cfg);
    const RenderConfig& GetConfig() const { return config_; }

    // XGetVideoMode hook implementation
    void HookXGetVideoMode(void* pVideoMode);

    // Source Engine shaderapidx9_360 render target dimensions hook
    void HookShaderApiDimensions(uint32_t& out_w, uint32_t& out_h);

    // EDRAM Tile calculation: ((w + 79) / 80) * ((h + 15) / 16)
    static uint32_t CalculateEdramTiles(uint32_t w, uint32_t h);

    // Single-fire MSAA resolve logging
    static void LogResolveWarningOnce(uint32_t sample_select, uint32_t msaa_samples, bool is_depth);

private:
    ResolutionManager() = default;
    RenderConfig config_;
};

} // namespace l4d2

