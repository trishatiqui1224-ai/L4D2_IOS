#!/usr/bin/env python3
"""
tools/generate_appicon.py
Generates Apple iOS/iPadOS AppIcon.appiconset assets for Left 4 Dead 2 Native Recompilation.
Conforms strictly to Apple App Store asset specifications:
- 1024x1024 master opaque RGB (NO alpha channel)
- High-order Lanczos downsampling for all required device resolutions
- Standard Xcode Contents.json descriptor
"""

import json
import math
import pathlib
import random
import sys
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPICONSET_DIR = ROOT / "ios" / "resources" / "Assets.xcassets" / "AppIcon.appiconset"

ICON_SPECS = [
    # Universal / App Store
    {"idiom": "universal", "size": "1024x1024", "scale": "1x", "pixels": 1024, "filename": "AppIcon-1024.png", "platform": "ios"},
    # iPhone
    {"idiom": "iphone", "size": "20x20", "scale": "2x", "pixels": 40, "filename": "AppIcon-20@2x.png"},
    {"idiom": "iphone", "size": "20x20", "scale": "3x", "pixels": 60, "filename": "AppIcon-20@3x.png"},
    {"idiom": "iphone", "size": "29x29", "scale": "2x", "pixels": 58, "filename": "AppIcon-29@2x.png"},
    {"idiom": "iphone", "size": "29x29", "scale": "3x", "pixels": 87, "filename": "AppIcon-29@3x.png"},
    {"idiom": "iphone", "size": "40x40", "scale": "2x", "pixels": 80, "filename": "AppIcon-40@2x.png"},
    {"idiom": "iphone", "size": "40x40", "scale": "3x", "pixels": 120, "filename": "AppIcon-40@3x.png"},
    {"idiom": "iphone", "size": "60x60", "scale": "2x", "pixels": 120, "filename": "AppIcon-60@2x.png"},
    {"idiom": "iphone", "size": "60x60", "scale": "3x", "pixels": 180, "filename": "AppIcon-60@3x.png"},
    # iPad
    {"idiom": "ipad", "size": "20x20", "scale": "1x", "pixels": 20, "filename": "AppIcon-20@1x.png"},
    {"idiom": "ipad", "size": "20x20", "scale": "2x", "pixels": 40, "filename": "AppIcon-20@2x-ipad.png"},
    {"idiom": "ipad", "size": "29x29", "scale": "1x", "pixels": 29, "filename": "AppIcon-29@1x.png"},
    {"idiom": "ipad", "size": "29x29", "scale": "2x", "pixels": 58, "filename": "AppIcon-29@2x-ipad.png"},
    {"idiom": "ipad", "size": "40x40", "scale": "1x", "pixels": 40, "filename": "AppIcon-40@1x.png"},
    {"idiom": "ipad", "size": "40x40", "scale": "2x", "pixels": 80, "filename": "AppIcon-40@2x-ipad.png"},
    {"idiom": "ipad", "size": "76x76", "scale": "1x", "pixels": 76, "filename": "AppIcon-76@1x.png"},
    {"idiom": "ipad", "size": "76x76", "scale": "2x", "pixels": 152, "filename": "AppIcon-76@2x.png"},
    {"idiom": "ipad", "size": "83.5x83.5", "scale": "2x", "pixels": 167, "filename": "AppIcon-83.5@2x.png"},
]


def render_master_icon(size: int = 1024) -> Image.Image:
    """Renders the authentic Left 4 Dead 2 two-finger severed zombie hand icon."""
    random.seed(454108)  # Deterministic seed based on Title ID
    img = Image.new("RGB", (size, size), (11, 14, 11))
    draw = ImageDraw.Draw(img)

    # 1. Background Swamp/Dead Center Gradient
    for y in range(size):
        t = y / size
        # #0B0E0B (11, 14, 11) to #1B2418 (27, 36, 24)
        r = int(11 + t * 16)
        g = int(14 + t * 22)
        b = int(11 + t * 13)
        draw.line([(0, y), (size, y)], fill=(r, g, b))

    # 2. Ambient apocalyptic glow (toxic amber & blood-crimson)
    glow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    # Toxic amber glow center-left
    glow_draw.ellipse([size * 0.1, size * 0.2, size * 0.9, size * 0.9], fill=(46, 55, 18, 60))
    # Blood red rim glow lower right
    glow_draw.ellipse([size * 0.3, size * 0.5, size * 1.1, size * 1.1], fill=(90, 15, 15, 80))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(size * 0.08))
    img.paste(glow_layer, (0, 0), glow_layer)

    # 3. Zombie Hand Drawing Layer
    hand_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(hand_layer)

    # Coordinates scaled to 1024
    # Wrist / Arm Base
    wrist = [
        (size * 0.38, size * 1.05),
        (size * 0.32, size * 0.82),
        (size * 0.36, size * 0.68),
        (size * 0.64, size * 0.68),
        (size * 0.70, size * 0.85),
        (size * 0.66, size * 1.05),
    ]
    # Palm body
    palm = [
        (size * 0.35, size * 0.69),
        (size * 0.30, size * 0.54),
        (size * 0.34, size * 0.45),
        (size * 0.44, size * 0.38),
        (size * 0.58, size * 0.38),
        (size * 0.69, size * 0.46),
        (size * 0.72, size * 0.58),
        (size * 0.65, size * 0.69),
    ]

    # Two prominent raised fingers: Index finger and Middle finger (Left 4 Dead "2")
    # Index finger (left raised finger)
    index_finger = [
        (size * 0.41, size * 0.38),
        (size * 0.39, size * 0.28),
        (size * 0.38, size * 0.18),
        (size * 0.40, size * 0.14),
        (size * 0.45, size * 0.14),
        (size * 0.47, size * 0.20),
        (size * 0.48, size * 0.38),
    ]

    # Middle finger (right raised finger)
    middle_finger = [
        (size * 0.51, size * 0.38),
        (size * 0.52, size * 0.24),
        (size * 0.53, size * 0.13),
        (size * 0.56, size * 0.10),
        (size * 0.62, size * 0.11),
        (size * 0.63, size * 0.18),
        (size * 0.61, size * 0.38),
    ]

    # Severed Thumb Stump (Left side) - bitten off with bone protruding
    thumb_stump = [
        (size * 0.31, size * 0.56),
        (size * 0.22, size * 0.50),
        (size * 0.20, size * 0.47),
        (size * 0.24, size * 0.44),
        (size * 0.32, size * 0.48),
    ]

    # Curled Severed Ring & Pinky Stump (Right side)
    ring_pinky_stump = [
        (size * 0.63, size * 0.39),
        (size * 0.71, size * 0.42),
        (size * 0.73, size * 0.51),
        (size * 0.67, size * 0.55),
        (size * 0.62, size * 0.48),
    ]

    # Draw Hand Silhouette & Dark Outline
    outline_color = (20, 26, 18, 255)
    flesh_base = (138, 154, 122, 255)       # Decaying pale green flesh
    flesh_highlight = (175, 192, 156, 255)  # Bone/pale tone
    flesh_shadow = (75, 92, 65, 255)        # Rotting green shadow
    bone_color = (215, 222, 205, 255)       # Exposed white bone

    # Polygons filled with flesh
    for poly in [wrist, palm, index_finger, middle_finger, thumb_stump, ring_pinky_stump]:
        hdraw.polygon(poly, fill=flesh_base)

    # Shading / Contours
    # Shadow side of fingers (inner crease)
    hdraw.polygon([(size * 0.47, size * 0.38), (size * 0.46, size * 0.20), (size * 0.52, size * 0.22), (size * 0.51, size * 0.38)], fill=flesh_shadow)
    # Palm crease & muscle definition
    hdraw.line([(size * 0.40, size * 0.55), (size * 0.55, size * 0.60)], fill=flesh_shadow, width=int(size * 0.015))
    hdraw.line([(size * 0.42, size * 0.46), (size * 0.58, size * 0.48)], fill=flesh_shadow, width=int(size * 0.012))

    # Exposed Thumb Bone Tip
    hdraw.polygon([(size * 0.19, size * 0.49), (size * 0.16, size * 0.46), (size * 0.22, size * 0.43)], fill=bone_color)
    # Exposed Ring Finger Bone Fragment
    hdraw.polygon([(size * 0.70, size * 0.41), (size * 0.75, size * 0.40), (size * 0.72, size * 0.44)], fill=bone_color)

    # Highlights on finger tips
    hdraw.ellipse([size * 0.40, size * 0.14, size * 0.44, size * 0.22], fill=flesh_highlight)
    hdraw.ellipse([size * 0.54, size * 0.11, size * 0.60, size * 0.20], fill=flesh_highlight)

    # Grungy weathered outlines
    for poly in [index_finger, middle_finger, thumb_stump, ring_pinky_stump, palm, wrist]:
        hdraw.line(poly + [poly[0]], fill=outline_color, width=int(size * 0.012))

    # Knuckle Creases
    for y_knuckle in [0.24, 0.32]:
        hdraw.line([(size * 0.40, size * y_knuckle), (size * 0.46, size * (y_knuckle + 0.01))], fill=outline_color, width=int(size * 0.008))
        hdraw.line([(size * 0.53, size * (y_knuckle - 0.02)), (size * 0.61, size * (y_knuckle - 0.01))], fill=outline_color, width=int(size * 0.008))

    # 4. Blood Splatter & Gore Details
    gore_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gore_layer)

    blood_dark = (110, 12, 12, 230)
    blood_crimson = (179, 27, 27, 245)
    blood_fresh = (210, 35, 35, 220)

    # Severed thumb gore
    gdraw.ellipse([size * 0.17, size * 0.44, size * 0.25, size * 0.52], fill=blood_dark)
    gdraw.ellipse([size * 0.19, size * 0.46, size * 0.23, size * 0.50], fill=blood_crimson)
    # Blood drips down thumb
    gdraw.line([(size * 0.21, size * 0.51), (size * 0.21, size * 0.62)], fill=blood_crimson, width=int(size * 0.01))
    gdraw.circle((size * 0.21, size * 0.62), int(size * 0.008), fill=blood_crimson)

    # Severed ring finger gore
    gdraw.ellipse([size * 0.68, size * 0.40, size * 0.74, size * 0.48], fill=blood_dark)
    gdraw.ellipse([size * 0.69, size * 0.42, size * 0.72, size * 0.46], fill=blood_crimson)
    # Blood drip down side of palm
    gdraw.line([(size * 0.71, size * 0.47), (size * 0.72, size * 0.65)], fill=blood_crimson, width=int(size * 0.008))

    # Splatters across palm and fingers
    splatters = [
        (0.44, 0.20, 0.02),
        (0.55, 0.28, 0.025),
        (0.58, 0.16, 0.015),
        (0.42, 0.45, 0.035),
        (0.52, 0.52, 0.04),
        (0.48, 0.62, 0.045),
        (0.38, 0.75, 0.05),
        (0.60, 0.78, 0.035),
        (0.45, 0.88, 0.06),
        # Spray droplets
        (0.35, 0.25, 0.008),
        (0.37, 0.12, 0.006),
        (0.65, 0.12, 0.007),
        (0.66, 0.26, 0.01),
        (0.28, 0.38, 0.009),
        (0.72, 0.33, 0.008),
    ]
    for sx, sy, srad in splatters:
        cx, cy, r_px = size * sx, size * sy, size * srad
        gdraw.ellipse([cx - r_px, cy - r_px, cx + r_px, cy + r_px], fill=blood_dark)
        gdraw.ellipse([cx - r_px * 0.7, cy - r_px * 0.7, cx + r_px * 0.7, cy + r_px * 0.7], fill=blood_crimson)

    # 5. Composite layers
    img.paste(hand_layer, (0, 0), hand_layer)
    img.paste(gore_layer, (0, 0), gore_layer)

    # 6. Subtle vignette & distressed grain
    vignette = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for i in range(16):
        inset = int(i * (size * 0.02))
        alpha = int(8 + i * 10)
        vdraw.rectangle([inset, inset, size - inset, size - inset], outline=(0, 0, 0, alpha), width=int(size * 0.02))
    vignette = vignette.filter(ImageFilter.GaussianBlur(size * 0.05))
    img.paste(vignette, (0, 0), vignette)

    return img.convert("RGB")


def main():
    print(f"[generate_appicon] Generating L4D2 Recomp master app icon...")
    master = render_master_icon(1024)

    APPICONSET_DIR.mkdir(parents=True, exist_ok=True)
    master_path = APPICONSET_DIR / "AppIcon-1024.png"
    master.save(master_path, format="PNG", optimize=True)
    print(f"[generate_appicon] Saved master 1024x1024 icon to {master_path}")

    # Generate all iOS AppIcon variants
    contents_images = []
    for spec in ICON_SPECS:
        px = spec["pixels"]
        fn = spec["filename"]
        out_path = APPICONSET_DIR / fn
        if px == 1024:
            resized = master
        else:
            resized = master.resize((px, px), Image.Resampling.LANCZOS)
            # Gentle unsharp mask for crisp thumb rendition
            resized = resized.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))

        resized.save(out_path, format="PNG", optimize=True)
        print(f"  Generated {fn:<22} ({px}x{px})")

        img_entry = {
            "idiom": spec["idiom"],
            "size": spec["size"],
            "scale": spec["scale"],
            "filename": fn,
        }
        if "platform" in spec:
            img_entry["platform"] = spec["platform"]
        contents_images.append(img_entry)

    # Write Contents.json
    contents = {
        "images": contents_images,
        "info": {
            "author": "xcode",
            "version": 1
        }
    }
    contents_path = APPICONSET_DIR / "Contents.json"
    with open(contents_path, "w", encoding="utf-8") as f:
        json.dump(contents, f, indent=2)
    print(f"[generate_appicon] Contents.json written successfully with {len(contents_images)} images.")


if __name__ == "__main__":
    main()
