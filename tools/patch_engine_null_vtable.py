"""Guard an engine startup vtable call when its global object is not initialized."""

from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "generated" / "engine_360"
          / "l4d2_engine_recomp.53.cpp")
anchor = """	// lwz r3,12372(r11)
	ctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + 12372);
	// lwz r10,0(r3)
"""
patched = """	// lwz r3,12372(r11)
	ctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + 12372);
	if (__builtin_expect(ctx.r3.u32 == 0, 0)) goto loc_86C31984;
	// lwz r10,0(r3)
"""
text = source.read_text(encoding="utf-8")
if patched not in text:
    if text.count(anchor) != 1:
        raise SystemExit("Engine null-vtable patch: expected exactly one startup call")
    source.write_text(text.replace(anchor, patched, 1), encoding="utf-8", newline="\n")
