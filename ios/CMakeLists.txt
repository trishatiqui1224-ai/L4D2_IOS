# =============================================================================
#  Left 4 Dead 2 Native Recompilation - iOS App (ARM64, iOS 16.0+)
# =============================================================================

cmake_minimum_required(VERSION 3.25)

if(NOT CMAKE_SYSTEM_NAME)
    set(CMAKE_SYSTEM_NAME "iOS")
endif()
if(NOT CMAKE_SYSTEM_PROCESSOR)
    set(CMAKE_SYSTEM_PROCESSOR "arm64")
endif()
if(NOT CMAKE_OSX_ARCHITECTURES)
    set(CMAKE_OSX_ARCHITECTURES "arm64")
endif()
if(NOT CMAKE_OSX_SYSROOT)
    set(CMAKE_OSX_SYSROOT "iphoneos")
endif()
if(NOT CMAKE_OSX_DEPLOYMENT_TARGET)
    set(CMAKE_OSX_DEPLOYMENT_TARGET "16.4")
endif()

project(l4d2recomp_ios LANGUAGES C CXX OBJC OBJCXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_BUILD_WITH_INSTALL_RPATH ON)
set(CMAKE_INSTALL_RPATH "@executable_path/Frameworks")

set(L4D2_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(L4D2_SRC "${L4D2_ROOT}/src")
set(L4D2_SDK "${L4D2_ROOT}/../rexglue-sdk-ios" CACHE PATH "ReXGlue SDK for iOS")
set(L4D2_GEN_DIR "${L4D2_ROOT}/generated")

# =============================================================================
# 1. STRICT REQUIREMENT: No stub / optional-codegen fallbacks allowed!
# =============================================================================
if(NOT EXISTS "${L4D2_SDK}/CMakeLists.txt")
    message(FATAL_ERROR "Missing recompiled C++ sources or runtime frameworks! rexglue-sdk-ios not found at ${L4D2_SDK}")
endif()

# Locate MoltenVK.framework
set(_mvk_candidates
    "${L4D2_SDK}/.nfsc-ios/MoltenVK/v1.4.1/ios-arm64/MoltenVK.framework"
    "${L4D2_SDK}/.nfsmw-ios/MoltenVK/v1.4.1/ios-arm64/MoltenVK.framework"
    "${L4D2_SDK}/.nfsc-ios/MoltenVK/ios-arm64/MoltenVK.framework"
    "${L4D2_SDK}/.nfsmw-ios/MoltenVK/ios-arm64/MoltenVK.framework"
    "${L4D2_SDK}/MoltenVK.framework"
    "${L4D2_ROOT}/Frameworks/MoltenVK.framework"
)
set(L4D2_MOLTENVK_FW "")
foreach(c ${_mvk_candidates})
    if(EXISTS "${c}/MoltenVK")
        set(L4D2_MOLTENVK_FW "${c}")
        break()
    endif()
endforeach()
if(NOT L4D2_MOLTENVK_FW)
    set(_mvk_marker "${L4D2_SDK}/.nfsc-ios/MoltenVK/v1.4.1.ready")
    if(EXISTS "${_mvk_marker}")
        file(STRINGS "${_mvk_marker}" _mvk_rel LIMIT_COUNT 1)
        if(EXISTS "${L4D2_SDK}/.nfsc-ios/MoltenVK/${_mvk_rel}/ios-arm64/MoltenVK.framework/MoltenVK")
            set(L4D2_MOLTENVK_FW "${L4D2_SDK}/.nfsc-ios/MoltenVK/${_mvk_rel}/ios-arm64/MoltenVK.framework")
        endif()
    endif()
endif()
if(NOT L4D2_MOLTENVK_FW)
    message(FATAL_ERROR "Missing recompiled C++ sources or runtime frameworks! MoltenVK.framework not found in SDK or project.")
endif()
message(STATUS "L4D2: Found MoltenVK.framework at ${L4D2_MOLTENVK_FW}")

# Add ReXGlue SDK
set(REXGLUE_ENABLE_TRACY OFF CACHE BOOL "" FORCE)
set(REXGLUE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(REXGLUE_USE_VULKAN ON CACHE BOOL "" FORCE)
set(REXGLUE_USE_D3D12 OFF CACHE BOOL "" FORCE)
set(REXGLUE_ENABLE_DESKTOP_SDL_BACKENDS OFF CACHE BOOL "" FORCE)

add_subdirectory("${L4D2_SDK}" rexglue-sdk)

# =============================================================================
# 1.5. Common ReXGlue & Thirdparty Header Configuration
# =============================================================================
add_library(l4d2_headers INTERFACE)
target_include_directories(l4d2_headers INTERFACE
    "${L4D2_ROOT}"
    "${L4D2_SRC}"
    "${L4D2_GEN_DIR}"
    "${L4D2_SDK}/include"
    "${L4D2_SDK}/src"
    "${L4D2_SDK}/thirdparty"
    "${L4D2_SDK}/thirdparty/fmt/include"
    "${L4D2_SDK}/thirdparty/spdlog/include"
    "${L4D2_SDK}/thirdparty/xxHash"
    "${L4D2_SDK}/thirdparty/simde"
    "${L4D2_SDK}/thirdparty/vulkan-headers/include"
    "${L4D2_SDK}/thirdparty/vulkan-memory-allocator/include"
    "${L4D2_SDK}/thirdparty/tomlplusplus/include"
    "${L4D2_SDK}/thirdparty/utfcpp/source"
)

if(TARGET fmt::fmt)
    target_link_libraries(l4d2_headers INTERFACE fmt::fmt)
elseif(TARGET fmt)
    target_link_libraries(l4d2_headers INTERFACE fmt)
endif()

if(TARGET spdlog::spdlog)
    target_link_libraries(l4d2_headers INTERFACE spdlog::spdlog)
elseif(TARGET spdlog)
    target_link_libraries(l4d2_headers INTERFACE spdlog)
endif()

if(TARGET Vulkan::Headers)
    target_link_libraries(l4d2_headers INTERFACE Vulkan::Headers)
endif()

if(TARGET GPUOpen::VulkanMemoryAllocator)
    target_link_libraries(l4d2_headers INTERFACE GPUOpen::VulkanMemoryAllocator)
endif()

if(TARGET spirv-tools-headers)
    target_link_libraries(l4d2_headers INTERFACE spirv-tools-headers)
endif()

if(TARGET rex::runtime)
    target_link_libraries(l4d2_headers INTERFACE rex::runtime)
elseif(TARGET rexruntime)
    target_link_libraries(l4d2_headers INTERFACE rexruntime)
endif()

# =============================================================================
# 2. Build All 19 Static Recompilation Module Libraries
# =============================================================================
set(L4D2_MODULE_SPECS
    "default:default:default"
    "engine_360:engine_360:engine"
    "client_360:client_360:client"
    "server_360:server_360:server"
    "materialsystem_360:MaterialSystem_360:materialsystem"
    "shaderapidx9_360:shaderapidx9_360:shaderapidx9"
    "stdshader_dx9_360:stdshader_dx9_360:stdshader_dx9"
    "studiorender_360:StudioRender_360:studiorender"
    "vphysics_360:vphysics_360:vphysics"
    "soundemittersystem_360:SoundEmitterSystem_360:soundemitter"
    "datacache_360:datacache_360:datacache"
    "scenefilecache_360:SceneFileCache_360:scenefilecache"
    "vgui2_360:vgui2_360:vgui2"
    "vguimatsurface_360:vguimatsurface_360:vguimatsurface"
    "inputsystem_360:inputsystem_360:inputsystem"
    "filesystem_stdio_360:FileSystem_Stdio_360:filesystem"
    "vstdlib_360:vstdlib_360:vstdlib"
    "tier0_360:tier0_360:tier0"
    "matchmaking_360:matchmaking_360:matchmaking"
)

set(RECOMP_LIBS "")
set(FORCE_LOAD_FLAGS "")

foreach(spec ${L4D2_MODULE_SPECS})
    string(REPLACE ":" ";" spec_list ${spec})
    list(GET spec_list 0 mod_target)
    list(GET spec_list 1 mod_dir_name)
    list(GET spec_list 2 mod_prefix)

    set(_mod_dir "${L4D2_GEN_DIR}/${mod_dir_name}")
    if(NOT EXISTS "${_mod_dir}")
        set(_mod_dir "${L4D2_GEN_DIR}/${mod_target}")
    endif()

    set(_mod_sources "${_mod_dir}/sources.cmake")
    if(NOT EXISTS "${_mod_sources}")
        message(FATAL_ERROR "Missing recompiled C++ sources or runtime frameworks! Module ${_mod_sources} does not exist.")
    endif()
    include("${_mod_sources}")
    if(NOT GENERATED_SOURCES)
        message(FATAL_ERROR "Missing recompiled C++ sources or runtime frameworks! GENERATED_SOURCES is empty in ${_mod_sources}.")
    endif()

    set(_target "l4d2_${mod_target}_recomp")
    add_library(${_target} STATIC ${GENERATED_SOURCES})
    target_include_directories(${_target} PRIVATE
        "${_mod_dir}"
        "${L4D2_SDK}/thirdparty/fmt/include"
        "${L4D2_SDK}/thirdparty/spdlog/include"
        "${L4D2_SDK}/thirdparty/xxHash"
        "${L4D2_SDK}/thirdparty/simde"
        "${L4D2_SDK}/thirdparty/vulkan-headers/include"
        "${L4D2_SDK}/thirdparty/vulkan-memory-allocator/include"
        "${L4D2_SDK}/thirdparty/tomlplusplus/include"
        "${L4D2_SDK}/thirdparty/utfcpp/source"
    )
    target_link_libraries(${_target} PUBLIC l4d2_headers)
    if(TARGET rex::runtime)
        target_link_libraries(${_target} PUBLIC rex::runtime)
    elseif(TARGET rexruntime)
        target_link_libraries(${_target} PUBLIC rexruntime)
    endif()

    target_compile_definitions(${_target} PRIVATE
        REX_PLATFORM_IOS=1
        __APPLE__=1
        _LIBCPP_DISABLE_AVAILABILITY=1
    )
    target_compile_options(${_target} PRIVATE -gline-tables-only -Wno-unused-variable -O2)

    # Function registration tables compile much faster and use less RAM at -O1
    if(EXISTS "${_mod_dir}/l4d2_${mod_prefix}_register.cpp")
        set_source_files_properties("${_mod_dir}/l4d2_${mod_prefix}_register.cpp"
            PROPERTIES COMPILE_OPTIONS "-O1")
    endif()

    list(APPEND RECOMP_LIBS ${_target})
    list(APPEND FORCE_LOAD_FLAGS "-Wl,-force_load,$<TARGET_FILE:${_target}>")
endforeach()

# =============================================================================
# =============================================================================
# 3. Target 1: Pure Minimal UIKit Launcher (Zero Custom LC_LOAD_DYLIBs)
# =============================================================================
set(L4D2_LAUNCHER_SOURCES
    src/ios_main.mm
    src/boot_trace.mm
    src/launcher.mm
    src/touch_controls.mm
    src/ingame_options.mm
    ${L4D2_SRC}/logging/logger.cpp
)

add_executable(L4D2Recomp MACOSX_BUNDLE ${L4D2_LAUNCHER_SOURCES})

set_target_properties(L4D2Recomp PROPERTIES
    OUTPUT_NAME "L4D2Recomp"
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_BINARY_DIR}/Info.plist"
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "@executable_path/Frameworks"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${CMAKE_CURRENT_SOURCE_DIR}/l4d2recomp.entitlements"
    XCODE_ATTRIBUTE_CODE_SIGNING_ALLOWED "NO"
    XCODE_ATTRIBUTE_CODE_SIGNING_REQUIRED "NO"
)

target_compile_options(L4D2Recomp PRIVATE
    $<$<COMPILE_LANGUAGE:OBJCXX>:-fobjc-arc>
    $<$<CXX_COMPILER_ID:Clang,AppleClang>:-gline-tables-only>
)

target_include_directories(L4D2Recomp PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${L4D2_SRC}"
    "${L4D2_ROOT}"
)

target_compile_definitions(L4D2Recomp PRIVATE
    REX_PLATFORM_IOS=1
    __APPLE__=1
    _LIBCPP_DISABLE_AVAILABILITY=1
    TITLE_ID="454108D4"
)

# Pure UIKit Launcher links ONLY Apple system frameworks! ZERO custom @rpath load-time dependencies!
target_link_libraries(L4D2Recomp PRIVATE
    "-framework UIKit"
    "-framework Foundation"
    "-framework QuartzCore"
    "-framework Metal"
    "-framework AVFAudio"
    "-framework AudioToolbox"
    "-framework GameController"
    "-framework CoreHaptics"
    "-framework UniformTypeIdentifiers"
    z
)

# =============================================================================
# 4. Target 2: L4D2Game Dynamic Framework (Stage-2 Recomp Runtime)
# =============================================================================
set(L4D2_GAME_SOURCES
    src/game_entry.mm
    src/boot_trace.mm
    src/touch_controls.mm
    src/ingame_options.mm
    src/audio/coreaudio_driver.mm
    ${L4D2_SRC}/logging/logger.cpp
    ${L4D2_SRC}/crash_handler.cpp
    ${L4D2_SRC}/module_loader.cpp
    ${L4D2_SRC}/resolution_hooks.cpp
    ${L4D2_SRC}/guest_stubs.cpp
)

add_library(L4D2Game SHARED ${L4D2_GAME_SOURCES})

set_target_properties(L4D2Game PROPERTIES
    OUTPUT_NAME "L4D2Game"
    PREFIX ""
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "@executable_path/Frameworks;@loader_path;@loader_path/.."
    INSTALL_NAME_DIR "@rpath/L4D2Game.framework"
)

target_link_options(L4D2Game PRIVATE
    "-Wl,-undefined,dynamic_lookup"
)

target_compile_options(L4D2Game PRIVATE
    $<$<COMPILE_LANGUAGE:OBJCXX>:-fobjc-arc>
    $<$<CXX_COMPILER_ID:Clang,AppleClang>:-gline-tables-only>
)

target_include_directories(L4D2Game PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${L4D2_SRC}"
    "${L4D2_ROOT}"
    "${L4D2_GEN_DIR}"
    "${L4D2_SDK}/include"
    "${L4D2_SDK}/src"
    "${L4D2_SDK}/thirdparty/fmt/include"
    "${L4D2_SDK}/thirdparty/spdlog/include"
    "${L4D2_SDK}/thirdparty/xxHash"
    "${L4D2_SDK}/thirdparty/simde"
    "${L4D2_SDK}/thirdparty/vulkan-headers/include"
    "${L4D2_SDK}/thirdparty/vulkan-memory-allocator/include"
    "${L4D2_SDK}/thirdparty/tomlplusplus/include"
    "${L4D2_SDK}/thirdparty/utfcpp/source"
)

target_compile_definitions(L4D2Game PRIVATE
    REX_PLATFORM_IOS=1
    __APPLE__=1
    _LIBCPP_DISABLE_AVAILABILITY=1
    TITLE_ID="454108D4"
)

target_link_libraries(L4D2Game PRIVATE
    l4d2_headers
    ${FORCE_LOAD_FLAGS}
    ${RECOMP_LIBS}
    "-framework UIKit"
    "-framework Foundation"
    "-framework Metal"
    "-framework AudioToolbox"
    "-framework AVFoundation"
    "-framework GameController"
    "-framework CoreHaptics"
    "-framework QuartzCore"
    "-framework UniformTypeIdentifiers"
    z
)

if(TARGET rex::runtime)
    target_link_libraries(L4D2Game PRIVATE rex::runtime)
elseif(TARGET rexruntime)
    target_link_libraries(L4D2Game PRIVATE rexruntime)
endif()

if(TARGET rexgpu-xenos)
    add_dependencies(L4D2Game rexgpu-xenos)
endif()

# App Bundle Properties
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
    "${CMAKE_CURRENT_BINARY_DIR}/Info.plist"
    @ONLY
)

# =============================================================================
# 5. Stage Dereferenced Frameworks & Ad-Hoc Sign
# =============================================================================
set(_app "$<TARGET_BUNDLE_DIR:L4D2Recomp>")
set(_fw "${_app}/Frameworks")
set(_game_fw "${_fw}/L4D2Game.framework")

if(TARGET rexruntime)
    set(_copy_rexruntime COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:rexruntime>" "${_fw}/")
    set(_sign_rexruntime COMMAND codesign --force --sign - --timestamp=none "${_fw}/$<TARGET_FILE_NAME:rexruntime>" || true)
    set(_dep_rexruntime rexruntime)
else()
    set(_copy_rexruntime COMMAND ${CMAKE_COMMAND} -E true)
    set(_sign_rexruntime COMMAND ${CMAKE_COMMAND} -E true)
    set(_dep_rexruntime "")
endif()

if(TARGET rexgpu-xenos)
    set(_copy_rexgpu COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:rexgpu-xenos>" "${_fw}/")
    set(_sign_rexgpu COMMAND codesign --force --sign - --timestamp=none "${_fw}/$<TARGET_FILE_NAME:rexgpu-xenos>" || true)
    set(_dep_rexgpu rexgpu-xenos)
else()
    set(_copy_rexgpu COMMAND ${CMAKE_COMMAND} -E true)
    set(_sign_rexgpu COMMAND ${CMAKE_COMMAND} -E true)
    set(_dep_rexgpu "")
endif()

add_custom_target(l4d2_stage_frameworks ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${_fw}"
    COMMAND ${CMAKE_COMMAND} -E make_directory "${_game_fw}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:L4D2Game>" "${_game_fw}/L4D2Game"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "${CMAKE_CURRENT_SOURCE_DIR}/framework_Info.plist" "${_game_fw}/Info.plist"
    ${_copy_rexruntime}
    ${_copy_rexgpu}
    COMMAND cp -RL "${L4D2_MOLTENVK_FW}" "${_fw}/MoltenVK.framework"
    COMMAND codesign --force --sign - --timestamp=none "${_game_fw}" || true
    ${_sign_rexruntime}
    ${_sign_rexgpu}
    COMMAND codesign --force --sign - --timestamp=none "${_fw}/MoltenVK.framework" || true
    COMMAND codesign --force --sign - --timestamp=none "${_app}" || true
    DEPENDS L4D2Recomp L4D2Game ${_dep_rexruntime} ${_dep_rexgpu}
    COMMENT "Staging real dereferenced MoltenVK, rexruntime, rexgpu-xenos, and L4D2Game.framework..."
    VERBATIM
)

# Custom target for .ipa packaging
add_custom_target(l4d2recomp_package
    COMMAND python3 "${L4D2_ROOT}/tools/package_ipa.py" --app "$<TARGET_BUNDLE_DIR:L4D2Recomp>" --out "${CMAKE_BINARY_DIR}/L4D2Recomp.ipa"
    DEPENDS L4D2Recomp L4D2Game l4d2_stage_frameworks
    COMMENT "Packaging L4D2 Recomp .ipa..."
)
