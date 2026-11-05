import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DISPLAY_W, DISPLAY_H = 880, 300
SCALE = 4
FINAL_SCALE = 2
RENDER_W, RENDER_H = DISPLAY_W * SCALE, DISPLAY_H * SCALE

FONTS = {
    "serif": [
        r"C:\Windows\Fonts\NotoSerifSC-VF.ttf",
        r"C:\Windows\Fonts\Source Han Serif SC Heavy (TrueType).ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ],
    "latin": [
        r"C:\Windows\Fonts\georgia.ttf",
        r"C:\Windows\Fonts\times.ttf",
    ],
    "mono": [
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\cour.ttf",
    ],
    "seal": [
        r"C:\Windows\Fonts\Source Han Serif SC Heavy (TrueType).ttf",
        r"C:\Windows\Fonts\NotoSerifSC-VF.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
    ],
}

THEMES = {
    "light": {
        "bg_top": (250, 246, 237),
        "bg_bottom": (241, 233, 219),
        "ink": (30, 28, 25),
        "ink_soft": (74, 70, 61),
        "muted": (126, 117, 102),
        "bamboo": (78, 103, 80),
        "leaf": (108, 137, 106),
        "seal": (167, 67, 57),
        "seal_text": (250, 245, 235),
        "enso": (30, 28, 25, 42),
        "grain": 6,
    },
    "dark": {
        "bg_top": (17, 18, 19),
        "bg_bottom": (10, 11, 12),
        "ink": (236, 229, 213),
        "ink_soft": (178, 170, 154),
        "muted": (128, 121, 108),
        "bamboo": (124, 157, 129),
        "leaf": (148, 181, 153),
        "seal": (194, 96, 82),
        "seal_text": (18, 18, 18),
        "enso": (236, 229, 213, 34),
        "grain": 5,
    },
}


def load_font(kind, size):
    for path in FONTS[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def lerp(a, b, t):
    return a + (b - a) * t


def gradient(size, top, bottom):
    image = Image.new("RGB", (1, size[1]))
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        t = y / max(size[1] - 1, 1)
        draw.point((0, y), fill=tuple(round(lerp(top[i], bottom[i], t)) for i in range(3)))
    return image.resize(size, Image.Resampling.BILINEAR)


def paper_texture(size, amount, seed):
    rng = random.Random(seed)
    small = Image.new("L", (size[0] // 24, size[1] // 24))
    pixels = small.load()
    for y in range(small.height):
        for x in range(small.width):
            pixels[x, y] = 128 + rng.randint(-amount, amount)
    grain = small.resize(size, Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(1))
    return grain


def add_wash(image, box, color, alpha, blur):
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse(box, fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    image.alpha_composite(layer)


def bezier(p0, p1, p2, steps=48):
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        points.append((x, y))
    return points


def draw_stalk(draw, base_x, top_x, y_bottom, y_top, width_bottom, width_top, color, bend=0.0):
    left, right, samples = [], [], []
    steps = 40
    for i in range(steps + 1):
        t = i / steps
        y = lerp(y_bottom, y_top, t)
        x = lerp(base_x, top_x, t) + bend * math.sin(math.pi * t)
        half = lerp(width_bottom, width_top, t) / 2
        left.append((x - half, y))
        right.append((x + half, y))
        samples.append((x, y))
    draw.polygon(left + right[::-1], fill=color)
    return samples


def stalk_nodes(draw, centers, width, color):
    for x, y in centers:
        draw.line([(x - width, y), (x + width, y)], fill=color, width=max(2, int(width * 0.5)))


def draw_leaf(draw, base, tip, width, curve, color):
    bx, by = base
    tx, ty = tip
    dx, dy = tx - bx, ty - by
    length = math.hypot(dx, dy)
    if length == 0:
        return
    nx, ny = -dy / length, dx / length
    steps = 36
    upper, lower = [], []
    for i in range(steps + 1):
        t = i / steps
        cx = bx + dx * t + nx * curve * math.sin(math.pi * t)
        cy = by + dy * t + ny * curve * math.sin(math.pi * t)
        half = width * math.sin(math.pi * t) ** 0.8
        upper.append((cx + nx * half, cy + ny * half))
        lower.append((cx - nx * half, cy - ny * half))
    draw.polygon(upper + lower[::-1], fill=color)


def leaf_from_stalk(draw, samples, fraction, angle, length, width, curve, color):
    index = int(fraction * (len(samples) - 1))
    base = samples[index]
    radians = math.radians(angle)
    tip = (base[0] + math.cos(radians) * length, base[1] + math.sin(radians) * length)
    draw_leaf(draw, base, tip, width, curve, color)


def draw_enso(draw, center, radius, color, brush=1.0):
    cx, cy = center
    points = []
    steps = 240
    for i in range(steps + 1):
        angle = math.radians(-100 + 340 * i / steps)
        variation = 2.5 * math.sin(3.1 * angle + 0.7) + 1.2 * math.sin(7.3 * angle + 2.1)
        r = radius + variation * brush
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    for i in range(len(points) - 1):
        t = i / (len(points) - 1)
        width = (2.2 + 2.6 * math.sin(math.pi * t)) * brush
        draw.line([points[i], points[i + 1]], fill=color, width=max(1, int(width)))


def text(draw, xy, string, font, fill, tracking=0):
    x, y = xy
    for char in string:
        draw.text((x, y), char, font=font, fill=fill)
        x += font.getlength(char) + tracking


def text_width(string, font, tracking=0):
    return sum(font.getlength(c) for c in string) + tracking * max(len(string) - 1, 0)


def seal(image, xy, size, theme, label="竹言"):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    radius = size // 8
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=theme["seal"] + (255,))
    inner = size // 11
    draw.rounded_rectangle([inner, inner, size - 1 - inner, size - 1 - inner], radius=max(2, radius // 2), outline=theme["seal_text"] + (110,), width=max(2, size // 34))
    glyph = load_font("seal", int(size * 0.34))
    for char, center in zip(label, (0.28, 0.72)):
        draw.text((size / 2, size * center), char, font=glyph, fill=theme["seal_text"] + (255,), anchor="mm")
    layer = layer.rotate(-3, resample=Image.Resampling.BICUBIC, expand=False)
    image.alpha_composite(layer, (int(xy[0]), int(xy[1])))


def render(theme_name, out_path):
    theme = THEMES[theme_name]
    s = SCALE
    base = gradient((RENDER_W, RENDER_H), theme["bg_top"], theme["bg_bottom"]).convert("RGBA")

    wash = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 0))
    highlight = (255, 251, 240) if theme_name == "light" else (236, 229, 213)
    add_wash(wash, (int(0.45 * RENDER_W), int(-0.25 * RENDER_H), int(1.25 * RENDER_W), int(0.9 * RENDER_H)), highlight, 70 if theme_name == "light" else 14, 80 * s)
    add_wash(wash, (int(0.5 * RENDER_W), int(0.1 * RENDER_H), int(1.2 * RENDER_W), int(1.1 * RENDER_H)), theme["bamboo"], 20 if theme_name == "light" else 30, 70 * s)
    add_wash(wash, (int(-0.2 * RENDER_W), int(0.4 * RENDER_H), int(0.5 * RENDER_W), int(1.2 * RENDER_H)), theme["seal"], 12 if theme_name == "light" else 16, 110 * s)
    base.alpha_composite(wash)

    art = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(art)

    draw_enso(draw, (700 * s, 152 * s), 112 * s, theme["enso"], brush=1.7)

    stalk1 = draw_stalk(draw, 636 * s, 652 * s, 312 * s, 18 * s, 15 * s, 7 * s, theme["bamboo"] + (255,), bend=2 * s)
    stalk_nodes(draw, stalk1[4::9], 9 * s, theme["bamboo"] + (160,))
    stalk2 = draw_stalk(draw, 706 * s, 694 * s, 306 * s, 58 * s, 11 * s, 5 * s, theme["bamboo"] + (235,), bend=-2 * s)
    stalk_nodes(draw, stalk2[5::9], 6.5 * s, theme["bamboo"] + (150,))
    stalk3 = draw_stalk(draw, 768 * s, 780 * s, 300 * s, 96 * s, 8 * s, 4 * s, theme["bamboo"] + (215,), bend=1.5 * s)
    stalk_nodes(draw, stalk3[6::9], 5 * s, theme["bamboo"] + (140,))

    leaf_specs = [
        (stalk1, 0.14, -138, 62, 6.5, 5),
        (stalk1, 0.30, -52, 68, 6.5, -5),
        (stalk1, 0.46, -146, 54, 5.5, 4),
        (stalk2, 0.22, -44, 56, 5.5, -4),
        (stalk2, 0.40, -140, 50, 5, 3),
        (stalk3, 0.26, -50, 46, 4.5, -3),
        (stalk3, 0.46, -144, 42, 4, 2),
    ]
    leaf_alpha = 200 if theme_name == "light" else 215
    for samples, fraction, angle, length, width, curve in leaf_specs:
        leaf_from_stalk(draw, samples, fraction, angle, length * s, width * s, curve * s, theme["leaf"] + (leaf_alpha,))

    art = art.filter(ImageFilter.GaussianBlur(0.8 * s))
    base.alpha_composite(art)

    draw = ImageDraw.Draw(base)

    label_font = load_font("latin", int(14 * s))
    text(draw, (64 * s, 58 * s), "SILICON  ×  PIXELS", label_font, theme["bamboo"] + (255,), tracking=4.2 * s)

    title_font = load_font("latin", int(67 * s))
    title = "Gyanano"
    text(draw, (62 * s, 80 * s), title, title_font, theme["ink"] + (255,), tracking=3.4 * s)
    seal(base, ((62 + text_width(title, title_font, 3.4 * s) / s + 26) * s, 90 * s), 50 * s, theme)

    tag_font = load_font("serif", int(24 * s))
    text(draw, (64 * s, 176 * s), "在硅与浏览器之间，落笔生万物", tag_font, theme["ink_soft"] + (255,), tracking=1.4 * s)

    meta_font = load_font("serif", int(13 * s))
    line_y = 222 * s
    draw.line([(64 * s, line_y), (196 * s, line_y)], fill=theme["ink"] + (55,), width=max(1, int(1 * s)))
    text(draw, (64 * s, 234 * s), "嵌入式 · 全栈 · INTP", meta_font, theme["muted"] + (255,), tracking=2.6 * s)

    vol_font = load_font("serif", int(12 * s))
    text(draw, (64 * s, 268 * s), "道 · 术 · 演 · 器 · 墨痕", vol_font, theme["muted"] + (220,), tracking=3 * s)

    grain = paper_texture((RENDER_W, RENDER_H), 6, 7 if theme_name == "light" else 11)
    if theme["grain"]:
        layer = Image.new("L", (RENDER_W, RENDER_H), 0)
        layer.paste(grain.point(lambda v: int(abs(v - 128) * 0.55)), (0, 0))
        noise = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 0))
        noise.putalpha(layer)
        base.alpha_composite(noise)

    final = base.convert("RGB").resize((RENDER_W // FINAL_SCALE, RENDER_H // FINAL_SCALE), Image.Resampling.LANCZOS)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    final.save(out, "PNG", optimize=True, compress_level=9)
    print(out, final.size, out.stat().st_size)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    render("light", root / "assets" / "banner-light.png")
    render("dark", root / "assets" / "banner-dark.png")
