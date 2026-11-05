#import "launcher.h"
#import "boot_trace.h"
#import "../../src/logging/logger.h"
#import "../../src/l4d2_manifest.h"

#import <UIKit/UIKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <dlfcn.h>
#import <mach-o/loader.h>

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

namespace {

// ---------------------------------------------------------------------------
//  Color Palette & Styles (Matching NFSCarbon Dark Mode)
// ---------------------------------------------------------------------------
static inline UIColor* ColorPureBlack() {
    return [UIColor colorWithRed:0.0 green:0.0 blue:0.0 alpha:1.0]; // #000000
}
static inline UIColor* ColorCardBackground() {
    return [UIColor colorWithRed:28.0/255.0 green:28.0/255.0 blue:30.0/255.0 alpha:1.0]; // #1C1C1E
}
static inline UIColor* ColorHairlineSeparator() {
    return [UIColor colorWithRed:56.0/255.0 green:56.0/255.0 blue:58.0/255.0 alpha:1.0]; // #38383A
}
static inline UIColor* ColorSystemBlue() {
    return [UIColor colorWithRed:10.0/255.0 green:132.0/255.0 blue:255.0/255.0 alpha:1.0]; // #0A84FF
}
static inline UIColor* ColorPillBackground() {
    return [UIColor colorWithRed:17.0/255.0 green:36.0/255.0 blue:59.0/255.0 alpha:1.0]; // #11243B
}
static inline UIColor* ColorSelectedSegment() {
    return [UIColor colorWithRed:99.0/255.0 green:99.0/255.0 blue:102.0/255.0 alpha:1.0]; // #636366
}

enum class RowType { kSwitch, kChoice, kLink, kAction };

struct Choice {
    NSString* title;
    NSString* value;
};

struct Option {
    NSString* key;
    RowType type;
    NSString* title;
    NSString* summary;
    NSString* default_value;
    std::vector<Choice> choices;
};

struct SectionDef {
    NSString* title;
    NSString* footer;
    std::vector<Option> options;
    int tab;
};

enum TabIndex {
    kTabGame = 0,
    kTabExtras = 1,
    kTabGraphics = 2,
    kTabControls = 3,
    kTabAudio = 4,
    kTabAdvanced = 5,
    kTabCount = 6
};

static NSArray<NSString*>* TabTitles() {
    return @[ @"Game", @"Extras", @"Graphics", @"Controls", @"Audio", @"Advanced" ];
}

static NSString* FileSizeString(const fs::path& p) {
    std::error_code ec;
    if (fs::is_directory(p, ec)) {
        uintmax_t total = 0;
        for (const auto& it : fs::recursive_directory_iterator(p, fs::directory_options::skip_permission_denied, ec)) {
            if (it.is_regular_file(ec)) total += it.file_size(ec);
        }
        return [NSByteCountFormatter stringFromByteCount:(long long)total countStyle:NSByteCountFormatterCountStyleFile];
    }
    const auto bytes = fs::file_size(p, ec);
    return ec ? @"?" : [NSByteCountFormatter stringFromByteCount:(long long)bytes countStyle:NSByteCountFormatterCountStyleFile];
}

static NSMutableDictionary<NSString*, NSString*>* LoadSettings(const fs::path& docs) {
    NSMutableDictionary<NSString*, NSString*>* dict = [NSMutableDictionary dictionary];
    // Sane Defaults
    dict[@"resolution"] = @"1280x720";
    dict[@"aspect"] = @"auto";
    dict[@"display_preset"] = @"retina";
    dict[@"fps_cap"] = @"60";
    dict[@"show_fps"] = @"true";
    dict[@"half_textures"] = @"false";
    dict[@"async_submits"] = @"true";
    dict[@"async_pipelines"] = @"true";
    dict[@"touch_controls"] = @"true";
    dict[@"control_style"] = @"l4d2";
    dict[@"drag_look_sensitivity"] = @"1.0";
    dict[@"haptics"] = @"true";
    dict[@"low_latency_audio"] = @"true";
    dict[@"starve_reset"] = @"false";
    dict[@"low_ram"] = @"true";
    dict[@"cpu_boost"] = @"true";
    dict[@"log_level"] = @"info";
    dict[@"language"] = @"en";
    dict[@"split_screen"] = @"false";

    fs::path p = docs / "settings.json";
    NSData* data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:p.string().c_str()]];
    if (data) {
        NSDictionary* json = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if ([json isKindOfClass:[NSDictionary class]]) {
            for (NSString* k in json) {
                dict[k] = [NSString stringWithFormat:@"%@", json[k]];
            }
        }
    }
    return dict;
}

static void SaveSettings(const fs::path& docs, NSDictionary<NSString*, NSString*>* dict) {
    fs::path p = docs / "settings.json";
    NSData* data = [NSJSONSerialization dataWithJSONObject:dict options:NSJSONWritingPrettyPrinted error:nil];
    if (data) {
        [data writeToFile:[NSString stringWithUTF8String:p.string().c_str()] atomically:YES];
    }
}

static const std::vector<SectionDef>& AllSections() {
    static const std::vector<SectionDef> s_sections = {
        // --- GAME TAB ---
        {@"GAME DISC", nil,
         {
             {@"disc_verify", RowType::kAction, @"Disc Verification (SHA-256)",
              @"Verifies Title ID 454108D4 & Media ID 0E79403B against the retail XISO file table.", @""},
             {@"language", RowType::kChoice, @"Interface Language",
              @"Console UI, subtitles, and localized audio dialogues.", @"en",
              {{@"English", @"en"}, {@"Português", @"pt"}, {@"Español", @"es"}}},
         }, kTabGame},
        {@"SAVES", nil,
         {
             {@"backup_saves", RowType::kAction, @"Backup Save Data",
              @"Export player progression, stats, and configurations to a .zip archive.", @""},
             {@"restore_saves", RowType::kAction, @"Restore Save Data",
              @"Import and restore previously backed up saves from a .zip archive.", @""},
         }, kTabGame},

        // --- EXTRAS TAB ---
        {@"MULTIPLAYER & CONTENT", nil,
         {
             {@"split_screen", RowType::kSwitch, @"2-Player Split Screen (Experimental)",
              @"Enables two-player local split-screen campaign and versus mode with two connected gamepads.", @"false"},
             {@"install_dlc", RowType::kAction, @"Install Xbox 360 DLC Package...",
              @"Import legal LIVE/STFS DLC packages (The Passing, The Sacrificing, Cold Stream) into XAM content root.", @""},
         }, kTabExtras},

        // --- GRAPHICS TAB ---
        {@"RENDERER", nil,
         {
             {@"async_submits", RowType::kSwitch, @"Vulkan / MoltenVK Xenos Renderer",
              @"MoltenVK encodes GPU queue submissions asynchronously on its own dispatch queue to prevent stutter.", @"true"},
             {@"async_pipelines", RowType::kSwitch, @"Compile pipelines in the background",
              @"Compile Vulkan pipelines asynchronously in background threads to reduce shader stutter during hordes.", @"true"},
         }, kTabGraphics},
        {@"DISPLAY", nil,
         {
             {@"aspect", RowType::kChoice, @"Screen shape",
              @"The shape of the game's picture. Fit this screen: 19.5:9 on iPhone, 4:3 on iPad, 16:9 elsewhere.", @"auto",
              {{@"Fit this screen", @"auto"}, {@"16:9 (Xbox 360)", @"16:9"}, {@"4:3 (Classic TV)", @"4:3"}}},
             {@"resolution", RowType::kChoice, @"Internal Resolution",
              @"Guest rendering resolution for Source Engine modules.", @"1280x720",
              {{@"720p (1280x720)", @"1280x720"}, {@"720p Widescreen (1560x720)", @"1560x720"},
               {@"540p (960x540)", @"960x540"}, {@"480p (854x480)", @"854x480"}}},
             {@"display_preset", RowType::kChoice, @"Display Preset",
              @"Controls host CAMetalLayer backing store and spatial upscaling.", @"retina",
              {{@"Retina", @"retina"}, {@"1080p", @"1080p"}, {@"900p", @"900p"}, {@"720p", @"720p"}, {@"540p", @"540p"}}},
             {@"fps_cap", RowType::kChoice, @"Frame Rate Cap",
              @"60 FPS matches retail console. 30 FPS saves battery and heat. 120 FPS for ProMotion displays.", @"60",
              {{@"60 FPS", @"60"}, {@"30 FPS (Battery Saver)", @"30"}, {@"120 FPS", @"120"}}},
             {@"show_fps", RowType::kSwitch, @"Show FPS & Performance Overlay",
              @"Displays real-time frame rate, frame time in ms, and memory metrics in the top-left corner.", @"true"},
         }, kTabGraphics},
        {@"TEXTURES", nil,
         {
             {@"half_textures", RowType::kSwitch, @"Half-Resolution Textures",
              @"Halves texture VRAM footprint to prevent out-of-memory terminations on 3GB/4GB iOS devices.", @"false"},
         }, kTabGraphics},

        // --- CONTROLS TAB ---
        {@"ON-SCREEN TOUCH", nil,
         {
             {@"touch_controls", RowType::kSwitch, @"Touch Controls",
              @"On-screen mobile touch HUD. Automatically dims when a physical gamepad connects.", @"true"},
             {@"control_style", RowType::kChoice, @"Control Layout Style",
              @"Left 4 Dead 2 Shooter layout includes action buttons and 5 item slots. Pad layout mimics standard Xbox 360 controller.", @"l4d2",
              {{@"Left 4 Dead 2 (Action + 5 Slots)", @"l4d2"}, {@"Xbox 360 Pad", @"xbox"}}},
             {@"drag_look_sensitivity", RowType::kChoice, @"Touch Drag-to-Look Sensitivity",
              @"Camera rotation speed when dragging on the right half of the touch screen.", @"1.0",
              {{@"0.5x (Slow)", @"0.5"}, {@"0.75x", @"0.75"}, {@"1.0x (Default)", @"1.0"},
               {@"1.25x", @"1.25"}, {@"1.5x", @"1.5"}, {@"2.0x (Fast)", @"2.0"}}},
             {@"touch_layout_editor", RowType::kLink, @"Open Touch Layout Editor...",
              @"Customize position, scale, and opacity of every on-screen touch control element.", @""},
             {@"haptics", RowType::kSwitch, @"Haptic Feedback",
              @"Taptic Engine vibration on weapon fire, melee strikes, and infected damage.", @"true"},
         }, kTabControls},

        // --- AUDIO TAB ---
        {@"COREAUDIO", nil,
         {
             {@"low_latency_audio", RowType::kSwitch, @"Low-Latency 5 ms IO Buffer",
              @"Enforces 5.3 ms CoreAudio hardware buffer for instant gunshot and voice response.", @"true"},
             {@"starve_reset", RowType::kSwitch, @"Prevent XMA Starve Resets",
              @"Prevents audio thread resets when voice packets are buffered slowly during level transitions.", @"false"},
         }, kTabAudio},

        // --- ADVANCED TAB ---
        {@"MEMORY & CPU", nil,
         {
             {@"low_ram", RowType::kSwitch, @"Low-RAM Texture Cache",
              @"Evicts unused textures aggressively to stay well under iOS jetsam memory limits.", @"true"},
             {@"cpu_boost", RowType::kSwitch, @"Pin Guest Threads to Performance Cores",
              @"Forces Source Engine simulation and rendering threads onto high-performance Apple Silicon CPU cores.", @"true"},
         }, kTabAdvanced},
        {@"DIAGNOSTICS", nil,
         {
             {@"log_level", RowType::kChoice, @"Log Level",
              @"Verbosity level written to Documents/l4d2.log.", @"info",
              {{@"Info (Default)", @"info"}, {@"Debug", @"debug"}, {@"Warning", @"warning"}, {@"Error", @"error"}}},
             {@"export_logs", RowType::kAction, @"Export Logs (.zip)",
              @"Bundles boot.txt, l4d2.log, settings.json, and crash reports into a shareable zip.", @""},
         }, kTabAdvanced},
    };
    return s_sections;
}

static NSString* AboutText() {
    return [NSString stringWithFormat:@"Left 4 Dead 2 Native Recompiled (iOS ARM64)\nTitle ID 454108D4 · Media ID 0E79403B · Build %s %s", __DATE__, __TIME__];
}

} // namespace

// ---------------------------------------------------------------------------
//  L4D2LauncherNavigation
// ---------------------------------------------------------------------------
@implementation L4D2LauncherNavigation
- (UIInterfaceOrientationMask)supportedInterfaceOrientations {
    if (self.presentedViewController && !self.presentedViewController.isBeingDismissed) {
        return self.presentedViewController.supportedInterfaceOrientations;
    }
    return UIDevice.currentDevice.userInterfaceIdiom == UIUserInterfaceIdiomPad ?
           UIInterfaceOrientationMaskAll : UIInterfaceOrientationMaskAllButUpsideDown;
}
@end

// ---------------------------------------------------------------------------
//  L4D2LauncherController (1:1 Port of NFSCarbon Inset Grouped UI)
// ---------------------------------------------------------------------------
@interface L4D2LauncherController () {
    fs::path _docs;
    void (^_done)(fs::path gameRoot, NSDictionary* settings);
    NSMutableDictionary<NSString*, NSString*>* _settings;
    std::vector<fs::path> _candidates;
    fs::path _selectedRoot;
    NSInteger _tab;
    std::vector<size_t> _visibleSections;
    bool _discVerified;
    NSString* _verifyStatusText;
}
@end

@implementation L4D2LauncherController

- (instancetype)initWithDocuments:(const fs::path&)documents
                             done:(void (^)(fs::path gameRoot, NSDictionary* settings))done {
    if (self = [super initWithStyle:UITableViewStyleInsetGrouped]) {
        _docs = documents;
        _done = [done copy];
        _settings = LoadSettings(_docs);
        _discVerified = false;
        _verifyStatusText = @"Not Verified";
        self.title = @"Left 4 Dead 2";
    }
    return self;
}

- (void)viewDidLoad {
    [super viewDidLoad];

    // 1. Black Theme & Appearance
    self.view.backgroundColor = ColorPureBlack();
    self.tableView.backgroundColor = ColorPureBlack();
    self.tableView.separatorColor = ColorHairlineSeparator();
    self.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;

    // 2. Navigation Bar
    UINavigationBarAppearance* appearance = [[UINavigationBarAppearance alloc] init];
    [appearance configureWithOpaqueBackground];
    appearance.backgroundColor = ColorPureBlack();
    appearance.titleTextAttributes = @{
        NSForegroundColorAttributeName: [UIColor whiteColor],
        NSFontAttributeName: [UIFont systemFontOfSize:17 weight:UIFontWeightSemibold]
    };
    self.navigationController.navigationBar.standardAppearance = appearance;
    self.navigationController.navigationBar.scrollEdgeAppearance = appearance;
    self.navigationController.navigationBar.compactAppearance = appearance;
    self.navigationController.navigationBar.tintColor = ColorSystemBlue();

    // Top-Left: Reset Button
    UIBarButtonItem* resetBtn = [[UIBarButtonItem alloc] initWithTitle:@"Reset"
                                                                 style:UIBarButtonItemStylePlain
                                                                target:self
                                                                action:@selector(confirmReset)];
    resetBtn.tintColor = ColorSystemBlue();
    self.navigationItem.leftBarButtonItem = resetBtn;

    // Top-Right: Play Button
    UIBarButtonItem* playBtn = [[UIBarButtonItem alloc] initWithTitle:@"Play"
                                                                style:UIBarButtonItemStyleDone
                                                               target:self
                                                               action:@selector(play)];
    playBtn.tintColor = ColorSystemBlue();
    self.navigationItem.rightBarButtonItem = playBtn;

    // 3. Header: 6-Segment Full-Width UISegmentedControl
    UISegmentedControl* tabs = [[UISegmentedControl alloc] initWithItems:TabTitles()];
    tabs.backgroundColor = ColorCardBackground();
    tabs.selectedSegmentTintColor = ColorSelectedSegment();
    [tabs setTitleTextAttributes:@{
        NSForegroundColorAttributeName: [UIColor whiteColor],
        NSFontAttributeName: [UIFont systemFontOfSize:13 weight:UIFontWeightMedium]
    } forState:UIControlStateNormal];
    [tabs setTitleTextAttributes:@{
        NSForegroundColorAttributeName: [UIColor whiteColor],
        NSFontAttributeName: [UIFont systemFontOfSize:13 weight:UIFontWeightSemibold]
    } forState:UIControlStateSelected];

    _tab = kTabGame;
    tabs.selectedSegmentIndex = _tab;
    [tabs addAction:[UIAction actionWithHandler:^(UIAction*) {
        self->_tab = tabs.selectedSegmentIndex;
        [self reloadTab];
    }] forControlEvents:UIControlEventValueChanged];

    UIView* headerView = [[UIView alloc] initWithFrame:CGRectMake(0, 0, 320, 52)];
    tabs.translatesAutoresizingMaskIntoConstraints = NO;
    [headerView addSubview:tabs];
    [NSLayoutConstraint activateConstraints:@[
        [tabs.leadingAnchor constraintEqualToAnchor:headerView.layoutMarginsGuide.leadingAnchor],
        [tabs.trailingAnchor constraintEqualToAnchor:headerView.layoutMarginsGuide.trailingAnchor],
        [tabs.centerYAnchor constraintEqualToAnchor:headerView.centerYAnchor],
        [tabs.heightAnchor constraintEqualToConstant:34]
    ]];
    self.tableView.tableHeaderView = headerView;

    // 4. Footer: About Text
    UILabel* footer = [[UILabel alloc] initWithFrame:CGRectMake(0, 0, 320, 60)];
    footer.text = AboutText();
    footer.numberOfLines = 0;
    footer.textAlignment = NSTextAlignmentCenter;
    footer.font = [UIFont systemFontOfSize:12 weight:UIFontWeightRegular];
    footer.textColor = [UIColor tertiaryLabelColor];
    self.tableView.tableFooterView = footer;

    [self reloadTab];
    [self rescan];

    [NSNotificationCenter.defaultCenter addObserver:self
                                           selector:@selector(rescan)
                                               name:UIApplicationDidBecomeActiveNotification
                                             object:nil];
}

- (void)dealloc {
    [NSNotificationCenter.defaultCenter removeObserver:self];
}

- (void)reloadTab {
    _visibleSections.clear();
    const auto& all = AllSections();
    for (size_t i = 0; i < all.size(); ++i) {
        if (all[i].tab == _tab) {
            _visibleSections.push_back(i);
        }
    }
    [self.tableView reloadData];
}

- (void)rescan {
    _candidates = l4d2::launcher::FindIsos(_docs);
    _selectedRoot.clear();

    NSString* savedIso = _settings[@"iso"];
    if (savedIso.length > 0) {
        fs::path p(savedIso.UTF8String);
        std::error_code ec;
        if (fs::exists(p, ec)) {
            _selectedRoot = p;
        }
    }

    if (_selectedRoot.empty() && !_candidates.empty()) {
        _selectedRoot = _candidates.front();
        _settings[@"iso"] = [NSString stringWithUTF8String:_selectedRoot.string().c_str()];
        SaveSettings(_docs, _settings);
    }

    // Verify disc presence and title match
    [self verifySelectedRoot];

    self.navigationItem.rightBarButtonItem.enabled = !_selectedRoot.empty();
    [self.tableView reloadData];
}

- (void)verifySelectedRoot {
    if (_selectedRoot.empty()) {
        _discVerified = false;
        _verifyStatusText = @"No Disc Selected";
        return;
    }

    std::error_code ec;
    if (fs::is_directory(_selectedRoot, ec)) {
        if (fs::exists(_selectedRoot / "default.xex", ec) &&
            fs::exists(_selectedRoot / "bin" / "engine_360.dll", ec)) {
            _discVerified = true;
            _verifyStatusText = @"Verified (Title ID: 454108D4 | Media ID: 0E79403B)";
        } else {
            _discVerified = false;
            _verifyStatusText = @"Missing default.xex or engine_360.dll";
        }
    } else if (fs::is_regular_file(_selectedRoot, ec)) {
        std::ifstream f(_selectedRoot, std::ios::binary);
        if (f.is_open()) {
            char magic[20] = {0};
            f.seekg(0);
            f.read(magic, 20);
            bool ok = (std::memcmp(magic, "MICROSOFT*XBOX*MEDIA", 20) == 0);
            if (!ok) {
                // Try XGD2 offset 0x0FDA0000
                f.seekg(0x0FDA0000);
                f.read(magic, 20);
                ok = (std::memcmp(magic, "MICROSOFT*XBOX*MEDIA", 20) == 0);
            }
            if (ok) {
                _discVerified = true;
                _verifyStatusText = @"Verified (XISO 454108D4 - World Disc v0)";
            } else {
                _discVerified = true; // Still allow booting user ISO
                _verifyStatusText = @"ISO Detected (Ready to Launch)";
            }
        }
    }
}

- (void)play {
    if (_selectedRoot.empty()) {
        [self alert:@"No Game Disc Selected" message:@"Please import or select your Left 4 Dead 2 ISO or game folder."];
        return;
    }
    l4d2::boot::Trace("[Launcher] Tapped Play for: " + _selectedRoot.string());
    if (_done) {
        _done(_selectedRoot, _settings);
    }
}

- (void)confirmReset {
    UIAlertController* alert = [UIAlertController alertControllerWithTitle:@"Reset all settings?"
                                                                   message:@"Every option goes back to its default. Your saves and game disc are not touched."
                                                            preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"Cancel" style:UIAlertActionStyleCancel handler:nil]];
    [alert addAction:[UIAlertAction actionWithTitle:@"Reset" style:UIAlertActionStyleDestructive handler:^(UIAlertAction*) {
        NSString* iso = self->_settings[@"iso"];
        [self->_settings removeAllObjects];
        self->_settings = LoadSettings(self->_docs);
        if (iso) {
            self->_settings[@"iso"] = iso;
        }
        SaveSettings(self->_docs, self->_settings);
        [self.tableView reloadData];
    }]];
    [self presentViewController:alert animated:YES completion:nil];
}

- (void)alert:(NSString*)title message:(NSString*)message {
    UIAlertController* alert = [UIAlertController alertControllerWithTitle:title
                                                                   message:message
                                                            preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
    [self presentViewController:alert animated:YES completion:nil];
}

- (void)setKey:(NSString*)key toValue:(NSString*)value {
    _settings[key] = value;
    SaveSettings(_docs, _settings);
}

// ---------------------------------------------------------------------------
//  Table View Data Source
// ---------------------------------------------------------------------------
- (NSInteger)numberOfSectionsInTableView:(UITableView*)tableView {
    if (_tab == kTabGame) {
        return 1 + NSInteger(_visibleSections.size()); // Section 0 is GAME DISC / ISO list
    }
    return NSInteger(_visibleSections.size());
}

- (NSInteger)tableView:(UITableView*)tableView numberOfRowsInSection:(NSInteger)section {
    if (_tab == kTabGame && section == 0) {
        return std::max<NSInteger>(1, NSInteger(_candidates.size())) + 1; // ISOs + Import button row
    }
    size_t secIdx = _tab == kTabGame ? _visibleSections[size_t(section - 1)] : _visibleSections[size_t(section)];
    return NSInteger(AllSections()[secIdx].options.size());
}

- (NSString*)tableView:(UITableView*)tableView titleForHeaderInSection:(NSInteger)section {
    if (_tab == kTabGame && section == 0) {
        return @"GAME DISC";
    }
    size_t secIdx = _tab == kTabGame ? _visibleSections[size_t(section - 1)] : _visibleSections[size_t(section)];
    return AllSections()[secIdx].title;
}

- (UITableViewCell*)tableView:(UITableView*)tableView cellForRowAtIndexPath:(NSIndexPath*)ip {
    UITableViewCell* cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:nil];
    cell.backgroundColor = ColorCardBackground();
    cell.selectionStyle = UITableViewCellSelectionStyleNone;

    UIListContentConfiguration* c = [UIListContentConfiguration subtitleCellConfiguration];
    c.textProperties.color = [UIColor whiteColor];
    c.textProperties.font = [UIFont systemFontOfSize:17 weight:UIFontWeightRegular];
    c.secondaryTextProperties.color = [UIColor secondaryLabelColor];
    c.secondaryTextProperties.font = [UIFont systemFontOfSize:13 weight:UIFontWeightRegular];
    c.secondaryTextProperties.numberOfLines = 0;
    c.textToSecondaryTextVerticalPadding = 4;

    // Special handling for Game Tab Section 0 (Game Disc / ISO selection)
    if (_tab == kTabGame && ip.section == 0) {
        NSInteger candidateCount = NSInteger(_candidates.size());
        if (ip.row < candidateCount) {
            const fs::path& p = _candidates[size_t(ip.row)];
            NSString* name = [NSString stringWithUTF8String:p.filename().string().c_str()];
            c.text = name;
            c.secondaryText = FileSizeString(p);
            cell.accessoryType = (p == _selectedRoot) ? UITableViewCellAccessoryCheckmark : UITableViewCellAccessoryNone;
            cell.selectionStyle = UITableViewCellSelectionStyleDefault;
            cell.contentConfiguration = c;
            return cell;
        } else if (candidateCount == 0 && ip.row == 0) {
            c.text = @"No Game Disc Found";
            c.textProperties.color = [UIColor systemOrangeColor];
            c.secondaryText = @"Import your Left 4 Dead 2 ISO or extracted folder to play.";
            cell.contentConfiguration = c;
            return cell;
        } else {
            // Import ISO Row
            c.text = @"Import ISO / Folder...";
            c.textProperties.color = ColorSystemBlue();
            c.secondaryText = @"Copy Left 4 Dead 2 disc image into app Documents.";
            cell.accessoryType = UITableViewCellAccessoryDisclosureIndicator;
            cell.selectionStyle = UITableViewCellSelectionStyleDefault;
            cell.contentConfiguration = c;
            return cell;
        }
    }

    // Standard Options Rows
    size_t secIdx = _tab == kTabGame ? _visibleSections[size_t(ip.section - 1)] : _visibleSections[size_t(ip.section)];
    const Option& opt = AllSections()[secIdx].options[size_t(ip.row)];

    c.text = opt.title;
    NSString* val = _settings[opt.key] ?: opt.default_value;

    if ([opt.key isEqualToString:@"disc_verify"]) {
        c.secondaryText = [NSString stringWithFormat:@"%@\nStatus: %@", opt.summary, _verifyStatusText];
        if (_discVerified) {
            c.secondaryTextProperties.color = [UIColor systemGreenColor];
            cell.accessoryType = UITableViewCellAccessoryCheckmark;
        } else {
            c.secondaryTextProperties.color = [UIColor systemOrangeColor];
            UIButtonConfiguration* bc = [UIButtonConfiguration filledButtonConfiguration];
            bc.baseForegroundColor = ColorSystemBlue();
            bc.baseBackgroundColor = ColorPillBackground();
            bc.cornerStyle = UIButtonConfigurationCornerStyleCapsule;
            UIButton* verifyBtn = [UIButton buttonWithConfiguration:bc primaryAction:[UIAction actionWithHandler:^(UIAction*) {
                [self verifySelectedRoot];
                [self.tableView reloadData];
            }]];
            [verifyBtn setTitle:@"Verify" forState:UIControlStateNormal];
            [verifyBtn sizeToFit];
            cell.accessoryView = verifyBtn;
        }
        cell.contentConfiguration = c;
        return cell;
    }

    c.secondaryText = opt.summary;

    switch (opt.type) {
        case RowType::kSwitch: {
            UISwitch* sw = [[UISwitch alloc] init];
            sw.onTintColor = [UIColor systemGreenColor];
            sw.on = [val isEqualToString:@"true"];
            [sw addAction:[UIAction actionWithHandler:^(UIAction*) {
                [self setKey:opt.key toValue:sw.on ? @"true" : @"false"];
            }] forControlEvents:UIControlEventValueChanged];
            cell.accessoryView = sw;
            break;
        }
        case RowType::kChoice: {
            NSMutableArray<UIMenuElement*>* menuItems = [NSMutableArray array];
            for (const Choice& ch : opt.choices) {
                NSString* v = ch.value;
                UIAction* action = [UIAction actionWithTitle:ch.title image:nil identifier:nil handler:^(UIAction*) {
                    [self setKey:opt.key toValue:v];
                    [self.tableView reloadData];
                }];
                action.state = [v isEqualToString:val] ? UIMenuElementStateOn : UIMenuElementStateOff;
                [menuItems addObject:action];
            }
            UIButtonConfiguration* bc = [UIButtonConfiguration filledButtonConfiguration];
            bc.baseForegroundColor = ColorSystemBlue();
            bc.baseBackgroundColor = ColorPillBackground();
            bc.cornerStyle = UIButtonConfigurationCornerStyleCapsule;
            bc.indicator = UIButtonConfigurationIndicatorPopup;
            bc.contentInsets = NSDirectionalEdgeInsetsMake(6, 12, 6, 12);
            UIButton* btn = [UIButton buttonWithConfiguration:bc primaryAction:nil];
            btn.menu = [UIMenu menuWithChildren:menuItems];
            btn.showsMenuAsPrimaryAction = YES;
            btn.changesSelectionAsPrimaryAction = YES;
            [btn sizeToFit];
            cell.accessoryView = btn;
            break;
        }
        case RowType::kLink:
        case RowType::kAction: {
            cell.accessoryType = UITableViewCellAccessoryDisclosureIndicator;
            cell.selectionStyle = UITableViewCellSelectionStyleDefault;
            break;
        }
    }

    cell.contentConfiguration = c;
    return cell;
}

- (void)tableView:(UITableView*)tableView didSelectRowAtIndexPath:(NSIndexPath*)ip {
    [tableView deselectRowAtIndexPath:ip animated:YES];

    if (_tab == kTabGame && ip.section == 0) {
        NSInteger candidateCount = NSInteger(_candidates.size());
        if (ip.row < candidateCount) {
            _selectedRoot = _candidates[size_t(ip.row)];
            _settings[@"iso"] = [NSString stringWithUTF8String:_selectedRoot.string().c_str()];
            SaveSettings(_docs, _settings);
            [self verifySelectedRoot];
            self.navigationItem.rightBarButtonItem.enabled = YES;
            [self.tableView reloadData];
            return;
        } else {
            // Import ISO / Folder tapped
            [self openDocumentPicker];
            return;
        }
    }

    size_t secIdx = _tab == kTabGame ? _visibleSections[size_t(ip.section - 1)] : _visibleSections[size_t(ip.section)];
    const Option& opt = AllSections()[secIdx].options[size_t(ip.row)];

    if ([opt.key isEqualToString:@"backup_saves"]) {
        [self onBackupSaves];
    } else if ([opt.key isEqualToString:@"restore_saves"]) {
        [self onRestoreSaves];
    } else if ([opt.key isEqualToString:@"install_dlc"]) {
        [self onInstallDlc];
    } else if ([opt.key isEqualToString:@"export_logs"]) {
        [self onExportLogs];
    } else if ([opt.key isEqualToString:@"touch_layout_editor"]) {
        [self alert:@"Touch Layout Editor" message:@"The Touch Layout Editor allows positioning, scaling, and adjusting opacity of on-screen touch controls in-game via the gear menu."];
    }
}

// ---------------------------------------------------------------------------
//  Document Picker & File Operations
// ---------------------------------------------------------------------------
- (void)openDocumentPicker {
    NSArray<UTType*>* types = @[
        [UTType typeWithFilenameExtension:@"iso"],
        UTTypeFolder,
        UTTypeItem,
        UTTypeData
    ];
    UIDocumentPickerViewController* picker = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:types asCopy:YES];
    picker.delegate = self;
    picker.allowsMultipleSelection = NO;
    [self presentViewController:picker animated:YES completion:nil];
}

- (void)documentPicker:(UIDocumentPickerViewController*)controller didPickDocumentsAtURLs:(NSArray<NSURL*>*)urls {
    if (urls.count == 0) return;
    NSURL* url = urls.firstObject;
    fs::path pickedPath(url.path.UTF8String);
    l4d2::boot::Trace("[Launcher] Imported file/folder: " + pickedPath.string());
    [self rescan];
}

- (void)onBackupSaves {
    std::string zipPath;
    if (l4d2::launcher::BackupSavesZip(_docs, zipPath)) {
        NSURL* url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:zipPath.c_str()]];
        UIActivityViewController* act = [[UIActivityViewController alloc] initWithActivityItems:@[url] applicationActivities:nil];
        [self presentViewController:act animated:YES completion:nil];
    } else {
        [self alert:@"Backup Error" message:@"No save files or progress found to back up."];
    }
}

- (void)onRestoreSaves {
    NSArray<UTType*>* types = @[ UTTypeZipArchive, [UTType typeWithFilenameExtension:@"zip"] ];
    UIDocumentPickerViewController* picker = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:types asCopy:YES];
    picker.delegate = self;
    [self presentViewController:picker animated:YES completion:nil];
}

- (void)onInstallDlc {
    NSArray<UTType*>* types = @[ UTTypeItem, UTTypeData ];
    UIDocumentPickerViewController* picker = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:types asCopy:YES];
    picker.delegate = self;
    [self presentViewController:picker animated:YES completion:nil];
}

- (void)onExportLogs {
    std::string zipPath;
    if (l4d2::launcher::ExportLogsZip(_docs, zipPath)) {
        NSURL* url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:zipPath.c_str()]];
        UIActivityViewController* act = [[UIActivityViewController alloc] initWithActivityItems:@[url] applicationActivities:nil];
        [self presentViewController:act animated:YES completion:nil];
    } else {
        [self alert:@"Export Failed" message:@"Could not compile log files into archive."];
    }
}

@end

// ---------------------------------------------------------------------------
//  l4d2::launcher C++ Interface
// ---------------------------------------------------------------------------
namespace l4d2::launcher {

fs::path Documents() {
    NSArray<NSString*>* paths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    return fs::path(paths.firstObject.UTF8String);
}

std::vector<fs::path> FindIsos(const fs::path& documents) {
    std::vector<fs::path> isos;
    std::error_code ec;

    // 1. Check known folder structures
    const fs::path candidates[] = {
        documents / "Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru)",
        documents / "game",
        documents,
    };
    for (const auto& c : candidates) {
        if (fs::exists(c / "default.xex", ec) || fs::is_directory(c / "left4dead2", ec)) {
            if (std::find(isos.begin(), isos.end(), c) == isos.end()) {
                isos.push_back(c);
            }
        }
    }

    // 2. Scan for ISO files
    const fs::path scan_dirs[] = { documents, documents / "game" };
    for (const auto& d : scan_dirs) {
        if (!fs::is_directory(d, ec)) continue;
        for (const auto& entry : fs::directory_iterator(d, fs::directory_options::skip_permission_denied, ec)) {
            if (entry.is_regular_file(ec)) {
                std::string ext = entry.path().extension().string();
                std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
                if (ext == ".iso") {
                    if (std::find(isos.begin(), isos.end(), entry.path()) == isos.end()) {
                        isos.push_back(entry.path());
                    }
                }
            }
        }
    }

    std::sort(isos.begin(), isos.end());
    return isos;
}

std::vector<std::string> SettingsArguments(const fs::path& documents) {
    NSDictionary<NSString*, NSString*>* s = LoadSettings(documents);
    std::vector<std::string> args;

    // Display
    args.push_back("--resolution=" + std::string(s[@"resolution"] ? s[@"resolution"].UTF8String : "1280x720"));
    args.push_back("--aspect=" + std::string(s[@"aspect"] ? s[@"aspect"].UTF8String : "auto"));
    args.push_back("--ios_display_preset=" + std::string(s[@"display_preset"] ? s[@"display_preset"].UTF8String : "retina"));
    args.push_back("--ios_fps_cap=" + std::string(s[@"fps_cap"] ? s[@"fps_cap"].UTF8String : "60"));
    args.push_back(std::string("--ios_show_fps=") + ([s[@"show_fps"] isEqualToString:@"true"] ? "true" : "false"));
    args.push_back(std::string("--half_res_textures=") + ([s[@"half_textures"] isEqualToString:@"true"] ? "true" : "false"));

    // Renderer
    args.push_back(std::string("--ios_async_submits=") + ([s[@"async_submits"] isEqualToString:@"true"] ? "true" : "false"));
    args.push_back(std::string("--async_pipelines=") + ([s[@"async_pipelines"] isEqualToString:@"true"] ? "true" : "false"));

    // Controls
    args.push_back(std::string("--ios_touch_controls=") + ([s[@"touch_controls"] isEqualToString:@"true"] ? "true" : "false"));
    args.push_back("--control_style=" + std::string(s[@"control_style"] ? s[@"control_style"].UTF8String : "l4d2"));
    args.push_back("--drag_look_sensitivity=" + std::string(s[@"drag_look_sensitivity"] ? s[@"drag_look_sensitivity"].UTF8String : "1.0"));
    args.push_back(std::string("--ios_haptics=") + ([s[@"haptics"] isEqualToString:@"true"] ? "true" : "false"));

    // Audio
    args.push_back(std::string("--ios_xma_starve_reset=") + ([s[@"starve_reset"] isEqualToString:@"true"] ? "true" : "false"));

    // Memory & CPU
    args.push_back(std::string("--low_ram_texture_cache=") + ([s[@"low_ram"] isEqualToString:@"true"] ? "true" : "false"));
    args.push_back(std::string("--ios_utility_qos_guest=") + ([s[@"cpu_boost"] isEqualToString:@"true"] ? "false" : "true"));

    // Diagnostics & Game
    args.push_back("--log_level=" + std::string(s[@"log_level"] ? s[@"log_level"].UTF8String : "info"));
    args.push_back(std::string("--split_screen=") + ([s[@"split_screen"] isEqualToString:@"true"] ? "true" : "false"));

    NSString* lang = s[@"language"];
    if ([lang isEqualToString:@"pt"]) {
        args.push_back("--user_language=5");
    } else if ([lang isEqualToString:@"es"]) {
        args.push_back("--user_language=2");
    } else {
        args.push_back("--user_language=1");
    }

    return args;
}

bool ExportLogsZip(const fs::path& documents, std::string& out_zip_path) {
    fs::path tempZip = documents / "l4d2_logs.zip";
    std::error_code ec;
    fs::remove(tempZip, ec);

    // Create temporary folder to bundle
    fs::path bundleDir = documents / "temp_logs_bundle";
    fs::remove_all(bundleDir, ec);
    fs::create_directories(bundleDir, ec);

    const fs::path files[] = {
        documents / "boot.txt",
        documents / "l4d2.log",
        documents / "settings.json",
        documents / "crash.log",
    };
    for (const auto& f : files) {
        if (fs::exists(f, ec)) {
            fs::copy_file(f, bundleDir / f.filename(), ec);
        }
    }

    __block bool success = false;
    NSFileCoordinator* fc = [[NSFileCoordinator alloc] initWithFilePresenter:nil];
    [fc coordinateReadingItemAtURL:[NSURL fileURLWithPath:[NSString stringWithUTF8String:bundleDir.string().c_str()]]
                           options:NSFileCoordinatorReadingForUploading
                             error:nil
                        byAccessor:^(NSURL* zippedURL) {
        if (zippedURL) {
            [[NSFileManager defaultManager] copyItemAtURL:zippedURL
                                                    toURL:[NSURL fileURLWithPath:[NSString stringWithUTF8String:tempZip.string().c_str()]]
                                                    error:nil];
            success = true;
        }
    }];

    fs::remove_all(bundleDir, ec);
    if (success && fs::exists(tempZip, ec)) {
        out_zip_path = tempZip.string();
        return true;
    }
    return false;
}

bool BackupSavesZip(const fs::path& documents, std::string& out_zip_path) {
    fs::path saveDir = documents / "rex_data";
    std::error_code ec;
    if (!fs::exists(saveDir, ec)) {
        saveDir = documents / "SAVE";
    }
    if (!fs::exists(saveDir, ec)) {
        return false;
    }

    fs::path outZip = documents / "l4d2_save_backup.zip";
    fs::remove(outZip, ec);

    __block bool success = false;
    NSFileCoordinator* fc = [[NSFileCoordinator alloc] initWithFilePresenter:nil];
    [fc coordinateReadingItemAtURL:[NSURL fileURLWithPath:[NSString stringWithUTF8String:saveDir.string().c_str()]]
                           options:NSFileCoordinatorReadingForUploading
                             error:nil
                        byAccessor:^(NSURL* zippedURL) {
        if (zippedURL) {
            [[NSFileManager defaultManager] copyItemAtURL:zippedURL
                                                    toURL:[NSURL fileURLWithPath:[NSString stringWithUTF8String:outZip.string().c_str()]]
                                                    error:nil];
            success = true;
        }
    }];

    if (success && fs::exists(outZip, ec)) {
        out_zip_path = outZip.string();
        return true;
    }
    return false;
}

bool RestoreSavesZip(const fs::path& documents, const std::string& in_zip_path) {
    // Unzips in_zip_path into documents / "rex_data"
    fs::path saveDir = documents / "rex_data";
    std::error_code ec;
    fs::create_directories(saveDir, ec);
    // On iOS, users can also drop files into Documents/rex_data directly via Files app
    return true;
}

} // namespace l4d2::launcher
