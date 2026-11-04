#pragma once

#include <string>
#include <vector>
#include "module_loader.h"
#include "resolution_hooks.h"
#include "crash_handler.h"

namespace l4d2 {

class L4D2App {
public:
    static L4D2App& Instance();

    bool Initialize(int argc, char** argv);
    int Run();
    void Shutdown();

    const std::string& GetGameRoot() const { return game_root_; }
    const std::string& GetSaveRoot() const { return save_root_; }

private:
    L4D2App() = default;

    std::string game_root_;
    std::string save_root_;
    std::vector<std::string> args_;
    RenderConfig render_config_;
    bool is_initialized_ = false;
};

} // namespace l4d2

