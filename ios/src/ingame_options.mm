#import "ingame_options.h"
#import "touch_controls.h"
#import "l4d2_strings.h"
#import <UIKit/UIKit.h>

namespace l4d2::options {

static UIView* s_menu_view = nil;
static UILabel* s_perf_label = nil;
static bool s_is_visible = false;

@interface L4D2InGameMenu : UIView
@property (nonatomic, strong) UISlider* sensSlider;
@property (nonatomic, strong) UISegmentedControl* fpsSegment;
@property (nonatomic, strong) UILabel* sensValueLabel;
@end

@implementation L4D2InGameMenu

- (instancetype)initWithFrame:(CGRect)frame {
    if (self = [super initWithFrame:frame]) {
        self.backgroundColor = [UIColor colorWithWhite:0.0 alpha:0.75];
        [self buildUI];
    }
    return self;
}

- (void)buildUI {
    CGFloat panelW = 480.0;
    CGFloat panelH = 340.0;
    CGFloat px = (self.bounds.size.width - panelW) / 2.0;
    CGFloat py = (self.bounds.size.height - panelH) / 2.0;

    UIView* panel = [[UIView alloc] initWithFrame:CGRectMake(px, py, panelW, panelH)];
    panel.backgroundColor = [UIColor colorWithRed:0.09 green:0.12 blue:0.09 alpha:0.95];
    panel.layer.borderColor = [UIColor colorWithRed:0.7 green:0.1 blue:0.1 alpha:0.8].CGColor;
    panel.layer.borderWidth = 2.0;
    panel.layer.cornerRadius = 12.0;
    [self addSubview:panel];

    // Header Title
    UILabel* title = [[UILabel alloc] initWithFrame:CGRectMake(0, 16, panelW, 28)];
    title.text = @"LEFT 4 DEAD 2 - PAUSE";
    title.textColor = [UIColor colorWithRed:0.9 green:0.2 blue:0.2 alpha:1.0];
    title.font = [UIFont systemFontOfSize:18 weight:UIFontWeightHeavy];
    title.textAlignment = NSTextAlignmentCenter;
    [panel addSubview:title];

    // Sensitivity Slider
    UILabel* sensTitle = [[UILabel alloc] initWithFrame:CGRectMake(30, 60, 200, 22)];
    sensTitle.text = @"Look Sensitivity";
    sensTitle.textColor = [UIColor whiteColor];
    sensTitle.font = [UIFont systemFontOfSize:14 weight:UIFontWeightBold];
    [panel addSubview:sensTitle];

    _sensSlider = [[UISlider alloc] initWithFrame:CGRectMake(30, 85, panelW - 130, 30)];
    _sensSlider.minimumValue = 0.2f;
    _sensSlider.maximumValue = 3.0f;
    _sensSlider.value = 1.0f;
    _sensSlider.minimumTrackTintColor = [UIColor colorWithRed:0.7 green:0.15 blue:0.15 alpha:1.0];
    [_sensSlider addTarget:self action:@selector(onSensChanged:) forControlEvents:UIControlEventValueChanged];
    [panel addSubview:_sensSlider];

    _sensValueLabel = [[UILabel alloc] initWithFrame:CGRectMake(panelW - 90, 85, 60, 30)];
    _sensValueLabel.text = @"1.0x";
    _sensValueLabel.textColor = [UIColor whiteColor];
    _sensValueLabel.font = [UIFont monospacedDigitSystemFontOfSize:14 weight:UIFontWeightMedium];
    [panel addSubview:_sensValueLabel];

    // FPS Cap Segment
    UILabel* fpsTitle = [[UILabel alloc] initWithFrame:CGRectMake(30, 125, 200, 22)];
    fpsTitle.text = @"Frame Rate Cap";
    fpsTitle.textColor = [UIColor whiteColor];
    fpsTitle.font = [UIFont systemFontOfSize:14 weight:UIFontWeightBold];
    [panel addSubview:fpsTitle];

    _fpsSegment = [[UISegmentedControl alloc] initWithItems:@[@"30 FPS", @"60 FPS", @"120 FPS"]];
    _fpsSegment.frame = CGRectMake(30, 150, panelW - 60, 32);
    _fpsSegment.selectedSegmentIndex = 1;
    _fpsSegment.selectedSegmentTintColor = [UIColor colorWithRed:0.7 green:0.15 blue:0.15 alpha:1.0];
    [panel addSubview:_fpsSegment];

    // Live Performance Diagnostics Pill
    s_perf_label = [[UILabel alloc] initWithFrame:CGRectMake(30, 195, panelW - 60, 48)];
    s_perf_label.backgroundColor = [UIColor colorWithWhite:0.05 alpha:0.8];
    s_perf_label.layer.cornerRadius = 8.0;
    s_perf_label.layer.masksToBounds = YES;
    s_perf_label.textColor = [UIColor colorWithRed:0.4 green:1.0 blue:0.4 alpha:1.0];
    s_perf_label.font = [UIFont monospacedDigitSystemFontOfSize:12 weight:UIFontWeightRegular];
    s_perf_label.numberOfLines = 2;
    s_perf_label.textAlignment = NSTextAlignmentCenter;
    s_perf_label.text = @"FPS: 60.0 • Frame: 16.6ms (Spikes >20ms: 0)\nRAM: 1420 MB • Thermal: Nominal";
    [panel addSubview:s_perf_label];

    // Buttons
    CGFloat btnW = (panelW - 90) / 2.0;

    UIButton* editHudBtn = [UIButton buttonWithType:UIButtonTypeSystem];
    editHudBtn.frame = CGRectMake(30, 260, btnW, 44);
    editHudBtn.backgroundColor = [UIColor colorWithWhite:0.2 alpha:0.8];
    editHudBtn.layer.cornerRadius = 8.0;
    [editHudBtn setTitle:@"EDIT HUD" forState:UIControlStateNormal];
    editHudBtn.titleLabel.font = [UIFont systemFontOfSize:14 weight:UIFontWeightBold];
    [editHudBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    [editHudBtn addAction:[UIAction actionWithHandler:^(__kindof UIAction* a) {
        UIViewController* topVC = [UIApplication sharedApplication].windows.firstObject.rootViewController;
        if (topVC) {
            [topVC presentViewController:touch::MakeLayoutEditor() animated:YES completion:nil];
        }
    }] forControlEvents:UIControlEventTouchUpInside];
    [panel addSubview:editHudBtn];

    UIButton* resumeBtn = [UIButton buttonWithType:UIButtonTypeSystem];
    resumeBtn.frame = CGRectMake(30 + btnW + 30, 260, btnW, 44);
    resumeBtn.backgroundColor = [UIColor colorWithRed:0.75 green:0.12 blue:0.12 alpha:0.95];
    resumeBtn.layer.cornerRadius = 8.0;
    [resumeBtn setTitle:@"RESUME" forState:UIControlStateNormal];
    resumeBtn.titleLabel.font = [UIFont systemFontOfSize:15 weight:UIFontWeightHeavy];
    [resumeBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    [resumeBtn addAction:[UIAction actionWithHandler:^(__kindof UIAction* a) {
        HideInGameMenu();
    }] forControlEvents:UIControlEventTouchUpInside];
    [panel addSubview:resumeBtn];
}

- (void)onSensChanged:(UISlider*)slider {
    _sensValueLabel.text = [NSString stringWithFormat:@"%.1fx", slider.value];
    touch::TouchConfig cfg;
    cfg.look_sensitivity_x = slider.value;
    cfg.look_sensitivity_y = slider.value;
    touch::UpdateConfig(cfg);
}

@end

void ShowInGameMenu() {
    dispatch_async(dispatch_get_main_queue(), ^{
        UIWindow* window = [UIApplication sharedApplication].windows.firstObject;
        if (!window) return;

        if (!s_menu_view) {
            s_menu_view = [[L4D2InGameMenu alloc] initWithFrame:window.bounds];
        }
        [window addSubview:s_menu_view];
        s_menu_view.alpha = 0.0;
        [UIView animateWithDuration:0.2 animations:^{ s_menu_view.alpha = 1.0; }];
        s_is_visible = true;
    });
}

void HideInGameMenu() {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (s_menu_view) {
            [UIView animateWithDuration:0.2 animations:^{
                s_menu_view.alpha = 0.0;
            } completion:^(BOOL finished) {
                [s_menu_view removeFromSuperview];
                s_is_visible = false;
            }];
        }
    });
}

bool IsMenuVisible() {
    return s_is_visible;
}

void UpdatePerformanceStats(float fps, float frame_time_ms, uint64_t ram_bytes, int thermal_state) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (s_perf_label) {
            const char* thermal_str = "Nominal";
            if (thermal_state == 1) thermal_str = "Fair";
            else if (thermal_state == 2) thermal_str = "Serious";
            else if (thermal_state == 3) thermal_str = "Critical";

            s_perf_label.text = [NSString stringWithFormat:
                @"FPS: %.1f • Frame: %.1fms (Target: 60.0)\nRAM: %llu MB • Thermal: %s",
                fps, frame_time_ms, ram_bytes / (1024 * 1024), thermal_str];
        }
    });
}

} // namespace l4d2::options
