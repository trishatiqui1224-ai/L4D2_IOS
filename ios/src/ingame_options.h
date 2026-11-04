#pragma once

#ifdef __OBJC__
#import <UIKit/UIKit.h>
#endif

namespace l4d2::options {

void ShowInGameMenu();
void HideInGameMenu();
bool IsMenuVisible();

void UpdatePerformanceStats(float fps, float frame_time_ms, uint64_t ram_bytes, int thermal_state);

} // namespace l4d2::options
