#pragma once

#include <cstdarg>
#include <cstdio>
#include <string>
#include <string_view>
#include <mutex>
#include <vector>

namespace l4d2::log {

enum class Level {
    Debug,
    Info,
    Warn,
    Error,
    Fatal
};

class Logger {
public:
    static Logger& Instance();

    void Init(const std::string& log_file_path);
    void Shutdown();

    void Log(Level level, const char* module_tag, const char* format, ...);
    void LogV(Level level, const char* module_tag, const char* format, va_list args);

    void RecordBreadcrumb(const std::string& crumb);
    std::vector<std::string> GetRecentBreadcrumbs(size_t count = 16);

    void Flush();

private:
    Logger() = default;
    ~Logger();

    std::mutex mutex_;
    FILE* file_ = nullptr;
    std::string log_path_;
    std::vector<std::string> breadcrumbs_;
    static constexpr size_t kMaxBreadcrumbs = 64;
};

#define L4D2_LOG_DEBUG(mod, fmt, ...) l4d2::log::Logger::Instance().Log(l4d2::log::Level::Debug, mod, fmt, ##__VA_ARGS__)
#define L4D2_LOG_INFO(mod, fmt, ...)  l4d2::log::Logger::Instance().Log(l4d2::log::Level::Info,  mod, fmt, ##__VA_ARGS__)
#define L4D2_LOG_WARN(mod, fmt, ...)  l4d2::log::Logger::Instance().Log(l4d2::log::Level::Warn,  mod, fmt, ##__VA_ARGS__)
#define L4D2_LOG_ERROR(mod, fmt, ...) l4d2::log::Logger::Instance().Log(l4d2::log::Level::Error, mod, fmt, ##__VA_ARGS__)
#define L4D2_LOG_FATAL(mod, fmt, ...) l4d2::log::Logger::Instance().Log(l4d2::log::Level::Fatal, mod, fmt, ##__VA_ARGS__)

} // namespace l4d2::log

