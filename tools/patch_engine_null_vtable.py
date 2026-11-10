"""Guard startup virtual calls whose engine-owned singleton is not ready."""

from pathlib import Path


ENGINE_DIR = Path(__file__).resolve().parents[1] / "generated" / "engine_360"


def patch_function(name: str, anchor: str, replacement: str) -> bool:
    for source in ENGINE_DIR.glob("l4d2_engine_recomp.*.cpp"):
        text = source.read_text(encoding="utf-8")
        marker = f"DEFINE_REX_FUNC({name}) {{"
        start = text.find(marker)
        if start < 0:
            continue

        next_function = text.find("DEFINE_REX_FUNC(", start + len(marker))
        end = len(text) if next_function < 0 else next_function
        body = text[start:end]

        if replacement in body:
            return False
        if body.count(anchor) != 1:
            raise SystemExit(
                f"Engine null-vtable patch: expected one anchor in {name} ({source.name})"
            )

        patched_body = body.replace(anchor, replacement, 1)
        source.write_text(text[:start] + patched_body + text[end:], encoding="utf-8", newline="\n")
        print(f"[engine-null-vtable] Guarded {name} in {source.name}.")
        return True

    raise SystemExit(f"Engine null-vtable patch: function {name} was not generated")


# Keep the existing sub_86C31938 guard. The iOS crash log points into
# sub_86C314B8, where startup can reach a virtual call before its interface
# pointer chain has been initialized.
old_anchor = """\t// lwz r3,12372(r11)
\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + 12372);
\t// lwz r10,0(r3)
"""

patch_function(
    "sub_86C31938",
    old_anchor,
    """\t// lwz r3,12372(r11)
\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + 12372);
\tif (__builtin_expect(ctx.r3.u32 == 0, 0)) goto loc_86C31984;
\t// lwz r10,0(r3)
""",
)

patch_function(
    "sub_86C314B8",
    old_anchor,
    """\t// lwz r3,12372(r11)
\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + 12372);
\tif (__builtin_expect(ctx.r3.u32 == 0, 0)) goto loc_86C3150C;
\t// lwz r10,0(r3)
""",
)

patch_function(
    "sub_86C314B8",
    """\t// lwz r10,0(r3)
\tctx.r10.u64 = REX_LOAD_U32(ctx.r3.u32 + 0);
\t// lwz r9,512(r10)
""",
    """\t// lwz r10,0(r3)
\tctx.r10.u64 = REX_LOAD_U32(ctx.r3.u32 + 0);
\tif (__builtin_expect(ctx.r10.u32 == 0, 0)) goto loc_86C3150C;
\t// lwz r9,512(r10)
""",
)

patch_function(
    "sub_86C314B8",
    """\t// lwz r9,512(r10)
\tctx.r9.u64 = REX_LOAD_U32(ctx.r10.u32 + 512);
\t// mtctr r9
""",
    """\t// lwz r9,512(r10)
\tctx.r9.u64 = REX_LOAD_U32(ctx.r10.u32 + 512);
\tif (__builtin_expect(ctx.r9.u32 == 0, 0)) goto loc_86C3150C;
\t// mtctr r9
""",
)

patch_function(
    "sub_86C314B8",
    """\t// lwz r3,4(r31)
\tctx.r3.u64 = REX_LOAD_U32(ctx.r31.u32 + 4);
\t// mr r4,r30
""",
    """\t// lwz r3,4(r31)
\tctx.r3.u64 = REX_LOAD_U32(ctx.r31.u32 + 4);
\t// The nested interface can be absent while engine_360 is starting.
\tif (__builtin_expect(ctx.r3.u32 == 0, 0)) goto loc_86C31524;
\t// mr r4,r30
""",
)

patch_function(
    "sub_86C314B8",
    """\t// lwz r11,0(r3)
\tctx.r11.u64 = REX_LOAD_U32(ctx.r3.u32 + 0);
\t// lwz r10,4(r11)
""",
    """\t// lwz r11,0(r3)
\tctx.r11.u64 = REX_LOAD_U32(ctx.r3.u32 + 0);
\tif (__builtin_expect(ctx.r11.u32 == 0, 0)) {
\t\tctx.r3.u64 = 0;
\t\tgoto loc_86C31524;
\t}
\t// lwz r10,4(r11)
""",
)

patch_function(
    "sub_86C314B8",
    """\t// lwz r10,4(r11)
\tctx.r10.u64 = REX_LOAD_U32(ctx.r11.u32 + 4);
\t// mtctr r10
""",
    """\t// lwz r10,4(r11)
\tctx.r10.u64 = REX_LOAD_U32(ctx.r11.u32 + 4);
\tif (__builtin_expect(ctx.r10.u32 == 0, 0)) {
\t\tctx.r3.u64 = 0;
\t\tgoto loc_86C31524;
\t}
\t// mtctr r10
""",
)

patch_function(
    "sub_86C314B8",
    """\t// addi r1,r1,112
\tctx.r1.s64 = ctx.r1.s64 + 112;
""",
    """loc_86C31524:
\t// addi r1,r1,112
\tctx.r1.s64 = ctx.r1.s64 + 112;
""",
)

patch_function(
    "sub_86C314B8",
    """\tREX_FUNC_PROLOGUE();
\tuint32_t ea{};
\t// mflr r12
""",
    """\tREX_FUNC_PROLOGUE();
\t// Do not enter the allocator method body with an absent receiver.
\tif (__builtin_expect(ctx.r3.u32 == 0, 0)) return;
\tuint32_t ea{};
\t// mflr r12
""",
)

# The engine's singleton can already be installed when its backing allocator
# is still null. Bind it to Tier0's default object, rather than its mutable
# allocator slot, which can point back to this wrapper.
patch_function(
    "sub_86C314B8",
    """loc_86C3150C:
\t// lwz r3,4(r31)
""",
    """loc_86C3150C:
\tif (ctx.r31.u32 == 0x86F2A9A0u && REX_LOAD_U32(ctx.r31.u32 + 4) == 0 &&
\t    REX_LOAD_U32(0x82C406D0u) != 0) {
\t\tREX_STORE_U32(ctx.r31.u32 + 4, 0x82C406D0u);
\t}
\t// lwz r3,4(r31)
""",
)

# The zeroing allocator wrapper must propagate allocation failure before memset.
patch_function(
    "sub_86C37F58",
    """\tctx.lr = 0x86C37FA0;
\tsub_86EBE180(ctx, base);
""",
    """\tif (ctx.r3.u32 != 0) {
\t\tctx.lr = 0x86C37FA0;
\t\tsub_86EBE180(ctx, base);
\t}
""",
)
