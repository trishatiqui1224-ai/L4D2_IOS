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
    option(L4D2_USE_REXGLUE "Build ReXGlue-linked desktop executable when SDK and generated sources exist" ON)
    set(L4D2_SDK "${CMAKE_CURRENT_SOURCE_DIR}/build-sdk" CACHE PATH "Path to ReXGlue SDK source/build root")
    set(_L4D2_SDK_INSTALL "${L4D2_SDK}/out/install/win-amd64")

    set(_L4D2_CAN_BUILD_REXGLUE OFF)
    if(L4D2_USE_REXGLUE
       AND CMAKE_CXX_COMPILER_ID MATCHES "^(Apple)?Clang$"
       AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/generated/default/sources.cmake"
       AND (EXISTS "${_L4D2_SDK_INSTALL}/lib/cmake/rexglue/rexglueConfig.cmake"
            OR EXISTS "${L4D2_SDK}/CMakeLists.txt"))
        set(_L4D2_CAN_BUILD_REXGLUE ON)
    endif()

    if(_L4D2_CAN_BUILD_REXGLUE)
        if(EXISTS "${_L4D2_SDK_INSTALL}/lib/cmake/rexglue/rexglueConfig.cmake")
            find_package(rexglue CONFIG REQUIRED HINTS "${_L4D2_SDK_INSTALL}")
        else()
            find_package(rexglue CONFIG QUIET)
            if(NOT rexglue_FOUND)
                add_subdirectory("${L4D2_SDK}" "${CMAKE_CURRENT_BINARY_DIR}/rexglue-sdk")
            endif()
        endif()

        set(L4D2_RECOMP_BASE_OPTS
            -O2
            -Wno-unused-variable
            -Wno-unused-but-set-variable
            -Wno-unused-function
        )
        if(WIN32)
            list(APPEND L4D2_RECOMP_BASE_OPTS -fasync-exceptions -gline-tables-only)
        endif()

        set(L4D2_MODULE_SPECS
            "default|l4d2_default|default"
            "tier0_360|l4d2_tier0|tier0"
            "vstdlib_360|l4d2_vstdlib|vstdlib"
            "FileSystem_Stdio_360|l4d2_filesystem|filesystem"
            "inputsystem_360|l4d2_inputsystem|inputsystem"
            "launcher_360|l4d2_launcher|launcher"
            "datacache_360|l4d2_datacache|datacache"
            "MaterialSystem_360|l4d2_materialsystem|materialsystem"
            "shaderapidx9_360|l4d2_shaderapidx9|shaderapidx9"
            "stdshader_dx9_360|l4d2_stdshader_dx9|stdshader_dx9"
            "StudioRender_360|l4d2_studiorender|studiorender"
            "vgui2_360|l4d2_vgui2|vgui2"
            "vguimatsurface_360|l4d2_vguimatsurface|vguimatsurface"
            "vphysics_360|l4d2_vphysics|vphysics"
            "vscript_360|l4d2_vscript|vscript"
            "SoundEmitterSystem_360|l4d2_soundemitter|soundemitter"
            "SceneFileCache_360|l4d2_scenefilecache|scenefilecache"
            "GameUI_360|l4d2_gameui|gameui"
            "matchmaking_360|l4d2_matchmaking|matchmaking"
            "engine_360|l4d2_engine|engine"
            "client_360|l4d2_client|client"
            "server_360|l4d2_server|server"
        )

        set(L4D2_RECOMP_LIBS)
        set(L4D2_MODULE_INCLUDE_DIRS)
        foreach(_spec IN LISTS L4D2_MODULE_SPECS)
            string(REPLACE "|" ";" _parts "${_spec}")
            list(GET _parts 0 _mod_dir)
            list(GET _parts 1 _mod_prefix)
            list(GET _parts 2 _mod_target)

            set(_mod_lib "l4d2_${_mod_target}_recomp")
            set(_mod_inc "${CMAKE_CURRENT_SOURCE_DIR}/generated/${_mod_dir}")
            list(APPEND L4D2_MODULE_INCLUDE_DIRS "${_mod_inc}")

            unset(GENERATED_SOURCES)
            include("${_mod_inc}/sources.cmake")

            add_library(${_mod_lib} STATIC ${GENERATED_SOURCES})
            set_target_properties(${_mod_lib} PROPERTIES
                CXX_STANDARD 23
                CXX_STANDARD_REQUIRED ON
            )
            target_include_directories(${_mod_lib} PRIVATE
                "${CMAKE_CURRENT_SOURCE_DIR}/src"
                "${_mod_inc}"
            )
            target_link_libraries(${_mod_lib} PRIVATE rex::runtime)
            target_compile_definitions(${_mod_lib} PRIVATE
                L4D2_USE_REXGLUE=1
                _CRT_SECURE_NO_WARNINGS
                NOMINMAX
                WIN32_LEAN_AND_MEAN
            )
            rexglue_apply_target_settings(${_mod_lib})
            target_precompile_headers(${_mod_lib} PRIVATE
                "${_mod_inc}/${_mod_prefix}_pch.h"
            )
            target_compile_options(${_mod_lib} PRIVATE ${L4D2_RECOMP_BASE_OPTS})

            foreach(_src IN LISTS GENERATED_SOURCES)
                if(_src MATCHES "_register\\.cpp$")
                    set_source_files_properties("${_src}" PROPERTIES
                        SKIP_PRECOMPILE_HEADERS ON
                        COMPILE_OPTIONS "-O1")
                endif()
            endforeach()

            list(APPEND L4D2_RECOMP_LIBS ${_mod_lib})
        endforeach()

        set(L4D2_SOURCES
            src/rex_main.cpp
            src/logging/logger.cpp
            src/module_loader.cpp
            src/resolution_hooks.cpp
            src/crash_handler.cpp
            src/guest_stubs.cpp
        )

        if(WIN32)
            add_executable(l4d2_recomp WIN32 ${L4D2_SOURCES})
            target_link_options(l4d2_recomp PRIVATE
                "LINKER:/STACK:8388608"
                "LINKER:/force:multiple"
                "LINKER:/DEBUG"
            )
        else()
            add_executable(l4d2_recomp ${L4D2_SOURCES})
        endif()

        set_target_properties(l4d2_recomp PROPERTIES
            CXX_STANDARD 23
            CXX_STANDARD_REQUIRED ON
        )
        target_include_directories(l4d2_recomp PRIVATE
            "${CMAKE_CURRENT_SOURCE_DIR}/src"
            ${L4D2_MODULE_INCLUDE_DIRS}
        )
        target_compile_definitions(l4d2_recomp PRIVATE
            L4D2_USE_REXGLUE=1
            _CRT_SECURE_NO_WARNINGS
            NOMINMAX
            WIN32_LEAN_AND_MEAN
        )
        target_compile_options(l4d2_recomp PRIVATE ${L4D2_RECOMP_BASE_OPTS})
        target_link_libraries(l4d2_recomp PRIVATE
            rex::runtime
            ${L4D2_RECOMP_LIBS}
        )
        if(WIN32)
            target_link_libraries(l4d2_recomp PRIVATE dbghelp)
        endif()
        rexglue_configure_target(l4d2_recomp GPU_PLUGINS xenos)
    else()
        # Desktop / Tooling / Unit Test Scaffold Build
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

