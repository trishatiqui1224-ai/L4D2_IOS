#!/usr/bin/env python3
"""
tools/preparar_sdk.py - Prepares ReXGlue SDK base for NFS Carbon.
"""

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]

SDK_REPO = "https://github.com/rexglue/rexglue-sdk.git"
SDK_TAG = "v0.10.0"

REF_COMMIT = "0a79f938ab839c187d25bd7bf48e51e30a6150be"
REF_URL = (
    "https://raw.githubusercontent.com/deivid22srk/hells-gate-recomp-android/"
    f"{REF_COMMIT}/patches/sdk/"
)
PARCHES_REF = [
    ("rexglue-sdk-v0.10.0-android.patch", []),
    ("rexglue-sdk-v0.10.0-android-perf.patch", ["src/system/mmio_handler.cpp"]),
]

PARCHES_PROYECTO = [
    "parche_diagnostico",
    "parche_anillo",
    "parche_desatasco",
    "parche_restaurar",
    "parche_velocidad",
    "parche_backend",
    "parche_privilegios",
    "parche_iso",
    "parche_turnip",
    "parche_pausa",
    "parche_fps",
    "parche_pipeline",
    "parche_fallos",
    "parche_esperas",
    "parche_teclado",
    "parche_tiempos",
    "parche_espera_anillo",
    "parche_cola_presentar",
    "parche_subidas",
    "parche_cvars",
    "parche_fences",
    "parche_area",
    "parche_vblank",
    "parche_msaa",
    "parche_xma_paquetes",
    "parche_xma_edge",
    "parche_anillo_bloques",
    "parche_una_pasada",
    "parche_camino_edram",
    "parche_gamertag",
    "parche_cache_pipelines",
]


def run(cmd, cwd=None, check=True, quiet=False):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and r.returncode != 0:
        if r.stdout:
            sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        sys.exit(f"[ERROR] Failed: {' '.join(str(c) for c in cmd)}")
    if not quiet and r.stdout.strip():
        print(r.stdout.rstrip())
    return r


def paso(n, texto):
    print(f"\n== {n}. {texto}")


def clonar(sdk):
    if (sdk / "CMakeLists.txt").exists():
        print(f"[ok] Already cloned at {sdk}")
    else:
        print(f"[..] Cloning rexglue-sdk ({SDK_TAG})...")
        run(["git", "clone", "--branch", SDK_TAG, "--depth", "1", SDK_REPO, str(sdk)])

    # Ensure git tags are fetched and reachable so rex_compute_version resolves cleanly
    run(["git", "fetch", "--tags", "--depth=1"], cwd=sdk, check=False, quiet=True)
    chk = run(["git", "describe", "--tags", "--match", "v*"], cwd=sdk, check=False, quiet=True)
    if chk.returncode != 0:
        run(["git", "tag", "-f", SDK_TAG, "HEAD"], cwd=sdk, check=False, quiet=True)
        print(f"[ok] Tagged {SDK_TAG} on HEAD")

    run(
        [
            "git",
            "-c",
            "core.symlinks=false",
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--depth",
            "1",
        ],
        cwd=sdk,
        quiet=True,
    )
    print("[ok] Submodules up to date")


def symlinks_de(repo, prefijo):
    r = run(["git", "ls-files", "-s"], cwd=repo, quiet=True)
    for linea in r.stdout.splitlines():
        modo, _, _, ruta = linea.split(maxsplit=3)
        if modo == "120000":
            yield prefijo / ruta


def reparar_symlinks(sdk):
    enlaces = list(symlinks_de(sdk, pathlib.Path(".")))
    subs = run(
        ["git", "submodule", "foreach", "--quiet", "--recursive", "echo $displaypath"],
        cwd=sdk,
        quiet=True,
    ).stdout.split()
    for sub in subs:
        enlaces += list(symlinks_de(sdk / sub, pathlib.Path(sub)))

    reparados = 0
    for rel in enlaces:
        f = sdk / rel
        if f.is_symlink() or not f.is_file() or f.stat().st_size > 512:
            continue
        destino_txt = f.read_text(encoding="utf-8", errors="replace").strip()
        destino = (f.parent / destino_txt).resolve()
        if not destino.is_file():
            continue
        shutil.copyfile(destino, f)
        reparados += 1
    print(f"[ok] {reparados} symlinks replaced with copies ({len(enlaces)} total symlinks)")


def aplicar_parches_ref(sdk):
    carpeta = sdk / ".nfsc-ios"
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, excluir in PARCHES_REF:
        f = carpeta / nombre
        if not f.exists():
            print(f"[..] Downloading {nombre} (commit {REF_COMMIT[:8]})")
            try:
                with urllib.request.urlopen(REF_URL + nombre, timeout=60) as resp:
                    f.write_bytes(resp.read())
            except Exception as e:
                print(f"[WARN] Failed to download {nombre}: {e}")
                continue

        marca = carpeta / (nombre + ".aplicado")
        extra = [f"--exclude={e}" for e in excluir]
        base = ["git", "apply", "--whitespace=nowarn", *extra]
        if marca.exists():
            print(f"[ok] {nombre} already applied")
        elif run([*base, "--check", str(f)], cwd=sdk, check=False, quiet=True).returncode == 0:
            run([*base, str(f)], cwd=sdk)
            marca.write_text(REF_COMMIT + "\n", encoding="utf-8")
            print(f"[ok] Applied {nombre}")
        else:
            r = run([*base, "--check", str(f)], cwd=sdk, check=False, quiet=True)
            if r.stderr:
                sys.stderr.write(r.stderr)
            print(f"[WARN] {nombre} cannot be applied or is already applied.")


def parches_proyecto(sdk, estado=False):
    env = dict(
        os.environ,
        NFSCARBON_SDK=str(sdk),
        NFSC_SDK=str(sdk),
        NFSMW_SDK=str(sdk),
    )
    for p in PARCHES_PROYECTO:
        patch_script = RAIZ / "tools" / f"{p}.py"
        if not patch_script.exists():
            print(f"[WARN] Patch script not found: {patch_script}")
            continue
        cmd = [sys.executable, str(patch_script)]
        if estado:
            cmd.append("--estado")
        r = subprocess.run(cmd, env=env, text=True, capture_output=True)
        salida = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            print(salida)
            sys.exit(f"[ERROR] {p} failed. Re-running is safe once resolved.")
        if estado:
            print(salida)
        else:
            primera = next((l for l in salida.splitlines() if l.startswith("[")), "")
            print(f"  {p:24s} {primera}")


def main():
    ap = argparse.ArgumentParser(description="Prepares ReXGlue SDK for NFS Carbon.")
    ap.add_argument("--sdk", default=str(RAIZ.parent / "rexglue-sdk-ios"),
                    help="SDK directory (default: ../rexglue-sdk-ios)")
    ap.add_argument("--estado", action="store_true", help="Report patch status")
    args = ap.parse_args()
    sdk = pathlib.Path(args.sdk).resolve()

    if args.estado:
        if not (sdk / "CMakeLists.txt").exists():
            sys.exit(f"[ERROR] No SDK in {sdk}")
        parches_proyecto(sdk, estado=True)
        return 0

    paso(1, f"SDK {SDK_TAG}")
    clonar(sdk)
    paso(2, "Symlinks")
    reparar_symlinks(sdk)
    paso(3, "ARM64 Memory Barrier Patches")
    aplicar_parches_ref(sdk)
    paso(4, "Project Patches")
    parches_proyecto(sdk)

    print(f"\n[ok] SDK base ready in {sdk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
