#import <Foundation/Foundation.h>
#import "boot_trace.h"
#import "touch_controls.h"
#import "ingame_options.h"
#import "audio/coreaudio_driver.h"
#import "../../src/logging/logger.h"
#import "../../src/crash_handler.h"
#import "../../src/module_loader.h"
#import "../../src/resolution_hooks.h"

#include <filesystem>
#include <string>

namespace fs = std::filesystem;

extern "C" __attribute__((visibility("default")))
int L4D2_StartGame(const char* game_root_cstr, const char* save_root_cstr, const char* settings_json_cstr) {
    l4d2::boot::Trace("[L4D2Game] L4D2_StartGame entrypoint reached!");
    fs::path gameRoot(game_root_cstr ? game_root_cstr : "");
    fs::path saveRoot(save_root_cstr ? save_root_cstr : "");

    NSDictionary* settings = nil;
    if (settings_json_cstr && strlen(settings_json_cstr) > 0) {
        NSData* data = [NSData dataWithBytes:settings_json_cstr length:strlen(settings_json_cstr)];
        if (data) {
            settings = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        }
    }
    if (!settings) {
        settings = @{};
    }

    // 0. Install symbolicated crash handler for guest execution
    l4d2::CrashHandler::SetBootFilePath((saveRoot / "boot.txt").string());
    l4d2::CrashHandler::Install();
    l4d2::boot::Trace("[CrashHandler] Installed symbolicated guest crash handler");

    // 1. Pre-activate CoreAudio session for 5.3ms ultra-low latency output
    rex::audio::ios::PrepareAudioSession();
    l4d2::boot::Trace("[Audio] CoreAudio session prepared");

    // 2. Apply resolution, FPS cap, and render configuration
    l4d2::RenderConfig renderCfg;
    NSString* res = settings[@"resolution"];
    if ([res isEqualToString:@"480p"]) {
        renderCfg.resolution = l4d2::ResolutionPreset::Res480p;
    } else if ([res isEqualToString:@"540p"]) {
        renderCfg.resolution = l4d2::ResolutionPreset::Res540p;
    } else {
        renderCfg.resolution = l4d2::ResolutionPreset::Res720p;
    }

    NSString* fps = settings[@"fps_cap"];
    if ([fps isEqualToString:@"30"]) {
        renderCfg.fps_cap = l4d2::FrameRateCap::Fps30;
    } else if ([fps isEqualToString:@"120"]) {
        renderCfg.fps_cap = l4d2::FrameRateCap::Fps120;
    } else {
        renderCfg.fps_cap = l4d2::FrameRateCap::Fps60;
    }

    renderCfg.half_res_textures = [settings[@"half_textures"] isEqualToString:@"true"];
    renderCfg.low_ram_texture_cache = [settings[@"low_ram"] isEqualToString:@"true"];
    renderCfg.cpu_boost_pinning = [settings[@"cpu_boost"] isEqualToString:@"true"];
    l4d2::ResolutionManager::Instance().ApplyConfig(renderCfg);
    l4d2::boot::Trace("[Renderer] RenderConfig applied");

    // 3. Install Mobile Shooter Touch HUD & FPS Counter
    l4d2::touch::TouchConfig touchCfg;
    touchCfg.style = [settings[@"control_style"] isEqualToString:@"xbox"] ?
                     l4d2::touch::ControlStyle::Xbox360Pad : l4d2::touch::ControlStyle::L4D2ShooterMode;
    touchCfg.drag_to_look = [settings[@"drag_look"] isEqualToString:@"true"];
    l4d2::touch::Install(touchCfg);
    l4d2::touch::InstallFpsCounter();
    l4d2::boot::Trace("[Touch] Mobile Shooter Touch HUD installed");

    // 4. Initialize Multi-Module Loader
    l4d2::ModuleLoader::Instance().Init(gameRoot.string(), saveRoot.string());
    l4d2::boot::Trace("[ModuleLoader] Initialized");

    // 5. Dispatch default.xex entry point
    l4d2::boot::Trace("[Game] Dispatching default.xex entrypoint...");
    void* handle = nullptr;
    uint32_t status = l4d2::ModuleLoader::Instance().XexLoadImage("default.xex", 0, 0, &handle);
    char statusBuf[128];
    snprintf(statusBuf, sizeof(statusBuf), "[Game] XexLoadImage returned status: 0x%08X", status);
    l4d2::boot::Trace(statusBuf);

    return (status == 0) ? 0 : 1;
}

