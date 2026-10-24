#!/usr/bin/env python3
"""Pixel-level assertions for the Fire-X B4 browser screenshots.

Fire outline color ~ #d65916 (warning @ 0.6). Detection: red-dominant, low blue.
The 3D canvas is the left ~900px of the 1280px viewport; the right side is the
inspector panel (whose amber UI tags are excluded by the canvas region + strict
threshold).

Usage (run with the backend venv, which has Pillow):
  python analyze_fire_pixels.py count <png> [x_limit]
  python analyze_fire_pixels.py assert-present <png> [x_limit]
  python analyze_fire_pixels.py assert-gone <png> [x_limit]
  python analyze_fire_pixels.py assert-grew <png1> <png2> [factor]
  python analyze_fire_pixels.py assert-stable <png1> <png2> [tolerance]
  python analyze_fire_pixels.py assert-terrain <png> [x_limit] [min_pixels]
Exit non-zero when the assertion fails (used by the browser verification).
"""
import sys

from PIL import Image


def fire_pixels(path, x_limit):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    px = im.load()
    pts = []
    for y in range(h):
        for x in range(min(w, x_limit)):
            r, g, b = px[x, y]
            if r > 150 and (r - g) > 80 and b < 80:
                pts.append((x, y))
    xs = [p[0] for p in pts] if pts else []
    ys = [p[1] for p in pts] if pts else []
    bbox = (min(xs), min(ys), max(xs), max(ys)) if pts else None
    return len(pts), bbox


def terrain_pixels(path, x_limit):
    """Count canvas pixels that are NOT the clear-color background (#0c1927).
    Proves the terrain/model is still rendered (e.g. after the overlay clears)."""
    im = Image.open(path).convert('RGB')
    w, h = im.size
    px = im.load()
    n = 0
    for y in range(h):
        for x in range(min(w, x_limit)):
            r, g, b = px[x, y]
            if abs(r - 12) + abs(g - 25) + abs(b - 39) > 90:
                n += 1
    return n


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == 'count':
        png = argv[1]
        x_limit = int(argv[2]) if len(argv) > 2 else 900
        n, bbox = fire_pixels(png, x_limit)
        print(f'{png}: count={n} bbox={bbox}')
        return 0
    if cmd == 'assert-present':
        png = argv[1]
        x_limit = int(argv[2]) if len(argv) > 2 else 900
        n, bbox = fire_pixels(png, x_limit)
        print(f'{png}: count={n} bbox={bbox}')
        if n == 0:
            print('FAIL: expected fire outline pixels, found none')
            return 1
        print('PASS: fire outline present')
        return 0
    if cmd == 'assert-gone':
        png = argv[1]
        x_limit = int(argv[2]) if len(argv) > 2 else 900
        n, bbox = fire_pixels(png, x_limit)
        print(f'{png}: count={n} bbox={bbox}')
        if n > 0:
            print(f'FAIL: expected no fire outline, found {n} pixels')
            return 1
        print('PASS: fire outline cleared')
        return 0
    if cmd == 'assert-grew':
        png1, png2 = argv[1], argv[2]
        factor = float(argv[3]) if len(argv) > 3 else 2.0
        n1, _ = fire_pixels(png1, 900)
        n2, b2 = fire_pixels(png2, 900)
        print(f'{png1}: {n1}  {png2}: {n2} bbox={b2} (need >= {n1}x{factor})')
        if n1 == 0 or n2 < n1 * factor:
            print('FAIL: outline did not grow as expected')
            return 1
        print('PASS: outline grew on new revision')
        return 0
    if cmd == 'assert-stable':
        png1, png2 = argv[1], argv[2]
        tol = int(argv[3]) if len(argv) > 3 else 10
        n1, _ = fire_pixels(png1, 900)
        n2, _ = fire_pixels(png2, 900)
        print(f'{png1}: {n1}  {png2}: {n2} (tolerance +/-{tol})')
        if abs(n1 - n2) > tol:
            print('FAIL: outline changed while no new revision arrived')
            return 1
        print('PASS: outline stable after uploads stopped')
        return 0
    if cmd == 'assert-terrain':
        png = argv[1]
        x_limit = int(argv[2]) if len(argv) > 2 else 900
        min_pixels = int(argv[3]) if len(argv) > 3 else 5000
        n = terrain_pixels(png, x_limit)
        print(f'{png}: terrain_pixels={n} (need >= {min_pixels})')
        if n < min_pixels:
            print('FAIL: terrain/model not visible (canvas appears blank)')
            return 1
        print('PASS: terrain still visible')
        return 0
    print(f'unknown command: {cmd}')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
