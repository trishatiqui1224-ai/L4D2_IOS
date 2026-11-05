#import <UIKit/UIKit.h>
#import "launcher.h"
#import "boot_trace.h"
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
#include <filesystem>
#include <sys/stat.h>

namespace fs = std::filesystem;

namespace l4d2::ios {

static fs::path DocumentsFolder() {
    NSArray<NSString*>* paths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    return fs::path(paths.firstObject.UTF8String);
}

static fs::path CachesFolder() {
    NSArray<NSString*>* paths = NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES);
    return fs::path(paths.firstObject.UTF8String);
}

static fs::path ApplicationSupportFolder() {
    NSArray<NSString*>* paths = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES);
    return fs::path(paths.firstObject.UTF8String);
}

static fs::path TemporaryFolder() {
    NSString* tmp = NSTemporaryDirectory();
    return fs::path(tmp.UTF8String);
}

} // namespace l4d2::ios

@interface L4D2AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong, nonatomic) UIWindow *window;
@property (strong, nonatomic) L4D2LauncherVC *launcherVC;
- (void)startGameWithRoot:(fs::path)gameRoot settings:(NSDictionary*)settings;
@end

@implementation L4D2AppDelegate

- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)launchOptions {
    l4d2::boot::Trace("[AppDelegate] didFinishLaunchingWithOptions entered");

    fs::path docs = l4d2::ios::DocumentsFolder();
    fs::path logPath = docs / "l4d2.log";
    l4d2::log::Logger::Instance().Init(logPath.string());
    l4d2::boot::SetLogFilePath(logPath.string());
    L4D2_LOG_INFO("iOS", "L4D2 Recomp iOS Runtime Booting... (Build %s %s)", __DATE__, __TIME__);

    // 1. Create full screen window
    self.window = [[UIWindow alloc] initWithFrame:[UIScreen mainScreen].bounds];
    self.window.backgroundColor = [UIColor colorWithRed:0.06 green:0.08 blue:0.06 alpha:1.0];

    // 2. Instantiate interactive Left 4 Dead 2 Launcher
    self.launcherVC = [[L4D2LauncherVC alloc] initWithDocuments:docs];
    __weak typeof(self) weakSelf = self;
    self.launcherVC.onPlayHandler = ^(fs::path gameRoot, NSDictionary* settings) {
        [weakSelf startGameWithRoot:gameRoot settings:settings];
    };

    self.window.rootViewController = self.launcherVC;
    [self.window makeKeyAndVisible];

    l4d2::boot::Trace("[AppDelegate] Launcher UI successfully presented on main window");
    return YES;
}

- (void)startGameWithRoot:(fs::path)gameRoot settings:(NSDictionary*)settings {
    l4d2::boot::Trace("[Launcher] Starting Source Engine with game root: " + gameRoot.string());

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
                     l4d2::touch::ControlStyle::XboxStandard : l4d2::touch::ControlStyle::L4D2ShooterMode;
    touchCfg.drag_to_look = [settings[@"drag_look"] isEqualToString:@"true"];
    l4d2::touch::Install(touchCfg);
    l4d2::touch::InstallFpsCounter();
    l4d2::boot::Trace("[Touch] Mobile Shooter Touch HUD installed");

    // 4. Initialize Multi-Module Loader
    fs::path docs = l4d2::ios::DocumentsFolder();
    fs::path saveRoot = docs / "SAVE";
    l4d2::ModuleLoader::Instance().Init(gameRoot.string(), saveRoot.string());
    l4d2::boot::Trace("[ModuleLoader] Initialized");

    // 5. Dispatch default.xex entry point
    l4d2::boot::Trace("[Game] Dispatching default.xex entrypoint...");
    void* handle = nullptr;
    uint32_t status = l4d2::ModuleLoader::Instance().XexLoadImage("default.xex", 0, 0, &handle);
    char statusBuf[128];
    snprintf(statusBuf, sizeof(statusBuf), "[Game] XexLoadImage returned status: 0x%08X", status);
    l4d2::boot::Trace(statusBuf);
}

@end

int main(int argc, char* argv[]) {
    @autoreleasepool {
        // 1. Enforce 8 MiB host stack for guest threads (Source Engine BSP trace, Havok & Director pathfinding)
        pthread_attr_t attr;
        if (pthread_attr_init(&attr) == 0) {
            constexpr size_t kMinHostStack = 8 * 1024 * 1024; // 8 MiB
            pthread_attr_setstacksize(&attr, kMinHostStack);
        }

        // 2. Resolve sandbox directories early via Foundation
        const fs::path docs = l4d2::ios::DocumentsFolder();
        const fs::path caches = l4d2::ios::CachesFolder();
        const fs::path app_support = l4d2::ios::ApplicationSupportFolder();
        const fs::path tmp = l4d2::ios::TemporaryFolder();

        // 3. Pre-create writable sandbox directories before any component can touch them
        std::error_code ec;
        fs::create_directories(docs, ec);
        fs::create_directories(docs / "logs", ec);
        fs::create_directories(docs / "SAVE", ec);
        fs::create_directories(docs / "data", ec);
        fs::create_directories(docs / "config", ec);
        fs::create_directories(docs / "rex_data", ec);
        fs::create_directories(caches, ec);
        fs::create_directories(app_support, ec);
        fs::create_directories(tmp, ec);

        // 4. Redirect XDG & Temp env vars so POSIX/XDG libraries never touch ~/.local, ~/.cache, ~/.config
        setenv("XDG_DATA_HOME", (docs / "rex_data").c_str(), 1);
        setenv("XDG_CACHE_HOME", (caches).c_str(), 1);
        setenv("XDG_CONFIG_HOME", (docs / "config").c_str(), 1);
        setenv("TMPDIR", tmp.c_str(), 1);
        if (!docs.empty()) {
            setenv("HOME", docs.parent_path().c_str(), 1);
        }

        // 5. Open Documents/boot.txt and setup alternate signal stack IMMEDIATELY
        l4d2::boot::SetupAltStack();
        l4d2::boot::Open((docs / "boot.txt").string());
        l4d2::boot::Trace("---- start, build " __DATE__ " " __TIME__);
        l4d2::boot::Trace("Documents: " + docs.string());
        l4d2::boot::Trace("Caches: " + caches.string());
        l4d2::boot::Trace("XDG_DATA_HOME: " + (docs / "rex_data").string());

        // 6. Install symbolicated crash handler
        l4d2::CrashHandler::SetBootFilePath((docs / "boot.txt").string());
        l4d2::CrashHandler::Install();

        // 7. Start UIApplicationMain on main thread
        l4d2::boot::Trace("[main] Calling UIApplicationMain...");
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([L4D2AppDelegate class]));
    }
}
