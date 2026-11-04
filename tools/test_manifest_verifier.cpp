#include <iostream>
#include <cassert>
#include <cstring>
#include "../src/l4d2_manifest.h"

int main() {
    std::cout << "[test_manifest_verifier] Testing L4D2 Recomp embedded manifest..." << std::endl;

    assert(l4d2::kTargetTitleId == 0x454108D4);
    assert(l4d2::kTargetMediaId == 0x0E79403B);
    assert(l4d2::kDemoTitleId   == 0x454188D6);
    assert(l4d2::kExpectedFileCount == 96);
    assert(l4d2::kDiscManifest.size() == 96);
    std::cout << "  Title ID, Media ID, and File count assertions PASSED." << std::endl;

    bool found_default_xex = false;
    bool found_engine = false;
    bool found_client = false;
    bool found_server = false;
    bool found_zip0 = false;

    for (const auto& item : l4d2::kDiscManifest) {
        assert(item.relative_path != nullptr && std::strlen(item.relative_path) > 0);
        assert(item.expected_size > 0);
        assert(item.expected_sha256 != nullptr && std::strlen(item.expected_sha256) == 64);

        std::string_view p(item.relative_path);
        if (p == "default.xex") found_default_xex = true;
        if (p == "bin/engine_360.dll") found_engine = true;
        if (p == "left4dead2/bin/client_360.dll") found_client = true;
        if (p == "left4dead2/bin/server_360.dll") found_server = true;
        if (p == "left4dead2/zip0.360.zip") found_zip0 = true;
    }

    assert(found_default_xex);
    assert(found_engine);
    assert(found_client);
    assert(found_server);
    assert(found_zip0);
    std::cout << "  Critical module paths & SHA-256 length assertions PASSED." << std::endl;

    std::cout << "[test_manifest_verifier] ALL MANIFEST ASSERTIONS PASSED!" << std::endl;
    return 0;
}
