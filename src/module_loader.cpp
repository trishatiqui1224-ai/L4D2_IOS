#include "module_loader.h"
#include "logging/logger.h"

#include <rex/logging.h>
#include <rex/types.h>
#include <rex/image_info.h>
#include <rex/runtime.h>
#include <rex/system/function_dispatcher.h>
#include <rex/system/kernel_state.h>
#include <rex/system/user_module.h>

#include <algorithm>
#include <atomic>
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

    FILE* bf = nullptr;
    const char* bp = std::getenv("L4D2_BOOT_PATH");
    if (!bp) bp = std::getenv("NFSMW_SIGNAL_REPORT");
    if (bp) bf = fopen(bp, "a");
    if (!bf) bf = fopen("boot.txt", "a");
    if (bf) {
        fprintf(bf, "%s\n", buf);
        fflush(bf);
#if !defined(_WIN32)
        fsync(fileno(bf));
#endif
        fclose(bf);
    }
    l4d2::log::Logger::Instance().Flush();
    rex::FlushLogging();
}

extern "C" {
__attribute__((visibility("default"))) std::atomic<uint32_t> g_current_ppc_fn{0};
__attribute__((visibility("default"))) std::atomic<uint32_t> g_current_ppc_lr{0};
__attribute__((visibility("default"))) std::atomic<uint64_t> g_ppc_call_count{0};
__attribute__((visibility("default"))) std::atomic<uint32_t> g_ppc_ring_idx{0};
__attribute__((visibility("default"))) uint32_t g_ppc_call_ring[32] = {0};
__attribute__((visibility("default"))) uint32_t g_ppc_lr_ring[32] = {0};

__attribute__((visibility("default"))) void RecordDispatchBreadcrumb(uint32_t target_addr, uint32_t caller_lr) {
    g_current_ppc_fn.store(target_addr, std::memory_order_relaxed);
    g_current_ppc_lr.store(caller_lr, std::memory_order_relaxed);
    g_ppc_call_count.fetch_add(1, std::memory_order_relaxed);
    uint32_t idx = g_ppc_ring_idx.fetch_add(1, std::memory_order_relaxed) & 31;
    g_ppc_call_ring[idx] = target_addr;
    g_ppc_lr_ring[idx] = caller_lr;
}

__attribute__((visibility("default"))) void DumpDispatchRingBuffer() {
    uint32_t cur_fn = g_current_ppc_fn.load(std::memory_order_relaxed);
    uint32_t cur_lr = g_current_ppc_lr.load(std::memory_order_relaxed);
    uint64_t count  = g_ppc_call_count.load(std::memory_order_relaxed);
    uint32_t head   = g_ppc_ring_idx.load(std::memory_order_relaxed);

    std::string mod_fn = l4d2::ModuleLoader::Instance().SymbolicateAddress(cur_fn);
    std::string mod_lr = l4d2::ModuleLoader::Instance().SymbolicateAddress(cur_lr);

    char buf[1024];
    snprintf(buf, sizeof(buf),
             "[WATCHDOG] Total PPC calls: %llu | Last Target: 0x%08X (%s) | Last LR: 0x%08X (%s)",
             (unsigned long long)count, cur_fn, mod_fn.c_str(), cur_lr, mod_lr.c_str());
    L4D2_LOG_WARN("WATCHDOG", "%s", buf);

    FILE* bf = nullptr;
    const char* bp = std::getenv("L4D2_BOOT_PATH");
    if (!bp) bp = std::getenv("NFSMW_SIGNAL_REPORT");
    if (bp) bf = fopen(bp, "a");
    if (!bf) bf = fopen("boot.txt", "a");
    if (bf) {
        fprintf(bf, "%s\n", buf);
        fprintf(bf, "[WATCHDOG] Ring buffer of last 32 indirect calls (newest to oldest):\n");
        for (uint32_t i = 0; i < 32; ++i) {
            uint32_t ring_idx = (head - 1 - i) & 31;
            uint32_t target = g_ppc_call_ring[ring_idx];
            uint32_t lr = g_ppc_lr_ring[ring_idx];
            if (target != 0) {
                std::string s_t = l4d2::ModuleLoader::Instance().SymbolicateAddress(target);
                std::string s_lr = l4d2::ModuleLoader::Instance().SymbolicateAddress(lr);
                fprintf(bf, "  [%02u] Target: 0x%08X (%s), LR: 0x%08X (%s)\n",
                        i, target, s_t.c_str(), lr, s_lr.c_str());
            }
        }
        fflush(bf);
#if !defined(_WIN32)
        fsync(fileno(bf));
#endif
        fclose(bf);
    }
    l4d2::log::Logger::Instance().Flush();
    rex::FlushLogging();
}
}

extern "C" void SafeDispatchIndirect(PPCContext& ctx, uint8_t* base, uint32_t target_addr, uint32_t caller_lr) {
    RecordDispatchBreadcrumb(target_addr, caller_lr);

    if (__builtin_expect(target_addr == 0, 0)) {
        LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
        ctx.r3.u64 = 0;
        return;
    }

    thread_local uint32_t tls_dispatching_target = 0;
    if (__builtin_expect(tls_dispatching_target == target_addr, 0)) {
        LogUnresolvedIndirectCall(target_addr, caller_lr, ctx.r3.u32);
        ctx.r3.u64 = 0;
        return;
    }

    struct ScopedDispatchTarget {
        uint32_t prev;
        ScopedDispatchTarget(uint32_t t) : prev(tls_dispatching_target) { tls_dispatching_target = t; }
        ~ScopedDispatchTarget() { tls_dispatching_target = prev; }
    } guard(target_addr);

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

// Left 4 Dead 2 default.xex entrypoint (0x82010CB8) calls 0x82010AD0 right after startup
// to verify PAL50 / AVPack video settings. On emulation/iOS, XGetAVPack() returns 0,
// which triggers an error dialog and causes default.xex to invoke XamLoaderTerminateTitle (exit code 1).
// Bypassing this check by returning ctx.r3 = 0 ensures the title proceeds directly to loc_82010D0C
// and initializes the Source Engine DLLs.
extern "C" void sub_82010AD0(PPCContext& ctx, [[maybe_unused]] uint8_t* base) {
    L4D2_LOG_INFO("Kernel", "Bypassing PAL50/AVPack video check in default.xex (0x82010AD0 -> r3 = 0)");
    ctx.r3.u64 = 0;
}

extern "C" void __imp__sub_82010AD0(PPCContext& ctx, uint8_t* base) {
    sub_82010AD0(ctx, base);
}

// 1. tier0_360:0x1E5 (0x82C18D10) - memalloc setter
// lis r11, 0x82C6 (-2100953088); stw r3, 0x49B8(r11); blr
extern "C" void sub_82C18D10(PPCContext& ctx, uint8_t* base) {
    if (__builtin_expect(base != nullptr, 1)) {
        *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C649B8u) = static_cast<uint32_t>(ctx.r3.u32);
    }
}
extern "C" void __imp__sub_82C18D10(PPCContext& ctx, uint8_t* base) {
    sub_82C18D10(ctx, base);
}

// 2. tier0_360:0x24B (0x82C1AAC8) - leaf wrapper to sub_82C1A478
// li r7, 0; b 0x82C1A478
extern "C" void sub_82C1A478(PPCContext& __restrict ctx, uint8_t* base);
extern "C" void sub_82C1AAC8(PPCContext& ctx, uint8_t* base) {
    ctx.r7.s64 = 0;
    sub_82C1A478(ctx, base);
}
extern "C" void __imp__sub_82C1AAC8(PPCContext& ctx, uint8_t* base) {
    sub_82C1AAC8(ctx, base);
}

// 3. vstdlib_360:0x00F (0x82E1BEF0) - memalloc setter / fallback to sub_82E1BF04
// cmpli cr6, 0, r3, 0; beq cr6, 0x82E1BF04; lis r11, 0x82E3 (-2099052544); stw r3, 0x06D0(r11); blr
extern "C" void sub_82E1BF04(PPCContext& __restrict ctx, uint8_t* base);
extern "C" void sub_82E1BEF0(PPCContext& ctx, uint8_t* base) {
    if (ctx.r3.u32 == 0) {
        sub_82E1BF04(ctx, base);
        return;
    }
    if (__builtin_expect(base != nullptr, 1)) {
        *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E306D0u) = static_cast<uint32_t>(ctx.r3.u32);
    }
}
extern "C" void __imp__sub_82E1BEF0(PPCContext& ctx, uint8_t* base) {
    sub_82E1BEF0(ctx, base);
}

// 4. vstdlib_360:0x012 (0x82E1BF50) - vtable dispatch wrapper
// lis r11, 0x82E3; lwz r3, 0x06D0(r11); lwz r10, 0(r3); lwz r9, 12(r10); mtctr r9; bctr
extern "C" void sub_82E1BF50(PPCContext& ctx, uint8_t* base) {
    if (__builtin_expect(base != nullptr, 1)) {
        uint32_t r3_val = rex::byte_swap(*reinterpret_cast<const uint32_t*>(base + 0x82E306D0u));
        uint32_t r10_val = rex::byte_swap(*reinterpret_cast<const uint32_t*>(base + r3_val));
        uint32_t r9_val = rex::byte_swap(*reinterpret_cast<const uint32_t*>(base + r10_val + 12));
        ctx.r3.u64 = r3_val;
        ctx.r10.u64 = r10_val;
        ctx.r9.u64 = r9_val;
        ctx.ctr.u64 = r9_val;
        SafeDispatchIndirect(ctx, base, r9_val, static_cast<uint32_t>(ctx.lr));
    }
}
extern "C" void __imp__sub_82E1BF50(PPCContext& ctx, uint8_t* base) {
    sub_82E1BF50(ctx, base);
}

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

    // 0. Pre-initialize critical cross-DLL variables and default allocator pointers in guest memory
    if (auto* mem = kernel_state->memory()) {
        uint8_t* base = mem->virtual_membase();
        if (base) {
            // tier0_360.dll allocator pointers:
            // 0x82C406CC holds &g_DefaultMemAlloc (0x82C406D0)
            // 0x82C406D0 holds &CStdMemAlloc::vtable (0x82C00BF4)
            // 0x82C00BF4 / 0x82C00BF8 holds CStdMemAlloc::Alloc (0x82C16CD0)
            // 0x82C42EB0 holds fallback allocator function sub_82C13FF0 (0x82C13FF0)
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C406CCu) = 0x82C406D0u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C406D0u) = 0x82C00BF4u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C00BF4u) = 0x82C16CD0u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C00BF8u) = 0x82C16CD0u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82C42EB0u) = 0x82C13FF0u;

            // vstdlib_360.dll cross-DLL variable imports from tier0_360.dll:
            // 0x82E0046C (ord 0xEA, g_pMemAlloc) -> 0x82C406CC
            // 0x82E0047C (ord 0x2EA) -> 0x82C64C3C
            // 0x82E00484 (ord 0x78)  -> 0x82C446D8
            // 0x82E004A4 (ord 0x341) -> 0x82C434AC
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E0046Cu) = 0x82C406CCu;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E0047Cu) = 0x82C64C3Cu;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E00484u) = 0x82C446D8u;
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E004A4u) = 0x82C434ACu;

            // vstdlib_360.dll internal memalloc pointer:
            // 0x82E306D0 holds pointer to IMemAlloc (0x82C406D0)
            *reinterpret_cast<rex::be<uint32_t>*>(base + 0x82E306D0u) = 0x82C406D0u;

            L4D2_LOG_INFO("ModuleLoader", "Pre-initialized tier0/vstdlib allocator pointers and cross-DLL variables");
        }
    }

    // Pre-populate default.xex compiled functions into global table
    if (g_global_func_table && l4d2_default_PPCImageConfig.func_mappings) {
        for (const auto* m = l4d2_default_PPCImageConfig.func_mappings; m && m->host != nullptr; ++m) {
            if (m->guest >= kGlobalFuncTableBase && m->guest < kGlobalFuncTableEnd) {
                g_global_func_table[(m->guest - kGlobalFuncTableBase) >> 2] = m->host;
            }
        }
    }

    // Explicitly override 0x82010AD0 (PAL50 / AVPack video check in default.xex)
    // so default.xex proceeds to CRT initialization and LauncherMain without aborting with exit code 1.
    dispatcher->SetFunction(0x82010AD0, &sub_82010AD0);
    if (g_global_func_table) {
        g_global_func_table[(0x82010AD0 - kGlobalFuncTableBase) >> 2] = &sub_82010AD0;
    }

    // 2. Register all 21 compiled non-entrypoint modules into FunctionDispatcher and global table FIRST
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

    // 3. Register exported leaf functions (tier0_360, vstdlib_360)
    auto register_leaf = [&](uint32_t addr, PPCFunc* fn, const char* name) {
        dispatcher->SetFunction(addr, fn);
        if (g_global_func_table && addr >= kGlobalFuncTableBase && addr < kGlobalFuncTableEnd) {
            g_global_func_table[(addr - kGlobalFuncTableBase) >> 2] = fn;
        }
        L4D2_LOG_INFO("ModuleLoader", "Registered exported leaf function %s at 0x%08X", name, addr);
    };
    register_leaf(0x82C18D10, &sub_82C18D10, "tier0_360:0x1E5 (sub_82C18D10)");
    register_leaf(0x82C1AAC8, &sub_82C1AAC8, "tier0_360:0x24B (sub_82C1AAC8)");
    register_leaf(0x82E1BEF0, &sub_82E1BEF0, "vstdlib_360:0x00F (sub_82E1BEF0)");
    register_leaf(0x82E1BF50, &sub_82E1BF50, "vstdlib_360:0x012 (sub_82E1BF50)");
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
    rex::FlushLogging();

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
