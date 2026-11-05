#import <UIKit/UIKit.h>
#import <dlfcn.h>
#import <fcntl.h>
#import <unistd.h>
#import <sys/stat.h>
#import <pthread.h>
#import <vector>
#import <string>
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
    L4D2_LOG_INFO("iOS", "L4D2 Recomp iOS Pure Launcher Booting... (Build %s %s)", __DATE__, __TIME__);

    // 1. Create full screen window
    self.window = [[UIWindow alloc] initWithFrame:[UIScreen mainScreen].bounds];
    self.window.backgroundColor = [UIColor colorWithRed:0.06 green:0.08 blue:0.06 alpha:1.0];

    // 2. Instantiate interactive Left 4 Dead 2 Launcher
    self.launcherVC = [[L4D2LauncherVC alloc] initWithDocuments:docs];
    __weak L4D2AppDelegate* weakSelf = self;
    self.launcherVC.onPlayHandler = ^(fs::path gameRoot, NSDictionary* settings) {
        [weakSelf startGameWithRoot:gameRoot settings:settings];
    };

    self.window.rootViewController = self.launcherVC;
    [self.window makeKeyAndVisible];

    l4d2::boot::Trace("[AppDelegate] Launcher UI successfully presented on main window");
    return YES;
}

// ============================================================================
// STAGE 2: Dynamic dlopen Loading of ReXGlue & L4D2Game Framework on Play
// ============================================================================
- (void)startGameWithRoot:(fs::path)gameRoot settings:(NSDictionary*)settings {
    l4d2::boot::Trace("[Launcher] Play tapped! Preparing dynamic Stage-2 load...");
    l4d2::boot::Trace("[Launcher] Game Root: " + gameRoot.string());

    auto showDlopenError = ^(NSString* libName, const char* err) {
        NSString* errMsg = err ? [NSString stringWithUTF8String:err] : @"Unknown dynamic linker error";
        NSString* fullMsg = [NSString stringWithFormat:@"Failed to load %@:\n%@", libName, errMsg];
        l4d2::boot::Trace([NSString stringWithFormat:@"[FATAL] %@", fullMsg].UTF8String);

        dispatch_async(dispatch_get_main_queue(), ^{
            UIAlertController* alert = [UIAlertController alertControllerWithTitle:@"Launch Error"
                                                                           message:fullMsg
                                                                    preferredStyle:UIAlertControllerStyleAlert];
            [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
            [self.launcherVC presentViewController:alert animated:YES completion:nil];
        });
    };

    // 1. Load librexruntime.dylib
    l4d2::boot::Trace("[dlopen] Loading librexruntime.dylib...");
    void* hRuntime = dlopen("@executable_path/Frameworks/librexruntime.dylib", RTLD_NOW | RTLD_GLOBAL);
    if (!hRuntime) {
        showDlopenError(@"librexruntime.dylib", dlerror());
        return;
    }
    l4d2::boot::Trace("[dlopen] librexruntime.dylib loaded successfully");

    // 2. Load librexgpu-xenos.dylib (loads MoltenVK.framework dynamically)
    l4d2::boot::Trace("[dlopen] Loading librexgpu-xenos.dylib...");
    void* hGpu = dlopen("@executable_path/Frameworks/librexgpu-xenos.dylib", RTLD_NOW | RTLD_GLOBAL);
    if (!hGpu) {
        showDlopenError(@"librexgpu-xenos.dylib", dlerror());
        return;
    }
    l4d2::boot::Trace("[dlopen] librexgpu-xenos.dylib loaded successfully");

    // 3. Load L4D2Game.framework
    l4d2::boot::Trace("[dlopen] Loading L4D2Game.framework/L4D2Game...");
    void* hGame = dlopen("@executable_path/Frameworks/L4D2Game.framework/L4D2Game", RTLD_NOW | RTLD_GLOBAL);
    if (!hGame) {
        // Fallback check for direct dylib if not in framework bundle
        hGame = dlopen("@executable_path/Frameworks/libL4D2Game.dylib", RTLD_NOW | RTLD_GLOBAL);
    }
    if (!hGame) {
        showDlopenError(@"L4D2Game.framework", dlerror());
        return;
    }
    l4d2::boot::Trace("[dlopen] L4D2Game loaded successfully");

    // 4. Resolve L4D2_StartGame entry point
    typedef int (*L4D2_StartGameFn)(const char*, const char*, const char*);
    L4D2_StartGameFn startGameFn = (L4D2_StartGameFn)dlsym(hGame, "L4D2_StartGame");
    if (!startGameFn) {
        showDlopenError(@"L4D2Game symbol L4D2_StartGame", dlerror());
        return;
    }

    // 5. Serialize settings and invoke entry point
    NSData* jsonData = [NSJSONSerialization dataWithJSONObject:settings options:0 error:nil];
    NSString* jsonStr = jsonData ? [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding] : @"{}";
    fs::path docs = l4d2::ios::DocumentsFolder();
    fs::path saveRoot = docs / "SAVE";

    l4d2::boot::Trace("[dlopen] Calling L4D2_StartGame...");
    startGameFn(gameRoot.string().c_str(), saveRoot.string().c_str(), jsonStr.UTF8String);
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
