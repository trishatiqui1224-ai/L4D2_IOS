#include "module_loader.h"
#include "logging/logger.h"

#include <rex/image_info.h>
#include <rex/runtime.h>
#include <rex/system/function_dispatcher.h>
#include <rex/system/kernel_state.h>
#include <rex/system/user_module.h>

#include <algorithm>
#include <filesystem>
#include <iomanip>
#include <sstream>

#if defined(_WIN32)
#include <windows.h>
#else
#include <sys/mman.h>
#include <unistd.h>
#endif

constexpr uint32_t kGlobalFuncTableBase = 0x82000000u;
constexpr uint32_t kGlobalFuncTableEnd  = 0x90000000u;
constexpr size_t   kGlobalFuncTableEntries = (kGlobalFuncTableEnd - kGlobalFuncTableBase) >> 2;
constexpr size_t   kGlobalFuncTableBytes = kGlobalFuncTableEntries * sizeof(PPCFunc*);

// g_global_func_table is defined in function_dispatcher.cpp

static void InitializeGlobalFunctionTable() {
    if (g_global_func_table != nullptr) {
        return;
    }
#if defined(_WIN32)
    g_global_func_table = static_cast<PPCFunc**>(
        VirtualAlloc(nullptr, kGlobalFuncTableBytes, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
#else
    void* ptr = mmap(nullptr, kGlobalFuncTableBytes, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    if (ptr != MAP_FAILED) {
        g_global_func_table = static_cast<PPCFunc**>(ptr);
    }
#endif
    if (g_global_func_table) {
        L4D2_LOG_INFO("ModuleLoader", "Allocated unified global function table: %zu MB (0x%08X..0x%08X)",
                      kGlobalFuncTableBytes / (1024 * 1024), kGlobalFuncTableBase, kGlobalFuncTableEnd);
    } else {
        L4D2_LOG_ERROR("ModuleLoader", "Failed to allocate unified global function table");
    }
}

extern "C" PPCFunc* LookupGlobalFunction(uint8_t* base, uint32_t guest_addr) {
    if (__builtin_expect(guest_addr >= kGlobalFuncTableBase && guest_addr < kGlobalFuncTableEnd, 1)) {
        if (g_global_func_table) {
            PPCFunc* fn = g_global_func_table[(guest_addr - kGlobalFuncTableBase) >> 2];
            if (fn) return fn;
        }
    }
    return nullptr;
}

extern "C" void LogUnresolvedIndirectCall(uint32_t target_addr, uint32_t caller_lr, uint32_t r3) {
    std::string mod_target = l4d2::ModuleLoader::Instance().SymbolicateAddress(target_addr);
    std::string mod_caller = l4d2::ModuleLoader::Instance().SymbolicateAddress(caller_lr);

    char buf[512];
    snprintf(buf, sizeof(buf),
             "[UNRESOLVED INDIRECT CALL] Target: 0x%08X (%s), Caller LR: 0x%08X (%s), r3: 0x%08X",
             target_addr, mod_target.c_str(), caller_lr, mod_caller.c_str(), r3);

    L4D2_LOG_ERROR("CRASH", "%s", buf);

    FILE* bf = fopen("boot.txt", "a");
    if (!bf) {
        const char* bp = std::getenv("L4D2_BOOT_PATH");
        if (bp) bf = fopen(bp, "a");
    }
    if (bf) {
        fprintf(bf, "%s\n", buf);
        fflush(bf);
#if !defined(_WIN32)
        fsync(fileno(bf));
#endif
        fclose(bf);
    }
    l4d2::log::Logger::Instance().Flush();
}

extern "C" void SafeDispatchIndirect(PPCContext& ctx, uint8_t* base, uint32_t target_addr, uint32_t caller_lr) {
    if (__builtin_expect(target_addr == 0, 0)) {
        LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
        ctx.r3.u64 = 0;
        return;
    }

    PPCFunc* fn = LookupGlobalFunction(base, target_addr);
    if (__builtin_expect(fn != nullptr, 1)) {
        fn(ctx, base);
        return;
    }

    // Try fallback in runtime FunctionDispatcher if not yet cached in global table
    rex::runtime::FunctionDispatcher* dispatcher = nullptr;
    if (auto* runtime = rex::Runtime::instance()) {
        dispatcher = runtime->function_dispatcher();
    }
    if (dispatcher) {
        fn = dispatcher->GetFunction(target_addr);
        if (fn) {
            if (g_global_func_table && target_addr >= kGlobalFuncTableBase && target_addr < kGlobalFuncTableEnd) {
                g_global_func_table[(target_addr - kGlobalFuncTableBase) >> 2] = fn;
            }
            fn(ctx, base);
            return;
        }
    }

    LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
    ctx.r3.u64 = 0;
}

namespace rex::runtime { class IModuleRegistrar; }

#define DECLARE_MODULE_SYMBOLS(name) \
    void l4d2_##name##_RegisterFunctions(rex::runtime::IModuleRegistrar*); \
    extern const rex::PPCImageInfo l4d2_##name##_PPCImageConfig;

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
DECLARE_MODULE_SYMBOLS(launcher)
DECLARE_MODULE_SYMBOLS(gameui)
DECLARE_MODULE_SYMBOLS(vscript)
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

    L4D2_LOG_INFO("ModuleLoader", "Initialized Source Engine module index with %zu modules", loaded_modules_.size());
}

void ModuleLoader::RegisterRecompiledModules(rex::system::KernelState* kernel_state) {
    if (!kernel_state) {
        L4D2_LOG_ERROR("ModuleLoader", "Cannot register recompiled modules: KernelState is null");
        return;
    }
    auto* dispatcher = kernel_state->function_dispatcher();
    if (!dispatcher) {
        L4D2_LOG_ERROR("ModuleLoader", "Cannot register recompiled modules: FunctionDispatcher is null");
        return;
    }

    // 1. Initialize unified global function table (448 MB virtual memory covering 0x82000000..0x90000000)
    InitializeGlobalFunctionTable();

    // Pre-populate default.xex compiled functions into global table
    if (g_global_func_table && l4d2_default_PPCImageConfig.func_mappings) {
        for (const auto* m = l4d2_default_PPCImageConfig.func_mappings; m && m->host != nullptr; ++m) {
            if (m->guest >= kGlobalFuncTableBase && m->guest < kGlobalFuncTableEnd) {
                g_global_func_table[(m->guest - kGlobalFuncTableBase) >> 2] = m->host;
            }
        }
    }

    // 2. Pre-load all non-entrypoint DLL XEX2 sections into guest RAM before default.xex runs.
    // Loads tier0, vstdlib, filesystem and launcher first, so dependencies exist in guest memory.
    for (const auto& desc : kSourceModules) {
        if (strcmp(desc.module_name, "default") == 0) continue;
        L4D2_LOG_INFO("ModuleLoader", "Pre-loading module XEX2 sections into guest RAM: %s", desc.relative_path);
        auto mod = kernel_state->LoadUserModule(desc.relative_path, /*call_entry=*/false);
        if (mod) {
            L4D2_LOG_INFO("ModuleLoader", "Pre-loaded '%s' [0x%08X..0x%08X]",
                          desc.module_name, desc.image_base, desc.image_end);
        } else {
            L4D2_LOG_WARN("ModuleLoader", "Could not pre-load %s (will load on demand if requested)", desc.relative_path);
        }
    }

    struct RecompModuleBinding {
        const char* module_id;
        const rex::PPCImageInfo* image;
        rex::runtime::FunctionDispatcher::RegisterFn register_fn;
    };

    // Organized in dependency order: tier0, vstdlib, filesystem, launcher first
    static const RecompModuleBinding kBindings[] = {
        {"tier0_360.dll", &l4d2_tier0_PPCImageConfig, l4d2_tier0_RegisterFunctions},
        {"vstdlib_360.dll", &l4d2_vstdlib_PPCImageConfig, l4d2_vstdlib_RegisterFunctions},
        {"FileSystem_Stdio_360.dll", &l4d2_filesystem_PPCImageConfig, l4d2_filesystem_RegisterFunctions},
        {"launcher_360.dll", &l4d2_launcher_PPCImageConfig, l4d2_launcher_RegisterFunctions},
        {"datacache_360.dll", &l4d2_datacache_PPCImageConfig, l4d2_datacache_RegisterFunctions},
        {"vphysics_360.dll", &l4d2_vphysics_PPCImageConfig, l4d2_vphysics_RegisterFunctions},
        {"MaterialSystem_360.dll", &l4d2_materialsystem_PPCImageConfig, l4d2_materialsystem_RegisterFunctions},
        {"shaderapidx9_360.dll", &l4d2_shaderapidx9_PPCImageConfig, l4d2_shaderapidx9_RegisterFunctions},
        {"stdshader_dx9_360.dll", &l4d2_stdshader_dx9_PPCImageConfig, l4d2_stdshader_dx9_RegisterFunctions},
        {"StudioRender_360.dll", &l4d2_studiorender_PPCImageConfig, l4d2_studiorender_RegisterFunctions},
        {"SoundEmitterSystem_360.dll", &l4d2_soundemitter_PPCImageConfig, l4d2_soundemitter_RegisterFunctions},
        {"SceneFileCache_360.dll", &l4d2_scenefilecache_PPCImageConfig, l4d2_scenefilecache_RegisterFunctions},
        {"vgui2_360.dll", &l4d2_vgui2_PPCImageConfig, l4d2_vgui2_RegisterFunctions},
        {"vguimatsurface_360.dll", &l4d2_vguimatsurface_PPCImageConfig, l4d2_vguimatsurface_RegisterFunctions},
        {"inputsystem_360.dll", &l4d2_inputsystem_PPCImageConfig, l4d2_inputsystem_RegisterFunctions},
        {"vscript_360.dll", &l4d2_vscript_PPCImageConfig, l4d2_vscript_RegisterFunctions},
        {"GameUI_360.dll", &l4d2_gameui_PPCImageConfig, l4d2_gameui_RegisterFunctions},
        {"engine_360.dll", &l4d2_engine_PPCImageConfig, l4d2_engine_RegisterFunctions},
        {"client_360.dll", &l4d2_client_PPCImageConfig, l4d2_client_RegisterFunctions},
        {"server_360.dll", &l4d2_server_PPCImageConfig, l4d2_server_RegisterFunctions},
        {"matchmaking_360.dll", &l4d2_matchmaking_PPCImageConfig, l4d2_matchmaking_RegisterFunctions},
    };

    uint32_t registered = 0;
    for (const auto& binding : kBindings) {
        const auto& image = *binding.image;
        if (!dispatcher->InitializeFunctionTable(image.code_base, image.code_size,
                                                 image.image_base, image.image_size)) {
            L4D2_LOG_ERROR("ModuleLoader", "Failed to initialize function table for %s (code=%08X image=%08X)",
                           binding.module_id, image.code_base, image.image_base);
            continue;
        }

        // Populate unified global function table directly from func_mappings
        if (g_global_func_table && image.func_mappings) {
            for (const auto* m = image.func_mappings; m && m->host != nullptr; ++m) {
                if (m->guest >= kGlobalFuncTableBase && m->guest < kGlobalFuncTableEnd) {
                    g_global_func_table[(m->guest - kGlobalFuncTableBase) >> 2] = m->host;
                }
            }
        }

        dispatcher->RegisterModule(binding.module_id, image.code_base, binding.register_fn);
        ++registered;
        L4D2_LOG_INFO("ModuleLoader", "Registered compiled functions for %s: code=%08X-%08X image=%08X+%08X",
                      binding.module_id, image.code_base, image.code_base + image.code_size,
                      image.image_base, image.image_size);
    }
    L4D2_LOG_INFO("ModuleLoader", "Registered %u compiled non-entrypoint modules into unified function table", registered);
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
