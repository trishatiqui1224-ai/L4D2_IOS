#include "l4d2_app.h"
#include "logging/logger.h"
#include "l4d2_manifest.h"

#include <iostream>
#include <string>
#include <vector>

#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
#include <pthread.h>
#endif

namespace l4d2 {

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

L4D2App& L4D2App::Instance() {
    static L4D2App instance;
    return instance;
}

bool L4D2App::Initialize(int argc, char** argv) {
    // 1. Enforce 8 MiB host stack for POSIX threads
#if defined(__APPLE__) || defined(__linux__) || defined(__ANDROID__)
    pthread_attr_t attr;
    if (pthread_attr_init(&attr) == 0) {
        constexpr size_t kMinHostStack = 8 * 1024 * 1024; // 8 MiB
        pthread_attr_setstacksize(&attr, kMinHostStack);
    }
#endif

    // 2. Safe CLI argument deduplication
    args_.clear();
    args_.push_back(argv[0] ? argv[0] : "l4d2recomp");
    for (int i = 1; i < argc; ++i) {
        if (argv[i]) {
            SetArgument(args_, argv[i]);
        }
    }

    // Default flags
    SetArgument(args_, "--l4d2_title_id=454108D4");
    SetArgument(args_, "--l4d2_media_id=0E79403B");
    SetArgument(args_, "--ios_utility_qos_guest=false");
    SetArgument(args_, "--ios_xma_starve_reset=false");
    SetArgument(args_, "--mnk_mode=false");

    // 3. Parse flags
    game_root_ = "Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru)";
    save_root_ = "SAVE";
    std::string log_file = "l4d2.log";

    for (const auto& a : args_) {
        if (a.rfind("--game_data_root=", 0) == 0) {
            game_root_ = a.substr(17);
        } else if (a.rfind("--save_dir=", 0) == 0) {
            save_root_ = a.substr(11);
        } else if (a.rfind("--log_file=", 0) == 0) {
            log_file = a.substr(11);
        } else if (a == "--resolution=540p" || a == "--resolution=960x540") {
            render_config_.resolution = ResolutionPreset::Res540p;
        } else if (a == "--resolution=480p" || a == "--resolution=854x480") {
            render_config_.resolution = ResolutionPreset::Res480p;
        } else if (a == "--resolution=720p" || a == "--resolution=1280x720") {
            render_config_.resolution = ResolutionPreset::Res720p;
        } else if (a == "--l4d2_fps_cap=30") {
            render_config_.fps_cap = FrameRateCap::Fps30;
        } else if (a == "--l4d2_fps_cap=120") {
            render_config_.fps_cap = FrameRateCap::Fps120;
        } else if (a == "--l4d2_fps_cap=60") {
            render_config_.fps_cap = FrameRateCap::Fps60;
        } else if (a == "--half_res_textures=true") {
            render_config_.half_res_textures = true;
        } else if (a == "--low_ram_texture_cache=true") {
            render_config_.low_ram_texture_cache = true;
        }
    }

    // 4. Initialize logging & crash handling
    log::Logger::Instance().Init(log_file);
    CrashHandler::Install();

    L4D2_LOG_INFO("App", "Left 4 Dead 2 Native Recompilation (L4D2 Recomp) Starting...");
    L4D2_LOG_INFO("App", "Target: Title ID 454108D4 | Media ID 0E79403B | World Disc v0");
    L4D2_LOG_INFO("App", "Game Data Root: %s", game_root_.c_str());

    // 5. Initialize ModuleLoader & Resolution
    ModuleLoader::Instance().Init(game_root_, save_root_);
    ResolutionManager::Instance().ApplyConfig(render_config_);

    is_initialized_ = true;
    return true;
}

int L4D2App::Run() {
    if (!is_initialized_) {
        std::cerr << "[L4D2App] Run() called without successful Initialize()" << std::endl;
        return 1;
    }

    L4D2_LOG_INFO("App", "Dispatching entrypoint default.xex at 0x82000000...");
    void* handle = nullptr;
    uint32_t status = ModuleLoader::Instance().XexLoadImage("default.xex", 0, 0, &handle);
    if (status != STATUS_SUCCESS) {
        L4D2_LOG_FATAL("App", "Failed to load default.xex (Status: 0x%08X)", status);
        return 1;
    }

    L4D2_LOG_INFO("App", "Main loop active. Guest state running.");
    return 0;
}

void L4D2App::Shutdown() {
    if (is_initialized_) {
        L4D2_LOG_INFO("App", "Shutting down L4D2 Recomp...");
        ModuleLoader::Instance().Shutdown();
        log::Logger::Instance().Shutdown();
        is_initialized_ = false;
    }
}

} // namespace l4d2

int main(int argc, char** argv) {
    auto& app = l4d2::L4D2App::Instance();
    if (!app.Initialize(argc, argv)) {
        return 1;
    }
    int code = app.Run();
    app.Shutdown();
    return code;
}
