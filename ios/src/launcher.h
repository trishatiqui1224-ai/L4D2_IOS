#pragma once

#include <filesystem>
#include <string>
#include <vector>

#ifdef __OBJC__
#import <UIKit/UIKit.h>
#endif

namespace l4d2::launcher {

// Returns the active documents directory in app container
std::filesystem::path Documents();

// Runs the interactive L4D2 Recomp launcher UI before starting the engine.
// Returns the verified game data root path when PLAY is tapped.
std::filesystem::path Run(const std::filesystem::path& documents);

// Returns launch arguments configured in launcher settings
std::vector<std::string> SettingsArguments(const std::filesystem::path& documents);

// Bundles boot.txt, l4d2.log, settings.json, and system diagnostics into a zip file
bool ExportLogsZip(const std::filesystem::path& documents, std::string& out_zip_path);

} // namespace l4d2::launcher
