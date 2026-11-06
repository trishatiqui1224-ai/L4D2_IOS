#import <UIKit/UIKit.h>
#import <AVFAudio/AVFAudio.h>
#import <dlfcn.h>
#import <fcntl.h>
#import <unistd.h>
#import <sys/stat.h>
#import <pthread.h>
#import <vector>
#import <string>
#import <sstream>
#import <fstream>
#import <algorithm>
#import <filesystem>

#import "launcher.h"
#import "boot_trace.h"
#import "../../src/logging/logger.h"

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
                args[i] = arg;
                return;
            }
        }
    }
    args.push_back(arg);
}

static void ApplyExtraArguments(const fs::path& file, std::vector<std::string>& args) {
    NSData* data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:file.c_str()]];
    if (!data) return;

    NSString* text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    if (!text) return;

    if ([text hasPrefix:@"\uFEFF"]) {
        text = [text substringFromIndex:1];
    }
    std::istringstream in(text.UTF8String);
    std::string line;
    while (std::getline(in, line)) {
        const auto a = line.find_first_not_of(" \t");
        const auto b = line.find_last_not_of(" \t\r\n");
        if (a == std::string::npos || line[a] == '#') continue;
        line = line.substr(a, b - a + 1);
        if (line.compare(0, 2, "--") == 0) {
            SetArgument(args, line);
            l4d2::boot::Trace("extra_args.txt: " + line);
        }
    }
}

static std::vector<std::string> GameArguments(const fs::path& docs, const fs::path& gameRoot) {
    const fs::path caches = CachesFolder();
    return {
        "l4d2recomp",
        "--gpu_plugin=xenos",
        "--gpu_backend=vulkan",
        "--render_target_path_vulkan=fbo",
        "--present_letterbox=true",
        "--present_allow_overscan_cutoff=false",
        "--vulkan_sparse_shared_memory=false",
        "--fullscreen=true",
        "--resolution_scale=1",
        "--readback_resolve=fast",
        "--ios_readback_max_kb=64",
        "--occlusion_query_enable=false",
        "--readback_memexport=false",
        "--ios_iso_stream=true",
        "--gpu_sin_msaa=true",
        "--audio_maxqframes=64",
        "--ios_xma_starve_reset=false",
        "--ios_utility_qos_guest=false",
        "--ios_utility_qos=false",
        "--anisotropic_override=4",
        "--present_effect=none",
        "--resolution=1280x720",
        "--ios_display_preset=retina",
        "--ios_retina=true",
        "--ios_fps_cap=60",
        "--mnk_mode=false",
        "--mnk_mouse=false",
        "--ios_haptics=true",
        "--ios_mvk_performance=false",
        "--user_language=1",
        "--user_country=103",
        "--user_data_root=" + (docs / "rex_data").string(),
        "--cache_root=" + (caches / "rexglue").string(),
        "--log_file=" + (docs / "l4d2.log").string(),
        "--log_level=info",
        "--log_flush_interval=1",
        "--game_data_root=" + gameRoot.string(),
    };
}

} // namespace l4d2::ios

// ============================================================================
// STAGE 0: Pre-main() Constructor (Priority 101) - Guarantees boot.txt within 1ms
// ============================================================================
__attribute__((constructor(101)))
static void EarlyBootTrace() {
    const char* home = getenv("HOME");
    if (!home) {
        NSString* nsHome = NSHomeDirectory();
        home = nsHome.UTF8String;
    }
    if (!home) return;

    char docsPath[1024];
    snprintf(docsPath, sizeof(docsPath), "%s/Documents", home);
    mkdir(docsPath, 0755);

    char bootPath[1024];
    snprintf(bootPath, sizeof(bootPath), "%s/Documents/boot.txt", home);
    int fd = open(bootPath, O_CREAT | O_WRONLY | O_APPEND, 0644);
    if (fd >= 0) {
        char msg[256];
        int len = snprintf(msg, sizeof(msg), "---- early_init (constructor 101), build %s %s, pid=%d\n", __DATE__, __TIME__, getpid());
        write(fd, msg, len);
        fsync(fd);
        close(fd);
    }
}

// ============================================================================
// STAGE 1: Native Inset-Grouped Launcher inside SDL_RunApp (SDLUIKitDelegate)
// ============================================================================

static bool g_launch_requested = false;
static fs::path g_selected_game_root;
static NSDictionary* g_selected_settings = nil;

static std::string ReadLastErrorFromLog(const fs::path& logPath) {
    std::ifstream file(logPath);
    if (!file.is_open()) return "";
    std::string line;
    std::vector<std::string> lines;
    while (std::getline(file, line)) {
        if (!line.empty()) {
            lines.push_back(line);
        }
    }
    for (auto it = lines.rbegin(); it != lines.rend(); ++it) {
        if (it->find("[error]") != std::string::npos ||
            it->find("[critical]") != std::string::npos ||
            it->find("[fatal]") != std::string::npos ||
            it->find("FAILED") != std::string::npos) {
            return *it;
        }
    }
    if (!lines.empty()) return lines.back();
    return "";
}

static void ShowErrorAlert(NSString* title, NSString* message) {
    l4d2::boot::Trace([NSString stringWithFormat:@"[ALERT] %@: %@", title, message].UTF8String);
    __block bool dismissed = false;
    dispatch_async(dispatch_get_main_queue(), ^{
        UIAlertController* alert = [UIAlertController alertControllerWithTitle:title
                                                                       message:message
                                                                preferredStyle:UIAlertControllerStyleAlert];
        [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:^(UIAlertAction*) {
            dismissed = true;
        }]];

        UIWindow* alertWin = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
        alertWin.backgroundColor = [UIColor blackColor];
        alertWin.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
        alertWin.rootViewController = [[UIViewController alloc] init];
        alertWin.windowLevel = UIWindowLevelAlert + 1;
        [alertWin makeKeyAndVisible];
        [alertWin.rootViewController presentViewController:alert animated:YES completion:nil];
    });

    while (!dismissed) {
        @autoreleasepool {
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.016, true);
        }
    }
}

static int L4D2_SDLMain(int argc, char* argv[]) {
    l4d2::boot::Trace("[SDLMain] L4D2_SDLMain entered (SDLUIKitDelegate active)");

    const fs::path docs = l4d2::ios::DocumentsFolder();
    fs::path logPath = docs / "l4d2.log";
    l4d2::log::Logger::Instance().Init(logPath.string());
    l4d2::boot::SetLogFilePath(logPath.string());
    L4D2_LOG_INFO("iOS", "L4D2 Recomp iOS Pure Launcher Booting... (Build %s %s)", __DATE__, __TIME__);

    // 1. Create temporary UIWindow for the launcher on top of SDL launch screen
    UIWindowScene* scene = nil;
    for (UIScene* s in UIApplication.sharedApplication.connectedScenes) {
        if ([s isKindOfClass:UIWindowScene.class] && ((UIWindowScene*)s).screen == UIScreen.mainScreen) {
            scene = (UIWindowScene*)s;
            break;
        }
    }
    UIWindow* launcherWindow = scene ? [[UIWindow alloc] initWithWindowScene:scene]
                                     : [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    launcherWindow.backgroundColor = [UIColor blackColor];
    launcherWindow.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    launcherWindow.windowLevel = UIWindowLevelNormal + 1; // over SDL's launch screen

    g_launch_requested = false;
    g_selected_game_root.clear();
    g_selected_settings = nil;

    L4D2LauncherController* rootVC = [[L4D2LauncherController alloc] initWithDocuments:docs
                                                                                  done:^(fs::path gameRoot, NSDictionary* settings) {
        g_selected_game_root = gameRoot;
        g_selected_settings = settings;
        g_launch_requested = true;
    }];

    L4D2LauncherNavigation* nav = [[L4D2LauncherNavigation alloc] initWithRootViewController:rootVC];
    nav.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;

    launcherWindow.rootViewController = nav;
    [launcherWindow makeKeyAndVisible];
    l4d2::boot::Trace("launcher: on screen");

    // 2. Pump runloop while waiting for user to configure settings and tap Play
    while (!g_launch_requested) {
        @autoreleasepool {
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.016, true);
        }
    }

    l4d2::boot::Trace("launcher: Play");

    // 3. Dismiss launcher window cleanly
    [rootVC.view endEditing:YES];
    launcherWindow.hidden = YES;
    launcherWindow.rootViewController = nil;
    launcherWindow = nil;

    for (UIScene* s in UIApplication.sharedApplication.connectedScenes) {
        if (![s isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow* w in ((UIWindowScene*)s).windows) {
            if ([w.rootViewController isKindOfClass:L4D2LauncherNavigation.class]) {
                w.hidden = YES;
                w.rootViewController = nil;
            } else if ([NSStringFromClass(w.rootViewController.class) hasPrefix:@"SDL"]) {
                [w makeKeyAndVisible];
            }
        }
    }

    CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.001, false);

    if (scene) {
        for (UIWindow* w in scene.windows) {
            [w.rootViewController setNeedsUpdateOfSupportedInterfaceOrientations];
        }
        UIWindowSceneGeometryPreferencesIOS* prefs = [[UIWindowSceneGeometryPreferencesIOS alloc]
            initWithInterfaceOrientations:UIInterfaceOrientationMaskLandscape];
        [scene requestGeometryUpdateWithPreferences:prefs errorHandler:nil];
    }

    // 4. Activate AVAudioSession before game starts (5.3 ms preferred buffer)
    l4d2::boot::Trace("audio: activating the session");
    AVAudioSession* session = [AVAudioSession sharedInstance];
    NSError* audioError = nil;
    [session setCategory:AVAudioSessionCategoryPlayback
                    mode:AVAudioSessionModeDefault
                 options:AVAudioSessionCategoryOptionMixWithOthers
                   error:&audioError];
    [session setPreferredIOBufferDuration:0.0053 error:&audioError];
    [session setActive:YES error:&audioError];
    if (audioError) {
        l4d2::boot::Trace(std::string("audio: session activation notice: ") + audioError.localizedDescription.UTF8String);
    }

    // 5. Preload librexgpu-xenos.dylib
    l4d2::boot::Trace("[dlopen] Loading librexgpu-xenos.dylib...");
    dlerror();
    void* hGpu = dlopen("@executable_path/Frameworks/librexgpu-xenos.dylib", RTLD_NOW | RTLD_GLOBAL);
    if (!hGpu) {
        const char* err = dlerror();
        std::string msg = std::string("Failed to load librexgpu-xenos.dylib:\n") + (err ? err : "unknown error");
        l4d2::boot::Trace("[FATAL] " + msg);
        ShowErrorAlert(@"Launch Error", [NSString stringWithUTF8String:msg.c_str()]);
        return 1;
    }
    l4d2::boot::Trace("[dlopen] librexgpu-xenos.dylib loaded successfully");

    // 6. Preload L4D2Game.framework/L4D2Game
    l4d2::boot::Trace("[dlopen] Loading L4D2Game.framework/L4D2Game...");
    dlerror();
    void* hGame = dlopen("@executable_path/Frameworks/L4D2Game.framework/L4D2Game", RTLD_NOW | RTLD_GLOBAL);
    if (!hGame) {
        const char* err = dlerror();
        std::string msg = std::string("Failed to load L4D2Game.framework/L4D2Game:\n") + (err ? err : "unknown error");
        l4d2::boot::Trace("[FATAL] " + msg);
        ShowErrorAlert(@"Launch Error", [NSString stringWithUTF8String:msg.c_str()]);
        return 1;
    }
    l4d2::boot::Trace("[dlopen] L4D2Game.framework/L4D2Game loaded successfully");

    // 7. Resolve L4D2_StartGame entry point
    typedef int (*L4D2_StartGameFn)(int, char**);
    dlerror();
    L4D2_StartGameFn startGameFn = (L4D2_StartGameFn)dlsym(hGame, "L4D2_StartGame");
    const char* dlsymErr = dlerror();
    if (!startGameFn || dlsymErr) {
        std::string msg = std::string("Failed to resolve L4D2_StartGame:\n") + (dlsymErr ? dlsymErr : "dlsym returned NULL");
        l4d2::boot::Trace("[FATAL] " + msg);
        ShowErrorAlert(@"Launch Error", [NSString stringWithUTF8String:msg.c_str()]);
        return 1;
    }
    char fnPtrBuf[128];
    snprintf(fnPtrBuf, sizeof(fnPtrBuf), "[dlopen] Resolved L4D2_StartGame at %p", (void*)startGameFn);
    l4d2::boot::Trace(fnPtrBuf);

    // 8. Build arguments
    auto texts = l4d2::ios::GameArguments(docs, g_selected_game_root);

    for (const std::string& a : l4d2::launcher::SettingsArguments(docs)) {
        l4d2::ios::SetArgument(texts, a);
        l4d2::boot::Trace("setting: " + a);
    }
    l4d2::ios::ApplyExtraArguments(docs / "extra_args.txt", texts);

    // Hard defaults for stability
    l4d2::ios::SetArgument(texts, "--ios_xma_starve_reset=false");
    l4d2::ios::SetArgument(texts, "--ios_utility_qos_guest=false");
    l4d2::ios::SetArgument(texts, "--ios_utility_qos=false");
    l4d2::ios::SetArgument(texts, "--ios_retina=true");

    std::vector<char*> game_argv;
    game_argv.reserve(texts.size() + 1);
    for (auto& t : texts) {
        game_argv.push_back(t.data());
    }
    game_argv.push_back(nullptr);
    const int game_argc = static_cast<int>(texts.size());

    l4d2::boot::Trace("[main] Calling L4D2_StartGame synchronously inside L4D2_SDLMain...");
    for (int i = 0; i < game_argc; ++i) {
        l4d2::boot::Trace(std::string("arg: ") + game_argv[i]);
    }

    int result = startGameFn(game_argc, game_argv.data());
    l4d2::boot::Trace("[main] L4D2_StartGame exited with code " + std::to_string(result));

    if (result != 0) {
        std::string lastErr = ReadLastErrorFromLog(docs / "l4d2.log");
        NSString* detail = lastErr.empty()
            ? @"Check Documents/boot.txt and Documents/l4d2.log for diagnostics."
            : [NSString stringWithFormat:@"%s\n\nCheck Documents/boot.txt and Documents/l4d2.log for full diagnostics.", lastErr.c_str()];
        NSString* msg = [NSString stringWithFormat:@"Left 4 Dead 2 exited with code %d.\n\n%@", result, detail];
        ShowErrorAlert(@"Left 4 Dead 2 Exited", msg);
    }
    return result;
}

// ============================================================================
// Genuine iOS main() Entrypoint -> SDL_RunApp (librexruntime.dylib)
// ============================================================================
int main(int argc, char* argv[]) {
    // 1. Immediate Line 1 POSIX boot trace + fsync
    const char* home = getenv("HOME");
    if (!home) {
        NSString* nsHome = NSHomeDirectory();
        home = nsHome.UTF8String;
    }
    if (home) {
        char docsPath[1024];
        snprintf(docsPath, sizeof(docsPath), "%s/Documents", home);
        mkdir(docsPath, 0755);
        char bootPath[1024];
        snprintf(bootPath, sizeof(bootPath), "%s/Documents/boot.txt", home);
        int fd = open(bootPath, O_CREAT | O_WRONLY | O_APPEND, 0644);
        if (fd >= 0) {
            char msg[256];
            int len = snprintf(msg, sizeof(msg), "---- start, build %s %s, argc=%d\n", __DATE__, __TIME__, argc);
            write(fd, msg, len);
            fsync(fd);
            close(fd);
        }
    }

    @autoreleasepool {
        // 2. Enforce 8 MiB host stack for guest threads
        pthread_attr_t attr;
        if (pthread_attr_init(&attr) == 0) {
            constexpr size_t kMinHostStack = 8 * 1024 * 1024; // 8 MiB
            pthread_attr_setstacksize(&attr, kMinHostStack);
        }

        // 3. Resolve sandbox directories early via Foundation
        const fs::path docs = l4d2::ios::DocumentsFolder();
        const fs::path caches = l4d2::ios::CachesFolder();
        const fs::path app_support = l4d2::ios::ApplicationSupportFolder();
        const fs::path tmp = l4d2::ios::TemporaryFolder();

        // 4. Pre-create writable sandbox directories before any component can touch them
        std::error_code ec;
        fs::create_directories(docs, ec);
        fs::create_directories(docs / "logs", ec);
        fs::create_directories(docs / "SAVE", ec);
        fs::create_directories(docs / "data", ec);
        fs::create_directories(docs / "config", ec);
        fs::create_directories(docs / "rex_data", ec);
        fs::create_directories(caches, ec);
        fs::create_directories(caches / "rexglue", ec);
        fs::create_directories(app_support, ec);
        fs::create_directories(tmp, ec);

        // 5. Redirect XDG & Temp env vars so POSIX/XDG libraries never touch ~/.local, ~/.cache, ~/.config
        setenv("XDG_DATA_HOME", (docs / "rex_data").c_str(), 1);
        setenv("XDG_CACHE_HOME", (caches).c_str(), 1);
        setenv("XDG_CONFIG_HOME", (docs / "config").c_str(), 1);
        setenv("TMPDIR", tmp.c_str(), 1);
        if (!docs.empty()) {
            setenv("HOME", docs.parent_path().c_str(), 1);
        }

        setenv("SDL_IOS_ORIENTATIONS", "LandscapeLeft LandscapeRight", 1);

        // 6. Open Documents/boot.txt and setup alternate signal stack
        l4d2::boot::SetupAltStack();
        l4d2::boot::Open((docs / "boot.txt").string());
        l4d2::boot::Trace("---- start, build " __DATE__ " " __TIME__);
        l4d2::boot::Trace("Documents: " + docs.string());
        l4d2::boot::Trace("Caches: " + caches.string());
        l4d2::boot::Trace("XDG_DATA_HOME: " + (docs / "rex_data").string());

        // 7. Preload MoltenVK.framework/MoltenVK
        l4d2::boot::Trace("[dlopen] Preloading MoltenVK.framework/MoltenVK...");
        dlerror();
        void* hMvk = dlopen("@executable_path/Frameworks/MoltenVK.framework/MoltenVK", RTLD_NOW | RTLD_GLOBAL);
        if (!hMvk) {
            const char* err = dlerror();
            l4d2::boot::Trace(std::string("[FATAL] MoltenVK load failed: ") + (err ? err : "unknown error"));
            return 1;
        }
        l4d2::boot::Trace("[dlopen] MoltenVK.framework/MoltenVK loaded successfully");

        // 8. Preload librexruntime.dylib
        l4d2::boot::Trace("[dlopen] Preloading librexruntime.dylib...");
        dlerror();
        void* hRuntime = dlopen("@executable_path/Frameworks/librexruntime.dylib", RTLD_NOW | RTLD_GLOBAL);
        if (!hRuntime) {
            const char* err = dlerror();
            l4d2::boot::Trace(std::string("[FATAL] librexruntime load failed: ") + (err ? err : "unknown error"));
            return 1;
        }
        l4d2::boot::Trace("[dlopen] librexruntime.dylib loaded successfully");

        // 9. Resolve SDL_RunApp from librexruntime.dylib and run
        typedef int (*SDL_main_func)(int argc, char *argv[]);
        typedef int (*SDL_RunAppFn)(int argc, char *argv[], SDL_main_func mainFunction, void *reserved);
        SDL_RunAppFn sdlRunApp = (SDL_RunAppFn)dlsym(hRuntime, "SDL_RunApp");
        if (!sdlRunApp) {
            sdlRunApp = (SDL_RunAppFn)dlsym(RTLD_DEFAULT, "SDL_RunApp");
        }
        if (!sdlRunApp) {
            const char* err = dlerror();
            l4d2::boot::Trace(std::string("[FATAL] Failed to resolve SDL_RunApp: ") + (err ? err : "dlsym returned NULL"));
            return 1;
        }

        char ptrBuf[128];
        snprintf(ptrBuf, sizeof(ptrBuf), "[main] Resolved SDL_RunApp at %p, launching SDL_RunApp...", (void*)sdlRunApp);
        l4d2::boot::Trace(ptrBuf);

        return sdlRunApp(argc, argv, L4D2_SDLMain, nullptr);
    }
}
