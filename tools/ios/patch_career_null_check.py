#!/usr/bin/env python3
"""
Safeguard Career mode post-cutscene transition in sub_825F6A78.
Prevents read of guest 0x00000000 when *(r31 + 24) is NULL.
"""

import pathlib
import sys

TARGET = "generated/default/nfscarbon_recomp.20.cpp"

OLD_CODE = """\t// lwz r11,24(r31)
\tctx.r11.u64 = REX_LOAD_U32(ctx.r31.u32 + 24);
\t// lwz r21,0(r11)"""

PATCHED_CODE = """\t// lwz r11,24(r31)
\tctx.r11.u64 = REX_LOAD_U32(ctx.r31.u32 + 24);
\tif (!ctx.r11.u32) goto loc_825F7788;
\t// lwz r21,0(r11)"""


def apply_patch(root_dir: pathlib.Path) -> bool:
    target_file = root_dir / TARGET
    if not target_file.is_file():
        return False
    text = target_file.read_text(encoding="utf-8")
    if "if (!ctx.r11.u32) goto loc_825F7788;" in text:
        print("[patch_career_null_check] Already applied in nfscarbon_recomp.20.cpp")
        return True
    if OLD_CODE in text:
        text = text.replace(OLD_CODE, PATCHED_CODE, 1)
        target_file.write_text(text, encoding="utf-8")
        print("[patch_career_null_check] Successfully applied null-check in sub_825F6A78")
        return True
    print("[patch_career_null_check] WARNING: Anchor not found in nfscarbon_recomp.20.cpp")
    return False


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parents[2]
    ok = apply_patch(root)
    sys.exit(0 if ok else 1)

