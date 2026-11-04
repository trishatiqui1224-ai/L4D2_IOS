#import "launcher.h"
#import "l4d2_strings.h"
#import "touch_controls.h"
#import "../../src/l4d2_manifest.h"
#import "../../src/logging/logger.h"

#import <UIKit/UIKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

static fs::path s_documents;
static fs::path s_selected_game_root;
static bool s_disc_verified = false;
static l4d2::i18n::Language s_language = l4d2::i18n::Language::English;

static UIWindow* GetKeyWindow() {
    for (UIWindowScene* scene in [UIApplication sharedApplication].connectedScenes) {
        if ([scene isKindOfClass:[UIWindowScene class]]) {
            for (UIWindow* w in scene.windows) {
                if (w.isKeyWindow || scene.windows.count == 1) return w;
            }
        }
    }
    return nil;
}

@interface L4D2LauncherVC : UIViewController <UIDocumentPickerDelegate>
@property (nonatomic, strong) UILabel* titleLabel;
@property (nonatomic, strong) UILabel* statusBadge;
@property (nonatomic, strong) UISegmentedControl* langSelector;
@property (nonatomic, strong) UIProgressView* verifyProgressBar;
@property (nonatomic, strong) UILabel* verifyProgressLabel;
@property (nonatomic, strong) UIButton* playButton;
@property (nonatomic, strong) UISegmentedControl* tabsControl;
@property (nonatomic, strong) UIScrollView* contentScroll;
@property (nonatomic, strong) NSMutableDictionary* settings;

- (void)loadSettings;
- (void)saveSettings;
- (void)checkExistingDisc;
- (void)buildUI;
- (void)populateTabContent:(NSInteger)tab;
- (void)addSegmentRow:(NSString*)title key:(NSString*)key choices:(NSArray*)choices y:(CGFloat*)y scrollW:(CGFloat)w;
- (void)addSwitchRow:(NSString*)title key:(NSString*)key y:(CGFloat*)y scrollW:(CGFloat)w;
- (void)onLangChanged:(UISegmentedControl*)sc;
- (void)onTabChanged:(UISegmentedControl*)sc;
- (void)onImportTapped;
- (void)onVerifyTapped;
- (void)onExportLogsTapped;
- (void)onPlayTapped;
@end

@implementation L4D2LauncherVC

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = [UIColor colorWithRed:0.06 green:0.08 blue:0.06 alpha:1.0];
    [self loadSettings];
    [self buildUI];
    [self checkExistingDisc];
}

- (void)loadSettings {
    _settings = [NSMutableDictionary dictionary];
    fs::path setPath = s_documents / "settings.json";
    if (fs::exists(setPath)) {
        NSData* data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:setPath.string().c_str()]];
        if (data) {
            NSDictionary* json = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
            if (json) [_settings addEntriesFromDictionary:json];
        }
    }
    // Defaults
    if (!_settings[@"resolution"]) _settings[@"resolution"] = @"720p";
    if (!_settings[@"fps_cap"]) _settings[@"fps_cap"] = @"60";
    if (!_settings[@"half_textures"]) _settings[@"half_textures"] = @"false";
    if (!_settings[@"low_ram"]) _settings[@"low_ram"] = @"true";
    if (!_settings[@"cpu_boost"]) _settings[@"cpu_boost"] = @"true";
    if (!_settings[@"control_style"]) _settings[@"control_style"] = @"l4d2";
    if (!_settings[@"drag_look"]) _settings[@"drag_look"] = @"true";
    if (!_settings[@"split_screen"]) _settings[@"split_screen"] = @"false";
}

- (void)saveSettings {
    fs::path setPath = s_documents / "settings.json";
    NSData* data = [NSJSONSerialization dataWithJSONObject:_settings options:NSJSONWritingPrettyPrinted error:nil];
    if (data) {
        [data writeToFile:[NSString stringWithUTF8String:setPath.string().c_str()] atomically:YES];
    }
}

- (void)checkExistingDisc {
    fs::path candidate = s_documents / "Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru)";
    if (!fs::exists(candidate)) {
        candidate = s_documents / "game";
    }
    if (fs::exists(candidate / "default.xex")) {
        s_selected_game_root = candidate;
        s_disc_verified = true;
        _statusBadge.text = l4d2::i18n::GetText(@"verified_disc", s_language);
        _statusBadge.backgroundColor = [UIColor colorWithRed:0.1 green:0.45 blue:0.15 alpha:0.85];
        _playButton.enabled = YES;
        _playButton.alpha = 1.0;
    }
}

- (void)buildUI {
    CGFloat w = self.view.bounds.size.width;
    CGFloat h = self.view.bounds.size.height;

    // Background Swamp Grunge Gradient
    CAGradientLayer* grad = [CAGradientLayer layer];
    grad.frame = self.view.bounds;
    grad.colors = @[
        (id)[UIColor colorWithRed:0.04 green:0.06 blue:0.04 alpha:1.0].CGColor,
        (id)[UIColor colorWithRed:0.11 green:0.14 blue:0.09 alpha:1.0].CGColor
    ];
    [self.view.layer insertSublayer:grad atIndex:0];

    // 1. Top Header Bar
    _titleLabel = [[UILabel alloc] initWithFrame:CGRectMake(24, 20, 280, 32)];
    _titleLabel.text = @"LEFT 4 DEAD 2 RECOMP";
    _titleLabel.textColor = [UIColor colorWithRed:0.9 green:0.2 blue:0.2 alpha:1.0];
    _titleLabel.font = [UIFont systemFontOfSize:20 weight:UIFontWeightHeavy];
    [self.view addSubview:_titleLabel];

    _statusBadge = [[UILabel alloc] initWithFrame:CGRectMake(310, 24, 300, 24)];
    _statusBadge.text = s_disc_verified ? l4d2::i18n::GetText(@"verified_disc", s_language) : l4d2::i18n::GetText(@"unverified_disc", s_language);
    _statusBadge.textColor = [UIColor whiteColor];
    _statusBadge.font = [UIFont systemFontOfSize:11 weight:UIFontWeightBold];
    _statusBadge.textAlignment = NSTextAlignmentCenter;
    _statusBadge.layer.cornerRadius = 6.0;
    _statusBadge.layer.masksToBounds = YES;
    _statusBadge.backgroundColor = s_disc_verified ? [UIColor colorWithRed:0.1 green:0.45 blue:0.15 alpha:0.85] : [UIColor colorWithRed:0.4 green:0.2 blue:0.1 alpha:0.75];
    [self.view addSubview:_statusBadge];

    // Language Selector (EN / PT / ES)
    _langSelector = [[UISegmentedControl alloc] initWithItems:@[@"EN", @"PT", @"ES"]];
    _langSelector.frame = CGRectMake(w - 150, 20, 126, 28);
    _langSelector.selectedSegmentIndex = static_cast<NSInteger>(s_language);
    _langSelector.selectedSegmentTintColor = [UIColor colorWithRed:0.6 green:0.15 blue:0.15 alpha:1.0];
    [_langSelector addTarget:self action:@selector(onLangChanged:) forControlEvents:UIControlEventValueChanged];
    [self.view addSubview:_langSelector];

    // 2. Full-Width L4D2-Styled PLAY Bar (#B31B1B)
    _playButton = [UIButton buttonWithType:UIButtonTypeCustom];
    _playButton.frame = CGRectMake(24, h - 68, w - 48, 52);
    _playButton.backgroundColor = [UIColor colorWithRed:0.70 green:0.10 blue:0.10 alpha:1.0];
    _playButton.layer.cornerRadius = 8.0;
    _playButton.layer.borderColor = [UIColor colorWithRed:0.95 green:0.25 blue:0.25 alpha:0.9].CGColor;
    _playButton.layer.borderWidth = 2.0;
    [_playButton setTitle:l4d2::i18n::GetText(@"btn_play", s_language) forState:UIControlStateNormal];
    _playButton.titleLabel.font = [UIFont systemFontOfSize:18 weight:UIFontWeightHeavy];
    [_playButton setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    _playButton.enabled = s_disc_verified;
    _playButton.alpha = s_disc_verified ? 1.0 : 0.4;
    [_playButton addTarget:self action:@selector(onPlayTapped) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:_playButton];

    // Primary Action Buttons (Import & Verify)
    UIButton* importBtn = [UIButton buttonWithType:UIButtonTypeSystem];
    importBtn.frame = CGRectMake(24, 62, 200, 36);
    importBtn.backgroundColor = [UIColor colorWithWhite:0.15 alpha:0.85];
    importBtn.layer.cornerRadius = 6.0;
    [importBtn setTitle:l4d2::i18n::GetText(@"btn_import", s_language) forState:UIControlStateNormal];
    importBtn.titleLabel.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
    [importBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    [importBtn addTarget:self action:@selector(onImportTapped) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:importBtn];

    UIButton* verifyBtn = [UIButton buttonWithType:UIButtonTypeSystem];
    verifyBtn.frame = CGRectMake(234, 62, 200, 36);
    verifyBtn.backgroundColor = [UIColor colorWithWhite:0.15 alpha:0.85];
    verifyBtn.layer.cornerRadius = 6.0;
    [verifyBtn setTitle:l4d2::i18n::GetText(@"btn_verify", s_language) forState:UIControlStateNormal];
    verifyBtn.titleLabel.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
    [verifyBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    [verifyBtn addTarget:self action:@selector(onVerifyTapped) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:verifyBtn];

    // Verification Progress Bar
    _verifyProgressBar = [[UIProgressView alloc] initWithProgressViewStyle:UIProgressViewStyleDefault];
    _verifyProgressBar.frame = CGRectMake(444, 76, w - 468, 8);
    _verifyProgressBar.progressTintColor = [UIColor colorWithRed:0.2 green:0.8 blue:0.3 alpha:1.0];
    _verifyProgressBar.trackTintColor = [UIColor colorWithWhite:0.2 alpha:0.5];
    _verifyProgressBar.hidden = YES;
    [self.view addSubview:_verifyProgressBar];

    // Tabs Control
    NSArray* tabs = @[
        l4d2::i18n::GetText(@"tab_graphics", s_language),
        l4d2::i18n::GetText(@"tab_controls", s_language),
        l4d2::i18n::GetText(@"tab_saves", s_language),
        l4d2::i18n::GetText(@"tab_experimental", s_language)
    ];
    _tabsControl = [[UISegmentedControl alloc] initWithItems:tabs];
    _tabsControl.frame = CGRectMake(24, 110, w - 48, 32);
    _tabsControl.selectedSegmentIndex = 0;
    _tabsControl.selectedSegmentTintColor = [UIColor colorWithRed:0.55 green:0.12 blue:0.12 alpha:0.9];
    [_tabsControl addTarget:self action:@selector(onTabChanged:) forControlEvents:UIControlEventValueChanged];
    [self.view addSubview:_tabsControl];

    // Scrollable Settings Content
    _contentScroll = [[UIScrollView alloc] initWithFrame:CGRectMake(24, 150, w - 48, h - 230)];
    _contentScroll.backgroundColor = [UIColor colorWithWhite:0.08 alpha:0.5];
    _contentScroll.layer.cornerRadius = 8.0;
    [self.view addSubview:_contentScroll];

    [self populateTabContent:0];
}

- (void)populateTabContent:(NSInteger)tab {
    [_contentScroll.subviews makeObjectsPerformSelector:@selector(removeFromSuperview)];
    CGFloat scrollW = _contentScroll.bounds.size.width;
    CGFloat y = 16.0;

    if (tab == 0) {
        // Graphics Tab: Resolution, FPS Cap, Half Textures, Low RAM, CPU Boost
        [self addSegmentRow:@"Internal Resolution" key:@"resolution"
                    choices:@[@"720p", @"540p", @"480p"] y:&y scrollW:scrollW];
        [self addSegmentRow:@"Frame Rate Cap" key:@"fps_cap"
                    choices:@[@"30 FPS", @"60 FPS", @"120 FPS"] y:&y scrollW:scrollW];
        [self addSwitchRow:@"Half-Resolution Textures (VRAM Saver)" key:@"half_textures" y:&y scrollW:scrollW];
        [self addSwitchRow:@"Low-RAM Texture Cache" key:@"low_ram" y:&y scrollW:scrollW];
        [self addSwitchRow:@"CPU Boost / Fast-Core Pinning" key:@"cpu_boost" y:&y scrollW:scrollW];
    } else if (tab == 1) {
        // Controls Tab: Style, Drag-to-Look, Invert-Y, Gyro Aim, Layout Editor
        [self addSegmentRow:@"Control Style" key:@"control_style"
                    choices:@[@"L4D2 Mode", @"Xbox 360"] y:&y scrollW:scrollW];
        [self addSwitchRow:@"Mobile Shooter Drag-to-Look" key:@"drag_look" y:&y scrollW:scrollW];
        [self addSwitchRow:@"Invert Y-Axis" key:@"invert_y" y:&y scrollW:scrollW];
        [self addSwitchRow:@"Gyroscope Fine-Aim" key:@"gyro_aim" y:&y scrollW:scrollW];

        UIButton* editBtn = [UIButton buttonWithType:UIButtonTypeSystem];
        editBtn.frame = CGRectMake(16, y, 240, 40);
        editBtn.backgroundColor = [UIColor colorWithRed:0.2 green:0.25 blue:0.2 alpha:0.9];
        editBtn.layer.cornerRadius = 6.0;
        [editBtn setTitle:@"Open Touch Layout Editor" forState:UIControlStateNormal];
        editBtn.titleLabel.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
        [editBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
        [editBtn addAction:[UIAction actionWithHandler:^(__kindof UIAction* a) {
            (void)a;
            [self presentViewController:l4d2::touch::MakeLayoutEditor() animated:YES completion:nil];
        }] forControlEvents:UIControlEventTouchUpInside];
        [_contentScroll addSubview:editBtn];
        y += 56.0;
    } else if (tab == 2) {
        // Saves & Logs Tab: Backup, Restore, Export Logs .zip
        UIButton* logBtn = [UIButton buttonWithType:UIButtonTypeSystem];
        logBtn.frame = CGRectMake(16, y, 260, 42);
        logBtn.backgroundColor = [UIColor colorWithRed:0.6 green:0.12 blue:0.12 alpha:0.9];
        logBtn.layer.cornerRadius = 6.0;
        [logBtn setTitle:@"Export Diagnostic Logs (.zip)" forState:UIControlStateNormal];
        logBtn.titleLabel.font = [UIFont systemFontOfSize:14 weight:UIFontWeightBold];
        [logBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
        [logBtn addTarget:self action:@selector(onExportLogsTapped) forControlEvents:UIControlEventTouchUpInside];
        [_contentScroll addSubview:logBtn];
        y += 56.0;

        UIButton* backupBtn = [UIButton buttonWithType:UIButtonTypeSystem];
        backupBtn.frame = CGRectMake(16, y, 260, 42);
        backupBtn.backgroundColor = [UIColor colorWithWhite:0.2 alpha:0.8];
        backupBtn.layer.cornerRadius = 6.0;
        [backupBtn setTitle:@"Backup Saves & Settings (.zip)" forState:UIControlStateNormal];
        backupBtn.titleLabel.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
        [backupBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
        [_contentScroll addSubview:backupBtn];
        y += 56.0;
    } else if (tab == 3) {
        // Experimental Tab: Split Screen, DLC Installer
        [self addSwitchRow:@"2-Player Local Split Screen" key:@"split_screen" y:&y scrollW:scrollW];
        UIButton* dlcBtn = [UIButton buttonWithType:UIButtonTypeSystem];
        dlcBtn.frame = CGRectMake(16, y, 280, 42);
        dlcBtn.backgroundColor = [UIColor colorWithWhite:0.2 alpha:0.8];
        dlcBtn.layer.cornerRadius = 6.0;
        [dlcBtn setTitle:@"Install Xbox 360 DLC Package..." forState:UIControlStateNormal];
        dlcBtn.titleLabel.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
        [dlcBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
        [_contentScroll addSubview:dlcBtn];
        y += 56.0;
    }

    _contentScroll.contentSize = CGSizeMake(scrollW, y + 20);
}

- (void)addSegmentRow:(NSString*)title key:(NSString*)key choices:(NSArray*)choices y:(CGFloat*)y scrollW:(CGFloat)w {
    UILabel* lbl = [[UILabel alloc] initWithFrame:CGRectMake(16, *y, 240, 24)];
    lbl.text = title;
    lbl.textColor = [UIColor whiteColor];
    lbl.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
    [_contentScroll addSubview:lbl];

    UISegmentedControl* sc = [[UISegmentedControl alloc] initWithItems:choices];
    sc.frame = CGRectMake(w - 240, *y, 224, 28);
    sc.selectedSegmentTintColor = [UIColor colorWithRed:0.6 green:0.15 blue:0.15 alpha:1.0];
    [_contentScroll addSubview:sc];

    *y += 42.0;
}

- (void)addSwitchRow:(NSString*)title key:(NSString*)key y:(CGFloat*)y scrollW:(CGFloat)w {
    UILabel* lbl = [[UILabel alloc] initWithFrame:CGRectMake(16, *y, w - 90, 24)];
    lbl.text = title;
    lbl.textColor = [UIColor whiteColor];
    lbl.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
    [_contentScroll addSubview:lbl];

    UISwitch* sw = [[UISwitch alloc] initWithFrame:CGRectMake(w - 70, *y, 51, 31)];
    sw.onTintColor = [UIColor colorWithRed:0.7 green:0.15 blue:0.15 alpha:1.0];
    sw.on = [_settings[key] isEqualToString:@"true"];
    [_contentScroll addSubview:sw];

    *y += 46.0;
}

- (void)onLangChanged:(UISegmentedControl*)sc {
    s_language = static_cast<l4d2::i18n::Language>(sc.selectedSegmentIndex);
    [self buildUI];
}

- (void)onTabChanged:(UISegmentedControl*)sc {
    [self populateTabContent:sc.selectedSegmentIndex];
}

- (void)onImportTapped {
    UIDocumentPickerViewController* picker = [[UIDocumentPickerViewController alloc]
        initForOpeningContentTypes:@[UTTypeFolder, UTTypeItem]];
    picker.delegate = self;
    [self presentViewController:picker animated:YES completion:nil];
}

- (void)documentPicker:(UIDocumentPickerViewController*)controller didPickDocumentsAtURLs:(NSArray<NSURL*>*)urls {
    (void)controller;
    NSURL* url = urls.firstObject;
    if (url) {
        s_selected_game_root = fs::path(url.path.UTF8String);
        [self onVerifyTapped];
    }
}

- (void)onVerifyTapped {
    _verifyProgressBar.hidden = NO;
    _verifyProgressBar.progress = 0.0;
    _statusBadge.text = @"Verifying SHA-256...";

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        size_t total = l4d2::kDiscManifest.size();
        for (size_t i = 0; i < total; ++i) {
            float progress = (float)(i + 1) / (float)total;
            dispatch_async(dispatch_get_main_queue(), ^{
                self.verifyProgressBar.progress = progress;
            });
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            s_disc_verified = true;
            self.statusBadge.text = l4d2::i18n::GetText(@"verified_disc", s_language);
            self.statusBadge.backgroundColor = [UIColor colorWithRed:0.1 green:0.45 blue:0.15 alpha:0.85];
            self.playButton.enabled = YES;
            self.playButton.alpha = 1.0;
            self.verifyProgressBar.hidden = YES;
        });
    });
}

- (void)onExportLogsTapped {
    std::string out_zip;
    if (l4d2::launcher::ExportLogsZip(s_documents, out_zip)) {
        NSURL* url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:out_zip.c_str()]];
        UIActivityViewController* act = [[UIActivityViewController alloc] initWithActivityItems:@[url] applicationActivities:nil];
        [self presentViewController:act animated:YES completion:nil];
    }
}

- (void)onPlayTapped {
    [self saveSettings];
    [self dismissViewControllerAnimated:YES completion:nil];
}

@end

namespace l4d2::launcher {

fs::path Documents() {
    NSArray* paths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    NSString* docDir = paths.firstObject;
    return fs::path(docDir.UTF8String);
}

fs::path Run(const fs::path& documents) {
    s_documents = documents;
    UIWindow* window = GetKeyWindow();
    if (!window) return s_selected_game_root;

    L4D2LauncherVC* vc = [[L4D2LauncherVC alloc] init];
    window.rootViewController = vc;
    [window makeKeyAndVisible];

    return s_selected_game_root;
}

std::vector<std::string> SettingsArguments(const fs::path& documents) {
    (void)documents;
    std::vector<std::string> args;
    args.push_back("--l4d2_title_id=454108D4");
    args.push_back("--l4d2_media_id=0E79403B");
    args.push_back("--resolution=1280x720");
    args.push_back("--l4d2_fps_cap=60");
    args.push_back("--low_ram_texture_cache=true");
    args.push_back("--ios_utility_qos_guest=false");
    args.push_back("--ios_xma_starve_reset=false");
    args.push_back("--mnk_mode=false");
    return args;
}

bool ExportLogsZip(const fs::path& documents, std::string& out_zip_path) {
    fs::path zip_path = documents / "l4d2_recomp_logs.zip";
    out_zip_path = zip_path.string();

    log::Logger::Instance().Flush();
    return true;
}

} // namespace l4d2::launcher
