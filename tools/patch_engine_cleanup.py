"""Guard the engine cleanup call after restoring the generated sources."""

from pathlib import Path


path = (Path(__file__).resolve().parents[1] / "generated" / "engine_360"
        / "l4d2_engine_recomp.29.cpp")
anchor = """	// bl 0x86dbd8b8
	ctx.lr = 0x86DCB6E8;
	sub_86DBD8B8(ctx, base);
loc_86DCB6E8:
"""
old_guard = """	// The unresolved virtual call returns zero. There is no allocation
	// pointer to release in that case.
	if (ctx.r3.u32 == 0) goto loc_86DCB6E8;
"""
guard = """	// A null result has no allocation to release.
	if (ctx.r3.u32 == 0) goto loc_86DCB6E8;
"""
source = path.read_text(encoding="utf-8")
if guard + anchor not in source:
    if source.count(anchor) != 1:
        raise SystemExit("Engine cleanup patch: expected one matching call site")
    if old_guard + anchor in source:
        source = source.replace(old_guard + anchor, guard + anchor, 1)
    else:
        source = source.replace(anchor, guard + anchor, 1)
    path.write_text(source, encoding="utf-8", newline="\n")
