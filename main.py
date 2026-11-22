#!/usr/bin/env python3
"""The picture that tastes of one ingredient — make.fun entry.

A program that writes one food picture to /output/entry.png.
The picture is drawn procedurally, pixel by pixel, with the Python
standard library only (no network, no third-party packages, no
downloaded photos): a top-down bowl of ramen — glossy golden broth,
wheat noodle swirls, chashu, a soft egg with a molten yolk, green
onion, nori and rising steam — on a warm dark wood table, lit from
the top left. One hero dish, no text, big and high-contrast so it
reads clearly even at ~300 px.

Deterministic: fixed geometry and colours, no randomness, no time or
environment input, so two runs produce byte-identical output.
"""

import math
import os
import struct
import zlib

W = H = 1024
OUT_PATH = "/output/entry.png"

# ---------------------------------------------------------------- canvas
buf = bytearray(W * H * 3)


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def mix(a, b, t):
    return a + (b - a) * t


def put(x, y, r, g, b, a):
    """Blend one pixel (integer coords, 0..255 colours, 0..1 alpha)."""
    if a <= 0.0 or x < 0 or x >= W or y < 0 or y >= H:
        return
    i = (y * W + x) * 3
    if a >= 1.0:
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b
        return
    ia = 1.0 - a
    buf[i] = int(r * a + buf[i] * ia + 0.5)
    buf[i + 1] = int(g * a + buf[i + 1] * ia + 0.5)
    buf[i + 2] = int(b * a + buf[i + 2] * ia + 0.5)


def hspan(y, x0, x1, r, g, b, a=1.0):
    """Fill a horizontal run on row y (float x bounds, AA at the ends)."""
    if y < 0 or y >= H or x1 <= x0:
        return
    lo = int(math.floor(x0))
    hi = int(math.ceil(x1)) - 1
    if hi < 0 or lo >= W:
        return
    if a >= 1.0:
        s = max(lo, 0)
        e = min(hi, W - 1)
        i = (y * W + s) * 3
        n = e - s + 1
        buf[i:i + n * 3] = bytes((r, g, b)) * n
        # AA the two fractional edge pixels
        if lo >= 0:
            put(lo, y, r, g, b, clamp(lo + 1.0 - x0))
        if hi < W:
            put(hi, y, r, g, b, clamp(x1 - hi))
    else:
        for x in range(max(lo, 0), min(hi, W - 1) + 1):
            cov = min(1.0, min(x + 1.0 - x0, x1 - x))
            put(x, y, r, g, b, a * clamp(cov))


def disc(cx, cy, rad, col, a=1.0):
    """Filled circle with a 1 px antialiased edge."""
    r, g, b = col
    y0 = max(0, int(cy - rad - 1))
    y1 = min(H - 1, int(cy + rad + 1))
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) - cy
        d2 = rad * rad - dy * dy
        if d2 <= 0:
            continue
        dx = math.sqrt(d2)
        hspan(y, cx - dx, cx + dx, r, g, b, a)


def soft_disc(cx, cy, rad, col, peak=0.25):
    """Radial falloff glow: alpha peaks at centre, fades to 0 at edge."""
    r, g, b = col
    y0 = max(0, int(cy - rad))
    y1 = min(H - 1, int(cy + rad))
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) - cy
        for x in range(max(0, int(cx - rad)), min(W - 1, int(cx + rad)) + 1):
            ddx = (x + 0.5) - cx
            d = math.sqrt(ddx * ddx + dy * dy) / rad
            if d >= 1.0:
                continue
            t = 1.0 - d
            put(x, y, r, g, b, peak * t * t)


def radial_disc(cx, cy, rad, c_in, c_out, a=1.0, power=1.0):
    """Filled circle shaded centre -> edge (radial gradient)."""
    y0 = max(0, int(cy - rad - 1))
    y1 = min(H - 1, int(cy + rad + 1))
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) - cy
        d2 = rad * rad - dy * dy
        if d2 <= 0:
            continue
        dx = math.sqrt(d2)
        x0 = max(0, int(math.ceil(cx - dx)))
        x1 = min(W - 1, int(math.floor(cx + dx)))
        for x in range(x0, x1 + 1):
            ddx = (x + 0.5) - cx
            t = math.sqrt(ddx * ddx + dy * dy) / rad
            t = clamp(t) ** power
            r = int(mix(c_in[0], c_out[0], t) + 0.5)
            g = int(mix(c_in[1], c_out[1], t) + 0.5)
            bl = int(mix(c_in[2], c_out[2], t) + 0.5)
            # AA the rim: fade within the last pixel of radius
            aa = clamp(rad + 0.5 - math.sqrt(ddx * ddx + dy * dy))
            put(x, y, r, g, bl, a * aa)


def ellipse(cx, cy, rx, ry, col, a=1.0, rot=0.0):
    """Filled rotated ellipse with a 1 px antialiased edge."""
    r, g, b = col
    cr, sr = math.cos(rot), math.sin(rot)
    y0 = max(0, int(cy - max(rx, ry) - 1))
    y1 = min(H - 1, int(cy + max(rx, ry) + 1))
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) - cy
        # solve for x range of the rotated ellipse on this row
        # ((x')/rx)^2 + ((y')/ry)^2 = 1 with x' = dx*cr + dy*sr
        # -> quadratic in dx; use sampling of the unrotated row band
        # simpler: scan x across the bounding box, test normalised dist
        x0 = max(0, int(cx - max(rx, ry) - 1))
        x1 = min(W - 1, int(cx + max(rx, ry) + 1))
        for x in range(x0, x1 + 1):
            ddx = (x + 0.5) - cx
            ex = ddx * cr + dy * sr
            ey = -ddx * sr + dy * cr
            q = (ex / rx) ** 2 + (ey / ry) ** 2
            if q >= 1.02:
                continue
            aa = clamp((1.0 - math.sqrt(q)) * min(rx, ry) + 0.5)
            put(x, y, r, g, b, a * aa)


def poly(points, col, a=1.0):
    """Filled polygon (scanline, no AA — used for flat shapes)."""
    r, g, b = col
    ys = [p[1] for p in points]
    y0 = max(0, int(min(ys)))
    y1 = min(H - 1, int(max(ys)))
    n = len(points)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x1, y1p = points[i]
            x2, y2p = points[(i + 1) % n]
            if (y1p <= yc < y2p) or (y2p <= yc < y1p):
                t = (yc - y1p) / (y2p - y1p)
                xs.append(x1 + t * (x2 - x1))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            hspan(y, xs[k], xs[k + 1], r, g, b, a)


def stroke_path(points, width, col, a=1.0):
    """Thick polyline drawn as overlapping discs (round caps/joins)."""
    rad = width / 2.0
    step = max(1.0, rad * 0.55)
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(seg / step))
        for k in range(n + 1):
            t = k / n
            disc(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, rad, col, a)


def arc_points(cx, cy, rad, a0, a1, step_deg=2.0, wobble=0.0, phase=0.0):
    pts = []
    n = max(2, int(abs(a1 - a0) / math.radians(step_deg)))
    for k in range(n + 1):
        t = a0 + (a1 - a0) * k / n
        rr = rad + wobble * math.sin(t * 3.0 + phase)
        pts.append((cx + rr * math.cos(t), cy + rr * math.sin(t)))
    return pts


# ------------------------------------------------------------------ scene
def draw_table():
    # warm vertical gradient: lighter at top, deep brown at bottom
    top = (122, 82, 47)
    bot = (58, 36, 20)
    for y in range(H):
        t = y / (H - 1)
        r = int(mix(top[0], bot[0], t) + 0.5)
        g = int(mix(top[1], bot[1], t) + 0.5)
        b = int(mix(top[2], bot[2], t) + 0.5)
        hspan(y, 0, W, r, g, b)
    # wood grain: a few long wavy darker bands
    for base_y, amp, thick, col, a in (
        (180, 9, 26, (74, 47, 26), 0.45),
        (330, 12, 18, (84, 55, 30), 0.35),
        (760, 10, 30, (66, 42, 23), 0.45),
        (905, 14, 22, (80, 52, 29), 0.35),
    ):
        pts = []
        for x in range(0, W + 1, 16):
            pts.append((x, base_y + amp * math.sin(x * 0.006 + base_y)))
        stroke_path(pts, thick, col, a)
    # warm light pooling from the top left
    soft_disc(330, 300, 640, (255, 196, 120), 0.20)
    soft_disc(300, 260, 380, (255, 220, 160), 0.12)


def draw_bowl():
    cx, cy = 512, 540
    # soft shadow on the table, down-right
    ellipse(cx + 26, cy + 300, 400, 92, (20, 10, 5), 0.42)
    ellipse(cx + 18, cy + 292, 372, 78, (28, 14, 7), 0.35)
    # lacquered bowl: deep red-black outside, bright rim
    radial_disc(cx, cy, 402, (122, 38, 26), (52, 16, 12), 1.0, 0.8)
    # rim ring: pale ceramic edge
    ring_outer = 402
    ring_inner = 372
    for y in range(cy - ring_outer, cy + ring_outer + 1):
        dy = (y + 0.5) - cy
        d2 = ring_outer * ring_outer - dy * dy
        if d2 <= 0:
            continue
        dx = math.sqrt(d2)
        x0, x1 = cx - dx, cx + dx
        d2i = ring_inner * ring_inner - dy * dy
        if d2i > 0:
            dxi = math.sqrt(d2i)
            hspan(y, x0, cx - dxi, 214, 96, 62)
            hspan(y, cx + dxi, x1, 214, 96, 62)
        else:
            hspan(y, x0, x1, 214, 96, 62)
    # rim highlight, upper-left arc
    pts = arc_points(cx, cy, 387, math.radians(150), math.radians(285))
    stroke_path(pts, 7, (255, 190, 140), 0.55)
    # golden broth
    radial_disc(cx, cy, 368, (232, 164, 62), (146, 84, 18), 1.0, 0.9)
    # broth sheen: glossy light patches
    soft_disc(400, 420, 190, (255, 214, 130), 0.30)
    soft_disc(620, 640, 150, (255, 196, 110), 0.18)
    soft_disc(470, 620, 90, (255, 226, 150), 0.16)
    soft_disc(390, 400, 120, (255, 232, 160), 0.22)


def draw_noodles():
    cx, cy = 470, 560
    wheats = [(242, 212, 146), (232, 196, 120), (222, 178, 98),
              (246, 220, 158), (214, 164, 88)]
    shadow = (176, 128, 62)
    # layered wavy noodle arcs, denser toward the centre; each strand
    # wobbles and sits slightly off-centre so they tangle, not fingerprint
    arcs = []
    for i, rad in enumerate(range(70, 330, 14)):
        a0 = math.radians(-160 + (i * 37) % 120)
        span = math.radians(150 + (i * 53) % 170)
        arcs.append((rad, a0, a0 + span))
    for j, (rad, a0, a1) in enumerate(arcs):
        col = wheats[j % len(wheats)]
        jx = cx + 10 * math.sin(j * 1.7)
        jy = cy + 8 * math.cos(j * 1.3)
        wob = 5.0 + (j % 4)
        width = 9.0 + (j % 3)
        # drop shadow first, offset down-right, then the noodle
        pts = arc_points(jx + 3, jy + 4, rad, a0, a1, wobble=wob, phase=j)
        stroke_path(pts, width + 1, shadow, 0.35)
        pts = arc_points(jx, jy, rad, a0, a1, wobble=wob, phase=j)
        stroke_path(pts, width, col, 1.0)
        # glossy top edge on some strands
        if j % 3 == 0:
            pts = arc_points(jx, jy - 2, rad, a0, a1, wobble=wob, phase=j)
            stroke_path(pts, 3.5, (255, 238, 190), 0.5)


def draw_chashu():
    # two overlapping pork slices, pink-brown with a pale fat ring
    for cx, cy, rad in ((648, 430, 82), (700, 500, 74)):
        radial_disc(cx, cy, rad, (198, 118, 84), (138, 70, 46), 1.0, 0.7)
        disc(cx, cy, rad * 0.62, (226, 158, 116), 0.9)
        disc(cx, cy, rad * 0.42, (196, 116, 82), 0.9)
        # spiral-ish sear arcs
        pts = arc_points(cx, cy, rad * 0.78, math.radians(20), math.radians(200))
        stroke_path(pts, 4, (120, 58, 38), 0.5)
        # gloss
        soft_disc(cx - rad * 0.3, cy - rad * 0.35, rad * 0.45, (255, 210, 170), 0.35)


def draw_egg():
    # halved soft egg, tilted, white + molten orange yolk
    cx, cy = 372, 660
    ellipse(cx, cy, 98, 72, (250, 244, 228), 1.0, rot=math.radians(-18))
    ellipse(cx, cy, 92, 66, (244, 234, 214), 1.0, rot=math.radians(-18))
    # yolk: glossy deep orange, brighter toward its top-left
    radial_disc(cx - 6, cy - 4, 46, (255, 176, 60), (214, 106, 16), 1.0, 0.6)
    soft_disc(cx - 18, cy - 16, 16, (255, 236, 170), 0.85)
    soft_disc(cx + 14, cy + 12, 10, (255, 220, 140), 0.5)


def draw_onion_and_extras():
    # green onion rings scattered over the broth
    greens = [(74, 146, 62), (96, 168, 74), (58, 124, 52)]
    spots = [(300, 430), (350, 480), (560, 380), (610, 700), (430, 760),
             (520, 300), (680, 620), (330, 600), (590, 470), (460, 380)]
    for i, (x, y) in enumerate(spots):
        col = greens[i % len(greens)]
        disc(x, y, 13, col)
        disc(x, y, 7, (206, 146, 56))  # broth showing through the ring
        disc(x - 3, y - 3, 4, (190, 230, 140), 0.8)
    # chili oil droplets: glossy red-orange beads
    for x, y, r in ((560, 600, 12), (420, 470, 9), (650, 560, 10), (500, 720, 8)):
        radial_disc(x, y, r, (226, 62, 20), (150, 30, 8), 1.0, 0.5)
        disc(x - r * 0.3, y - r * 0.35, r * 0.28, (255, 200, 160), 0.9)
    # sesame seeds
    for x, y, rot in ((380, 520, 20), (540, 660, -30), (620, 430, 45),
                      (470, 330, 10), (300, 560, -15), (680, 480, 60)):
        ellipse(x, y, 7, 4, (250, 232, 190), 1.0, rot=math.radians(rot))


def draw_nori():
    # dark nori sheet tucked at the bowl's right edge (rounded corners)
    cx, cy = 800, 620
    poly([(cx - 52, cy - 80), (cx + 52, cy - 80), (cx + 52, cy + 80),
          (cx - 52, cy + 80)], (22, 38, 22))
    poly([(cx - 40, cy - 92), (cx + 40, cy - 92), (cx + 40, cy + 92),
          (cx - 40, cy + 92)], (22, 38, 22))
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        disc(cx + sx * 40, cy + sy * 80, 12, (22, 38, 22))
    # sheen stripes
    poly([(cx - 52, cy - 60), (cx + 52, cy - 78), (cx + 52, cy - 58),
          (cx - 52, cy - 40)], (74, 110, 66), 0.35)
    poly([(cx - 52, cy + 10), (cx + 52, cy - 8), (cx + 52, cy + 12),
          (cx - 52, cy + 30)], (74, 110, 66), 0.28)


def draw_chopsticks():
    # two wooden chopsticks resting across the bowl's upper-right rim
    for off in (0, 26):
        pts = [(742 + off * 0.4, 168 + off), (950 + off * 0.4, 330 + off)]
        stroke_path(pts, 15, (96, 58, 30), 1.0)
        pts2 = [(742 + off * 0.4, 164 + off), (950 + off * 0.4, 326 + off)]
        stroke_path(pts2, 4, (190, 130, 80), 0.7)
    # squared tips
    disc(950, 330, 8, (96, 58, 30))
    disc(950, 356, 8, (96, 58, 30))


def draw_steam():
    # three soft rising wisps, white, fading as they climb
    for base_x, phase, height in ((430, 0.0, 300), (540, 1.4, 330), (640, 2.6, 280)):
        y = 330
        step = 0
        while y > 330 - height:
            t = (330 - y) / height
            x = base_x + 26 * math.sin(phase + t * 5.2) + t * 30
            rad = 20 + t * 40
            soft_disc(x, y, rad, (255, 255, 255), 0.16 * (1 - t * 0.55))
            y -= 14
            step += 1


def draw_vignette():
    # gentle darkening at the corners keeps the eye on the bowl
    for cx, cy in ((-120, -120), (W + 120, -120),
                   (-120, H + 120), (W + 120, H + 120)):
        soft_disc(cx, cy, 520, (16, 8, 4), 0.38)


def build():
    draw_table()
    draw_bowl()
    draw_noodles()
    draw_chashu()
    draw_egg()
    draw_onion_and_extras()
    draw_nori()
    draw_chopsticks()
    draw_steam()
    draw_vignette()


# --------------------------------------------------------------------- png
def png_bytes():
    raw = bytearray()
    for y in range(H):
        raw.append(0)  # filter: none
        raw += buf[y * W * 3:(y + 1) * W * 3]

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def main():
    build()
    data = png_bytes()
    try:
        os.makedirs("/output", exist_ok=True)
        path = OUT_PATH
        with open(path, "wb") as f:
            f.write(data)
    except OSError:
        os.makedirs("output", exist_ok=True)
        path = os.path.join("output", "entry.png")
        with open(path, "wb") as f:
            f.write(data)
    print("wrote %s (%d bytes, %dx%d)" % (path, len(data), W, H))


if __name__ == "__main__":
    main()
