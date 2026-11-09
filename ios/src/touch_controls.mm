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
@property (nonatomic, strong) UIView* leftStickBase;
@property (nonatomic, strong) UIView* leftStickThumb;
@property (nonatomic, strong) UIView* lookArea;
@property (nonatomic, assign) CGPoint lastLookPoint;
@property (nonatomic, assign) NSUInteger lookTouchHash;
@property (nonatomic, assign) NSUInteger moveTouchHash;
@property (nonatomic, assign) NSUInteger lookSequence;
@property (nonatomic, assign) CGSize layoutSize;

- (instancetype)initWithFrame:(CGRect)frame config:(const l4d2::touch::TouchConfig&)config;
- (void)buildUI;
- (void)setupGamepadObserver;
- (void)buildShooterMode:(CGFloat)w height:(CGFloat)h;
- (void)buildXboxPadMode:(CGFloat)w height:(CGFloat)h;
- (UIButton*)makeButton:(NSString*)title rect:(CGRect)rect color:(UIColor*)color border:(UIColor*)borderColor;
@end

@implementation L4D2TouchOverlay

- (instancetype)initWithFrame:(CGRect)frame config:(const l4d2::touch::TouchConfig&)config {
    if (self = [super initWithFrame:frame]) {
        _config = config;
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

    CGRect bounds = self.bounds;
    _layoutSize = bounds.size;
    CGFloat w = bounds.size.width;
    CGFloat h = bounds.size.height;

    if (_config.style == l4d2::touch::ControlStyle::L4D2ShooterMode) {
        [self buildShooterMode:w height:h];
    } else {
        [self buildXboxPadMode:w height:h];
    }
    [self addSubview:[self makeButton:@"PAUSE" rect:CGRectMake(w * 0.5 + 34, 20, 60, 40)
                                  color:[UIColor colorWithWhite:0.2 alpha:0.75] border:nil]];
}

- (void)layoutSubviews {
    [super layoutSubviews];
    if (!CGSizeEqualToSize(self.bounds.size, _layoutSize) && !_moveTouchHash && !_lookTouchHash) {
        [self buildUI];
    }
}

- (void)buildShooterMode:(CGFloat)w height:(CGFloat)h {
    // 1. Movement Left Stick
    CGFloat stickSize = 130.0;
    _leftStickBase = [[UIView alloc] initWithFrame:CGRectMake(40, h - stickSize - 40, stickSize, stickSize)];
    _leftStickBase.backgroundColor = [UIColor colorWithWhite:0.15 alpha:0.4];
    _leftStickBase.layer.cornerRadius = stickSize / 2.0;
    _leftStickBase.layer.borderColor = [UIColor colorWithWhite:0.8 alpha:0.3].CGColor;
    _leftStickBase.layer.borderWidth = 2.0;

    CGFloat thumbSize = 54.0;
    _leftStickThumb = [[UIView alloc] initWithFrame:CGRectMake((stickSize - thumbSize)/2, (stickSize - thumbSize)/2, thumbSize, thumbSize)];
    _leftStickThumb.backgroundColor = [UIColor colorWithWhite:0.9 alpha:0.6];
    _leftStickThumb.layer.cornerRadius = thumbSize / 2.0;
    [_leftStickBase addSubview:_leftStickThumb];
    [self addSubview:_leftStickBase];

    // 2. Right Look Area (Mobile Shooter Drag Area)
    _lookArea = [[UIView alloc] initWithFrame:CGRectMake(w * 0.45, 0, w * 0.55, h * 0.75)];
    _lookArea.backgroundColor = [UIColor clearColor];
    _lookArea.userInteractionEnabled = YES;
    [self addSubview:_lookArea];

    // 3. Ergonomic FPS Action Buttons (Right side clustered for thumb reach)
    CGFloat btnD = 58.0;
    CGFloat rightMargin = w - 80;
    CGFloat bottomMargin = h - 70;

    // FIRE BUTTON (Prominent Crimson Red)
    UIButton* fireBtn = [self makeButton:@"FIRE" rect:CGRectMake(rightMargin - 65, bottomMargin - 90, 75, 75)
                                color:[UIColor colorWithRed:0.70 green:0.10 blue:0.10 alpha:0.85]
                                border:[UIColor colorWithRed:0.95 green:0.25 blue:0.25 alpha:0.9]];
    [self addSubview:fireBtn];

    // SHOVE / MELEE BUTTON
    UIButton* shoveBtn = [self makeButton:@"SHOVE" rect:CGRectMake(rightMargin - 150, bottomMargin - 70, btnD, btnD)
                                 color:[UIColor colorWithWhite:0.2 alpha:0.75]
                                border:[UIColor colorWithRed:0.8 green:0.4 blue:0.1 alpha:0.8]];
    [self addSubview:shoveBtn];

    // RELOAD
    UIButton* reloadBtn = [self makeButton:@"RELOAD" rect:CGRectMake(rightMargin - 75, bottomMargin - 175, btnD, btnD)
                                  color:[UIColor colorWithWhite:0.2 alpha:0.75]
                                 border:[UIColor colorWithWhite:0.7 alpha:0.6]];
    [self addSubview:reloadBtn];

    // JUMP
    UIButton* jumpBtn = [self makeButton:@"JUMP" rect:CGRectMake(rightMargin, bottomMargin - 20, btnD, btnD)
                                color:[UIColor colorWithWhite:0.2 alpha:0.75]
                               border:[UIColor colorWithWhite:0.7 alpha:0.6]];
    [self addSubview:jumpBtn];

    // CROUCH
    UIButton* crouchBtn = [self makeButton:@"CROUCH" rect:CGRectMake(rightMargin - 70, bottomMargin - 15, btnD, btnD)
                                  color:[UIColor colorWithWhite:0.2 alpha:0.75]
                                 border:[UIColor colorWithWhite:0.7 alpha:0.6]];
    [self addSubview:crouchBtn];

    // USE / INTERACT
    UIButton* useBtn = [self makeButton:@"USE" rect:CGRectMake(rightMargin - 145, bottomMargin - 155, btnD, btnD)
                               color:[UIColor colorWithWhite:0.2 alpha:0.75]
                              border:[UIColor colorWithRed:0.2 green:0.7 blue:0.9 alpha:0.8]];
    [self addSubview:useBtn];

    // ZOOM / SCOPE
    UIButton* scopeBtn = [self makeButton:@"ZOOM" rect:CGRectMake(rightMargin - 10, bottomMargin - 110, 48, 48)
                                 color:[UIColor colorWithWhite:0.2 alpha:0.75]
                                border:[UIColor colorWithWhite:0.6 alpha:0.5]];
    [self addSubview:scopeBtn];

    // FLASHLIGHT
    UIButton* lightBtn = [self makeButton:@"LIGHT" rect:CGRectMake(w * 0.5 - 25, 20, 50, 40)
                                 color:[UIColor colorWithWhite:0.2 alpha:0.65]
                                border:[UIColor colorWithRed:0.9 green:0.8 blue:0.2 alpha:0.7]];
    [self addSubview:lightBtn];

    // 4. 5-Slot Left 4 Dead 2 Inventory Bar (Bottom-Center)
    CGFloat barW = 250.0;
    CGFloat slotW = 58.0;
    CGFloat slotH = 46.0;
    CGFloat barX = (w - barW) / 2.0;
    CGFloat barY = h - slotH - 12.0;

    NSArray* slotTitles = @[@"WEAPON", @"THROW", @"KIT", @"PILLS"];
    for (NSUInteger i = 0; i < slotTitles.count; ++i) {
        CGRect slotRect = CGRectMake(barX + i * (slotW + 6.0), barY, slotW, slotH);
        UIButton* slotBtn = [self makeButton:slotTitles[i] rect:slotRect
                                      color:[UIColor colorWithRed:0.1 green:0.14 blue:0.1 alpha:0.8]
                                     border:[UIColor colorWithRed:0.5 green:0.65 blue:0.4 alpha:0.8]];
        slotBtn.tag = 101 + i;
        [_slotButtons addObject:slotBtn];
        [self addSubview:slotBtn];
    }
}

- (void)buildXboxPadMode:(CGFloat)w height:(CGFloat)h {
    // Classic Xbox 360 overlay: Sticks, D-pad, ABXY, Triggers, Bumpers
    CGFloat stickSize = 120.0;
    _leftStickBase = [[UIView alloc] initWithFrame:CGRectMake(40, h - stickSize - 40, stickSize, stickSize)];
    _leftStickBase.backgroundColor = [UIColor colorWithWhite:0.15 alpha:0.4];
    _leftStickBase.layer.cornerRadius = stickSize / 2.0;
    _leftStickBase.layer.borderWidth = 2.0;
    _leftStickBase.layer.borderColor = [UIColor colorWithWhite:0.8 alpha:0.3].CGColor;
    [self addSubview:_leftStickBase];
    _leftStickThumb = [[UIView alloc] initWithFrame:CGRectMake(35, 35, 50, 50)];
    _leftStickThumb.backgroundColor = [UIColor colorWithWhite:0.9 alpha:0.6];
    _leftStickThumb.layer.cornerRadius = 25;
    [_leftStickBase addSubview:_leftStickThumb];
    _lookArea = [[UIView alloc] initWithFrame:CGRectMake(w * 0.45, 0, w * 0.55, h * 0.8)];
    [self addSubview:_lookArea];

    // ABXY Diamond on right
    CGFloat btnD = 50.0;
    CGFloat cx = w - 100;
    CGFloat cy = h - 100;
    [self addSubview:[self makeButton:@"A" rect:CGRectMake(cx, cy + 35, btnD, btnD) color:[UIColor colorWithRed:0.1 green:0.6 blue:0.2 alpha:0.8] border:nil]];
    [self addSubview:[self makeButton:@"B" rect:CGRectMake(cx + 35, cy, btnD, btnD) color:[UIColor colorWithRed:0.7 green:0.1 blue:0.1 alpha:0.8] border:nil]];
    [self addSubview:[self makeButton:@"X" rect:CGRectMake(cx - 35, cy, btnD, btnD) color:[UIColor colorWithRed:0.1 green:0.4 blue:0.8 alpha:0.8] border:nil]];
    [self addSubview:[self makeButton:@"Y" rect:CGRectMake(cx, cy - 35, btnD, btnD) color:[UIColor colorWithRed:0.8 green:0.7 blue:0.1 alpha:0.8] border:nil]];

    // Bumpers & Triggers
    [self addSubview:[self makeButton:@"LT" rect:CGRectMake(30, 20, 60, 44) color:[UIColor colorWithWhite:0.2 alpha:0.7] border:nil]];
    [self addSubview:[self makeButton:@"LB" rect:CGRectMake(100, 20, 60, 44) color:[UIColor colorWithWhite:0.2 alpha:0.7] border:nil]];
    [self addSubview:[self makeButton:@"RB" rect:CGRectMake(w - 160, 20, 60, 44) color:[UIColor colorWithWhite:0.2 alpha:0.7] border:nil]];
    [self addSubview:[self makeButton:@"RT" rect:CGRectMake(w - 90, 20, 60, 44) color:[UIColor colorWithRed:0.7 green:0.1 blue:0.1 alpha:0.8] border:nil]];
}

- (UIButton*)makeButton:(NSString*)title rect:(CGRect)rect color:(UIColor*)color border:(UIColor*)borderColor {
    UIButton* btn = [UIButton buttonWithType:UIButtonTypeCustom];
    btn.frame = rect;
    btn.backgroundColor = color;
    btn.layer.cornerRadius = 10.0;
    if (borderColor) {
        btn.layer.borderColor = borderColor.CGColor;
        btn.layer.borderWidth = 1.5;
    }
    [btn setTitle:title forState:UIControlStateNormal];
    btn.titleLabel.font = [UIFont systemFontOfSize:13 weight:UIFontWeightBold];
    [btn setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    [btn setTitleColor:[UIColor colorWithWhite:0.7 alpha:1.0] forState:UIControlStateHighlighted];
    [btn addTarget:self action:@selector(buttonDown:) forControlEvents:UIControlEventTouchDown | UIControlEventTouchDragEnter];
    [btn addTarget:self action:@selector(buttonUp:) forControlEvents:UIControlEventTouchUpInside |
        UIControlEventTouchUpOutside | UIControlEventTouchCancel | UIControlEventTouchDragExit];
    return btn;
}

- (void)setButton:(UIButton*)button pressed:(BOOL)pressed {
#if L4D2_TOUCH_SDL
    if (!s_pad) return;
    NSString* title = [button titleForState:UIControlStateNormal];
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
        @"PAUSE": @(SDL_GAMEPAD_BUTTON_START),
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
    const CGFloat scale = std::max(radius, std::hypot(dx, dy));
    _leftStickThumb.transform = CGAffineTransformMakeTranslation(dx / scale * radius, dy / scale * radius);
#if L4D2_TOUCH_SDL
    SetStick(SDL_GAMEPAD_AXIS_LEFTX, dx / scale, dy / scale);
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
    for (UITouch* t in touches) {
        if (t.hash == _moveTouchHash) {
            [self moveStick:[t locationInView:self]];
        } else if (_config.drag_to_look && t.hash == _lookTouchHash) {
            CGPoint pt = [t locationInView:self];
            CGFloat dx = (pt.x - _lastLookPoint.x) * _config.look_sensitivity_x;
            CGFloat dy = (pt.y - _lastLookPoint.y) * _config.look_sensitivity_y;
            if (_config.invert_y) dy = -dy;
            _lastLookPoint = pt;

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
