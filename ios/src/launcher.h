#pragma once

#include <filesystem>
#include <string>
#include <vector>

#ifdef __OBJC__
#import <UIKit/UIKit.h>

@interface L4D2LauncherController : UITableViewController <UIDocumentPickerDelegate>
@property (nonatomic, copy) void (^onPlayHandler)(std::filesystem::path gameRoot, NSDictionary* settings);

- (instancetype)initWithDocuments:(const std::filesystem::path&)documents
                             done:(void (^)(std::filesystem::path gameRoot, NSDictionary* settings))done;
- (void)rescan;
@end

@interface L4D2LauncherNavigation : UINavigationController
@end

// Alias for backwards compatibility
using L4D2LauncherVC = L4D2LauncherController;
#endif

namespace l4d2::launcher {

// Returns the active documents directory in app container
std::filesystem::path Documents();

// Find ISO files or game folders in Documents/
std::vector<std::filesystem::path> FindIsos(const std::filesystem::path& documents);

// Returns launch arguments configured in launcher settings
std::vector<std::string> SettingsArguments(const std::filesystem::path& documents);

// Bundles boot.txt, l4d2.log, settings.json, and system diagnostics into a zip file
bool ExportLogsZip(const std::filesystem::path& documents, std::string& out_zip_path);

// Backup saves to a zip file
bool BackupSavesZip(const std::filesystem::path& documents, std::string& out_zip_path);

// Restore saves from a zip file
bool RestoreSavesZip(const std::filesystem::path& documents, const std::string& in_zip_path);

} // namespace l4d2::launcher
