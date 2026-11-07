#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include <rex/cvar.h>
#include <rex/filesystem.h>
#include <rex/logging.h>
#include <rex/rex_app.h>
#include <rex/runtime.h>
#include <rex/system/kernel_state.h>
#include <rex/ui/windowed_app.h>
#include <rex/ui/windowed_app_context_sdl.h>

#ifndef SDL_MAIN_HANDLED
#define SDL_MAIN_HANDLED 1
#endif
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#import "boot_trace.h"
#import "touch_controls.h"
#import "ingame_options.h"
#import "audio/coreaudio_driver.h"
#import "../../src/logging/logger.h"
#import "../../src/crash_handler.h"
#import "../../src/module_loader.h"
#import "../../src/resolution_hooks.h"
#import "../../generated/default/l4d2_default_init.h"

namespace fs = std::filesystem;

static void RegisterL4D2StaticModules(rex::system::KernelState* kernel_state) {
    l4d2::ModuleLoader::RegisterRecompiledModules(kernel_state);
}

static const rex::PPCImageInfo kL4D2PPCImageConfig = [] {
    auto config = l4d2_default_PPCImageConfig;
    config.register_modules = &RegisterL4D2StaticModules;
    return config;
}();

// ReXGlue cvars declared or defined for L4D2 on iOS
REXCVAR_DECLARE(std::string, log_level);
REXCVAR_DECLARE(std::string, game_data_root);
REXCVAR_DECLARE(std::string, user_data_root);
REXCVAR_DECLARE(std::string, cache_root);

REXCVAR_DEFINE_BOOL(ios_async_submits, true, "GPU",
                    "iOS: MoltenVK encodes queue submissions on its own thread");
REXCVAR_DEFINE_BOOL(ios_mvk_performance, false, "GPU",
                    "iOS: MoltenVK performance tracking");
REXCVAR_DEFINE_BOOL(ios_gpu_capture, false, "GPU",
                    "iOS: Metal frame capture");
REXCVAR_DEFINE_BOOL(ios_touch_controls, true, "Input",
                    "iOS: on-screen touch controls");
REXCVAR_DEFINE_BOOL(ios_show_fps, true, "Display",
                    "iOS: frames per second overlay");
REXCVAR_DEFINE_BOOL(ios_xma_starve_reset, false, "Audio",
                    "iOS: XMA starve reset");
REXCVAR_DEFINE_BOOL(ios_utility_qos_guest, false, "CPU",
                    "iOS: utility QoS for guest threads");
REXCVAR_DEFINE_BOOL(ios_utility_qos, false, "CPU",
                    "iOS: utility QoS");
REXCVAR_DEFINE_BOOL(half_res_textures, false, "Graphics",
                    "Half-resolution textures");
REXCVAR_DEFINE_BOOL(low_ram_texture_cache, true, "Memory",
                    "Low-RAM texture cache");
REXCVAR_DEFINE_BOOL(split_screen, false, "Game",
                    "2-player split screen");
REXCVAR_DEFINE_BOOL(async_pipelines, true, "Graphics",
                    "Compile pipelines in the background");
REXCVAR_DEFINE_STRING(control_style, "l4d2", "Input",
                     "Touch control layout style");
REXCVAR_DEFINE_STRING(resolution, "1280x720", "Display",
                     "Guest internal rendering resolution");
REXCVAR_DEFINE_STRING(aspect, "auto", "Display",
                     "Screen shape aspect ratio");
REXCVAR_DEFINE_STRING(ios_display_preset, "retina", "Display",
                     "Display quality preset");
REXCVAR_DEFINE_INT32(ios_fps_cap, 60, "Display",
                    "Target frame rate cap");
REXCVAR_DEFINE_BOOL(ios_haptics, true, "Input",
                    "Haptic feedback");

// ============================================================================
// L4D2App (Native ReXApp Implementation for Left 4 Dead 2)
// ============================================================================
class L4D2App : public rex::ReXApp {
public:
    using rex::ReXApp::ReXApp;

    static std::unique_ptr<rex::ui::WindowedApp> Create(rex::ui::WindowedAppContext& ctx) {
        return std::unique_ptr<L4D2App>(new L4D2App(ctx, "l4d2recomp", kL4D2PPCImageConfig));
    }

protected:
    void OnConfigurePaths(rex::PathConfig& paths) override {
        l4d2::boot::Trace("game: OnConfigurePaths");

        NSArray<NSString*>* docPaths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
        std::filesystem::path docs = docPaths.firstObject ? std::filesystem::path(docPaths.firstObject.UTF8String) : std::filesystem::path("/var/mobile/Documents");

        if (paths.user_data_root.empty()) {
            paths.user_data_root = docs / "rex_data";
        }
        if (paths.cache_root.empty()) {
            NSArray<NSString*>* cachePaths = NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES);
            paths.cache_root = cachePaths.firstObject ? std::filesystem::path(cachePaths.firstObject.UTF8String) / "rexglue" : docs / "cache";
        }
        if (paths.config_path.empty()) {
            paths.config_path = docs / "config" / "l4d2.toml";
        }

        std::string cvar_root = rex::cvar::GetFlagByName("game_data_root");
        if (!cvar_root.empty()) {
            paths.game_data_root = cvar_root;
        } else {
            const std::filesystem::path candidates[] = {
                docs / "Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru)",
                docs / "game",
                docs,
            };
            for (const auto& c : candidates) {
                std::error_code ec;
                if (std::filesystem::exists(c / "default.xex", ec) ||
                    std::filesystem::is_directory(c / "left4dead2", ec)) {
                    paths.game_data_root = c;
                    break;
                }
            }
        }
        l4d2::boot::Trace("game: PathConfig game_data_root=" + paths.game_data_root.string());
    }

    void OnPreSetup(rex::RuntimeConfig& config) override {
        l4d2::boot::Trace("game: OnPreSetup");
        if (config.gpu_plugin.empty()) {
            config.gpu_plugin = "xenos";
        }
        config.audio_factory = REX_AUDIO_BACKEND(rex::audio::ios::CoreAudioSystem);

        auto set_default = [](const char* name, const char* value) {
            if (rex::cvar::GetFlagSource(name) == rex::cvar::Source::kDefault) {
                rex::cvar::SetFlagByName(name, value);
            }
        };
        set_default("input_backend", "sdl");
        set_default("mnk_mode", "false");
        set_default("mnk_mouse", "false");
    }

    void OnPostSetup() override {
        l4d2::boot::Trace("game: runtime set up (OnPostSetup)");

        // 1. Crash handler
        l4d2::CrashHandler::Install();

        // 2. Render Config
        l4d2::RenderConfig renderCfg;
        std::string res = rex::cvar::GetFlagByName("resolution");
        if (res == "720p") res = "1280x720";
        else if (res == "540p") res = "960x540";
        else if (res == "480p") res = "854x480";

        if (res.find("480") != std::string::npos) {
            renderCfg.resolution = l4d2::ResolutionPreset::Res480p;
        } else if (res.find("540") != std::string::npos) {
            renderCfg.resolution = l4d2::ResolutionPreset::Res540p;
        } else {
            renderCfg.resolution = l4d2::ResolutionPreset::Res720p;
        }

        int cap = REXCVAR_GET(ios_fps_cap);
        if (cap == 30) renderCfg.fps_cap = l4d2::FrameRateCap::Fps30;
        else if (cap == 120) renderCfg.fps_cap = l4d2::FrameRateCap::Fps120;
        else renderCfg.fps_cap = l4d2::FrameRateCap::Fps60;

        renderCfg.half_res_textures = REXCVAR_GET(half_res_textures);
        renderCfg.low_ram_texture_cache = REXCVAR_GET(low_ram_texture_cache);
        renderCfg.cpu_boost_pinning = !REXCVAR_GET(ios_utility_qos_guest);
        l4d2::ResolutionManager::Instance().ApplyConfig(renderCfg);

        // 3. Touch controls & FPS
        if (REXCVAR_GET(ios_touch_controls)) {
            l4d2::touch::TouchConfig touchCfg;
            touchCfg.style = (REXCVAR_GET(control_style) == "xbox") ?
                             l4d2::touch::ControlStyle::Xbox360Pad : l4d2::touch::ControlStyle::L4D2ShooterMode;
            touchCfg.drag_to_look = true;
            l4d2::touch::Install(touchCfg);
        }
        if (REXCVAR_GET(ios_show_fps)) {
            l4d2::touch::InstallFpsCounter();
        }
    }

    void OnPreLaunchModule() override {
        l4d2::boot::Trace("game: OnPreLaunchModule (registering Source Engine multi-module subsystem)");
        std::string game_root = rex::cvar::GetFlagByName("game_data_root");
        std::string save_root = rex::cvar::GetFlagByName("user_data_root");
        l4d2::ModuleLoader::Instance().Init(game_root, save_root);
    }

    void OnShutdown() override {
        l4d2::boot::Trace("game: OnShutdown");
        l4d2::ModuleLoader::Instance().Shutdown();
    }
};

REX_DEFINE_APP(l4d2recomp, L4D2App::Create)

// ============================================================================
// Alert Helper for Failures
// ============================================================================
static void ShowAlertAndHalt(NSString* title, NSString* msg) {
    l4d2::boot::Trace([NSString stringWithFormat:@"[FATAL] %@: %@", title, msg].UTF8String);
    dispatch_async(dispatch_get_main_queue(), ^{
        UIAlertController* alert = [UIAlertController alertControllerWithTitle:title
                                                                       message:msg
                                                                preferredStyle:UIAlertControllerStyleAlert];
        [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];

        UIWindow* win = nil;
        for (UIWindowScene* s in UIApplication.sharedApplication.connectedScenes) {
            if ([s isKindOfClass:UIWindowScene.class]) {
                for (UIWindow* w in ((UIWindowScene*)s).windows) {
                    if (w.isKeyWindow) { win = w; break; }
                }
            }
        }
        UIViewController* root = win ? win.rootViewController : nil;
        if (!root) {
            for (UIWindowScene* s in UIApplication.sharedApplication.connectedScenes) {
                if ([s isKindOfClass:UIWindowScene.class]) {
                    UIWindow* first = ((UIWindowScene*)s).windows.firstObject;
                    if (first) { root = first.rootViewController; break; }
                }
            }
        }
        if (root) {
            [root presentViewController:alert animated:YES completion:nil];
        }
    });
}

// ============================================================================
// Stage-2 Engine Entry Point
// ============================================================================
extern "C" __attribute__((visibility("default")))
int L4D2_StartGame(int argc, char** argv) {
    namespace boot = l4d2::boot;
    boot::Trace("---- L4D2_StartGame entrypoint entered ----");

    NSArray<NSString*>* docPaths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    fs::path docs = docPaths.firstObject ? fs::path(docPaths.firstObject.UTF8String) : fs::path("/var/mobile/Documents");
    boot::SetupAltStack();
    boot::Open((docs / "boot.txt").string());
    boot::SetLogFilePath((docs / "l4d2.log").string());
    l4d2::CrashHandler::Install();
    l4d2::CrashHandler::SetBootFilePath((docs / "boot.txt").string());

    // 1. audio: activating the session
    boot::Trace("audio: activating the session");
    rex::audio::ios::PrepareAudioSession();

    // 2. game: parsing the arguments
    boot::Trace("game: parsing the arguments");
    for (int i = 0; i < argc; ++i) {
        if (argv && argv[i]) {
            boot::Trace(std::string("arg: ") + argv[i]);
        }
    }

    rex::cvar::Init(argc, argv);
    rex::cvar::ApplyEnvironment();
    rex::InitLoggingEarly();

    setenv("MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS", REXCVAR_GET(ios_async_submits) ? "0" : "1", 1);
    setenv("MTL_CAPTURE_ENABLED", REXCVAR_GET(ios_gpu_capture) ? "1" : "0", 1);
    if (REXCVAR_GET(ios_mvk_performance)) {
        setenv("MVK_CONFIG_PERFORMANCE_TRACKING", "1", 1);
        setenv("MVK_CONFIG_PERFORMANCE_LOGGING_FRAME_COUNT", "300", 1);
    }

    fs::path logPath = docs / "l4d2.log";

    rex::InitLogging(logPath.c_str(), REXCVAR_GET(log_level) == "off" ? spdlog::level::off : spdlog::level::info);
    if (auto logger = spdlog::default_logger()) {
        logger->flush_on(spdlog::level::trace);
    }
    spdlog::flush_every(std::chrono::milliseconds(100));

    L4D2_LOG_INFO("iOS", "Left 4 Dead 2 Native Recompilation (build %s %s)", __DATE__, __TIME__);

    // 3. game: initializing the SDL context
    boot::Trace("game: initializing the SDL context");
    SDL_SetMainReady();

    rex::ui::SDLWindowedAppContext context;
    if (!context.Initialize()) {
        boot::Trace("game: the SDL context did NOT initialize");
        L4D2_LOG_ERROR("iOS", "Could not initialize the SDL context");
        ShowAlertAndHalt(@"SDL Initialization Failed", @"Could not initialize SDL3 video subsystem.");
        return EXIT_FAILURE;
    }

    // 4. game: creating the app
    boot::Trace("game: creating the app");
    std::unique_ptr<rex::ui::WindowedApp> app = rex::ui::GetWindowedAppCreator()(context);
    if (!app) {
        boot::Trace("game: failed to create WindowedApp instance");
        L4D2_LOG_ERROR("iOS", "GetWindowedAppCreator returned null");
        ShowAlertAndHalt(@"App Creation Failed", @"Failed to create L4D2 application.");
        return EXIT_FAILURE;
    }

    // 5. game: OnInitialize (paths, log, GPU plugin, runtime, XEX)
    boot::Trace("game: OnInitialize (paths, log, GPU plugin, runtime, XEX)");
    rex::FlushLogging();
    const bool initialized = app->OnInitialize();
    if (!initialized) {
        boot::Trace("game: OnInitialize FAILED (reason in l4d2.log)");
        L4D2_LOG_ERROR("iOS", "app->OnInitialize() failed!");
        ShowAlertAndHalt(@"Engine Initialization Failed", @"app->OnInitialize() failed. Check Documents/l4d2.log and boot.txt for details.");
        return EXIT_FAILURE;
    }

    // 6. entering the main loop
    boot::Trace("game: OnInitialize done, entering the main loop");
    L4D2_LOG_INFO("iOS", "entering main message loop...");
    rex::FlushLogging();
    if (auto logger = spdlog::default_logger()) {
        logger->flush();
    }

    const int result = context.RunMainMessageLoop();
    boot::Trace("game: main loop ended (exit code " + std::to_string(result) + ")");
    L4D2_LOG_INFO("iOS", "main message loop returned with exit code %d", result);

    rex::FlushLogging();
    if (auto logger = spdlog::default_logger()) {
        logger->flush();
    }
    std::fflush(nullptr);

    app->InvokeOnDestroy();
    return result;
}
