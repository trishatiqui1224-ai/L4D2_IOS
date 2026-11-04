# Left 4 Dead 2 Native Static Recompilation ("L4D2 Recomp")

[![Platform: iOS / ARM64](https://img.shields.io/badge/Platform-iOS%2016.0%2B%20%7C%20ARM64-blue.svg)](https://apple.com)
[![Renderer: Vulkan / Metal](https://img.shields.io/badge/Renderer-Metal%20%2F%20Vulkan-orange.svg)](https://github.com/rexglue/rexglue-sdk)
[![Title ID: 454108D4](https://img.shields.io/badge/Title%20ID-454108D4-green.svg)](http://redump.org/disc/12497/)
[![Media ID: 0E79403B](https://img.shields.io/badge/Media%20ID-0E79403B-lightgrey.svg)](http://redump.org/disc/12497/)

A native ARM64 static recompilation port of **Left 4 Dead 2 (Xbox 360 World Retail Disc)** using the **ReXGlue SDK**, featuring native Metal/Vulkan presentation, low-latency audio, multi-module Source Engine dynamic loading, and native mobile shooter touch controls.

---

## 1. Target Disc Specification & Zero Bundled Game Files
- **Target Disc:** `Left 4 Dead 2 (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko,Pl,Ru).iso` (Redump #12497)
  - **Title ID:** `454108D4`
  - **Media ID:** `0E79403B`
  - **Disc Version:** Retail Base Disc (`v0`, `00000003`, No Title Update)
  - **Total Files Verified on Disc:** 96 files (4,441.95 MB)
- **Zero Bundled Files Policy:** This repository contains **NO** copyrighted game assets, Valve binaries, textures, models, maps, sounds, or fonts. All game data is read and verified directly from the user's legally acquired retail disc image or extracted folder.
- **SHA-256 Verifier:** Deterministic manifest embedded in `src/l4d2_manifest.h`. The launcher verifies all 96 files with an animated progress bar and file counter before launch.

---

## 2. Multi-Module Source Engine Architecture
Unlike single-binary Xbox 360 games, Valve's Source Engine splits execution across `default.xex` plus 21 dynamically loaded XEX2 modules linked via `CreateInterface` (ordinal 1 / named export).

All 22 modules have been analyzed, relocated, and mapped to **100% disjoint virtual address ranges**:

| Module Name | Image Base | Image End | Virtual Span | PData Functions |
| :--- | :--- | :--- | :--- | :--- |
| `default.xex` | `0x82000000` | `0x82040030` | 0.25 MB | 119 |
| `bin\vphysics_360.dll` | `0x82200000` | `0x82330030` | 1.19 MB | 2,170 |
| `bin\tier0_360.dll` | `0x82C00000` | `0x82C90030` | 0.56 MB | 597 |
| `bin\vstdlib_360.dll` | `0x82E00000` | `0x82E80030` | 0.50 MB | 385 |
| `bin\FileSystem_Stdio_360.dll` | `0x83000000` | `0x830A0030` | 0.63 MB | 1,078 |
| `bin\datacache_360.dll` | `0x83280000` | `0x83310030` | 0.56 MB | 984 |
| `bin\inputsystem_360.dll` | `0x83500000` | `0x83560030` | 0.38 MB | 214 |
| `bin\launcher_360.dll` | `0x83680000` | `0x836F0030` | 0.44 MB | 419 |
| `bin\SoundEmitterSystem_360.dll` | `0x83880000` | `0x838E0030` | 0.38 MB | 371 |
| `bin\SceneFileCache_360.dll` | `0x83A80000` | `0x83AD0030` | 0.31 MB | 139 |
| `bin\vgui2_360.dll` | `0x83C00000` | `0x83C80030` | 0.50 MB | 614 |
| `bin\GameUI_360.dll` | `0x84000000` | `0x841A0030` | 1.63 MB | 4,031 |
| `bin\vscript_360.dll` | `0x84800000` | `0x84890030` | 0.56 MB | 824 |
| `bin\MaterialSystem_360.dll` | `0x84900000` | `0x84A10050` | 1.06 MB | 1,866 |
| `bin\vguimatsurface_360.dll` | `0x84E00000` | `0x84F20030` | 1.13 MB | 2,431 |
| `bin\shaderapidx9_360.dll` | `0x85200000` | `0x854300B0` | 2.19 MB | 4,300 |
| `bin\stdshader_dx9_360.dll` | `0x85F00000` | `0x85FD0030` | 0.81 MB | 1,889 |
| `bin\StudioRender_360.dll` | `0x86380000` | `0x86600030` | 2.50 MB | 741 |
| `bin\engine_360.dll` | `0x86B00000` | `0x871F00D0` | 6.94 MB | 10,837 |
| `left4dead2\bin\client_360.dll` | `0x88100000` | `0x888D0030` | 7.81 MB | 16,742 |
| `left4dead2\bin\server_360.dll` | `0x89780000` | `0x89FD0030` | 8.31 MB | 18,936 |
| `left4dead2\bin\matchmaking_360.dll` | `0x8B080000` | `0x8B120030` | 0.63 MB | 1,011 |

**Total Functions Discovered:** Over 69,000 PowerPC functions across all modules.

---

## 3. Mandatory Mobile Hardening Checklist
- **8 MB Host Thread Stacks:** All POSIX guest threads are configured with `pthread_attr_setstacksize(&attr, 8 * 1024 * 1024)`. Prevents stack overflows during BSP tracing, Havok `vphysics`, and AI Director horde pathfinding.
- **EDRAM Tile Calculation:** Formula `((width + 79) / 80) * ((height + 15) / 16)` guarantees exact tile counts (e.g. 1280x720 = 720 tiles, 1560x720 = 900 tiles).
- **Single-Fire GPU Logs:** MSAA resolve sample fallbacks log strictly once via `std::once_flag`, eliminating 360 lines/sec logging bottlenecks.
- **Low-Latency CoreAudio (5.3 ms Buffer):** Configured with `setPreferredIOBufferDuration:0.005` (256 frames @ 48 kHz = 5.33 ms) and `--ios_xma_starve_reset=false` for crystal-clear audio and zero gun sound delay.
- **Safe CLI Argument Builder:** Deduplicates all flags with last-occurrence wins before passing `char* argv[]`, verified via unit tests.
- **Symbolicated Crash Breadcrumbs:** `sigaltstack` crash handler logs PPC registers, faulting guest module name, and the last 16 call breadcrumbs into `boot.txt` and `l4d2.log`.

---

## 4. Left 4 Dead 2 Styled Touch Controls & HUD
1. **Left 4 Dead 2 Mode (FPS Action + 5-Slot Bar):**
   - Left Analog Thumbstick for movement.
   - Mobile Shooter Drag-to-Look on right half of screen.
   - Dedicated buttons: **FIRE**, **SHOVE / MELEE**, **RELOAD**, **JUMP**, **CROUCH**, **USE**, **ZOOM**, **FLASHLIGHT**.
   - 5-Slot Inventory Bar: Primary, Pistol/Melee, Grenade, Medkit, Pills.
2. **Xbox 360 Pad Mode:**
   - Full virtual controller with dual sticks, D-Pad, A/B/X/Y, LB/RB, LT/RT.
3. **Hardware Gamepad Support:**
   - Auto-hides touch HUD when Xbox, DualSense, DualShock, Backbone, or MFi controller is connected.

---

## 5. Building & Testing

### Host Unit Tests
```bash
# Build & run argument deduplication test
clang++ -std=c++20 tools/test_argv_dedup.cpp -o test_argv_dedup
./test_argv_dedup

# Build & run manifest verifier test
clang++ -std=c++20 tools/test_manifest_verifier.cpp -o test_manifest_verifier
./test_manifest_verifier
```

### Packaging iOS IPA
```bash
chmod +x build_ipa.sh
./build_ipa.sh
```

The resulting `L4D2-Recomp-iOS.ipa` can be installed on iOS 16.0+ devices via AltStore, SideStore, TrollStore, or Xcode.
