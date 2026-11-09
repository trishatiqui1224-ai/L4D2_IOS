"""Guard the engine cleanup call after restoring the generated sources."""

from pathlib import Path


path = (Path(__file__).resolve().parents[1] / "generated" / "engine_360"
        / "l4d2_engine_recomp.29.cpp")
anchor = """	ctx.lr = 0x86DCB6E4;
	REX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
"""
guard = """	// The unresolved virtual call returns zero. There is no allocation
	// pointer to release in that case.
	if (ctx.r3.u32 == 0) goto loc_86DCB6E8;
"""
source = path.read_text(encoding="utf-8")
if anchor + guard not in source:
    if source.count(anchor + "\t// bl 0x86dbd8b8") != 1:
        raise SystemExit("Engine cleanup patch: expected one matching call site")
    path.write_text(source.replace(anchor, anchor + guard, 1), encoding="utf-8", newline="\n")
