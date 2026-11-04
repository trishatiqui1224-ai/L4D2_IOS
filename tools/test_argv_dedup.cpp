#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

// Exact logic from src/main.cpp and ios/src/ios_main.mm
std::string OptionName(const std::string& arg) {
    return arg.substr(0, arg.find('='));
}

void SetArgument(std::vector<std::string>& args, const std::string& arg) {
    if (args.empty()) {
        args.push_back(arg);
        return;
    }
    const std::string name = OptionName(arg);
    if (name.rfind("--", 0) == 0) {
        for (size_t i = 1; i < args.size(); ++i) {
            if (OptionName(args[i]) == name) {
                args[i] = arg; // Last occurrence wins!
                return;
            }
        }
    }
    args.push_back(arg);
}

void ApplyUtilityQosDefault(std::vector<std::string>& args) {
    const std::pair<const char*, bool> defaults[] = {
        {"--ios_utility_qos", false},
        {"--ios_utility_qos_guest", false},
        {"--ios_adaptive_qos", false}
    };
    for (const auto& [flag, value] : defaults) {
        SetArgument(args, std::string(flag) + (value ? "=true" : "=false"));
    }
}

std::vector<char*> BuildLaunchArgv(std::vector<std::string>& args) {
    std::vector<char*> argv;
    argv.reserve(args.size() + 1);
    for (auto& s : args) {
        argv.push_back(s.data());
    }
    argv.push_back(nullptr);
    return argv;
}

int main() {
    std::cout << "[test_argv_dedup] Starting L4D2 Recomp argv deduplication tests..." << std::endl;

    // Test 1: Empty vector operations
    {
        std::vector<std::string> empty_args;
        SetArgument(empty_args, "l4d2recomp");
        assert(empty_args.size() == 1);
        assert(empty_args[0] == "l4d2recomp");

        SetArgument(empty_args, "--foo=bar");
        assert(empty_args.size() == 2);
        assert(empty_args[1] == "--foo=bar");

        SetArgument(empty_args, "--foo=baz");
        assert(empty_args.size() == 2);
        assert(empty_args[1] == "--foo=baz");
        std::cout << "  Test 1 (Empty vector handling & replacement) PASSED." << std::endl;
    }

    // Test 2: L4D2 Recomp runtime flags + override deduplication
    {
        std::vector<std::string> args{"l4d2recomp"};
        const std::vector<std::string> raw_flags = {
            "--title_id=454108D4",
            "--media_id=0E79403B",
            "--resolution=1280x720",
            "--l4d2_fps_cap=60",
            "--mnk_mode=false",
            "--audio_maxqframes=64",
            "--ios_xma_starve_reset=false",
            "--low_ram_texture_cache=true",
            "--half_res_textures=false",
            "--game_data_root=/path/to/l4d2_world",
            // Settings override re-passed from launcher
            "--resolution=960x540",
            "--l4d2_fps_cap=30",
            "--half_res_textures=true"
        };

        for (const auto& flag : raw_flags) {
            SetArgument(args, flag);
        }

        // Verify that duplicate flags were updated in-place (last-occurrence wins)
        auto find_flag = [&](const std::string& prefix) -> std::string {
            for (const auto& a : args) {
                if (a.rfind(prefix, 0) == 0) return a;
            }
            return "";
        };

        assert(find_flag("--resolution=") == "--resolution=960x540");
        assert(find_flag("--l4d2_fps_cap=") == "--l4d2_fps_cap=30");
        assert(find_flag("--half_res_textures=") == "--half_res_textures=true");
        assert(find_flag("--title_id=") == "--title_id=454108D4");
        assert(find_flag("--mnk_mode=") == "--mnk_mode=false");
        std::cout << "  Test 2 (L4D2 runtime flags deduplication) PASSED." << std::endl;
    }

    // Test 3: QoS defaults injection
    {
        std::vector<std::string> args{"l4d2recomp"};
        ApplyUtilityQosDefault(args);
        assert(args.size() == 4);
        assert(args[1] == "--ios_utility_qos=false");
        assert(args[2] == "--ios_utility_qos_guest=false");
        assert(args[3] == "--ios_adaptive_qos=false");
        std::cout << "  Test 3 (QoS defaults injection) PASSED." << std::endl;
    }

    // Test 4: BuildLaunchArgv pointer safety and null-terminator
    {
        std::vector<std::string> args{"l4d2recomp", "--foo=bar", "--baz=1"};
        auto argv = BuildLaunchArgv(args);
        assert(argv.size() == 4);
        assert(std::string(argv[0]) == "l4d2recomp");
        assert(std::string(argv[1]) == "--foo=bar");
        assert(std::string(argv[2]) == "--baz=1");
        assert(argv[3] == nullptr);
        std::cout << "  Test 4 (BuildLaunchArgv pointer safety) PASSED." << std::endl;
    }

    std::cout << "[test_argv_dedup] ALL TESTS PASSED SUCCESSFULLY!" << std::endl;
    return 0;
}
