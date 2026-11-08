#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
#include "l4d2_modules.h"

struct PPCContext;
using PPCFunc = void(PPCContext& ctx, uint8_t* base);

using RexDumpRingBufferFn = void (*)();

extern "C" {
__attribute__((visibility("default"))) extern PPCFunc** g_global_func_table;

PPCFunc* LookupGlobalFunction(uint8_t* base, uint32_t guest_addr);
void SafeDispatchIndirect(PPCContext& ctx, uint8_t* base, uint32_t target_addr, uint32_t caller_lr);
void LogUnresolvedIndirectCall(uint32_t target_addr, uint32_t caller_lr, uint32_t r3);
void RecordDispatchBreadcrumb(uint32_t target_addr, uint32_t caller_lr);
void DumpDispatchRingBuffer();

#if defined(__GNUC__) || defined(__clang__)
__attribute__((weak)) void RexRegisterDumpRingBufferCallback(RexDumpRingBufferFn fn);
#else
void RexRegisterDumpRingBufferCallback(RexDumpRingBufferFn fn);
#endif
}

namespace rex::system { class KernelState; }

namespace l4d2 {

// Xbox NT Status Codes
constexpr uint32_t STATUS_SUCCESS        = 0x00000000;
constexpr uint32_t STATUS_NO_SUCH_FILE   = 0xC000000F;
constexpr uint32_t STATUS_UNSUCCESSFUL   = 0xC0000001;

// ReXGlue / Valve CreateInterface export signature
using CreateInterfaceFn = void* (*)(const char* pName, int* pReturnCode);

struct LoadedModule {
    std::string name;
    std::string path;
    uint32_t image_base = 0;
    uint32_t image_end = 0;
    bool is_loaded = false;
    CreateInterfaceFn create_interface = nullptr;
    std::unordered_map<std::string, void*> named_exports;
    std::unordered_map<uint32_t, void*> ordinal_exports;
};

class ModuleLoader {
public:
    static ModuleLoader& Instance();

    // Called from PPCImageInfo::register_modules before the entrypoint XEX is launched.
    static void RegisterRecompiledModules(rex::system::KernelState* kernel_state);

    void Init(const std::string& game_root, const std::string& save_root);
    void Shutdown();

    // Emulated XEX2 module loader
    uint32_t XexLoadImage(const char* module_path, uint32_t flags, uint32_t min_version, void** module_handle);
    void* XexGetProcedureAddress(void* module_handle, uint32_t ordinal, const char* name);

    // VFS path resolver (translates game:\, d:\, SAVE\, etc.)
    std::string ResolveVFSPath(const std::string& guest_path, bool write_access = false);

    // Module boundary lookup for symbolication & crash diagnosis
    const ModuleDescriptor* FindModuleByAddress(uint32_t guest_pc) const;
    std::string SymbolicateAddress(uint32_t guest_pc) const;

    const std::vector<LoadedModule>& GetLoadedModules() const { return loaded_modules_; }

private:
    ModuleLoader() = default;

    std::string game_root_;
    std::string save_root_;
    std::string cfg_root_;
    std::vector<LoadedModule> loaded_modules_;
    std::unordered_map<std::string, size_t> module_index_by_name_;
};

} // namespace l4d2

