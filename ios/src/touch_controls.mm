#import "touch_controls.h"
#import "l4d2_strings.h"
#import <UIKit/UIKit.h>
#import <GameController/GameController.h>
#import "boot_trace.h"

#include <algorithm>
#include <cmath>
#if L4D2_TOUCH_SDL
#include <SDL3/SDL.h>

static SDL_Joystick* s_pad = nullptr;

static void StartTouchPad() {
    if (s_pad) return;
    SDL_VirtualJoystickDesc desc;
    SDL_INIT_INTERFACE(&desc);
    desc.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    desc.name = "L4D2 Touch Controller";
    desc.naxes = SDL_GAMEPAD_AXIS_COUNT;
    desc.nbuttons = SDL_GAMEPAD_BUTTON_DPAD_RIGHT + 1;
    desc.axis_mask = (1u << desc.naxes) - 1;
    desc.button_mask = (1u << desc.nbuttons) - 1;
    const auto id = SDL_AttachVirtualJoystick(&desc);
    if (id) s_pad = SDL_OpenJoystick(id);
    if (!s_pad) {
        l4d2::boot::Trace(std::string("touch: virtual gamepad failed: ") + SDL_GetError());
        if (id) SDL_DetachVirtualJoystick(id);
        return;
    }
    SDL_SetJoystickVirtualAxis(s_pad, SDL_GAMEPAD_AXIS_LEFT_TRIGGER, SDL_JOYSTICK_AXIS_MIN);
    SDL_SetJoystickVirtualAxis(s_pad, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, SDL_JOYSTICK_AXIS_MIN);
    l4d2::boot::Trace("touch: virtual gamepad attached");
}

static void SetStick(int axis, CGFloat x, CGFloat y) {
    if (!s_pad) return;
    SDL_SetJoystickVirtualAxis(s_pad, axis, std::clamp(x, CGFloat(-1), CGFloat(1)) * 32767);
    SDL_SetJoystickVirtualAxis(s_pad, axis + 1, std::clamp(y, CGFloat(-1), CGFloat(1)) * 32767);
}
#endif

static UIView* s_overlay = nil;
static UILabel* s_fps_label = nil;
static bool s_gamepad_connected = false;

@interface L4D2TouchOverlay : UIView
@property (nonatomic, assign) l4d2::touch::TouchConfig config;
@property (nonatomic, strong) NSMutableArray<UIButton*>* actionButtons;
@property (nonatomic, strong) NSMutableArray<UIButton*>* slotButtons;
@property (nonatomic, strong) NSMutableArray<UIButton*>* navigationButtons;
@property (nonatomic, strong) UIButton* modeButton;
@property (nonatomic, assign) BOOL navigationMode;
@property (nonatomic, strong) UIView* leftStickBase;
@property (nonatomic, strong) UIView* leftStickThumb;
@property (nonatomic, strong) UIView* lookArea;
@property (nonatomic, assign) CGPoint lastLookPoint;
@property (nonatomic, assign) NSUInteger lookTouchHash;
@property (nonatomic, assign) NSUInteger moveTouchHash;
@property (nonatomic, assign) NSUInteger lookSequence;
@property (nonatomic, assign) CGSize layoutSize;
@property (nonatomic, assign) UIEdgeInsets layoutInsets;

- (instancetype)initWithFrame:(CGRect)frame config:(const l4d2::touch::TouchConfig&)config;
- (void)buildUI;
- (void)setupGamepadObserver;
- (void)setButton:(UIButton*)button pressed:(BOOL)pressed;
- (void)buildShooterMode:(CGRect)layout;
- (void)buildXboxPadMode:(CGRect)layout;
- (void)addNavigationPadAtX:(CGFloat)x y:(CGFloat)y diameter:(CGFloat)diameter;
- (UIButton*)makeButton:(NSString*)title rect:(CGRect)rect color:(UIColor*)color border:(UIColor*)borderColor;
@end

@implementation L4D2TouchOverlay

- (instancetype)initWithFrame:(CGRect)frame config:(const l4d2::touch::TouchConfig&)config {
    if (self = [super initWithFrame:frame]) {
        _config = config;
        _navigationMode = YES; // Start in Menu Navigation mode so user can navigate the title/menu
        self.multipleTouchEnabled = YES;
        self.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
        self.backgroundColor = [UIColor clearColor];
        self.alpha = config.hud_opacity;
        [self buildUI];
        [self setupGamepadObserver];
    }
    return self;
}

- (void)buildUI {
    [self.subviews makeObjectsPerformSelector:@selector(removeFromSuperview)];
    _actionButtons = [NSMutableArray array];
    _slotButtons = [NSMutableArray array];
    _navigationButtons = [NSMutableArray array];

    CGRect layout = UIEdgeInsetsInsetRect(self.bounds, _layoutInsets);
    _layoutSize = self.bounds.size;

    if (_config.style == l4d2::touch::ControlStyle::L4D2ShooterMode) {
        [self buildShooterMode:layout];
    } else {
        [self buildXboxPadMode:layout];
    }

    const CGFloat top = CGRectGetMinY(layout) + 10.0;
    const CGFloat midX = CGRectGetMidX(layout);
    const BOOL xboxStyle = _config.style == l4d2::touch::ControlStyle::Xbox360Pad;
    const CGRect pauseRect = xboxStyle ? CGRectMake(midX - 76.0, top, 68.0, 38.0)
                                       : CGRectMake(midX - 75.0, top, 68.0, 38.0);
    const CGRect modeRect = xboxStyle ? CGRectMake(midX + 8.0, top, 82.0, 38.0)
                                      : CGRectMake(CGRectGetMaxX(layout) - 94.0, top, 82.0, 38.0);
    [self addSubview:[self makeButton:@"PAUSE" rect:pauseRect
                                  color:[UIColor colorWithWhite:0.16 alpha:0.82] border:nil]];
    _modeButton = [self makeButton:@"MENU" rect:modeRect
                             color:[UIColor colorWithRed:0.30 green:0.12 blue:0.10 alpha:0.88]
                            border:[UIColor colorWithRed:0.85 green:0.32 blue:0.20 alpha:0.9]];
    [_modeButton removeTarget:self action:@selector(buttonDown:) forControlEvents:UIControlEventTouchDown | UIControlEventTouchDragEnter];
    [_modeButton removeTarget:self action:@selector(buttonUp:) forControlEvents:UIControlEventTouchUpInside | UIControlEventTouchUpOutside | UIControlEventTouchCancel | UIControlEventTouchDragExit];
    [_modeButton addTarget:self action:@selector(toggleNavigationMode) forControlEvents:UIControlEventTouchUpInside];
    [_actionButtons removeObjectIdenticalTo:_modeButton];
    [self addSubview:_modeButton];
    [self updateControlMode];
}

- (void)layoutSubviews {
    [super layoutSubviews];
    UIEdgeInsets insets = self.window ? self.window.safeAreaInsets : self.safeAreaInsets;
    const BOOL geometryChanged = !CGSizeEqualToSize(self.bounds.size, _layoutSize) ||
        !UIEdgeInsetsEqualToEdgeInsets(insets, _layoutInsets);
    if (geometryChanged) {
        _moveTouchHash = 0;
        _lookTouchHash = 0;
        ++_lookSequence;
#if L4D2_TOUCH_SDL
        SetStick(SDL_GAMEPAD_AXIS_LEFTX, 0, 0);
        SetStick(SDL_GAMEPAD_AXIS_RIGHTX, 0, 0);
#endif
        _layoutInsets = insets;
        [self buildUI];
    }
}

- (void)safeAreaInsetsDidChange {
    [super safeAreaInsetsDidChange];
    [self setNeedsLayout];
}

- (void)buildShooterMode:(CGRect)layout {
    const CGFloat left = CGRectGetMinX(layout);
    const CGFloat top = CGRectGetMinY(layout);
    const CGFloat right = CGRectGetMaxX(layout);
    const CGFloat bottom = CGRectGetMaxY(layout);
    const CGFloat h = layout.size.height;
    const CGFloat edgeX = std::max(CGFloat(16.0), layout.size.width * 0.022);
    const CGFloat edgeY = std::max(CGFloat(12.0), h * 0.035);

    // The touch surface is laid out in points, inside the live safe area. This
    // keeps the thumb zones clear of the iPhone 17's landscape cutouts/home bar.
    const CGFloat stickSize = std::clamp(h * 0.32, CGFloat(104.0), CGFloat(136.0));
    _leftStickBase = [[UIView alloc] initWithFrame:CGRectMake(left + edgeX, bottom - edgeY - stickSize,
                                                              stickSize, stickSize)];
    _leftStickBase.backgroundColor = [UIColor colorWithWhite:0.15 alpha:0.4];
    _leftStickBase.layer.cornerRadius = stickSize / 2.0;
    _leftStickBase.layer.borderColor = [UIColor colorWithWhite:0.8 alpha:0.3].CGColor;
    _leftStickBase.layer.borderWidth = 2.0;

    const CGFloat thumbSize = stickSize * 0.42;
    _leftStickThumb = [[UIView alloc] initWithFrame:CGRectMake((stickSize - thumbSize)/2, (stickSize - thumbSize)/2, thumbSize, thumbSize)];
    _leftStickThumb.backgroundColor = [UIColor colorWithWhite:0.9 alpha:0.6];
    _leftStickThumb.layer.cornerRadius = thumbSize / 2.0;
    [_leftStickBase addSubview:_leftStickThumb];
    [self addSubview:_leftStickBase];

    // 2. Right Look Area (Mobile Shooter Drag Area)
    _lookArea = [[UIView alloc] initWithFrame:CGRectMake(left + layout.size.width * 0.42, top + 52.0,
                                                          layout.size.width * 0.58, h * 0.78)];
    _lookArea.backgroundColor = [UIColor clearColor];
    _lookArea.userInteractionEnabled = YES;
    [self addSubview:_lookArea];

    // A separated 3-column action cluster: common actions are one thumb move
    // from FIRE, with its larger hit target pinned above the home-indicator edge.
    const CGFloat btnD = std::clamp(h * 0.148, CGFloat(48.0), CGFloat(60.0));
    const CGFloat fireD = std::clamp(h * 0.195, CGFloat(64.0), CGFloat(78.0));
    const CGFloat gap = std::max(fireD - btnD + 6.0,
                                 std::clamp(btnD * 0.14, CGFloat(6.0), CGFloat(9.0)));
    const CGFloat clusterRight = right - edgeX;
    const CGFloat col3 = clusterRight - btnD;
    const CGFloat col2 = col3 - gap - btnD;
    const CGFloat col1 = col2 - gap - btnD;
    const CGFloat rowBottom = bottom - edgeY - btnD;
    const CGFloat rowMiddle = rowBottom - gap - fireD;
    const CGFloat rowTop = rowMiddle - gap - btnD;
    const CGFloat fireX = clusterRight - fireD;
    const CGFloat fireY = rowMiddle;

    [self addSubview:[self makeButton:@"FIRE" rect:CGRectMake(fireX, fireY, fireD, fireD)
                                color:[UIColor colorWithRed:0.70 green:0.10 blue:0.10 alpha:0.92]
                                border:[UIColor colorWithRed:0.95 green:0.25 blue:0.25 alpha:0.95]]];
    [self addSubview:[self makeButton:@"CROUCH" rect:CGRectMake(col1, rowBottom, btnD, btnD)
                                color:[UIColor colorWithWhite:0.15 alpha:0.83]
                                border:[UIColor colorWithWhite:0.7 alpha:0.7]]];
    [self addSubview:[self makeButton:@"JUMP" rect:CGRectMake(col2, rowBottom, btnD, btnD)
                                color:[UIColor colorWithWhite:0.15 alpha:0.83]
                                border:[UIColor colorWithWhite:0.7 alpha:0.7]]];
    [self addSubview:[self makeButton:@"SHOVE" rect:CGRectMake(col1, rowMiddle, btnD, btnD)
                                color:[UIColor colorWithWhite:0.18 alpha:0.84]
                                border:[UIColor colorWithRed:0.8 green:0.4 blue:0.1 alpha:0.9]]];
    [self addSubview:[self makeButton:@"RELOAD" rect:CGRectMake(col2, rowMiddle, btnD, btnD)
                                color:[UIColor colorWithWhite:0.18 alpha:0.84]
                                border:[UIColor colorWithWhite:0.7 alpha:0.7]]];
    [self addSubview:[self makeButton:@"USE" rect:CGRectMake(col3, rowBottom, btnD, btnD)
                                color:[UIColor colorWithWhite:0.18 alpha:0.84]
                                border:[UIColor colorWithRed:0.2 green:0.7 blue:0.9 alpha:0.9]]];
    [self addSubview:[self makeButton:@"ZOOM" rect:CGRectMake(col3, rowTop, btnD, btnD)
                                color:[UIColor colorWithWhite:0.18 alpha:0.84]
                                border:[UIColor colorWithWhite:0.6 alpha:0.7]]];

    const CGFloat smallD = std::clamp(h * 0.125, CGFloat(44.0), CGFloat(52.0));
    [self addSubview:[self makeButton:@"LIGHT" rect:CGRectMake(left + edgeX + stickSize + 16.0,
                                                                 top + 10.0, smallD, smallD)
                                  color:[UIColor colorWithWhite:0.16 alpha:0.82]
                                 border:[UIColor colorWithRed:0.9 green:0.8 blue:0.2 alpha:0.8]]];

    // Inventory controls stay centered and keep enough spacing for four fingers.
    const CGFloat slotW = std::clamp(layout.size.width * 0.068, CGFloat(48.0), CGFloat(58.0));
    const CGFloat slotH = std::clamp(h * 0.12, CGFloat(40.0), CGFloat(46.0));
    const CGFloat slotGap = 5.0;
    const CGFloat barW = slotW * 4.0 + slotGap * 3.0;
    const CGFloat barX = CGRectGetMidX(layout) - barW / 2.0;
    const CGFloat barY = bottom - edgeY - slotH;

    NSArray* slotTitles = @[@"WEAPON", @"THROW", @"KIT", @"PILLS"];
    for (NSUInteger i = 0; i < slotTitles.count; ++i) {
        CGRect slotRect = CGRectMake(barX + i * (slotW + slotGap), barY, slotW, slotH);
        UIButton* slotBtn = [self makeButton:slotTitles[i] rect:slotRect
                                      color:[UIColor colorWithRed:0.1 green:0.14 blue:0.1 alpha:0.8]
                                     border:[UIColor colorWithRed:0.5 green:0.65 blue:0.4 alpha:0.8]];
        slotBtn.tag = 101 + i;
        [_slotButtons addObject:slotBtn];
        [self addSubview:slotBtn];
    }
#if L4D2_TOUCH_SDL
    const CGFloat navD = std::clamp(h * 0.12, CGFloat(38.0), CGFloat(46.0));
    [self addNavigationPadAtX:left + edgeX y:bottom - edgeY - navD * 3.0 diameter:navD];
#endif
}

#if L4D2_TOUCH_SDL
- (void)addNavigationPadAtX:(CGFloat)x y:(CGFloat)y diameter:(CGFloat)d {
    const UIColor* color = [UIColor colorWithWhite:0.12 alpha:0.76];
    NSArray* controls = @[
        @[@"↑", @(x + d), @(y)],
        @[@"↓", @(x + d), @(y + d * 2)],
        @[@"←", @(x), @(y + d)],
        @[@"→", @(x + d * 2), @(y + d)],
    ];
    for (NSArray* item in controls) {
        NSString* title = item[0];
        CGRect frame = CGRectMake([item[1] doubleValue], [item[2] doubleValue], d, d);
        UIButton* button = [self makeButton:title rect:frame color:(UIColor*)color border:nil];
        button.accessibilityLabel = [NSString stringWithFormat:@"Menu %@", title];
        [_actionButtons removeObjectIdenticalTo:button];
        [_navigationButtons addObject:button];
        [self addSubview:button];
    }
    const CGFloat faceD = d + 6.0;
    const CGFloat right = CGRectGetMaxX(UIEdgeInsetsInsetRect(self.bounds, _layoutInsets)) - 18.0;
    const CGFloat bottom = CGRectGetMaxY(UIEdgeInsetsInsetRect(self.bounds, _layoutInsets)) - 18.0;
    const CGFloat faceGap = 8.0;
    for (NSArray* item in @[
        @[@"START", @(right - faceD * 3.0 - faceGap * 2.0), @(bottom - faceD)],
        @[@"A", @(right - faceD * 2.0 - faceGap), @(bottom - faceD)],
        @[@"B", @(right - faceD), @(bottom - faceD)],
    ]) {
        UIButton* button = [self makeButton:item[0]
                                       rect:CGRectMake([item[1] doubleValue], [item[2] doubleValue], faceD, faceD)
                                      color:[UIColor colorWithWhite:0.12 alpha:0.82]
                                     border:nil];
        [_actionButtons removeObjectIdenticalTo:button];
        [_navigationButtons addObject:button];
        [self addSubview:button];
    }
}
#endif

- (void)updateControlMode {
    for (UIButton* button in _actionButtons) button.hidden = self.navigationMode;
    for (UIButton* button in _slotButtons) button.hidden = self.navigationMode;
    for (UIButton* button in _navigationButtons) button.hidden = !self.navigationMode;
    _leftStickBase.hidden = self.navigationMode;
    _lookArea.hidden = self.navigationMode;
    UIButtonConfiguration* modeConfig = _modeButton.configuration;
    modeConfig.title = self.navigationMode ? @"GAME" : @"MENU";
    modeConfig.attributedTitle = nil;
    modeConfig.image = [UIImage systemImageNamed:self.navigationMode ? @"gamecontroller.fill" : @"list.bullet"];
    modeConfig.imagePlacement = NSDirectionalRectEdgeLeading;
    modeConfig.imagePadding = 5.0;
    modeConfig.preferredSymbolConfigurationForImage =
        [UIImageSymbolConfiguration configurationWithPointSize:14.0 weight:UIImageSymbolWeightSemibold];
    _modeButton.accessibilityLabel = self.navigationMode ? @"Switch to game controls" : @"Switch to menu controls";
    _modeButton.configuration = modeConfig;
}

- (void)toggleNavigationMode {
    _moveTouchHash = 0;
    _lookTouchHash = 0;
    ++_lookSequence;
#if L4D2_TOUCH_SDL
    SetStick(SDL_GAMEPAD_AXIS_LEFTX, 0, 0);
    SetStick(SDL_GAMEPAD_AXIS_RIGHTX, 0, 0);
#endif
    for (UIButton* button in _actionButtons) [self setButton:button pressed:NO];
    for (UIButton* button in _navigationButtons) [self setButton:button pressed:NO];
#if L4D2_TOUCH_SDL
    if (s_pad) {
        const SDL_GamepadButton button = self.navigationMode ? SDL_GAMEPAD_BUTTON_EAST : SDL_GAMEPAD_BUTTON_START;
        SDL_SetJoystickVirtualButton(s_pad, button, true);
        SDL_UpdateJoysticks();
        SDL_SetJoystickVirtualButton(s_pad, button, false);
        SDL_UpdateJoysticks();
    }
#endif
    self.navigationMode = !self.navigationMode;
    [self updateControlMode];
}

- (void)buildXboxPadMode:(CGRect)layout {
    const CGFloat left = CGRectGetMinX(layout);
    const CGFloat right = CGRectGetMaxX(layout);
    const CGFloat top = CGRectGetMinY(layout);
    const CGFloat bottom = CGRectGetMaxY(layout);
    const CGFloat h = layout.size.height;
    const CGFloat edgeX = std::max(CGFloat(16.0), layout.size.width * 0.022);
    const CGFloat edgeY = std::max(CGFloat(12.0), h * 0.035);
    const CGFloat stickSize = std::clamp(h * 0.32, CGFloat(104.0), CGFloat(136.0));
    _leftStickBase = [[UIView alloc] initWithFrame:CGRectMake(left + edgeX, bottom - edgeY - stickSize,
                                                              stickSize, stickSize)];
    _leftStickBase.backgroundColor = [UIColor colorWithWhite:0.15 alpha:0.4];
    _leftStickBase.layer.cornerRadius = stickSize / 2.0;
    _leftStickBase.layer.borderWidth = 2.0;
    _leftStickBase.layer.borderColor = [UIColor colorWithWhite:0.8 alpha:0.3].CGColor;
    [self addSubview:_leftStickBase];
    const CGFloat thumbSize = stickSize * 0.42;
    _leftStickThumb = [[UIView alloc] initWithFrame:CGRectMake((stickSize - thumbSize) / 2.0,
                                                                (stickSize - thumbSize) / 2.0,
                                                                thumbSize, thumbSize)];
    _leftStickThumb.backgroundColor = [UIColor colorWithWhite:0.9 alpha:0.6];
    _leftStickThumb.layer.cornerRadius = thumbSize / 2.0;
    [_leftStickBase addSubview:_leftStickThumb];
    _lookArea = [[UIView alloc] initWithFrame:CGRectMake(left + layout.size.width * 0.42, top + 52.0,
                                                          layout.size.width * 0.58, h * 0.78)];
    [self addSubview:_lookArea];

    // Xbox ABXY diamond and shoulder controls scale with the usable landscape height.
    const CGFloat btnD = std::clamp(h * 0.15, CGFloat(50.0), CGFloat(62.0));
    const CGFloat offset = btnD;
    const CGFloat cx = right - edgeX - offset - btnD;
    const CGFloat cy = bottom - edgeY - offset - btnD;
    [self addSubview:[self makeButton:@"A" rect:CGRectMake(cx, cy + offset, btnD, btnD) color:[UIColor colorWithRed:0.1 green:0.6 blue:0.2 alpha:0.8] border:nil]];
    [self addSubview:[self makeButton:@"B" rect:CGRectMake(cx + offset, cy, btnD, btnD) color:[UIColor colorWithRed:0.7 green:0.1 blue:0.1 alpha:0.8] border:nil]];
    [self addSubview:[self makeButton:@"X" rect:CGRectMake(cx - offset, cy, btnD, btnD) color:[UIColor colorWithRed:0.1 green:0.4 blue:0.8 alpha:0.8] border:nil]];
    [self addSubview:[self makeButton:@"Y" rect:CGRectMake(cx, cy - offset, btnD, btnD) color:[UIColor colorWithRed:0.8 green:0.7 blue:0.1 alpha:0.8] border:nil]];

    // Bumpers & Triggers
    const CGFloat shoulderW = std::clamp(layout.size.width * 0.075, CGFloat(58.0), CGFloat(72.0));
    const CGFloat shoulderH = std::clamp(h * 0.12, CGFloat(38.0), CGFloat(46.0));
    [self addSubview:[self makeButton:@"LT" rect:CGRectMake(left + edgeX, top + edgeY, shoulderW, shoulderH)
                                color:[UIColor colorWithWhite:0.2 alpha:0.78] border:nil]];
    [self addSubview:[self makeButton:@"LB" rect:CGRectMake(left + edgeX + shoulderW + 8.0, top + edgeY,
                                                              shoulderW, shoulderH)
                                color:[UIColor colorWithWhite:0.2 alpha:0.78] border:nil]];
    [self addSubview:[self makeButton:@"RB" rect:CGRectMake(right - edgeX - shoulderW * 2.0 - 8.0,
                                                              top + edgeY, shoulderW, shoulderH)
                                color:[UIColor colorWithWhite:0.2 alpha:0.78] border:nil]];
    [self addSubview:[self makeButton:@"RT" rect:CGRectMake(right - edgeX - shoulderW, top + edgeY,
                                                              shoulderW, shoulderH)
                                color:[UIColor colorWithRed:0.7 green:0.1 blue:0.1 alpha:0.84] border:nil]];
#if L4D2_TOUCH_SDL
    const CGFloat navD = std::clamp(h * 0.12, CGFloat(38.0), CGFloat(46.0));
    [self addNavigationPadAtX:left + edgeX y:bottom - edgeY - navD * 3.0 diameter:navD];
#endif
}

- (UIButton*)makeButton:(NSString*)title rect:(CGRect)rect color:(UIColor*)color border:(UIColor*)borderColor {
    UIButton* btn = [UIButton buttonWithType:UIButtonTypeCustom];
    btn.frame = rect;
    btn.layer.cornerRadius = MIN(rect.size.width, rect.size.height) * 0.34;
    btn.layer.shadowColor = UIColor.blackColor.CGColor;
    btn.layer.shadowOpacity = 0.32;
    btn.layer.shadowRadius = 5;
    btn.layer.shadowOffset = CGSizeMake(0, 2);
    btn.layer.borderColor = borderColor ? borderColor.CGColor : [UIColor colorWithWhite:1 alpha:0.36].CGColor;
    btn.layer.borderWidth = borderColor ? 1.5 : 1;
    NSDictionary<NSString*, NSString*>* symbols = @{
        @"FIRE": @"scope", @"SHOVE": @"hand.raised.fill", @"RELOAD": @"arrow.clockwise",
        @"JUMP": @"figure.jump", @"CROUCH": @"figure.crouching", @"USE": @"hand.tap.fill",
        @"ZOOM": @"plus.magnifyingglass", @"LIGHT": @"flashlight.on.fill",
        @"WEAPON": @"scope", @"THROW": @"flame.fill", @"KIT": @"cross.case.fill",
        @"PILLS": @"pills.fill", @"PAUSE": @"pause.fill",
        @"A": @"a.circle.fill", @"B": @"b.circle.fill", @"X": @"x.circle.fill", @"Y": @"y.circle.fill",
        @"LT": @"target", @"RT": @"scope", @"LB": @"arrow.left.to.line", @"RB": @"arrow.right.to.line",
    };
    NSString* symbol = symbols[title];
    UIButtonConfiguration* buttonConfig = [UIButtonConfiguration filledButtonConfiguration];
    buttonConfig.title = title;
    buttonConfig.baseBackgroundColor = color;
    buttonConfig.baseForegroundColor = UIColor.whiteColor;
    buttonConfig.contentInsets = NSDirectionalEdgeInsetsMake(4, 3, 4, 3);
    buttonConfig.cornerStyle = UIButtonConfigurationCornerStyleCapsule;
    buttonConfig.attributedTitle = [[NSAttributedString alloc]
        initWithString:title
            attributes:@{NSFontAttributeName: [UIFont systemFontOfSize:MIN(13.0, MAX(9.0, rect.size.height * 0.22))
                                                                  weight:UIFontWeightBold],
                         NSForegroundColorAttributeName: UIColor.whiteColor}];
    if (symbol) {
        buttonConfig.image = [UIImage systemImageNamed:symbol];
        buttonConfig.imagePlacement = NSDirectionalRectEdgeTop;
        buttonConfig.imagePadding = 2.0;
        btn.tintColor = UIColor.whiteColor;
        buttonConfig.preferredSymbolConfigurationForImage =
            [UIImageSymbolConfiguration configurationWithPointSize:MIN(19.0, MAX(14.0, rect.size.height * 0.31))
                                                              weight:UIImageSymbolWeightSemibold];
    }
    btn.configuration = buttonConfig;
    btn.titleLabel.font = [UIFont systemFontOfSize:MIN(13.0, MAX(9.0, rect.size.height * 0.22))
                                             weight:UIFontWeightBold];
    btn.titleLabel.adjustsFontSizeToFitWidth = YES;
    btn.titleLabel.minimumScaleFactor = 0.68;
    btn.accessibilityLabel = title;
    [btn addTarget:self action:@selector(buttonDown:) forControlEvents:UIControlEventTouchDown | UIControlEventTouchDragEnter];
    [btn addTarget:self action:@selector(buttonUp:) forControlEvents:UIControlEventTouchUpInside |
        UIControlEventTouchUpOutside | UIControlEventTouchCancel | UIControlEventTouchDragExit];
    [_actionButtons addObject:btn];
    return btn;
}

- (void)setButton:(UIButton*)button pressed:(BOOL)pressed {
#if L4D2_TOUCH_SDL
    if (!s_pad) return;
    NSString* title = button.configuration.title ?: button.configuration.attributedTitle.string ?: [button titleForState:UIControlStateNormal];
    if ([title isEqualToString:@"FIRE"] || [title isEqualToString:@"RT"] ||
        [title isEqualToString:@"SHOVE"] || [title isEqualToString:@"LT"]) {
        const bool right = [title isEqualToString:@"FIRE"] || [title isEqualToString:@"RT"];
        SDL_SetJoystickVirtualAxis(s_pad, right ? SDL_GAMEPAD_AXIS_RIGHT_TRIGGER : SDL_GAMEPAD_AXIS_LEFT_TRIGGER,
                                   pressed ? SDL_JOYSTICK_AXIS_MAX : SDL_JOYSTICK_AXIS_MIN);
        return;
    }
    NSDictionary<NSString*, NSNumber*>* buttons = @{
        @"A": @(SDL_GAMEPAD_BUTTON_SOUTH), @"JUMP": @(SDL_GAMEPAD_BUTTON_SOUTH),
        @"B": @(SDL_GAMEPAD_BUTTON_EAST), @"RELOAD": @(SDL_GAMEPAD_BUTTON_WEST),
        @"X": @(SDL_GAMEPAD_BUTTON_WEST), @"USE": @(SDL_GAMEPAD_BUTTON_EAST),
        @"Y": @(SDL_GAMEPAD_BUTTON_NORTH), @"WEAPON": @(SDL_GAMEPAD_BUTTON_NORTH),
        @"LB": @(SDL_GAMEPAD_BUTTON_LEFT_SHOULDER), @"RB": @(SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER),
        @"CROUCH": @(SDL_GAMEPAD_BUTTON_LEFT_STICK), @"ZOOM": @(SDL_GAMEPAD_BUTTON_RIGHT_STICK),
        @"LIGHT": @(SDL_GAMEPAD_BUTTON_DPAD_UP), @"THROW": @(SDL_GAMEPAD_BUTTON_DPAD_LEFT),
        @"KIT": @(SDL_GAMEPAD_BUTTON_DPAD_DOWN), @"PILLS": @(SDL_GAMEPAD_BUTTON_DPAD_RIGHT),
        @"PAUSE": @(SDL_GAMEPAD_BUTTON_START), @"MENU": @(SDL_GAMEPAD_BUTTON_START),
        @"START": @(SDL_GAMEPAD_BUTTON_START),
        @"BACK": @(SDL_GAMEPAD_BUTTON_BACK),
        @"↑": @(SDL_GAMEPAD_BUTTON_DPAD_UP), @"↓": @(SDL_GAMEPAD_BUTTON_DPAD_DOWN),
        @"←": @(SDL_GAMEPAD_BUTTON_DPAD_LEFT), @"→": @(SDL_GAMEPAD_BUTTON_DPAD_RIGHT),
    };
    NSNumber* index = buttons[title];
    if (index) SDL_SetJoystickVirtualButton(s_pad, index.intValue, pressed);
#endif
}

- (void)buttonDown:(UIButton*)button { [self setButton:button pressed:YES]; }
- (void)buttonUp:(UIButton*)button { [self setButton:button pressed:NO]; }

- (void)setupGamepadObserver {
    [[NSNotificationCenter defaultCenter] addObserverForName:GCControllerDidConnectNotification
                                                      object:nil queue:[NSOperationQueue mainQueue]
                                                  usingBlock:^(NSNotification* note) {
        (void)note;
        s_gamepad_connected = true;
        if (self.config.auto_hide_on_controller) {
            [UIView animateWithDuration:0.3 animations:^{ self.alpha = 0.0; }];
        }
    }];

    [[NSNotificationCenter defaultCenter] addObserverForName:GCControllerDidDisconnectNotification
                                                      object:nil queue:[NSOperationQueue mainQueue]
                                                  usingBlock:^(NSNotification* note) {
        (void)note;
        if ([GCController controllers].count == 0) {
            s_gamepad_connected = false;
            [UIView animateWithDuration:0.3 animations:^{ self.alpha = self.config.hud_opacity; }];
        }
    }];
}

- (UIView*)hitTest:(CGPoint)point withEvent:(UIEvent*)event {
    UIView* hit = [super hitTest:point withEvent:event];
    if (hit && (hit == _leftStickBase || hit == _leftStickThumb || hit == _lookArea)) return self;
    return hit == self ? nil : hit;
}

- (void)moveStick:(CGPoint)point {
    const CGFloat radius = _leftStickBase.bounds.size.width * 0.38;
    const CGFloat dx = point.x - CGRectGetMidX(_leftStickBase.frame);
    const CGFloat dy = point.y - CGRectGetMidY(_leftStickBase.frame);
    const CGFloat distance = std::hypot(dx, dy);
    const CGFloat scale = std::max(radius, distance);
    const CGFloat x = dx / scale * radius;
    const CGFloat y = dy / scale * radius;
    _leftStickThumb.transform = CGAffineTransformMakeTranslation(x, y);
#if L4D2_TOUCH_SDL
    SetStick(SDL_GAMEPAD_AXIS_LEFTX, x / radius, y / radius);
#endif
}

- (void)touchesBegan:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    (void)event;
    for (UITouch* t in touches) {
        CGPoint pt = [t locationInView:self];
        if (!_moveTouchHash && CGRectContainsPoint(_leftStickBase.frame, pt)) {
            _moveTouchHash = t.hash;
            [self moveStick:pt];
        } else if (!_lookTouchHash && _config.drag_to_look && CGRectContainsPoint(_lookArea.frame, pt)) {
            _lookTouchHash = (NSUInteger)t.hash;
            _lastLookPoint = pt;
        }
    }
}

- (void)touchesMoved:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    (void)event;
    for (UITouch* touch in touches) {
        CGPoint point = [touch locationInView:self];
        if (touch.hash == _moveTouchHash) {
            [self moveStick:point];
        } else if (_config.drag_to_look && touch.hash == _lookTouchHash) {
            CGFloat dx = (point.x - _lastLookPoint.x) * _config.look_sensitivity_x;
            CGFloat dy = (point.y - _lastLookPoint.y) * _config.look_sensitivity_y;
            if (_config.invert_y) dy = -dy;
            _lastLookPoint = point;
#if L4D2_TOUCH_SDL
            SetStick(SDL_GAMEPAD_AXIS_RIGHTX, dx / 18.0, dy / 18.0);
            const NSUInteger sequence = ++_lookSequence;
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 65 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
                if (self.lookSequence == sequence) SetStick(SDL_GAMEPAD_AXIS_RIGHTX, 0, 0);
            });
#endif
        }
    }
}

- (void)touchesEnded:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    (void)event;
    for (UITouch* t in touches) {
        if ((NSUInteger)t.hash == _lookTouchHash) {
            _lookTouchHash = 0;
            ++_lookSequence;
#if L4D2_TOUCH_SDL
            SetStick(SDL_GAMEPAD_AXIS_RIGHTX, 0, 0);
#endif
        }
        if (t.hash == _moveTouchHash) {
            _moveTouchHash = 0;
            _leftStickThumb.transform = CGAffineTransformIdentity;
#if L4D2_TOUCH_SDL
            SetStick(SDL_GAMEPAD_AXIS_LEFTX, 0, 0);
#endif
        }
    }
}

- (void)touchesCancelled:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    [self touchesEnded:touches withEvent:event];
}

@end

namespace l4d2::touch {

static UIWindow* GetKeyWindow() {
    UIWindow* keyWindow = nil;
    for (UIWindowScene* scene in [UIApplication sharedApplication].connectedScenes) {
        if ([scene isKindOfClass:[UIWindowScene class]]) {
            for (UIWindow* w in scene.windows) {
                if (w.hidden || !w.rootViewController) continue;
                if ([NSStringFromClass(w.rootViewController.class) hasPrefix:@"SDL"]) return w;
                if (w.isKeyWindow) keyWindow = w;
            }
        }
    }
    return keyWindow;
}

static void InstallOnMain(const TouchConfig config, unsigned retries) {
    UIWindow* window = GetKeyWindow();
    if (!window || ![NSStringFromClass(window.rootViewController.class) hasPrefix:@"SDL"]) {
        if (retries) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
                InstallOnMain(config, retries - 1);
            });
        } else {
            l4d2::boot::Trace("touch: SDL window unavailable");
        }
        return;
    }
#if L4D2_TOUCH_SDL
    StartTouchPad();
#endif
    [s_overlay removeFromSuperview];
    s_overlay = [[L4D2TouchOverlay alloc] initWithFrame:window.bounds config:config];
    s_overlay.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    s_overlay.layer.zPosition = 100;
    [window addSubview:s_overlay];
    l4d2::boot::Trace("touch: overlay attached to SDL window");
}

void Install(const TouchConfig& config) {
    const TouchConfig initial = config;
    dispatch_async(dispatch_get_main_queue(), ^{
        InstallOnMain(initial, 20);
    });
}

void InstallFpsCounter() {
    dispatch_async(dispatch_get_main_queue(), ^{
        UIWindow* window = GetKeyWindow();
        if (!window) return;

        if (!s_fps_label) {
            s_fps_label = [[UILabel alloc] initWithFrame:CGRectMake(24, 24, 160, 28)];
            s_fps_label.backgroundColor = [UIColor colorWithWhite:0.0 alpha:0.7];
            s_fps_label.textColor = [UIColor colorWithRed:0.4 green:1.0 blue:0.4 alpha:1.0];
            s_fps_label.font = [UIFont monospacedDigitSystemFontOfSize:13 weight:UIFontWeightBold];
            s_fps_label.textAlignment = NSTextAlignmentCenter;
            s_fps_label.layer.cornerRadius = 6.0;
            s_fps_label.layer.masksToBounds = YES;
            s_fps_label.text = @"60.0 FPS • 16.6ms";
            [window addSubview:s_fps_label];
        }
    });
}

void SetVisible(bool visible) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (s_overlay) {
            s_overlay.hidden = !visible;
        }
    });
}

void UpdateConfig(const TouchConfig& config) {
    const TouchConfig updated = config;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (s_overlay && [s_overlay isKindOfClass:[L4D2TouchOverlay class]]) {
            L4D2TouchOverlay* ov = (L4D2TouchOverlay*)s_overlay;
            ov.config = updated;
            [ov buildUI];
        }
    });
}

UIViewController* MakeLayoutEditor() {
    UIViewController* vc = [[UIViewController alloc] init];
    vc.view.backgroundColor = [UIColor colorWithRed:0.08 green:0.10 blue:0.08 alpha:0.95];

    UILabel* title = [[UILabel alloc] initWithFrame:CGRectMake(0, 30, vc.view.bounds.size.width, 32)];
    title.text = @"L4D2 TOUCH LAYOUT EDITOR";
    title.textColor = [UIColor colorWithRed:0.8 green:0.2 blue:0.2 alpha:1.0];
    title.font = [UIFont systemFontOfSize:18 weight:UIFontWeightHeavy];
    title.textAlignment = NSTextAlignmentCenter;
    [vc.view addSubview:title];

    UIButton* doneBtn = [UIButton buttonWithType:UIButtonTypeSystem];
    doneBtn.frame = CGRectMake(vc.view.bounds.size.width - 100, 26, 80, 36);
    [doneBtn setTitle:@"SAVE" forState:UIControlStateNormal];
    doneBtn.titleLabel.font = [UIFont systemFontOfSize:15 weight:UIFontWeightBold];
    [doneBtn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    doneBtn.backgroundColor = [UIColor colorWithRed:0.7 green:0.1 blue:0.1 alpha:0.9];
    doneBtn.layer.cornerRadius = 8.0;
    [doneBtn addAction:[UIAction actionWithHandler:^(__kindof UIAction* a) {
        (void)a;
        [vc dismissViewControllerAnimated:YES completion:nil];
    }] forControlEvents:UIControlEventTouchUpInside];
    [vc.view addSubview:doneBtn];

    return vc;
}

} // namespace l4d2::touch
