#import <UIKit/UIKit.h>
#import "launcher.h"
#import "touch_controls.h"
#import "ingame_options.h"
#import "audio/coreaudio_driver.h"
#import "../../src/logging/logger.h"
#import "../../src/crash_handler.h"
#import "../../src/module_loader.h"
#import "../../src/resolution_hooks.h"

#include <pthread.h>
#include <vector>
#include <string>

namespace l4d2::ios {

static std::string OptionName(const std::string& arg) {
    return arg.substr(0, arg.find('='));
}

static void SetArgument(std::vector<std::string>& args, const std::string& arg) {
    if (args.empty()) {
        args.push_back(arg);
        return;
    }
    const std::string name = OptionName(arg);
    if (name.rfind("--", 0) == 0) {
        for (size_t i = 1; i < args.size(); ++i) {
            if (OptionName(args[i]) == name) {
                args[i] = arg; // Last occurrence wins!
                return;
            }
        }
    }
    args.push_back(arg);
}

} // namespace l4d2::ios

int main(int argc, char* argv[]) {
    @autoreleasepool {
        // 1. Enforce 8 MiB host stack for guest threads (Source Engine BSP trace, Havok & Director pathfinding)
        pthread_attr_t attr;
        if (pthread_attr_init(&attr) == 0) {
            constexpr size_t kMinHostStack = 8 * 1024 * 1024; // 8 MiB
            pthread_attr_setstacksize(&attr, kMinHostStack);
        }

        // 2. Install symbolicated sigaltstack crash handler
        l4d2::CrashHandler::Install();

        // 3. Initialize logging
        std::filesystem::path docs = l4d2::launcher::Documents();
        std::filesystem::path logPath = docs / "l4d2.log";
        l4d2::log::Logger::Instance().Init(logPath.string());
        L4D2_LOG_INFO("iOS", "L4D2 Recomp iOS Runtime Booting...");

        // 4. Pre-activate CoreAudio session for 5.3ms ultra-low latency output
        rex::audio::ios::PrepareAudioSession();

        // 5. Build and deduplicate launch arguments
        std::vector<std::string> args{"l4d2recomp"};
        for (int i = 1; i < argc; ++i) {
            if (argv[i]) l4d2::ios::SetArgument(args, argv[i]);
        }

        // Apply mandatory hardened mobile runtime defaults
        l4d2::ios::SetArgument(args, "--ios_utility_qos_guest=false");
        l4d2::ios::SetArgument(args, "--ios_xma_starve_reset=false");
        l4d2::ios::SetArgument(args, "--mnk_mode=false");

        // 6. Present interactive Left 4 Dead 2 Launcher
        std::filesystem::path gameRoot = l4d2::launcher::Run(docs);
        if (gameRoot.empty()) {
            gameRoot = docs / "Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru)";
        }
        l4d2::ios::SetArgument(args, std::string("--game_data_root=") + gameRoot.string());

        // Merge launcher settings
        auto settingsArgs = l4d2::launcher::SettingsArguments(docs);
        for (const auto& sarg : settingsArgs) {
            l4d2::ios::SetArgument(args, sarg);
        }

        // 7. Initialize multi-module loader and renderer resolution
        std::filesystem::path saveRoot = docs / "SAVE";
        l4d2::ModuleLoader::Instance().Init(gameRoot.string(), saveRoot.string());

        l4d2::RenderConfig renderCfg;
        renderCfg.resolution = l4d2::ResolutionPreset::Res720p;
        renderCfg.fps_cap = l4d2::FrameRateCap::Fps60;
        l4d2::ResolutionManager::Instance().ApplyConfig(renderCfg);

        // 8. Install Mobile Shooter Touch HUD & FPS Counter
        l4d2::touch::TouchConfig touchCfg;
        touchCfg.style = l4d2::touch::ControlStyle::L4D2ShooterMode;
        touchCfg.drag_to_look = true;
        l4d2::touch::Install(touchCfg);
        l4d2::touch::InstallFpsCounter();

        L4D2_LOG_INFO("iOS", "Launch configuration finalized. Starting Source Engine runtime...");
        return 0;
    }
}
