#!/usr/bin/env python3
"""Render the setup/hold whiteboard lesson frames and encode them as H.264."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = ROOT / "videos"
OUT = VIDEO_DIR / "setup-hold-timing.mp4"
POSTER = ROOT / "assets" / "setup-hold-poster.jpg"
W, H, FPS = 1280, 720, 24

PAPER = (248, 248, 242)
GRID = (228, 232, 222)
INK = (20, 43, 47)
MUTED = (94, 113, 108)
TEAL = (43, 145, 132)
LIME = (145, 190, 92)
CORAL = (222, 118, 92)
BLUE = (78, 133, 184)
CARD = (255, 255, 251)
LINE = (211, 220, 211)

REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
MONO = "/System/Library/Fonts/Menlo.ttc"

SCENES = [
    (4.0, "SETUP / HOLD TIME", "A visual field guide to sequential timing"),
    (4.5, "A clock edge captures data", "The receiving flip-flop samples D at its active edge."),
    (5.0, "Setup: arrive early", "D must be stable for a short window before the capture edge."),
    (5.0, "Hold: stay steady after", "D must remain stable for a short window after the capture edge."),
    (5.0, "STA checks both extremes", "Setup checks the slowest path. Hold checks the fastest path."),
    (6.5, "Read the slack", "Positive slack passes. Negative slack means the check is violated."),
    (5.0, "Clock skew shifts the window", "A later capture clock helps setup, but can tighten hold."),
    (5.0, "Choose the right repair", "Speed up a setup path; add controlled delay to a hold path."),
    (4.0, "Arrive early. Stay steady.", "SETUP = max delay  /  HOLD = min delay"),
]


@lru_cache(maxsize=32)
def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    path = BOLD if weight == "bold" else MONO if weight == "mono" else REGULAR
    return ImageFont.truetype(path, size=size)


def rounded(draw: ImageDraw.ImageDraw, xy, radius=15, fill=CARD, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def label(draw, xy, text, fill=(233, 240, 230), color=INK, pad_x=12, pad_y=7):
    x, y = xy
    f = font(17, "mono")
    box = draw.textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0] + pad_x * 2, box[3] - box[1] + pad_y * 2
    rounded(draw, (x, y, x + w, y + h), radius=8, fill=fill)
    draw.text((x + pad_x, y + pad_y - 1), text, font=f, fill=color)


def line(draw, points, fill, width=4, joint="curve"):
    draw.line(points, fill=fill, width=width, joint=joint)


def arrow(draw, start, end, color=TEAL, width=4, head=14):
    x1, y1 = start
    x2, y2 = end
    line(draw, [(x1, y1), (x2, y2)], color, width)
    angle = math.atan2(y2 - y1, x2 - x1)
    left = (x2 - head * math.cos(angle - math.pi / 6), y2 - head * math.sin(angle - math.pi / 6))
    right = (x2 - head * math.cos(angle + math.pi / 6), y2 - head * math.sin(angle + math.pi / 6))
    draw.polygon([(x2, y2), left, right], fill=color)


def centered(draw, cx, y, text, f, fill):
    box = draw.textbbox((0, 0), text, font=f)
    draw.text((cx - (box[2] - box[0]) / 2, y), text, font=f, fill=fill)


def board():
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im, "RGB")
    for x in range(24, W, 36):
        color = (235, 238, 230) if x % 180 else (225, 231, 221)
        d.line((x, 0, x, H), fill=color, width=1)
    for y in range(16, H, 36):
        color = (235, 238, 230) if y % 180 else (225, 231, 221)
        d.line((0, y, W, y), fill=color, width=1)
    d.rectangle((0, 0, W, 9), fill=INK)
    return im, d


def topbar(d, scene_idx, title, progress):
    d.text((66, 42), "SILICON FIELD NOTES", font=font(16, "mono"), fill=MUTED)
    d.text((1036, 42), "SV  /  PD", font=font(16, "mono"), fill=TEAL)
    d.text((67, 101), f"{scene_idx:02d}   /   TIMING FUNDAMENTALS", font=font(17, "mono"), fill=TEAL)
    d.text((65, 135), title, font=font(48, "bold"), fill=INK, stroke_width=0)
    d.line((66, 207, 1212, 207), fill=LINE, width=2)
    # Thin progress indicator advances throughout the lesson.
    d.rounded_rectangle((66, 683, 1214, 689), radius=3, fill=(225, 231, 221))
    d.rounded_rectangle((66, 683, 66 + int(1148 * progress), 689), radius=3, fill=LIME)
    d.text((67, 647), "STATIC TIMING ANALYSIS   /   IDEALIZED SINGLE-CYCLE EXAMPLES", font=font(12, "mono"), fill=(117, 132, 124))


def draw_grid_panel(d, xy, x0, y0, x1, y1, rows=("CLK", "D")):
    rounded(d, xy, radius=17, fill=CARD, outline=LINE, width=2)
    for x in range(x0, x1 + 1, 50):
        d.line((x, y0, x, y1), fill=(238, 241, 234), width=1)
    for y in range(y0, y1 + 1, 36):
        d.line((x0, y, x1, y), fill=(238, 241, 234), width=1)
    for i, r in enumerate(rows):
        d.text((x0 - 66, y0 + 20 + i * 92), r, font=font(16, "mono"), fill=MUTED)


def draw_wave(d, y_low, y_high, x0, x1, transition_x, initial_high=False, color=TEAL, progress=1.0, width=6):
    stop = x0 + max(0, min(1, progress)) * (x1 - x0)
    pts = [(x0, y_high if initial_high else y_low)]
    if x0 < transition_x < stop:
        pts.extend([(transition_x, y_high if initial_high else y_low), (transition_x, y_low if initial_high else y_high)])
    pts.append((stop, y_high if initial_high else y_low) if stop < transition_x else (stop, y_low if initial_high else y_high))
    line(d, pts, color, width)
    if stop >= transition_x:
        d.ellipse((transition_x - 7, (y_low + y_high) / 2 - 7, transition_x + 7, (y_low + y_high) / 2 + 7), fill=color)


def edge_marker(d, x, y1=267, y2=501, color=INK, label_text="CAPTURE EDGE"):
    d.line((x, y1, x, y2), fill=color, width=2)
    d.polygon([(x, y1), (x - 7, y1 - 13), (x + 7, y1 - 13)], fill=color)
    label(d, (x + 13, y1 + 5), label_text, fill=(236, 242, 234), color=INK, pad_x=10, pad_y=6)


def scene_zero(d, im, u):
    d.text((72, 280), "SETUP", font=font(77, "bold"), fill=INK)
    d.text((72, 365), "/ HOLD", font=font(77, "bold"), fill=TEAL)
    d.text((78, 475), "Two timing checks. One sampling edge.", font=font(25), fill=MUTED)
    # Chip and routed signals form as the title settles in.
    cx, cy, cw, ch = 900, 290, 205, 170
    rounded(d, (cx, cy, cx + cw, cy + ch), radius=19, fill=(23, 51, 56), outline=TEAL, width=3)
    rounded(d, (cx + 22, cy + 22, cx + cw - 22, cy + ch - 22), radius=11, fill=(30, 67, 69), outline=(96, 161, 145), width=2)
    centered(d, cx + cw / 2, cy + 62, "D   →   Q", font(25, "mono"), (238, 247, 226))
    centered(d, cx + cw / 2, cy + 100, "FLIP-FLOP", font(13, "mono"), (167, 194, 177))
    routes = [[(840, 330), (875, 330), (875, 345), (900, 345)], [(840, 420), (875, 420), (875, 405), (900, 405)], [(1105, 345), (1140, 345), (1140, 325), (1180, 325)], [(1105, 415), (1140, 415), (1140, 435), (1180, 435)]]
    for route in routes:
        n = max(2, int(len(route) * u * 2.6))
        line(d, route[:min(n, len(route))], LIME, 4)
    d.text((850, 273), "CLK", font=font(14, "mono"), fill=BLUE)
    d.text((850, 442), "DATA", font=font(14, "mono"), fill=TEAL)
    d.text((1127, 285), "Q", font=font(14, "mono"), fill=TEAL)
    label(d, (73, 574), "MAX PATH   /   MIN PATH", fill=(232, 240, 228), color=INK)


def scene_one(d, im, u):
    draw_grid_panel(d, (90, 245, 1190, 575), 226, 280, 1155, 535)
    edge = 790
    draw_wave(d, 360, 302, 226, 1155, edge, progress=u, color=BLUE)
    draw_wave(d, 497, 439, 226, 1155, 590, progress=u, color=TEAL)
    edge_marker(d, edge, 255, 535)
    # Sampling point pulses at the rising clock edge.
    pulse = 8 + int(9 * (0.5 + 0.5 * math.sin(u * math.pi * 8))) if u > 0.2 else 7
    d.ellipse((edge - pulse, 294 - pulse, edge + pulse, 294 + pulse), fill=LIME, outline=CARD, width=3)
    d.text((242, 555), "D is read here and stored at Q", font=font(19), fill=MUTED)
    label(d, (956, 542), "ACTIVE EDGE", fill=(230, 243, 222), color=INK)


def scene_two(d, im, u):
    draw_grid_panel(d, (90, 245, 1190, 575), 226, 280, 1155, 535)
    edge = 840
    win_start, win_end = 740, 840
    alpha = max(0.15, min(1.0, u * 1.9))
    shade = (int(235 + (222 - 235) * alpha), int(246 + (226 - 246) * alpha), int(220 + (197 - 220) * alpha))
    d.rectangle((win_start, 272, win_end, 529), fill=shade)
    draw_wave(d, 360, 302, 226, 1155, 660, progress=u, color=BLUE)
    draw_wave(d, 497, 439, 226, 1155, 690, progress=u, initial_high=False, color=TEAL)
    edge_marker(d, edge, 255, 535)
    d.line((win_start, 310, win_start, 330), fill=LIME, width=3)
    d.line((win_end, 310, win_end, 330), fill=LIME, width=3)
    d.line((win_start, 319, win_end, 319), fill=LIME, width=3)
    label(d, (win_start + 14, 329), "t_setup", fill=(248, 252, 242), color=INK)
    d.text((257, 555), "Data is already stable before the edge.", font=font(19), fill=MUTED)


def scene_three(d, im, u):
    draw_grid_panel(d, (90, 245, 1190, 575), 226, 280, 1155, 535)
    edge = 840
    win_end = 940
    d.rectangle((edge, 272, win_end, 529), fill=(244, 229, 215))
    draw_wave(d, 360, 302, 226, 1155, edge + 145, progress=u, initial_high=True, color=BLUE)
    draw_wave(d, 497, 439, 226, 1155, edge + 144, progress=u, initial_high=True, color=TEAL)
    edge_marker(d, edge, 255, 535)
    d.line((edge, 319, edge, 338), fill=CORAL, width=3)
    d.line((win_end, 319, win_end, 338), fill=CORAL, width=3)
    d.line((edge, 328, win_end, 328), fill=CORAL, width=3)
    label(d, (edge + 8, 341), "t_hold", fill=(255, 248, 243), color=INK)
    d.text((257, 555), "Keep D unchanged until the hold window ends.", font=font(19), fill=MUTED)


def scene_four(d, im, u):
    cards = [(91, 261, 1190, 406), (91, 430, 1190, 575)]
    for box in cards:
        rounded(d, box, radius=18, fill=CARD, outline=LINE, width=2)
    d.text((124, 286), "SETUP CHECK", font=font(19, "mono"), fill=TEAL)
    d.text((124, 323), "Maximum delay  /  latest arrival", font=font(27, "bold"), fill=INK)
    d.text((124, 370), "Data must arrive before the next capture edge.", font=font(19), fill=MUTED)
    d.text((124, 453), "HOLD CHECK", font=font(19, "mono"), fill=CORAL)
    d.text((124, 489), "Minimum delay  /  earliest arrival", font=font(27, "bold"), fill=INK)
    d.text((124, 535), "New data must wait until the hold edge is safe.", font=font(19), fill=MUTED)
    # The two animated paths make max/min feel concrete.
    for y, col in [(335, TEAL), (503, CORAL)]:
        arrow(d, (760, y), (770 + int(230 * u), y), col, width=5, head=16)
        for j in range(4):
            x = 805 + j * 56
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=col)
    label(d, (993, 292), "MAX", fill=(226, 243, 220), color=INK)
    label(d, (993, 461), "MIN", fill=(250, 232, 222), color=INK)


def metric_box(d, xy, eyebrow, value, sub, color):
    x0, y0, x1, y1 = xy
    rounded(d, xy, radius=18, fill=CARD, outline=LINE, width=2)
    d.text((x0 + 25, y0 + 20), eyebrow, font=font(15, "mono"), fill=color)
    d.text((x0 + 25, y0 + 60), value, font=font(28, "bold"), fill=INK)
    d.text((x0 + 25, y0 + 107), sub, font=font(18), fill=MUTED)


def scene_five(d, im, u):
    metric_box(d, (91, 246, 631, 516), "SETUP  /  MAX PATH", "1.00 − (0.76 + 0.08)", "capture − (arrival + setup)", TEAL)
    metric_box(d, (649, 246, 1190, 516), "HOLD  /  MIN PATH", "0.07 − 0.05", "arrival − (edge + hold)", CORAL)
    d.text((117, 389), "=  +0.16 ns   PASS", font=font(24, "bold"), fill=TEAL)
    d.text((675, 389), "=  +0.02 ns   PASS", font=font(24, "bold"), fill=TEAL)
    # Animated marker runs toward each required boundary.
    d.line((136, 456, 573, 456), fill=(217, 226, 216), width=8)
    d.line((690, 456, 1127, 456), fill=(217, 226, 216), width=8)
    sx = 136 + int(437 * min(1.0, u * 1.3))
    hx = 690 + int(437 * min(1.0, u * 1.3))
    d.ellipse((sx - 10, 446, sx + 10, 466), fill=LIME, outline=CARD, width=2)
    d.ellipse((hx - 10, 446, hx + 10, 466), fill=CORAL, outline=CARD, width=2)
    label(d, (92, 548), "IDEALIZED EXAMPLE   /   skew and uncertainty omitted", fill=(237, 240, 231), color=MUTED, pad_x=13, pad_y=7)


def scene_six(d, im, u):
    rounded(d, (91, 250, 1190, 455), radius=18, fill=CARD, outline=LINE, width=2)
    d.text((125, 274), "CAPTURE CLOCK ARRIVES +50 ps LATER", font=font(18, "mono"), fill=TEAL)
    d.text((126, 319), "The sampling edge moves right.", font=font(26, "bold"), fill=INK)
    # Two clock edges, nominal and delayed.
    x1, x2 = 815, 870
    d.line((190, 407, 1060, 407), fill=(224, 230, 220), width=2)
    d.line((x1, 363, x1, 420), fill=(132, 148, 140), width=3)
    d.line((x2, 347, x2, 420), fill=TEAL, width=5)
    label(d, (x1 - 91, 369), "IDEAL", fill=(236, 240, 233), color=MUTED)
    label(d, (x2 + 13, 337), "LATE", fill=(226, 243, 220), color=INK)
    rounded(d, (91, 482, 622, 590), radius=16, fill=(229, 243, 221), outline=(200, 220, 188), width=2)
    rounded(d, (649, 482, 1190, 590), radius=16, fill=(249, 232, 221), outline=(235, 209, 191), width=2)
    d.text((119, 502), "SETUP  /  MORE TIME", font=font(20, "bold"), fill=INK)
    d.text((119, 540), "A later capture edge can help.", font=font(18), fill=MUTED)
    d.text((677, 502), "HOLD  /  LESS MARGIN", font=font(20, "bold"), fill=INK)
    d.text((677, 540), "That same shift can hurt.", font=font(18), fill=MUTED)
    if u > 0.3:
        arrow(d, (x1 + 9, 433), (x2 - 6, 433), LIME, width=4, head=13)


def scene_seven(d, im, u):
    rounded(d, (91, 249, 631, 526), radius=20, fill=CARD, outline=LINE, width=2)
    rounded(d, (649, 249, 1190, 526), radius=20, fill=CARD, outline=LINE, width=2)
    d.text((126, 277), "SETUP FAIL", font=font(17, "mono"), fill=CORAL)
    d.text((126, 316), "Shorten the slow path", font=font(27, "bold"), fill=INK)
    d.text((126, 362), "• optimize logic / cells", font=font(19), fill=MUTED)
    d.text((126, 402), "• reduce data-path delay", font=font(19), fill=MUTED)
    d.text((685, 277), "HOLD FAIL", font=font(17, "mono"), fill=CORAL)
    d.text((685, 316), "Add controlled delay", font=font(27, "bold"), fill=INK)
    d.text((685, 362), "• insert hold buffers", font=font(19), fill=MUTED)
    d.text((685, 402), "• recheck setup and routing", font=font(19), fill=MUTED)
    # Little route diagrams animate from long to short and then gain a delay cell.
    y = 477
    for x_start, x_end, col in [(136, 520, TEAL), (690, 1074, CORAL)]:
        d.line((x_start, y, x_end, y), fill=(217, 226, 216), width=4)
        d.ellipse((x_start - 8, y - 8, x_start + 8, y + 8), fill=BLUE)
        d.ellipse((x_end - 8, y - 8, x_end + 8, y + 8), fill=TEAL)
        count = 2 if col == TEAL else (1 + int(u * 3))
        for j in range(count):
            bx = x_start + 92 + j * 75
            rounded(d, (bx, y - 15, bx + 39, y + 15), radius=5, fill=(235, 242, 230), outline=col, width=2)
            centered(d, bx + 19, y - 8, "D" if col == CORAL else "G", font(13, "mono"), INK)
    label(d, (92, 552), "ALWAYS RECHECK POWER · PERFORMANCE · AREA", fill=(237, 240, 231), color=MUTED)


def scene_eight(d, im, u):
    rounded(d, (90, 255, 1190, 559), radius=22, fill=(24, 49, 53), outline=(79, 123, 106), width=2)
    d.text((139, 291), "SETUP", font=font(34, "mono"), fill=(194, 235, 144))
    d.text((139, 345), "arrive early", font=font(42, "bold"), fill=(250, 250, 243))
    d.text((139, 404), "MAX DELAY   /   before the next capture edge", font=font(17, "mono"), fill=(187, 209, 196))
    d.line((640, 296, 640, 516), fill=(89, 121, 111), width=2)
    d.text((700, 291), "HOLD", font=font(34, "mono"), fill=(194, 235, 144))
    d.text((700, 345), "stay steady", font=font(42, "bold"), fill=(250, 250, 243))
    d.text((700, 404), "MIN DELAY   /   after the capture edge", font=font(17, "mono"), fill=(187, 209, 196))
    # A slim repeating trace closes the lesson.
    x0, y0 = 142, 489
    line(d, [(x0, y0), (x0 + 70, y0), (x0 + 70, y0 - 34), (x0 + 138, y0 - 34), (x0 + 138, y0)], LIME, 3)
    line(d, [(705, y0), (705 + 70, y0), (775, y0 - 34), (843, y0 - 34), (843, y0)], TEAL, 3)


DRAWERS = [scene_zero, scene_one, scene_two, scene_three, scene_four, scene_five, scene_six, scene_seven, scene_eight]


def render_frame(index: int, scene_idx: int, u: float, global_progress: float):
    im, d = board()
    topbar(d, scene_idx + 1, SCENES[scene_idx][1], global_progress)
    DRAWERS[scene_idx](d, im, u)
    # Captions sit on a clean, consistent strip above the board progress line.
    caption = SCENES[scene_idx][2]
    centered(d, W / 2, 608, caption, font(20, "bold"), INK)
    return im


def main():
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    POSTER.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="setup-hold-render-", dir="/private/tmp"))
    frames_dir = work / "frames"
    frames_dir.mkdir()
    frame_index = 0
    total_duration = sum(duration for duration, _, _ in SCENES)
    elapsed = 0.0
    for scene_idx, (duration, _, _) in enumerate(SCENES):
        count = round(duration * FPS)
        for local_idx in range(count):
            u = local_idx / max(1, count - 1)
            global_progress = min(1.0, (elapsed + duration * u) / total_duration)
            frame = render_frame(frame_index, scene_idx, u, global_progress)
            path = frames_dir / f"frame_{frame_index:05d}.jpg"
            frame.save(path, quality=83, optimize=True, progressive=True)
            if frame_index == 0:
                frame.save(POSTER, quality=91, optimize=True)
            frame_index += 1
        elapsed += duration

    encoder = work / "encode.swift"
    cache = work / "swift-module-cache"
    cache.mkdir()
    encoder.write_text(SWIFT_ENCODER, encoding="utf-8")
    try:
        subprocess.run(["swift", "-module-cache-path", str(cache), str(encoder), str(frames_dir), str(OUT), str(FPS), str(frame_index)], check=True)
        print(f"Rendered {frame_index} frames at {FPS} fps ({total_duration:.1f}s)")
        print(f"Video: {OUT} ({OUT.stat().st_size:,} bytes)")
        print(f"Poster: {POSTER}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


SWIFT_ENCODER = r'''import AVFoundation
import CoreGraphics
import CoreVideo
import Foundation
import ImageIO

let args = CommandLine.arguments
let frameDir = URL(fileURLWithPath: args[1], isDirectory: true)
let outputURL = URL(fileURLWithPath: args[2])
let fps = Int32(args[3]) ?? 24
let frameCount = Int(args[4]) ?? 0
let width = 1280
let height = 720
try? FileManager.default.removeItem(at: outputURL)

let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: 3_800_000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        AVVideoMaxKeyFrameIntervalKey: Int(fps) * 2
    ]
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
        kCVPixelBufferWidthKey as String: width,
        kCVPixelBufferHeightKey as String: height,
        kCVPixelBufferCGImageCompatibilityKey as String: true,
        kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
    ]
)
guard writer.canAdd(input) else { fatalError("Cannot add video input") }
writer.add(input)
guard writer.startWriting() else { throw writer.error ?? NSError(domain: "VideoWriter", code: 1) }
writer.startSession(atSourceTime: .zero)

func loadImage(_ index: Int) throws -> CGImage {
    let url = frameDir.appendingPathComponent(String(format: "frame_%05d.jpg", index))
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw NSError(domain: "FrameRead", code: index, userInfo: [NSLocalizedDescriptionKey: "Missing frame \(index)"])
    }
    return image
}

func makeBuffer(_ image: CGImage) throws -> CVPixelBuffer {
    var maybeBuffer: CVPixelBuffer?
    let status = CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, adaptor.pixelBufferPool!, &maybeBuffer)
    guard status == kCVReturnSuccess, let buffer = maybeBuffer else {
        throw NSError(domain: "PixelBuffer", code: Int(status))
    }
    CVPixelBufferLockBaseAddress(buffer, [])
    defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
    guard let base = CVPixelBufferGetBaseAddress(buffer),
          let context = CGContext(
            data: base,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
          ) else { throw NSError(domain: "CGContext", code: 2) }
    context.interpolationQuality = .high
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    return buffer
}

let group = DispatchGroup()
group.enter()
var nextFrame = 0
input.requestMediaDataWhenReady(on: DispatchQueue(label: "setup-hold.video.writer")) {
    do {
        while input.isReadyForMoreMediaData && nextFrame < frameCount {
            let buffer = try makeBuffer(loadImage(nextFrame))
            let time = CMTime(value: Int64(nextFrame), timescale: fps)
            guard adaptor.append(buffer, withPresentationTime: time) else {
                throw writer.error ?? NSError(domain: "Append", code: nextFrame)
            }
            nextFrame += 1
        }
        if nextFrame == frameCount && writer.status == .writing {
            input.markAsFinished()
            writer.finishWriting { group.leave() }
        }
    } catch {
        input.markAsFinished()
        writer.cancelWriting()
        fputs("Video encoding failed: \(error)\n", stderr)
        group.leave()
    }
}
group.wait()
if writer.status != .completed { throw writer.error ?? NSError(domain: "VideoWriter", code: 3) }
'''


if __name__ == "__main__":
    main()
