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
    set(CMAKE_OSX_DEPLOYMENT_TARGET "16.0")
endif()

project(l4d2recomp_ios LANGUAGES C CXX OBJC OBJCXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(L4D2_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(L4D2_SRC "${L4D2_ROOT}/src")

# Core sources
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

target_include_directories(L4D2Recomp PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${L4D2_SRC}"
    "${L4D2_ROOT}"
)

target_compile_definitions(L4D2Recomp PRIVATE
    REX_PLATFORM_IOS=1
    __APPLE__=1
)

# Apple Frameworks
target_link_libraries(L4D2Recomp PRIVATE
    "-framework UIKit"
    "-framework Foundation"
    "-framework AudioToolbox"
    "-framework AVFoundation"
    "-framework GameController"
    "-framework Metal"
    "-framework QuartzCore"
)

# App Bundle Properties
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
    "${CMAKE_CURRENT_BINARY_DIR}/Info.plist"
    @ONLY
)

set_target_properties(L4D2Recomp PROPERTIES
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_BINARY_DIR}/Info.plist"
    XCODE_ATTRIBUTE_CODE_SIGN_ENTITLEMENTS "${CMAKE_CURRENT_SOURCE_DIR}/l4d2recomp.entitlements"
    XCODE_ATTRIBUTE_CODE_SIGNING_ALLOWED "NO"
    XCODE_ATTRIBUTE_CODE_SIGNING_REQUIRED "NO"
)

# Custom target for .ipa packaging
add_custom_target(l4d2recomp_package
    COMMAND python3 "${L4D2_ROOT}/tools/package_ipa.py" --app "$<TARGET_BUNDLE_DIR:L4D2Recomp>" --out "${CMAKE_BINARY_DIR}/L4D2Recomp.ipa"
    DEPENDS L4D2Recomp
    COMMENT "Packaging L4D2 Recomp .ipa..."
)

