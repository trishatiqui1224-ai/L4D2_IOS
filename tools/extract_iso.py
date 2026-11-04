#!/usr/bin/env python3
"""
tools/extract_iso.py
Standalone pure-Python Xbox 360 XDVDFS ISO Extractor & XEX Validator for NFS Carbon (454107EC).
Zero dependencies: standard library Python 3.8+ only.
"""

import argparse
import hashlib
import os
import struct
import sys

SECTOR = 2048
XDVDFS_MAGIC = b"MICROSOFT*XBOX*MEDIA"

KNOWN_BASES = [
    (0x00000000, "Raw partition / extracted image"),
    (0x0FD90000, "XGD2 partition (Standard Xbox 360)"),
    (0x02080000, "XGD3 partition (Late Xbox 360)"),
    (0x18300000, "XGD1 partition (Original Xbox)"),
]

ATTR_DIRECTORY = 0x10
EXPECTED_TITLE_ID = 0x454108D4  # Left 4 Dead 2 (World)


def magic_at(fh, offset):
    try:
        fh.seek(offset + 32 * SECTOR)
        return fh.read(len(XDVDFS_MAGIC)) == XDVDFS_MAGIC
    except OSError:
        return False


def detect_base(fh, limit_scan=1 << 30):
    for base, desc in KNOWN_BASES:
        if magic_at(fh, base):
            return base, desc

    # Fallback brute-force scan
    fh.seek(0, os.SEEK_END)
    size = fh.tell()
    limit = min(size, limit_scan)
    CHUNK = 16 << 20
    overlap = len(XDVDFS_MAGIC)
    pos = 0
    while pos < limit:
        fh.seek(pos)
        buf = fh.read(CHUNK + overlap)
        if not buf:
            break
        idx = buf.find(XDVDFS_MAGIC)
        while idx != -1:
            abs_off = pos + idx
            if abs_off % SECTOR == 0 and abs_off >= 32 * SECTOR:
                base = abs_off - 32 * SECTOR
                if magic_at(fh, base):
                    return base, "Scanned offset"
            idx = buf.find(XDVDFS_MAGIC, idx + 1)
        pos += CHUNK
    return None, None


class DirectoryEntry:
    def __init__(self, name, sector, size, is_dir):
        self.name = name
        self.sector = sector
        self.size = size
        self.is_dir = is_dir


def read_directory(fh, base_offset, root_sector, root_size):
    entries = []
    if root_size == 0:
        return entries

    fh.seek(base_offset + root_sector * SECTOR)
    data = fh.read(root_size)

    def parse_node(offset):
        if offset >= len(data) - 14:
            return
        left_sub = struct.unpack_from("<H", data, offset)[0]
        right_sub = struct.unpack_from("<H", data, offset + 2)[0]
        sector = struct.unpack_from("<I", data, offset + 4)[0]
        file_size = struct.unpack_from("<I", data, offset + 8)[0]
        attr = data[offset + 12]
        name_len = data[offset + 13]

        if name_len > 0 and offset + 14 + name_len <= len(data):
            name = data[offset + 14:offset + 14 + name_len].decode("latin-1", errors="replace")
            is_dir = bool(attr & ATTR_DIRECTORY)
            entries.append(DirectoryEntry(name, sector, file_size, is_dir))

        if left_sub != 0:
            parse_node(left_sub * 4)
        if right_sub != 0:
            parse_node(right_sub * 4)

    parse_node(0)
    return entries


def parse_xex_header(file_path):
    info = {"title_id": 0, "media_id": "", "valid": False}
    if not os.path.exists(file_path):
        return info

    with open(file_path, "rb") as f:
        magic = f.read(4)
        if magic != b"XEX2":
            return info

        f.seek(8)
        header_size = struct.unpack(">I", f.read(4))[0]
        f.seek(16)
        num_fields = struct.unpack(">I", f.read(4))[0]

        for _ in range(num_fields):
            key_data = struct.unpack(">I", f.read(4))[0]
            val_data = struct.unpack(">I", f.read(4))[0]
            # Key 0x00040310: Execution ID
            if (key_data >> 8) == 0x000403:
                pos = f.tell()
                f.seek(val_data)
                exec_data = f.read(24)
                if len(exec_data) >= 12:
                    media_id, ver, base_ver, title_id = struct.unpack(">IIII", exec_data[:16])
                    info["title_id"] = title_id
                    info["media_id"] = f"{media_id:08X}"
                    info["valid"] = True
                f.seek(pos)
                break

    return info


def extract_iso(iso_path, out_dir, solo_xex=False):
    if not os.path.isfile(iso_path):
        sys.exit(f"[ERROR] ISO file not found: {iso_path}")

    with open(iso_path, "rb") as fh:
        base, desc = detect_base(fh)
        if base is None:
            sys.exit(f"[ERROR] Could not find Xbox 360 filesystem in {iso_path}")

        print(f"[ISO] Found {desc} at 0x{base:X}")
        fh.seek(base + 32 * SECTOR + len(XDVDFS_MAGIC))
        root_sector, root_size = struct.unpack("<II", fh.read(8))

        os.makedirs(out_dir, exist_ok=True)

        def extract_tree(sector, size, cur_rel=""):
            entries = read_directory(fh, base, sector, size)
            for e in entries:
                rel = os.path.join(cur_rel, e.name)
                if e.is_dir:
                    if not solo_xex:
                        os.makedirs(os.path.join(out_dir, rel), exist_ok=True)
                        extract_tree(e.sector, e.size, rel)
                else:
                    if solo_xex and e.name.lower() != "default.xex":
                        continue
                    dest = os.path.join(out_dir, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    print(f"  [Extract] {rel} ({e.size:,} bytes)")
                    fh.seek(base + e.sector * SECTOR)
                    with open(dest, "wb") as out_f:
                        remaining = e.size
                        while remaining > 0:
                            chunk = fh.read(min(remaining, 1 << 20))
                            if not chunk:
                                break
                            out_f.write(chunk)
                            remaining -= len(chunk)

        extract_tree(root_sector, root_size)

    xex_path = os.path.join(out_dir, "default.xex")
    if os.path.exists(xex_path):
        info = parse_xex_header(xex_path)
        sha = hashlib.sha256(open(xex_path, "rb").read()).hexdigest()
        print(f"\n[XEX Info] Title ID: {info['title_id']:08X} (Expected: {EXPECTED_TITLE_ID:08X})")
        print(f"[XEX Info] SHA-256:  {sha}")
        if info["title_id"] == EXPECTED_TITLE_ID:
            print("[XEX Info] VERIFIED: Valid Need for Speed: Carbon Xbox 360 binary!")
        else:
            print("[XEX Info] NOTE: Title ID differs from retail retail Carbon (454107EC).")


def main():
    parser = argparse.ArgumentParser(description="Extract Xbox 360 ISO & Inspect default.xex")
    parser.add_argument("iso", help="Path to Xbox 360 ISO file or default.xex")
    parser.add_argument("-o", "--output", default="game", help="Output directory")
    parser.add_argument("--solo-xex", action="store_true", help="Extract only default.xex")
    args = parser.parse_args()

    if args.iso.lower().endswith(".xex"):
        info = parse_xex_header(args.iso)
        sha = hashlib.sha256(open(args.iso, "rb").read()).hexdigest()
        print(f"[XEX Info] File:     {args.iso}")
        print(f"[XEX Info] Title ID: {info['title_id']:08X}")
        print(f"[XEX Info] SHA-256:  {sha}")
    else:
        extract_iso(args.iso, args.output, solo_xex=args.solo_xex)


if __name__ == "__main__":
    main()
