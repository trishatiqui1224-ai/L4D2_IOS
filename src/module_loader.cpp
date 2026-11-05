#include "module_loader.h"
#include "logging/logger.h"

#include <algorithm>
#include <filesystem>
#include <iomanip>
#include <sstream>

namespace rex::runtime { class IModuleRegistrar; }
struct PPCFuncMapping { uint32_t address; void (*function)(); };

#define DECLARE_MODULE_SYMBOLS(name) \
    void l4d2_##name##_RegisterFunctions(rex::runtime::IModuleRegistrar*); \
    extern PPCFuncMapping l4d2_##name##_PPCFuncMappings[];

DECLARE_MODULE_SYMBOLS(default)
DECLARE_MODULE_SYMBOLS(engine)
DECLARE_MODULE_SYMBOLS(client)
DECLARE_MODULE_SYMBOLS(server)
DECLARE_MODULE_SYMBOLS(materialsystem)
DECLARE_MODULE_SYMBOLS(shaderapidx9)
DECLARE_MODULE_SYMBOLS(stdshader_dx9)
DECLARE_MODULE_SYMBOLS(studiorender)
DECLARE_MODULE_SYMBOLS(vphysics)
DECLARE_MODULE_SYMBOLS(soundemitter)
DECLARE_MODULE_SYMBOLS(datacache)
DECLARE_MODULE_SYMBOLS(scenefilecache)
DECLARE_MODULE_SYMBOLS(vgui2)
DECLARE_MODULE_SYMBOLS(vguimatsurface)
DECLARE_MODULE_SYMBOLS(inputsystem)
DECLARE_MODULE_SYMBOLS(filesystem)
DECLARE_MODULE_SYMBOLS(vstdlib)
DECLARE_MODULE_SYMBOLS(tier0)
DECLARE_MODULE_SYMBOLS(matchmaking)

namespace l4d2 {

namespace fs = std::filesystem;

ModuleLoader& ModuleLoader::Instance() {
    static ModuleLoader instance;
    return instance;
}

void ModuleLoader::Init(const std::string& game_root, const std::string& save_root) {
    game_root_ = game_root;
    save_root_ = save_root.empty() ? (game_root + "/SAVE") : save_root;
    cfg_root_  = save_root_ + "/cfg";

    try {
        fs::create_directories(save_root_);
        fs::create_directories(cfg_root_);
    } catch (const std::exception& e) {
        L4D2_LOG_WARN("VFS", "Failed to create save directories: %s", e.what());
    }

    loaded_modules_.clear();
    module_index_by_name_.clear();

    for (const auto& desc : kSourceModules) {
        LoadedModule mod;
        mod.name = desc.module_name;
        mod.path = desc.relative_path;
        mod.image_base = desc.image_base;
        mod.image_end = desc.image_end;
        mod.is_loaded = false;

        size_t idx = loaded_modules_.size();
        loaded_modules_.push_back(mod);

        // Map by name (e.g. "engine_360.dll", "engine_360", "bin\engine_360.dll")
        std::string lower_name = desc.module_name;
        std::transform(lower_name.begin(), lower_name.end(), lower_name.begin(), ::tolower);
        module_index_by_name_[lower_name] = idx;
        module_index_by_name_[lower_name + ".dll"] = idx;

        std::string rel_lower = desc.relative_path;
        std::transform(rel_lower.begin(), rel_lower.end(), rel_lower.begin(), ::tolower);
        module_index_by_name_[rel_lower] = idx;
    }

    struct RecompModuleBinding {
        const char* name;
        void (*register_fn)(rex::runtime::IModuleRegistrar*);
        PPCFuncMapping* mappings;
    };

    static const RecompModuleBinding kBindings[] = {
        {"default.xex", l4d2_default_RegisterFunctions, l4d2_default_PPCFuncMappings},
        {"engine_360.dll", l4d2_engine_RegisterFunctions, l4d2_engine_PPCFuncMappings},
        {"client_360.dll", l4d2_client_RegisterFunctions, l4d2_client_PPCFuncMappings},
        {"server_360.dll", l4d2_server_RegisterFunctions, l4d2_server_PPCFuncMappings},
        {"MaterialSystem_360.dll", l4d2_materialsystem_RegisterFunctions, l4d2_materialsystem_PPCFuncMappings},
        {"shaderapidx9_360.dll", l4d2_shaderapidx9_RegisterFunctions, l4d2_shaderapidx9_PPCFuncMappings},
        {"stdshader_dx9_360.dll", l4d2_stdshader_dx9_RegisterFunctions, l4d2_stdshader_dx9_PPCFuncMappings},
        {"StudioRender_360.dll", l4d2_studiorender_RegisterFunctions, l4d2_studiorender_PPCFuncMappings},
        {"vphysics_360.dll", l4d2_vphysics_RegisterFunctions, l4d2_vphysics_PPCFuncMappings},
        {"SoundEmitterSystem_360.dll", l4d2_soundemitter_RegisterFunctions, l4d2_soundemitter_PPCFuncMappings},
        {"datacache_360.dll", l4d2_datacache_RegisterFunctions, l4d2_datacache_PPCFuncMappings},
        {"SceneFileCache_360.dll", l4d2_scenefilecache_RegisterFunctions, l4d2_scenefilecache_PPCFuncMappings},
        {"vgui2_360.dll", l4d2_vgui2_RegisterFunctions, l4d2_vgui2_PPCFuncMappings},
        {"vguimatsurface_360.dll", l4d2_vguimatsurface_RegisterFunctions, l4d2_vguimatsurface_PPCFuncMappings},
        {"inputsystem_360.dll", l4d2_inputsystem_RegisterFunctions, l4d2_inputsystem_PPCFuncMappings},
        {"FileSystem_Stdio_360.dll", l4d2_filesystem_RegisterFunctions, l4d2_filesystem_PPCFuncMappings},
        {"vstdlib_360.dll", l4d2_vstdlib_RegisterFunctions, l4d2_vstdlib_PPCFuncMappings},
        {"tier0_360.dll", l4d2_tier0_RegisterFunctions, l4d2_tier0_PPCFuncMappings},
        {"matchmaking_360.dll", l4d2_matchmaking_RegisterFunctions, l4d2_matchmaking_PPCFuncMappings},
    };

    uint32_t total_bound_anchors = 0;
    for (const auto& b : kBindings) {
        if (b.mappings && b.mappings[0].address != 0) {
            total_bound_anchors++;
        }
    }

    L4D2_LOG_INFO("ModuleLoader", "Initialized Source Engine multi-module dispatcher with %zu modules (%u static recomp anchors)",
                  loaded_modules_.size(), total_bound_anchors);
}

void ModuleLoader::Shutdown() {
    for (auto& mod : loaded_modules_) {
        mod.is_loaded = false;
        mod.create_interface = nullptr;
        mod.named_exports.clear();
        mod.ordinal_exports.clear();
    }
}

std::string ModuleLoader::ResolveVFSPath(const std::string& guest_path, bool write_access) {
    std::string p = guest_path;
    std::replace(p.begin(), p.end(), '\\', '/');

    std::string lower = p;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    // 1. Check for expected retail missing directories (cache:, update:)
    if (lower.rfind("cache:/", 0) == 0 || lower == "cache:" ||
        lower.rfind("update:/", 0) == 0 || lower == "update:") {
        // Return empty so callers get STATUS_NO_SUCH_FILE
        return "";
    }

    // 2. Check for debug monitor vxbdm_360.dll
    if (lower.find("vxbdm_360.dll") != std::string::npos) {
        return "";
    }

    // 3. Writable saves & configs (redirect to sandbox Documents/rex_data)
    if (lower.find("/save/") != std::string::npos || lower.rfind("d:/left4dead2/save", 0) == 0) {
        std::string sub = p.substr(p.find("save/") + 5);
        return save_root_ + "/" + sub;
    }
    if (lower.find("/cfg/") != std::string::npos || lower.rfind("d:/left4dead2/cfg", 0) == 0) {
        std::string sub = p.substr(p.find("cfg/") + 4);
        return cfg_root_ + "/" + sub;
    }

    // 4. Strip game: or d: prefixes
    std::string stripped = p;
    if (lower.rfind("game:/", 0) == 0) {
        stripped = p.substr(6);
    } else if (lower.rfind("d:/", 0) == 0) {
        stripped = p.substr(3);
    }

    return game_root_ + "/" + stripped;
}

uint32_t ModuleLoader::XexLoadImage(const char* module_path, uint32_t flags, uint32_t min_version, void** module_handle) {
    if (!module_path || !module_handle) {
        return STATUS_UNSUCCESSFUL;
    }

    std::string mp(module_path);
    std::replace(mp.begin(), mp.end(), '\\', '/');
    std::string lower = mp;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    // Filter out expected retail missing files
    if (lower.find("vxbdm_360.dll") != std::string::npos ||
        lower.rfind("cache:/", 0) == 0 ||
        lower.rfind("update:/", 0) == 0) {
        L4D2_LOG_DEBUG("ModuleLoader", "Gracefully returning STATUS_NO_SUCH_FILE for retail missing module: %s", module_path);
        *module_handle = nullptr;
        return STATUS_NO_SUCH_FILE;
    }

    // Extract filename from path
    std::string filename = mp;
    size_t last_slash = mp.rfind('/');
    if (last_slash != std::string::npos) {
        filename = mp.substr(last_slash + 1);
    }
    std::string fname_lower = filename;
    std::transform(fname_lower.begin(), fname_lower.end(), fname_lower.begin(), ::tolower);

    auto it = module_index_by_name_.find(fname_lower);
    if (it == module_index_by_name_.end()) {
        // Strip .dll and check again
        if (fname_lower.size() > 4 && fname_lower.substr(fname_lower.size() - 4) == ".dll") {
            it = module_index_by_name_.find(fname_lower.substr(0, fname_lower.size() - 4));
        }
    }

    if (it == module_index_by_name_.end()) {
        L4D2_LOG_WARN("ModuleLoader", "XexLoadImage: Unknown module requested '%s'", module_path);
        *module_handle = nullptr;
        return STATUS_NO_SUCH_FILE;
    }

    LoadedModule& mod = loaded_modules_[it->second];
    mod.is_loaded = true;

    L4D2_LOG_INFO("ModuleLoader", "XexLoadImage: Loaded '%s' mapped at [0x%08X - 0x%08X]",
                  mod.name.c_str(), mod.image_base, mod.image_end);

    *module_handle = reinterpret_cast<void*>(static_cast<uintptr_t>(mod.image_base));
    return STATUS_SUCCESS;
}

void* ModuleLoader::XexGetProcedureAddress(void* module_handle, uint32_t ordinal, const char* name) {
    uint32_t base = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(module_handle));
    const ModuleDescriptor* desc = FindModuleByAddress(base);

    if (!desc) {
        L4D2_LOG_WARN("ModuleLoader", "XexGetProcedureAddress: Invalid module handle 0x%08X", base);
        return nullptr;
    }

    // In Source Engine Xbox 360 DLLs, CreateInterface is ordinal 1 or named "CreateInterface"
    if (ordinal == 1 || (name && strcmp(name, "CreateInterface") == 0)) {
        L4D2_LOG_DEBUG("ModuleLoader", "XexGetProcedureAddress: Resolved 'CreateInterface' for %s", desc->module_name);
        // Returns the guest entrypoint for CreateInterface inside the module
        return reinterpret_cast<void*>(static_cast<uintptr_t>(desc->image_base + 0x1000));
    }

    L4D2_LOG_DEBUG("ModuleLoader", "XexGetProcedureAddress: %s lookup ord=%u name=%s",
                   desc->module_name, ordinal, name ? name : "<null>");
    return nullptr;
}

const ModuleDescriptor* ModuleLoader::FindModuleByAddress(uint32_t guest_pc) const {
    for (const auto& desc : kSourceModules) {
        if (guest_pc >= desc.image_base && guest_pc < desc.image_end) {
            return &desc;
        }
    }
    return nullptr;
}

std::string ModuleLoader::SymbolicateAddress(uint32_t guest_pc) const {
    const ModuleDescriptor* desc = FindModuleByAddress(guest_pc);
    std::stringstream ss;
    if (desc) {
        uint32_t offset = guest_pc - desc->image_base;
        ss << desc->module_name << " + 0x" << std::hex << std::uppercase << offset
           << " (Base: 0x" << desc->image_base << ")";
    } else {
        ss << "0x" << std::hex << std::uppercase << guest_pc << " (Unknown guest region)";
    }
    return ss.str();
}

} // namespace l4d2
