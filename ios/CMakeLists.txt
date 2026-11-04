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

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

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
        break
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
# 2. Build All 19 Static Recompilation Module Libraries
# =============================================================================
set(L4D2_MODULE_NAMES
    default
    engine_360
    client_360
    server_360
    materialsystem_360
    shaderapidx9_360
    stdshader_dx9_360
    studiorender_360
    vphysics_360
    soundemittersystem_360
    datacache_360
    scenefilecache_360
    vgui2_360
    vguimatsurface_360
    inputsystem_360
    filesystem_stdio_360
    vstdlib_360
    tier0_360
    matchmaking_360
)

set(RECOMP_LIBS "")
set(FORCE_LOAD_FLAGS "")

foreach(mod ${L4D2_MODULE_NAMES})
    set(_mod_dir "${L4D2_GEN_DIR}/${mod}")
    set(_mod_sources "${_mod_dir}/sources.cmake")
    if(NOT EXISTS "${_mod_sources}")
        message(FATAL_ERROR "Missing recompiled C++ sources or runtime frameworks! Module ${_mod_sources} does not exist.")
    endif()
    include("${_mod_sources}")
    if(NOT GENERATED_SOURCES)
        message(FATAL_ERROR "Missing recompiled C++ sources or runtime frameworks! GENERATED_SOURCES is empty in ${_mod_sources}.")
    endif()

    set(_target "l4d2_${mod}_recomp")
    add_library(${_target} STATIC ${GENERATED_SOURCES})
    target_include_directories(${_target} PRIVATE
        "${_mod_dir}"
        "${L4D2_GEN_DIR}"
        "${L4D2_ROOT}"
        "${L4D2_SRC}"
        "${L4D2_SDK}/include"
        "${L4D2_SDK}/src"
    )
    target_compile_definitions(${_target} PRIVATE
        REX_PLATFORM_IOS=1
        __APPLE__=1
        _LIBCPP_DISABLE_AVAILABILITY=1
    )
    target_compile_options(${_target} PRIVATE -gline-tables-only -Wno-unused-variable -O2)
    list(APPEND RECOMP_LIBS ${_target})
    list(APPEND FORCE_LOAD_FLAGS "-Wl,-force_load,$<TARGET_FILE:${_target}>")
endforeach()

# =============================================================================
# 3. Main Executable Bundle Target
# =============================================================================
set(L4D2_IOS_SOURCES
    src/ios_main.mm
    src/launcher.mm
    src/touch_controls.mm
    src/ingame_options.mm
    src/audio/coreaudio_driver.mm
    ${L4D2_SRC}/logging/logger.cpp
    ${L4D2_SRC}/module_loader.cpp
    ${L4D2_SRC}/resolution_hooks.cpp
    ${L4D2_SRC}/crash_handler.cpp
)

add_executable(L4D2Recomp MACOSX_BUNDLE ${L4D2_IOS_SOURCES})

set_target_properties(L4D2Recomp PROPERTIES
    OUTPUT_NAME "L4D2Recomp"
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_BINARY_DIR}/Info.plist"
    INSTALL_RPATH "@executable_path/Frameworks"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${CMAKE_CURRENT_SOURCE_DIR}/l4d2recomp.entitlements"
    XCODE_ATTRIBUTE_CODE_SIGNING_ALLOWED "NO"
    XCODE_ATTRIBUTE_CODE_SIGNING_REQUIRED "NO"
)

target_include_directories(L4D2Recomp PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${L4D2_SRC}"
    "${L4D2_ROOT}"
    "${L4D2_GEN_DIR}"
    "${L4D2_SDK}/include"
    "${L4D2_SDK}/src"
)

target_compile_definitions(L4D2Recomp PRIVATE
    REX_PLATFORM_IOS=1
    __APPLE__=1
    _LIBCPP_DISABLE_AVAILABILITY=1
    TITLE_ID="454108D4"
)

# Apple ld64 force-loads every static recompilation library to prevent dead-stripping
target_link_libraries(L4D2Recomp PRIVATE
    ${FORCE_LOAD_FLAGS}
    ${RECOMP_LIBS}
    rexruntime
    rexgpu-xenos
    "-framework UIKit"
    "-framework Foundation"
    "-framework AudioToolbox"
    "-framework AVFoundation"
    "-framework GameController"
    "-framework Metal"
    "-framework QuartzCore"
    "-framework UniformTypeIdentifiers"
    z
)

# App Bundle Properties
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
    "${CMAKE_CURRENT_BINARY_DIR}/Info.plist"
    @ONLY
)

# =============================================================================
# 4. Stage Dereferenced Frameworks & Ad-Hoc Sign
# =============================================================================
set(_app "$<TARGET_BUNDLE_DIR:L4D2Recomp>")
set(_fw "${_app}/Frameworks")

add_custom_target(l4d2_stage_frameworks ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory "${_fw}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:rexruntime>" "${_fw}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:rexgpu-xenos>" "${_fw}/"
    COMMAND cp -RL "${L4D2_MOLTENVK_FW}" "${_fw}/MoltenVK.framework"
    COMMAND codesign --force --sign - --timestamp=none "${_fw}/$<TARGET_FILE_NAME:rexruntime>" || true
    COMMAND codesign --force --sign - --timestamp=none "${_fw}/$<TARGET_FILE_NAME:rexgpu-xenos>" || true
    COMMAND codesign --force --sign - --timestamp=none "${_fw}/MoltenVK.framework" || true
    COMMAND codesign --force --sign - --timestamp=none "${_app}" || true
    DEPENDS L4D2Recomp rexruntime rexgpu-xenos
    COMMENT "Staging real dereferenced MoltenVK, rexruntime, and rexgpu-xenos into Frameworks..."
    VERBATIM
)

# Custom target for .ipa packaging
add_custom_target(l4d2recomp_package
    COMMAND python3 "${L4D2_ROOT}/tools/package_ipa.py" --app "$<TARGET_BUNDLE_DIR:L4D2Recomp>" --out "${CMAKE_BINARY_DIR}/L4D2Recomp.ipa"
    DEPENDS L4D2Recomp l4d2_stage_frameworks
    COMMENT "Packaging L4D2 Recomp .ipa..."
)
