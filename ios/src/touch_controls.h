#pragma once

#ifdef __OBJC__
#import <UIKit/UIKit.h>
#endif

namespace l4d2::touch {

enum class ControlStyle {
    Xbox360Pad,
    L4D2ShooterMode
};

struct TouchConfig {
    ControlStyle style = ControlStyle::L4D2ShooterMode;
    bool drag_to_look = true;
    bool gyro_aim = false;
    float look_sensitivity_x = 1.0f;
    float look_sensitivity_y = 1.0f;
    bool invert_y = false;
    float hud_opacity = 0.85f;
    bool auto_hide_on_controller = false;
};

void Install(const TouchConfig& config);
void InstallFpsCounter();
void SetVisible(bool visible);
void UpdateConfig(const TouchConfig& config);

#ifdef __OBJC__
UIViewController* MakeLayoutEditor();
#endif

} // namespace l4d2::touch

