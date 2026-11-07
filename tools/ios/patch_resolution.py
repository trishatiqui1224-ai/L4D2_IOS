import pathlib

def patch_file(path_str, target, replacement):
    p = pathlib.Path(path_str)
    raw = p.read_bytes()
    is_crlf = b"\r\n" in raw
    txt = raw.decode("utf-8").replace("\r\n", "\n")
    assert target in txt, f"Target not found in {path_str}"
    new_txt = txt.replace(target, replacement)
    if is_crlf:
        new_raw = new_txt.replace("\n", "\r\n").encode("utf-8")
    else:
        new_raw = new_txt.encode("utf-8")
    p.write_bytes(new_raw)
    print(f"Patched {path_str} (crlf={is_crlf})")

# 1. ios/src/ios_main.mm
target_main = """static std::string OptionName(const std::string& arg) {
    return arg.substr(0, arg.find('='));
}

static void SetArgument(std::vector<std::string>& args, const std::string& arg) {"""

repl_main = """static std::string OptionName(const std::string& arg) {
    return arg.substr(0, arg.find('='));
}

static std::string NormalizeArgument(const std::string& arg) {
    if (arg.rfind("--resolution=", 0) == 0) {
        std::string val = arg.substr(13);
        if (val == "720p") return "--resolution=1280x720";
        if (val == "540p") return "--resolution=960x540";
        if (val == "480p") return "--resolution=854x480";
    }
    return arg;
}

static void SetArgument(std::vector<std::string>& args, const std::string& raw_arg) {
    const std::string arg = NormalizeArgument(raw_arg);"""

patch_file("ios/src/ios_main.mm", target_main, repl_main)

# 2. ios/src/launcher.mm
target_launch = """    // Display
    args.push_back("--resolution=" + std::string(s[@"resolution"] ? s[@"resolution"].UTF8String : "1280x720"));"""

repl_launch = """    // Display
    NSString* resStr = s[@"resolution"] ? s[@"resolution"] : @"1280x720";
    if ([resStr isEqualToString:@"720p"]) resStr = @"1280x720";
    else if ([resStr isEqualToString:@"540p"]) resStr = @"960x540";
    else if ([resStr isEqualToString:@"480p"]) resStr = @"854x480";
    args.push_back("--resolution=" + std::string(resStr.UTF8String));"""

patch_file("ios/src/launcher.mm", target_launch, repl_launch)

# 3. ios/src/game_entry.mm
target_entry = """        std::string res = rex::cvar::GetFlagByName("resolution");
        if (res.find("480") != std::string::npos) {
            renderCfg.resolution = l4d2::ResolutionPreset::Res480p;
        } else if (res.find("540") != std::string::npos) {
            renderCfg.resolution = l4d2::ResolutionPreset::Res540p;
        } else {
            renderCfg.resolution = l4d2::ResolutionPreset::Res720p;
        }"""

repl_entry = """        std::string res = rex::cvar::GetFlagByName("resolution");
        if (res == "720p") res = "1280x720";
        else if (res == "540p") res = "960x540";
        else if (res == "480p") res = "854x480";

        if (res.find("480") != std::string::npos) {
            renderCfg.resolution = l4d2::ResolutionPreset::Res480p;
        } else if (res.find("540") != std::string::npos) {
            renderCfg.resolution = l4d2::ResolutionPreset::Res540p;
        } else {
            renderCfg.resolution = l4d2::ResolutionPreset::Res720p;
        }"""

patch_file("ios/src/game_entry.mm", target_entry, repl_entry)
