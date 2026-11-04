cmake_minimum_required(VERSION 3.25)

if(APPLE)
    project(l4d2recomp LANGUAGES C CXX OBJC OBJCXX)
else()
    project(l4d2recomp LANGUAGES C CXX)
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(IOS OR CMAKE_SYSTEM_NAME STREQUAL "iOS")
    add_subdirectory(ios)
else()
    # Desktop / Tooling / Unit Test Build
    set(L4D2_SOURCES
        src/main.cpp
        src/logging/logger.cpp
        src/module_loader.cpp
        src/resolution_hooks.cpp
        src/crash_handler.cpp
    )

    add_executable(l4d2_recomp ${L4D2_SOURCES})
    target_include_directories(l4d2_recomp PRIVATE src)

    if(WIN32)
        target_compile_definitions(l4d2_recomp PRIVATE _CRT_SECURE_NO_WARNINGS)
        target_link_libraries(l4d2_recomp PRIVATE dbghelp)
    endif()

    # Unit Tests
    enable_testing()

    add_executable(test_argv_dedup tools/test_argv_dedup.cpp)
    target_include_directories(test_argv_dedup PRIVATE src)
    add_test(NAME test_argv_dedup COMMAND test_argv_dedup)

    add_executable(test_manifest_verifier tools/test_manifest_verifier.cpp)
    target_include_directories(test_manifest_verifier PRIVATE src)
    add_test(NAME test_manifest_verifier COMMAND test_manifest_verifier)
endif()

