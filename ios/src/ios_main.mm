#import <UIKit/UIKit.h>
#import <dlfcn.h>
#import <fcntl.h>
#import <unistd.h>
#import <sys/stat.h>
#import <pthread.h>
#import <vector>
#import <string>
#import <sstream>
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
// STAGE 1: Pure Minimal UIKit Launcher (Zero Custom LC_LOAD_DYLIB Dependencies)
// ============================================================================
@interface L4D2AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong, nonatomic) UIWindow *window;
@property (strong, nonatomic) L4D2LauncherController *launcherVC;
@property (assign, nonatomic) BOOL isLaunching;
- (void)startGameWithRoot:(fs::path)gameRoot settings:(NSDictionary*)settings;
@end

@implementation L4D2AppDelegate

- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)launchOptions {
    l4d2::boot::Trace("[AppDelegate] didFinishLaunchingWithOptions entered");

    fs::path docs = l4d2::ios::DocumentsFolder();
    fs::path logPath = docs / "l4d2.log";
    l4d2::log::Logger::Instance().Init(logPath.string());
    l4d2::boot::SetLogFilePath(logPath.string());
    L4D2_LOG_INFO("iOS", "L4D2 Recomp iOS Pure Launcher Booting... (Build %s %s)", __DATE__, __TIME__);

    // 1. Create full screen dark mode window
    self.window = [[UIWindow alloc] initWithFrame:[UIScreen mainScreen].bounds];
    self.window.backgroundColor = [UIColor blackColor];
    self.window.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;

    // 2. Instantiate interactive Left 4 Dead 2 Launcher with NFSCarbon styling
    __weak L4D2AppDelegate* weakSelf = self;
    self.launcherVC = [[L4D2LauncherController alloc] initWithDocuments:docs done:^(fs::path gameRoot, NSDictionary* settings) {
        [weakSelf startGameWithRoot:gameRoot settings:settings];
    }];

    L4D2LauncherNavigation* nav = [[L4D2LauncherNavigation alloc] initWithRootViewController:self.launcherVC];
    nav.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;

    self.window.rootViewController = nav;
    [self.window makeKeyAndVisible];

    l4d2::boot::Trace("[AppDelegate] Native Inset-Grouped Launcher UI presented on window");
    return YES;
}

// ============================================================================
// STAGE 2: Dynamic dlopen Loading of ReXGlue & L4D2Game Framework on Play
// ============================================================================
- (void)startGameWithRoot:(fs::path)gameRoot settings:(NSDictionary*)settings {
    if (self.isLaunching) {
        l4d2::boot::Trace("[Launcher] Guarded against double-tap re-entry");
        return;
    }
    self.isLaunching = YES;

    l4d2::boot::Trace("[Launcher] Play tapped! Preparing dynamic Stage-2 load...");
    l4d2::boot::Trace("[Launcher] Game Root: " + gameRoot.string());

    auto showDlopenError = ^(NSString* libName, const char* err) {
        std::string savedErr = err ? err : "Unknown dynamic linker error";
        NSString* fullMsg = [NSString stringWithFormat:@"Failed to load %@:\n%s", libName, savedErr.c_str()];
        l4d2::boot::Trace("[FATAL] " + std::string(fullMsg.UTF8String));

        dispatch_async(dispatch_get_main_queue(), ^{
            UIAlertController* alert = [UIAlertController alertControllerWithTitle:@"Launch Error"
                                                                           message:fullMsg
                                                                    preferredStyle:UIAlertControllerStyleAlert];
            [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
            [self.launcherVC presentViewController:alert animated:YES completion:nil];
            self.isLaunching = NO;
        });
    };

    // Inspect Frameworks directory contents for diagnostic tracing
    NSString* fwDir = [[NSBundle mainBundle] privateFrameworksPath];
    NSFileManager* fm = [NSFileManager defaultManager];
    NSArray* fwContents = [fm contentsOfDirectoryAtPath:fwDir error:nil];
    l4d2::boot::Trace("[dlopen] Inspecting Frameworks directory: " + std::string(fwDir ? fwDir.UTF8String : "(null)"));
    if (fwContents) {
        for (NSString* item in fwContents) {
            l4d2::boot::Trace("  - " + std::string(item.UTF8String));
        }
    }

    // 1. Strict dependency preload: MoltenVK.framework/MoltenVK
    l4d2::boot::Trace("[dlopen] Loading MoltenVK.framework/MoltenVK...");
    dlerror();
    void* hMvk = dlopen("@executable_path/Frameworks/MoltenVK.framework/MoltenVK", RTLD_NOW | RTLD_GLOBAL);
    if (!hMvk) {
        const char* err = dlerror();
        showDlopenError(@"MoltenVK.framework/MoltenVK", err);
        return;
    }
    l4d2::boot::Trace("[dlopen] MoltenVK.framework/MoltenVK loaded successfully");

    // 2. Strict dependency preload: SDL3 (if dynamic dylib / framework present)
    NSString* sdlPath = [fwDir stringByAppendingPathComponent:@"libSDL3.dylib"];
    if (![fm fileExistsAtPath:sdlPath]) {
        sdlPath = [fwDir stringByAppendingPathComponent:@"SDL3.framework/SDL3"];
    }
    if ([fm fileExistsAtPath:sdlPath]) {
        l4d2::boot::Trace("[dlopen] Loading dynamic SDL3: " + std::string(sdlPath.UTF8String) + "...");
        dlerror();
        void* hSdl = dlopen(sdlPath.UTF8String, RTLD_NOW | RTLD_GLOBAL);
        if (!hSdl) {
            const char* err = dlerror();
            showDlopenError(@"SDL3", err);
            return;
        }
        l4d2::boot::Trace("[dlopen] SDL3 loaded successfully");
    } else {
        l4d2::boot::Trace("[dlopen] Dynamic SDL3 not present (SDL3 is statically linked into L4D2Game)");
    }

    // 3. Strict dependency preload: librexruntime.dylib
    l4d2::boot::Trace("[dlopen] Loading librexruntime.dylib...");
    dlerror();
    void* hRuntime = dlopen("@executable_path/Frameworks/librexruntime.dylib", RTLD_NOW | RTLD_GLOBAL);
    if (!hRuntime) {
        const char* err = dlerror();
        showDlopenError(@"librexruntime.dylib", err);
        return;
    }
    l4d2::boot::Trace("[dlopen] librexruntime.dylib loaded successfully");

    // 4. Strict dependency preload: librexgpu-xenos.dylib
    l4d2::boot::Trace("[dlopen] Loading librexgpu-xenos.dylib...");
    dlerror();
    void* hGpu = dlopen("@executable_path/Frameworks/librexgpu-xenos.dylib", RTLD_NOW | RTLD_GLOBAL);
    if (!hGpu) {
        const char* err = dlerror();
        showDlopenError(@"librexgpu-xenos.dylib", err);
        return;
    }
    l4d2::boot::Trace("[dlopen] librexgpu-xenos.dylib loaded successfully");

    // 5. Strict dependency preload: L4D2Game.framework/L4D2Game (ZERO dlerror clobbering!)
    l4d2::boot::Trace("[dlopen] Loading L4D2Game.framework/L4D2Game...");
    dlerror();
    void* hGame = dlopen("@executable_path/Frameworks/L4D2Game.framework/L4D2Game", RTLD_NOW | RTLD_GLOBAL);
    if (!hGame) {
        const char* err = dlerror();
        showDlopenError(@"L4D2Game.framework/L4D2Game", err);
        return;
    }
    l4d2::boot::Trace("[dlopen] L4D2Game.framework/L4D2Game loaded successfully");

    // 6. Resolve L4D2_StartGame entry point
    typedef int (*L4D2_StartGameFn)(int, char**);
    dlerror();
    L4D2_StartGameFn startGameFn = (L4D2_StartGameFn)dlsym(hGame, "L4D2_StartGame");
    const char* dlsymErr = dlerror();
    if (!startGameFn || dlsymErr) {
        showDlopenError(@"L4D2Game symbol L4D2_StartGame", dlsymErr ? dlsymErr : "dlsym returned NULL");
        return;
    }
    char fnPtrBuf[128];
    snprintf(fnPtrBuf, sizeof(fnPtrBuf), "[dlopen] Resolved L4D2_StartGame at %p", (void*)startGameFn);
    l4d2::boot::Trace(fnPtrBuf);

    // 7. Build arguments
    fs::path docs = l4d2::ios::DocumentsFolder();
    auto texts = l4d2::ios::GameArguments(docs, gameRoot);

    for (const std::string& a : l4d2::launcher::SettingsArguments(docs)) {
        l4d2::ios::SetArgument(texts, a);
    }
    l4d2::ios::ApplyExtraArguments(docs / "extra_args.txt", texts);

    // Hard defaults for stability
    l4d2::ios::SetArgument(texts, "--ios_xma_starve_reset=false");
    l4d2::ios::SetArgument(texts, "--ios_utility_qos_guest=false");
    l4d2::ios::SetArgument(texts, "--ios_utility_qos=false");
    l4d2::ios::SetArgument(texts, "--ios_retina=true");

    l4d2::boot::Trace("[Launcher] Scheduling L4D2_StartGame on main runloop turn...");

    // 8. Dispatch launch on main queue, dismissing launcher window so SDL3 can own keyWindow
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.launcherVC.view endEditing:YES];
        self.window.hidden = YES;
        self.window.rootViewController = nil;
        self.window = nil;

        std::vector<char*> args;
        args.reserve(texts.size() + 1);
        for (auto& t : texts) {
            args.push_back(const_cast<char*>(t.data()));
        }
        args.push_back(nullptr);
        const int n = static_cast<int>(texts.size());

        l4d2::boot::Trace("[dlopen] Calling L4D2_StartGame with arguments...");
        int result = startGameFn(n, args.data());
        l4d2::boot::Trace("[main] L4D2_StartGame exited with code " + std::to_string(result));

        if (result != 0) {
            dispatch_async(dispatch_get_main_queue(), ^{
                UIAlertController* alert = [UIAlertController alertControllerWithTitle:@"Game Terminated"
                                                                               message:@"Left 4 Dead 2 exited with an error. Check Documents/boot.txt and Documents/l4d2.log for diagnostics."
                                                                        preferredStyle:UIAlertControllerStyleAlert];
                [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];

                // Restore launcher window
                self.window = [[UIWindow alloc] initWithFrame:[UIScreen mainScreen].bounds];
                self.window.backgroundColor = [UIColor blackColor];
                self.window.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
                self.window.rootViewController = [[L4D2LauncherNavigation alloc] initWithRootViewController:self.launcherVC];
                [self.window makeKeyAndVisible];
                [self.launcherVC presentViewController:alert animated:YES completion:nil];
                self.isLaunching = NO;
            });
        }
    });
}

@end

// ============================================================================
// Genuine iOS main() Entrypoint (NEVER Hijacked by SDL_main)
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
            int len = snprintf(msg, sizeof(msg), "---- main_entered (Line 1), build %s %s, argc=%d\n", __DATE__, __TIME__, argc);
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

        // 7. Start UIApplicationMain on main thread
        l4d2::boot::Trace("[main] Calling UIApplicationMain...");
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([L4D2AppDelegate class]));
    }
}
