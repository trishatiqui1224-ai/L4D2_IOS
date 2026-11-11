#include "l4d2_default_init.h"

#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/rex_app.h>
#include <rex/runtime.h>
#include <rex/system/kernel_state.h>

#include <spdlog/spdlog.h>

#include <cstdio>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include "crash_handler.h"
#include "logging/logger.h"
#include "module_loader.h"
#include "resolution_hooks.h"

namespace {

void RegisterL4D2StaticModules(rex::system::KernelState* kernel_state) {
    l4d2::ModuleLoader::RegisterRecompiledModules(kernel_state);
}

rex::PPCImageInfo MakeL4D2ImageInfo() {
    rex::PPCImageInfo info = l4d2_default_PPCImageConfig;
    info.register_modules = &RegisterL4D2StaticModules;
    return info;
}

std::filesystem::path FindDefaultGameDataRoot() {
    namespace fs = std::filesystem;
    const std::vector<fs::path> candidates = {
        fs::current_path() / "Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru)",
        fs::current_path().parent_path() / "Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru)",
        fs::current_path() / "game",
        fs::current_path(),
    };
    for (const auto& candidate : candidates) {
        std::error_code ec;
        if (fs::exists(candidate / "default.xex", ec)) {
            return fs::weakly_canonical(candidate, ec);
        }
    }
    return {};
}

void AppendBootBanner(const std::filesystem::path& boot_path) {
    FILE* f = std::fopen(boot_path.string().c_str(), "a");
    if (!f) {
        return;
    }
    std::fprintf(f, "---- start, build windows-d3d12 (rexglue 0.10.0) argc=1\n");
    std::fclose(f);
}

}  // namespace

class L4D2WinApp : public rex::ReXApp {
public:
    using rex::ReXApp::ReXApp;

    static std::unique_ptr<rex::ui::WindowedApp> Create(rex::ui::WindowedAppContext& ctx) {
        return std::unique_ptr<L4D2WinApp>(new L4D2WinApp(ctx, "l4d2_recomp", MakeL4D2ImageInfo()));
    }

protected:
    void OnPostInitLogging() override {
        namespace fs = std::filesystem;
        std::string log_file_cvar = rex::cvar::GetFlagByName("log_file");
        fs::path base_dir = fs::current_path();
        if (!log_file_cvar.empty()) {
            fs::path p(log_file_cvar);
            if (p.has_parent_path()) {
                base_dir = p.parent_path();
            }
        }
        std::error_code ec;
        fs::create_directories(base_dir, ec);

        fs::path boot_path = base_dir / "boot.txt";
        l4d2::CrashHandler::SetBootFilePath(boot_path.string());
        AppendBootBanner(boot_path);
        l4d2::log::Logger::Instance().Init((base_dir / "l4d2.log").string());

        if (auto logger = spdlog::default_logger()) {
            logger->flush_on(spdlog::level::info);
        }
        REXLOG_INFO("L4D2 Windows ReXGlue logging initialized (boot_path={})", boot_path.string());
    }

    void OnConfigurePaths(rex::PathConfig& paths) override {
        namespace fs = std::filesystem;
        std::string cvar_root = rex::cvar::GetFlagByName("game_data_root");
        if (!cvar_root.empty()) {
            paths.game_data_root = fs::path(cvar_root);
        } else if (paths.game_data_root.empty()) {
            paths.game_data_root = FindDefaultGameDataRoot();
        }
        if (paths.user_data_root.empty()) {
            paths.user_data_root = fs::current_path() / "SAVE";
        }
        if (paths.cache_root.empty()) {
            paths.cache_root = fs::current_path() / "CACHE";
        }
        std::error_code ec;
        fs::create_directories(paths.user_data_root, ec);
        fs::create_directories(paths.cache_root, ec);
        REXLOG_INFO("L4D2 paths: game_data_root='{}' user_data_root='{}' cache_root='{}'",
                    paths.game_data_root.string(),
                    paths.user_data_root.string(),
                    paths.cache_root.string());
    }

    void OnPreSetup(rex::RuntimeConfig& config) override {
        if (config.gpu_plugin.empty()) {
            config.gpu_plugin = "xenos";
        }
        REXLOG_INFO("L4D2 OnPreSetup: gpu_plugin='{}' gpu_backend='{}'",
                    config.gpu_plugin, rex::cvar::GetFlagByName("gpu_backend"));
    }

    void OnPostSetup() override {
        l4d2::CrashHandler::Install();
        l4d2::RenderConfig render_cfg;
        l4d2::ResolutionManager::Instance().ApplyConfig(render_cfg);
        REXLOG_INFO("L4D2 OnPostSetup complete");
    }

    void OnPreLaunchModule() override {
        std::string game_root = game_data_root().empty()
                                    ? rex::cvar::GetFlagByName("game_data_root")
                                    : game_data_root().string();
        std::string save_root = user_data_root().empty()
                                    ? (std::filesystem::current_path() / "SAVE").string()
                                    : user_data_root().string();
        l4d2::ModuleLoader::Instance().Init(game_root, save_root);
        if (runtime() && runtime()->kernel_state()) {
            l4d2::ModuleLoader::Instance().PreloadSourceModules(runtime()->kernel_state());
        }
    }

    void OnShutdown() override {
        l4d2::ModuleLoader::Instance().Shutdown();
        l4d2::log::Logger::Instance().Shutdown();
        if (auto logger = spdlog::default_logger()) {
            logger->flush();
        }
    }
};

REX_DEFINE_APP(l4d2_recomp, L4D2WinApp::Create)

