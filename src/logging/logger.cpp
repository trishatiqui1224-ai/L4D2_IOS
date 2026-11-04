#include "logger.h"

#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>

namespace l4d2::log {

Logger& Logger::Instance() {
    static Logger instance;
    return instance;
}

Logger::~Logger() {
    Shutdown();
}

void Logger::Init(const std::string& log_file_path) {
    std::lock_guard<std::mutex> lock(mutex_);
    log_path_ = log_file_path;
    if (file_) {
        fclose(file_);
        file_ = nullptr;
    }
    if (!log_file_path.empty()) {
        file_ = fopen(log_file_path.c_str(), "w");
        if (file_) {
            fprintf(file_, "================================================================================\n");
            fprintf(file_, "  Left 4 Dead 2 Native Recompilation (L4D2 Recomp) Log Initialized\n");
            fprintf(file_, "  Target Disc: Title ID 454108D4 | Media ID 0E79403B (World Retail v0)\n");
            fprintf(file_, "================================================================================\n");
            fflush(file_);
        }
    }
}

void Logger::Shutdown() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (file_) {
        fflush(file_);
        fclose(file_);
        file_ = nullptr;
    }
}

static const char* LevelToString(Level level) {
    switch (level) {
        case Level::Debug: return "DEBUG";
        case Level::Info:  return "INFO";
        case Level::Warn:  return "WARN";
        case Level::Error: return "ERROR";
        case Level::Fatal: return "FATAL";
        default:           return "LOG";
    }
}

void Logger::Log(Level level, const char* module_tag, const char* format, ...) {
    va_list args;
    va_start(args, format);
    LogV(level, module_tag, format, args);
    va_end(args);
}

void Logger::LogV(Level level, const char* module_tag, const char* format, va_list args) {
    char buffer[2048];
    vsnprintf(buffer, sizeof(buffer), format, args);

    auto now = std::chrono::system_clock::now();
    auto now_c = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;

    struct tm timeinfo;
#if defined(_WIN32)
    localtime_s(&timeinfo, &now_c);
#else
    localtime_r(&now_c, &timeinfo);
#endif

    char time_str[64];
    strftime(time_str, sizeof(time_str), "%H:%M:%S", &timeinfo);

    char formatted[2560];
    snprintf(formatted, sizeof(formatted), "[%s.%03d] [%s] [%s] %s\n",
             time_str, static_cast<int>(ms.count()), LevelToString(level),
             module_tag ? module_tag : "General", buffer);

    std::lock_guard<std::mutex> lock(mutex_);
    fputs(formatted, stdout);
    if (file_) {
        fputs(formatted, file_);
        fflush(file_);
    }
}

void Logger::RecordBreadcrumb(const std::string& crumb) {
    std::lock_guard<std::mutex> lock(mutex_);
    breadcrumbs_.push_back(crumb);
    if (breadcrumbs_.size() > kMaxBreadcrumbs) {
        breadcrumbs_.erase(breadcrumbs_.begin());
    }
}

std::vector<std::string> Logger::GetRecentBreadcrumbs(size_t count) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (breadcrumbs_.size() <= count) {
        return breadcrumbs_;
    }
    return std::vector<std::string>(breadcrumbs_.end() - count, breadcrumbs_.end());
}

void Logger::Flush() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (file_) {
        fflush(file_);
    }
}

} // namespace l4d2::log
