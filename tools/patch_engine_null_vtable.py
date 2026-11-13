"""Restore omitted guest routines and guard partial startup and shutdown."""

from pathlib import Path


GENERATED = Path(__file__).resolve().parents[1] / "generated"


def patch_function(name: str, anchor: str, replacement: str, *, module: str = "engine") -> bool:
    for source in (GENERATED / f"{module}_360").glob(f"l4d2_{module}_recomp.*.cpp"):
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


# All callbacks in this traversal take a record address in r4. A missing
# backing array would pass zero for the first record and offsets from zero
# for subsequent records, regardless of the callback address.
patch_function(
    "sub_86DAC498",
    """loc_86DAC4D0:
\t// lwz r11,0(r30)
\tctx.r11.u64 = REX_LOAD_U32(ctx.r30.u32 + 0);
\t// mr r3,r28
""",
    """loc_86DAC4D0:
\t// lwz r11,0(r30)
\tctx.r11.u64 = REX_LOAD_U32(ctx.r30.u32 + 0);
\tif (ctx.r11.u32 == 0) goto loc_86DAC4F8;
\t// mr r3,r28
""",
)


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

# The profiling hook is optional. Each wrapper must still delegate the real
# allocator operation when the hook is missing during engine startup.
for name, on_missing in (
    ("sub_86C31540", "goto loc_86C31590;"),
    ("sub_86C315B8", "goto loc_86C3160C;"),
    ("sub_86C31640", "goto loc_86C31694;"),
    ("sub_86C316C0", "goto loc_86C31718;"),
    ("sub_86C31748", "goto loc_86C3179C;"),
    ("sub_86C317C8", "goto loc_86C31818;"),
    ("sub_86C31840", "goto loc_86C31898;"),
    ("sub_86C318C8", "return;"),
    ("sub_86C31938", "goto loc_86C31984;"),
):
    if name != "sub_86C31938":
        patch_function(
            name, old_anchor,
            old_anchor.replace("\t// lwz r10,0(r3)",
                               f"\tif (ctx.r3.u32 == 0) {on_missing}\n\t// lwz r10,0(r3)"),
        )
    for reg, load, next_instruction in (
        ("r10", "ctx.r10.u64 = REX_LOAD_U32(ctx.r3.u32 + 0);", "lwz r9,512(r10)"),
        ("r9", "ctx.r9.u64 = REX_LOAD_U32(ctx.r10.u32 + 512);", "mtctr r9"),
    ):
        patch_function(
            name, f"\t{load}\n\t// {next_instruction}\n",
            f"\t{load}\n\tif (ctx.{reg}.u32 == 0) {on_missing}\n\t// {next_instruction}\n",
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

# Interface lookup can run before its registry exists. Return the same null
# result as the normal lookup miss, so the caller still sets its failure flag.
patch_function(
    "sub_86E13C10",
    """\tREX_FUNC_PROLOGUE();
\tuint32_t ea{};
\t// mflr r12
""",
    """\tREX_FUNC_PROLOGUE();
\tif (ctx.r3.u32 == 0) return;
\tuint32_t ea{};
\t// mflr r12
""",
)

# Startup failure can reach shutdown before the display object exists.
# Skip its virtual call and still destroy the temporary startup state.
patch_function(
    "sub_86C842F8",
    """\tctx.r3.u64 = REX_LOAD_U32(ctx.r8.u32 + -9688);
\t// lwz r7,0(r3)
""",
    """\tctx.r3.u64 = REX_LOAD_U32(ctx.r8.u32 + -9688);
\tif (ctx.r3.u32 == 0) goto destroy_startup_state;
\t// lwz r7,0(r3)
""",
)
patch_function(
    "sub_86C842F8",
    """\tctx.lr = 0x86C8438C;
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\t// addi r3,r1,80
""",
    """\tctx.lr = 0x86C8438C;
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
destroy_startup_state:
\t// addi r3,r1,80
""",
)

# The rest of shutdown can also run after only some subsystems initialized.
# Leave the independent teardown calls in place.
for load, vtable, return_address in (
    ("ctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + -14884);", "lwz r10,0(r3)", "86C825CC"),
    ("ctx.r3.u64 = REX_LOAD_U32(ctx.r8.u32 + 12368);", "lwz r7,0(r3)", "86C825E4"),
    ("ctx.r3.u64 = REX_LOAD_U32(ctx.r4.u32 + -7396);", "lwz r11,0(r3)", "86C82610"),
):
    label = f"loc_{return_address}"
    patch_function(
        "sub_86C82588",
        f"\t{load}\n\t// {vtable}\n",
        f"\t{load}\n\tif (ctx.r3.u32 == 0) goto {label};\n\t// {vtable}\n",
    )
    call = f"\tctx.lr = 0x{return_address};\n\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);\n"
    patch_function("sub_86C82588", call, f"{call}{label}:\n")


# The disc's CRT initializer table references these small tail-call functions,
# which have no .pdata entries. The recompiler omitted their entry points.
# Each row preserves the two immediate arguments encoded by the original PPC.
CRT_INITIALIZER_GROUPS = (
    (0x86EF0040, 0x86CB1DD8, (
        (2, 0x3AA8), (3, 0x3B90), (4, 0x3C00), (6, 0x3C70),
        (8, 0x3D48), (9, 0x3DB8), (10, 0x3FA8), (19, 0x41A8),
        (18, 0x3488), (20, 0x3898),
    )),
    (0x86EF00E0, 0x86CB1E10, (
        (1, 0x5910), (2, 0x59D8), (4, 0x5F50), (6, 0x66E0),
        (3, 0x6850), (8, 0x69B0), (10, 0x7930), (19, 0x70F8),
        (18, 0x7270), (20, 0x75F8),
    )),
)

initializer_dispatch = ["\tswitch (ctx.ctr.u32) {\n"]
for start, target, arguments in CRT_INITIALIZER_GROUPS:
    for index, (slot, offset) in enumerate(arguments):
        initializer_dispatch.extend((
            f"\tcase 0x{start + index * 16:08X}u:\n",
            "\t\tctx.r11.s64 = -2033516544; // lis r11,0x86CB\n",
            f"\t\tctx.r3.s64 = {slot};\n",
            f"\t\tctx.r4.s64 = ctx.r11.s64 + 0x{offset:04X};\n",
            f"\t\tREX_CALL_INDIRECT_FUNC(0x{target:08X}u);\n",
            "\t\tbreak;\n",
        ))
initializer_dispatch.append("""\tcase 0x86EF0180u:
\t\tctx.r11.s64 = -2031091712; // lis r11,0x86F0
\t\tctx.r3.s64 = ctx.r11.s64 + 0x1198;
\t\tREX_CALL_INDIRECT_FUNC(0x86EBF9E0u);
\t\tbreak;
\tdefault:
\t\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\t\tbreak;
\t}
""")
patch_function(
    "sub_86EDD968",
    "\tctx.lr = 0x86EDDA20;\n\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);\nloc_86EDDA20:\n",
    "\tctx.lr = 0x86EDDA20;\n" + "".join(initializer_dispatch) + "loc_86EDDA20:\n",
)

# VEngineCvar007 is registered by vstdlib's sub_82E2BC10. Its factory,
# sub_82E101B8, returns the singleton whose constructor installs this vtable.
# Use that factory if the engine's normal factory chain misses the interface.
patch_function(
    "sub_86E34C58",
    """\tctx.lr = 0x86E34CDC;
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\t// rotlwi r10,r3,0
""",
    """\tctx.lr = 0x86E34CDC;
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\tif (ctx.r3.u32 == 0 && REX_LOAD_U32(0x82E31FE8u) == 0x82E00A14u) {
\t\tREX_CALL_INDIRECT_FUNC(0x82E101B8u);
\t}
\t// rotlwi r10,r3,0
""",
)

# Launcher teardown can call this even if the cvar interface never connected.
patch_function(
    "sub_86BE3568",
    """\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + -16552);
\t// lwz r9,0(r3)
""",
    """\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + -16552);
\tif (ctx.r3.u32 == 0) goto clear_cvar_registration;
\t// lwz r9,0(r3)
""",
)
patch_function(
    "sub_86BE3568",
    """\tctx.lr = 0x86BE359C;
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\t// li r7,0
""",
    """\tctx.lr = 0x86BE359C;
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
clear_cvar_registration:
\t// li r7,0
""",
)

# The original factory at 0x832ABB08 has no compiled entry. Its entire body
# loads the model-cache singleton address into r3 and returns.
patch_function(
    "sub_832905F0",
    """\tctx.lr = 0x8329061C;
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
""",
    """\tctx.lr = 0x8329061C;
\tif (ctx.ctr.u32 == 0x832ABB08u) {
\t\tctx.r11.s64 = -2094071808; // lis r11,0x832F
\t\tctx.r3.s64 = ctx.r11.s64 - 16012;
\t} else {
\t\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\t}
""",
    module="datacache",
)


def restore_indirect_target(name, return_address, target, body, *, module="engine"):
    call = f"\tctx.lr = 0x{return_address};\n\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);\n"
    patch_function(
        name, call,
        f"\tctx.lr = 0x{return_address};\n\tif (ctx.ctr.u32 == 0x{target}u) {{\n"
        + body + "\t} else {\n\t\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);\n\t}\n",
        module=module,
    )


# The second callback in sub_86DAC500 has no generated entry point. The
# original PPC at 0x86DAB220 forwards the record's byte flag and handle to
# slot 56 of the same interface used by the adjacent compiled callback.
restore_indirect_target(
    "sub_86DAC498", "86DAC4E4", "86DAB220",
    """\t\tctx.r11.s64 = -2028208128; // lis r11,0x871C
\t\tctx.r5.u64 = REX_LOAD_U8(ctx.r4.u32);
\t\tctx.r4.u64 = REX_LOAD_U32(ctx.r4.u32 + 4);
\t\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 - 11288);
\t\tctx.r10.u64 = REX_LOAD_U32(ctx.r3.u32);
\t\tctx.r9.u64 = REX_LOAD_U32(ctx.r10.u32 + 56);
\t\tctx.ctr.u64 = ctx.r9.u64;
\t\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
""",
)


# This shader API leaf reads one state bit and forwards it through vtable
# slot 0x468. Without it, the shader API loop silently skipped the operation.
restore_indirect_target(
    "sub_852804A0", "85280530", "8527FDC0",
    """\t\tif (ctx.r3.u32 != 0) {
\t\t\tctx.r11.s64 = -2059534336; // lis r11,0x853E
\t\t\tctx.r10.u64 = REX_LOAD_U8(ctx.r3.u32 + 0x45);
\t\t\tctx.r4.u64 = (ctx.r10.u32 >> 4) & 1u;
\t\t\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + 0xE88);
\t\t\tif (ctx.r3.u32 != 0) {
\t\t\t\tctx.r9.u64 = REX_LOAD_U32(ctx.r3.u32);
\t\t\t\tif (ctx.r9.u32 != 0) {
\t\t\t\t\tctx.r8.u64 = REX_LOAD_U32(ctx.r9.u32 + 0x468);
\t\t\t\t\tctx.ctr.u64 = ctx.r8.u64;
\t\t\t\t\tif (ctx.ctr.u32 != 0) REX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\t\t\t\t}
\t\t\t}
\t\t}
""",
    module="shaderapidx9",
)

# Two engine thunks adjust the receiver before tail-calling a compiled method.
for name, return_address, target, adjustment, destination in (
    ("sub_86DCB5C8", "86DCB6E4", "86DC0A60", 4, "86DC0AF0"),
    ("sub_86DF4450", "86DF44D0", "86DC7930", 36, "86DC74D8"),
):
    restore_indirect_target(
        name, return_address, target,
        f"\t\tctx.r3.s64 -= {adjustment};\n\t\tREX_CALL_INDIRECT_FUNC(0x{destination}u);\n",
    )

# Both call sites use the same omitted virtual forwarding thunk.
for name, return_address in (("sub_86DBB188", "86DBB250"), ("sub_86DCB5C8", "86DCB6CC")):
    restore_indirect_target(
        name, return_address, "86DC59A8",
        """\t\tctx.r11.u64 = REX_LOAD_U32(ctx.r3.u32 + 72);
\t\tctx.r3.s64 = ctx.r11.s64 + 64;
\t\tctx.r11.u64 = REX_LOAD_U32(ctx.r11.u32 + 64);
\t\tctx.r11.u64 = REX_LOAD_U32(ctx.r11.u32 + 20);
\t\tctx.ctr.u64 = ctx.r11.u64;
\t\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
""",
    )

# Shutdown also runs if the launcher could not connect the model-cache service.
patch_function(
    "sub_86D104D0",
    """\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + -11264);
\t// lwz r10,0(r3)
""",
    """\tctx.r3.u64 = REX_LOAD_U32(ctx.r11.u32 + -11264);
\tif (ctx.r3.u32 == 0) return;
\t// lwz r10,0(r3)
""",
)

# CreateInterface in datacache_360 tail-calls the factory for the requested interface.
# The MDLCache / VModelLoader singleton factory at 0x832ABB08 loads the singleton address.
patch_function(
    "sub_832C10A0",
    """\t// bctr 
\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
""",
    """\t// bctr 
\tif (ctx.ctr.u32 == 0x832ABB08u) {
\t\tctx.r11.s64 = -2094071808; // lis r11,0x832F
\t\tctx.r3.s64 = ctx.r11.s64 - 16012;
\t} else {
\t\tREX_CALL_INDIRECT_FUNC(ctx.ctr.u32);
\t}
""",
    module="datacache",
)

# Guard sub_86DF36D0 against uninitialized guest subsystem interface.
# When r3 + 132 or its vtable is null, do not dereference null or jump to 0x0.
patch_function(
    "sub_86DF36D0",
    """\t// lwz r3,132(r3)
\tctx.r3.u64 = REX_LOAD_U32(ctx.r3.u32 + 132);
\t// mr r29,r4
""",
    """\t// lwz r3,132(r3)
\tctx.r3.u64 = REX_LOAD_U32(ctx.r3.u32 + 132);
\tif (ctx.r3.u32 == 0) {
\t\tctx.r3.s64 = -1;
\t\tgoto loc_86DF3768;
\t}
\t// mr r29,r4
""",
    module="engine",
)

