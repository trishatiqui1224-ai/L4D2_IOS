#!/usr/bin/env bash
# ==============================================================================
#  build_ipa.sh - Automated Build & Sideload Packaging for Left 4 Dead 2 Recomp
#
#  Targets: iOS 16.0+, iPadOS 16.0+ (ARM64 Native Metal / Vulkan)
#  Supported Sideloaders: SideStore, LiveContainer, AltStore, TrollStore
# ==============================================================================

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
CYAN="\033[0;36m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}======================================================================${RESET}"
echo -e "${BOLD}${CYAN}    LEFT 4 DEAD 2 (XBOX 360) - iOS ARM64 NATIVE BUILD PIPELINE       ${RESET}"
echo -e "${BOLD}${CYAN}======================================================================${RESET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PROJECT_NAME="L4D2Recomp"
BUILD_DIR="${SCRIPT_DIR}/build"
IPA_OUTPUT="${BUILD_DIR}/L4D2-Recomp-iOS.ipa"

# 1. Dependency Checks
echo -e "\n${BOLD}${YELLOW}[1/5] Checking build dependencies...${RESET}"
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}[ERROR] python3 is required.${RESET}"; exit 1; }
command -v cmake >/dev/null 2>&1 || { echo -e "${RED}[ERROR] cmake is required.${RESET}"; exit 1; }
command -v ninja >/dev/null 2>&1 || { echo -e "${RED}[ERROR] ninja is required.${RESET}"; exit 1; }

echo -e "${GREEN}[OK] Python, CMake, and Ninja detected.${RESET}"

# 2. Asset & AppIcon Preparation
echo -e "\n${BOLD}${YELLOW}[2/5] Verifying AppIcon and assets catalog...${RESET}"
if [ ! -f "${SCRIPT_DIR}/ios/resources/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png" ]; then
    echo -e "${CYAN}Generating AppIcon catalog via tools/generate_appicon.py...${RESET}"
    python3 "${SCRIPT_DIR}/tools/generate_appicon.py"
fi
echo -e "${GREEN}[OK] AppIcon catalog verified.${RESET}"

# 3. Disc Verification & Manifest Generation
echo -e "\n${BOLD}${YELLOW}[3/5] Verifying disc manifest header...${RESET}"
python3 "${SCRIPT_DIR}/tools/verify_assets.py" --gen-header
echo -e "${GREEN}[OK] Embedded C++ manifest verified.${RESET}"

# 4. Configure & Compile via CMake
echo -e "\n${BOLD}${YELLOW}[4/5] Configuring and building iOS targets...${RESET}"
mkdir -p "${BUILD_DIR}"

cd "${SCRIPT_DIR}/ios"
if command -v xcrun >/dev/null 2>&1; then
    export CC="$(xcrun --sdk iphoneos --find clang 2>/dev/null || which clang)"
    export CXX="$(xcrun --sdk iphoneos --find clang++ 2>/dev/null || which clang++)"
    export OBJC="${CC}"
    export OBJCXX="${CXX}"
fi

cmake -B "${BUILD_DIR}" -G Ninja \
    -DCMAKE_SYSTEM_NAME=iOS \
    -DCMAKE_SYSTEM_PROCESSOR=arm64 \
    -DCMAKE_OSX_ARCHITECTURES=arm64 \
    -DCMAKE_OSX_SYSROOT=iphoneos \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=16.0 \
    -DCMAKE_BUILD_TYPE=Release

cmake --build "${BUILD_DIR}" --config Release

# 5. Packaging into IPA
echo -e "\n${BOLD}${YELLOW}[5/5] Packaging distributable .ipa...${RESET}"
python3 "${SCRIPT_DIR}/tools/package_ipa.py" --app "${BUILD_DIR}/L4D2Recomp.app" --out "${IPA_OUTPUT}"

echo -e "\n${BOLD}${GREEN}======================================================================${RESET}"
echo -e "${BOLD}${GREEN}  BUILD SUCCESSFUL: ${IPA_OUTPUT}${RESET}"
echo -e "${BOLD}${GREEN}======================================================================${RESET}"
