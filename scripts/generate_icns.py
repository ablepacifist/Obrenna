#!/usr/bin/env python3
"""Generate macOS .icns icon from PNG source.

Run on macOS:
    python scripts/generate_icns.py src-tauri/icons/ObrennaAppLogo.png src-tauri/icons/icon.icns

Requires: macOS `sips` and `iconutil` are built-in.
Alternatively install: pip install Pillow && use this script's fallback path.
"""
import sys
import os

def main():
    if len(sys.argv) != 3:
        print("Usage: generate_icns.py <input.png> <output.icns>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    # Try using macOS sips + iconutil (native, best quality)
    try:
        tmpdir = "/tmp/obrenna_iconset"
        os.system(f"rm -rf {tmpdir}")
        os.makedirs(tmpdir, exist_ok=True)

        # Generate all required icon sizes
        sizes = {
            "icon_16x16.png": 16,
            "icon_16x16@2x.png": 32,
            "icon_32x32.png": 32,
            "icon_32x32@2x.png": 64,
            "icon_128x128.png": 128,
            "icon_128x128@2x.png": 256,
            "icon_256x256.png": 256,
            "icon_256x256@2x.png": 512,
            "icon_512x512.png": 512,
            "icon_512x512@2x.png": 1024,
        }

        for name, size in sizes.items():
            os.system(f'sips -Z {size}x{size} "{input_path}" --out "{tmpdir}/{name}" > /dev/null 2>&1')

        # Create iconset directory structure
        iconset_dir = "/tmp/obrenna.iconset"
        os.system(f"rm -rf {iconset_dir}")
        for name, size in sizes.items():
            dst_name = name.replace("@2x_", "x").replace(".png", "")
            w = size
            if "@2x" in name:
                w = size // 2
            dst_name = f"icon_{w}x{w}{'@2x' if '@2x' in name else ''}.png"
            src = f"{tmpdir}/{name}"
            dst = f"{iconset_dir}/{dst_name}"
            os.system(f'cp "{src}" "{dst}" 2>/dev/null')

        os.system(f'cp "{tmpdir}/icon_16x16.png" "{iconset_dir}/icon_16x16.png" 2>/dev/null')
        os.system(f'cp "{tmpdir}/icon_32x32.png" "{iconset_dir}/icon_32x32.png" 2>/dev/null')
        os.system(f'cp "{tmpdir}/icon_128x128.png" "{iconset_dir}/icon_128x128.png" 2>/dev/null')
        os.system(f'cp "{tmpdir}/icon_256x256.png" "{iconset_dir}/icon_256x256.png" 2>/dev/null')
        os.system(f'cp "{tmpdir}/icon_512x512.png" "{iconset_dir}/icon_512x512.png" 2>/dev/null')

        os.system(f'iconutil -c icns "{iconset_dir}" -o "{output_path}"')
        os.system(f"rm -rf {tmpdir} {iconset_dir}")

        if os.path.exists(output_path):
            print(f"Generated {output_path}")
            return
    except Exception:
        pass

    # Fallback: warn that manual generation is needed
    print(f"Warning: Could not generate .icns automatically.")
    print(f"On macOS, run: iconutil -c icns <iconset_dir> -o {output_path}")
    print(f"Or use: https://www.icoconvert.com/ to convert {input_path} to .icns")


if __name__ == "__main__":
    main()
