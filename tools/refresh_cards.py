import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

USER = "Gyanano"
API = "https://api.github.com"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FONT_DIR = HERE / "fonts"
OUT_DIR = ROOT / "assets" / "cards"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SS = 3
FINAL = 2

THEMES = {
    "dark": {
        "bg": (16, 17, 19, 255),
        "border": (37, 39, 44, 255),
        "ink": (238, 236, 230, 255),
        "sub": (185, 182, 174, 255),
        "dim": (133, 131, 125, 255),
        "accent": (95, 212, 160, 255),
        "track": (30, 31, 35, 255),
        "chart": (95, 212, 160),
    },
    "light": {
        "bg": (255, 255, 255, 255),
        "border": (216, 222, 228, 255),
        "ink": (31, 35, 40, 255),
        "sub": (87, 96, 106, 255),
        "dim": (110, 119, 129, 255),
        "accent": (26, 127, 90, 255),
        "track": (234, 238, 242, 255),
        "chart": (26, 127, 90),
    },
}


def token():
    value = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not value:
        raise SystemExit("GITHUB_TOKEN is required")
    return value


AUTH = {"Authorization": "Bearer " + token(), "Accept": "application/vnd.github+json", "User-Agent": "gyanano-profile-cards"}


def rest(path):
    request = urllib.request.Request(API + path, headers=AUTH)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def graphql(query):
    payload = json.dumps({"query": query}).encode("utf-8")
    headers = dict(AUTH)
    headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + "/graphql", data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def search_count(query):
    path = "/search/issues?q=" + urllib.parse.quote(query) + "&per_page=1"
    return rest(path)["total_count"]


def rank_for(stats):
    commits_median = 250
    prs_median = 50
    issues_median = 25
    reviews_median = 2
    stars_median = 50
    followers_median = 10
    weights = {"commits": 2, "prs": 3, "issues": 1, "reviews": 1, "stars": 4, "followers": 1}
    total = sum(weights.values())

    def exponential_cdf(x):
        return 1 - 2 ** -x

    def log_normal_cdf(x):
        return x / (1 + x)

    rank = 1 - (
        weights["commits"] * exponential_cdf(stats["commits"] / commits_median)
        + weights["prs"] * exponential_cdf(stats["prs"] / prs_median)
        + weights["issues"] * exponential_cdf(stats["issues"] / issues_median)
        + weights["reviews"] * exponential_cdf(stats["reviews"] / reviews_median)
        + weights["stars"] * log_normal_cdf(stats["stars"] / stars_median)
        + weights["followers"] * log_normal_cdf(stats["followers"] / followers_median)
    ) / total
    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
    percentile = rank * 100
    index = next((i for i, threshold in enumerate(thresholds) if percentile <= threshold), len(levels) - 1)
    return {"level": levels[index], "percentile": round(percentile, 1)}


def streak_for(days):
    ordered = sorted(days, key=lambda day: day["date"])
    longest = 0
    run = 0
    for day in ordered:
        if day["count"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    current = 0
    index = len(ordered) - 1
    if index >= 0 and ordered[index]["count"] == 0:
        index -= 1
    while index >= 0 and ordered[index]["count"] > 0:
        current += 1
        index -= 1
    return current, longest


def fetch():
    query = """
    query {
      user(login: "%s") {
        followers { totalCount }
        contributionsCollection {
          totalCommitContributions
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
        repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
          totalCount
          nodes {
            stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name color } }
            }
          }
        }
      }
    }
    """ % USER
    data = graphql(query)["data"]["user"]
    repos = data["repositories"]
    stars = sum(node["stargazerCount"] for node in repos["nodes"])
    language_bytes = {}
    for node in repos["nodes"]:
        for edge in node["languages"]["edges"]:
            name = edge["node"]["name"]
            language_bytes[name] = language_bytes.get(name, 0) + edge["size"]
    languages = sorted(language_bytes.items(), key=lambda item: item[1], reverse=True)
    total_bytes = sum(value for _, value in languages) or 1
    languages = [{"name": name, "bytes": value, "percent": round(value * 100 / total_bytes, 1)} for name, value in languages[:5]]

    weeks = []
    days = []
    for week in data["contributionsCollection"]["contributionCalendar"]["weeks"]:
        total = 0
        for day in week["contributionDays"]:
            days.append({"date": day["date"], "count": day["contributionCount"]})
            total += day["contributionCount"]
        if week["contributionDays"]:
            weeks.append({"start": week["contributionDays"][0]["date"], "total": total})

    current, longest = streak_for(days)
    commits = data["contributionsCollection"]["totalCommitContributions"]
    prs = search_count("author:%s type:pr is:public" % USER)
    issues = search_count("author:%s type:issue is:public" % USER)
    reviews = search_count("reviewed-by:%s type:pr is:public" % USER)

    stats = {
        "user": USER,
        "name": "Gyanano",
        "followers": data["followers"]["totalCount"],
        "repos": repos["totalCount"],
        "stars": stars,
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "reviews": reviews,
        "contributions": data["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "current_streak": current,
        "longest_streak": longest,
        "weeks": weeks,
        "languages": languages,
        "rank": rank_for({"commits": commits, "prs": prs, "issues": issues, "reviews": reviews, "stars": stars, "followers": data["followers"]["totalCount"]}),
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    (OUT_DIR / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats


def font(name, size, weight=None, width=None):
    path = str(FONT_DIR / name)
    face = ImageFont.truetype(path, size)
    try:
        axes = face.get_variation_axes()
        values = []
        for axis in axes:
            raw_name = axis["name"] if isinstance(axis, dict) else axis.name
            axis_name = (raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)).lower()
            if "weight" in axis_name or "wght" in axis_name:
                values.append(weight if weight is not None else axis["default"])
            elif "width" in axis_name or "wdth" in axis_name:
                values.append(width if width is not None else axis["default"])
            else:
                values.append(axis["default"])
        face.set_variation_by_axes(values)
    except Exception:
        pass
    return face


def draw_text(draw, xy, text, face, fill, tracking=0, anchor="ls"):
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=face, fill=fill, anchor=anchor)
        x += face.getlength(char) + tracking


def text_width(text, face, tracking=0):
    return sum(face.getlength(char) for char in text) + tracking * max(0, len(text) - 1)


def draw_text_right(draw, xy, text, face, fill, tracking=0):
    x, y = xy
    draw_text(draw, (x - text_width(text, face, tracking), y), text, face, fill, tracking)


def card(width, height, theme):
    image = Image.new("RGBA", (width * SS, height * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, width * SS - 1, height * SS - 1),
        radius=14 * SS,
        fill=theme["bg"],
        outline=theme["border"],
        width=max(1, SS),
    )
    return image, draw


def label(draw, xy, text, theme):
    mono = font("JetBrainsMono.ttf", 9 * SS, weight=500)
    x, y = xy
    draw.rectangle((x, y - 6 * SS, x + 5 * SS, y - 1 * SS), fill=theme["accent"])
    draw_text(draw, (x + 12 * SS, y), text, mono, theme["dim"], tracking=1.9 * SS)


def grade_card(stats, theme):
    width, height = 288, 200
    image, draw = card(width, height, theme)
    label(draw, (24 * SS, 32 * SS), "GITHUB RANK", theme)
    display = font("Anybody.ttf", 96 * SS, weight=800, width=112)
    draw_text(draw, (22 * SS, 118 * SS), stats["rank"]["level"], display, theme["ink"], tracking=2 * SS)
    top = stats["rank"]["percentile"]
    mono = font("JetBrainsMono.ttf", 10 * SS, weight=500)
    draw_text(draw, (24 * SS, 152 * SS), "TOP %s%%" % (("%g" % top)), mono, theme["accent"], tracking=2 * SS)

    track_x, track_y, track_w, track_h = 24 * SS, 170 * SS, 240 * SS, 4 * SS
    draw.rounded_rectangle((track_x, track_y, track_x + track_w, track_y + track_h), radius=track_h // 2, fill=theme["track"])
    filled = track_w * max(0.0, min(1.0, (100 - top) / 100))
    draw.rounded_rectangle((track_x, track_y, track_x + filled, track_y + track_h), radius=track_h // 2, fill=theme["accent"])
    mono_small = font("JetBrainsMono.ttf", 8 * SS, weight=400)
    draw_text(draw, (24 * SS, 190 * SS), "PERCENTILE RANK", mono_small, theme["dim"], tracking=1.6 * SS)
    return image


def stat_block(draw, x, y, value, caption, theme):
    number = font("Anybody.ttf", 40 * SS, weight=700, width=108)
    mono = font("JetBrainsMono.ttf", 8 * SS, weight=500)
    draw_text(draw, (x, y), value, number, theme["ink"], tracking=0.5 * SS)
    draw_text(draw, (x, y + 20 * SS), caption, mono, theme["dim"], tracking=1.5 * SS)


def stats_card(stats, theme):
    width, height = 576, 200
    image, draw = card(width, height, theme)
    label(draw, (24 * SS, 32 * SS), "STATS", theme)
    commits = ("%.1fk" % (stats["commits"] / 1000)) if stats["commits"] >= 1000 else str(stats["commits"])
    stat_block(draw, 24 * SS, 92 * SS, "{:,}".format(stats["stars"]), "STARS", theme)
    stat_block(draw, 300 * SS, 92 * SS, commits, "COMMITS / YEAR", theme)
    stat_block(draw, 24 * SS, 166 * SS, "{:,}".format(stats["prs"]), "PULL REQUESTS", theme)
    stat_block(draw, 300 * SS, 166 * SS, "{:,}".format(stats["issues"]), "ISSUES", theme)
    return image


def streak_card(stats, theme):
    width, height = 432, 220
    image, draw = card(width, height, theme)
    label(draw, (24 * SS, 32 * SS), "STREAK", theme)
    big = font("Anybody.ttf", 78 * SS, weight=800, width=108)
    draw_text(draw, (22 * SS, 128 * SS), str(stats["current_streak"]), big, theme["ink"], tracking=1 * SS)
    unit = font("JetBrainsMono.ttf", 10 * SS, weight=500)
    draw_text(draw, (26 * SS, 152 * SS), "DAYS IN A ROW", unit, theme["dim"], tracking=1.6 * SS)
    mono = font("JetBrainsMono.ttf", 9 * SS, weight=500)
    draw_text(draw, (250 * SS, 96 * SS), "LONGEST", mono, theme["dim"], tracking=1.6 * SS)
    medium = font("Anybody.ttf", 32 * SS, weight=700, width=108)
    draw_text(draw, (248 * SS, 130 * SS), "%d days" % stats["longest_streak"], medium, theme["ink"], tracking=0.5 * SS)
    draw_text(draw, (250 * SS, 168 * SS), "TOTAL CONTRIBUTIONS", mono, theme["dim"], tracking=1.6 * SS)
    draw_text(draw, (248 * SS, 196 * SS), "{:,}".format(stats["contributions"]), font("Anybody.ttf", 26 * SS, weight=700, width=108), theme["accent"], tracking=0.5 * SS)
    return image


def languages_card(stats, theme):
    width, height = 432, 220
    image, draw = card(width, height, theme)
    label(draw, (24 * SS, 32 * SS), "LANGUAGES", theme)
    name_font = font("HankenGrotesk.ttf", 12 * SS, weight=600)
    mono = font("JetBrainsMono.ttf", 9 * SS, weight=500)
    top = stats["languages"][:4] or [{"name": "n/a", "percent": 0}]
    y = 72 * SS
    for index, language in enumerate(top):
        percent = language["percent"]
        draw_text(draw, (24 * SS, y), language["name"], name_font, theme["ink"], tracking=0.2 * SS)
        draw_text_right(draw, (408 * SS, y), "%s%%" % (("%g" % percent)), mono, theme["dim"], tracking=1.2 * SS)
        track_y = y + 10 * SS
        draw.rounded_rectangle((24 * SS, track_y, 408 * SS, track_y + 3 * SS), radius=1.5 * SS, fill=theme["track"])
        fill_w = 384 * SS * max(0.0, min(1.0, percent / 100))
        if fill_w > 0:
            draw.rounded_rectangle((24 * SS, track_y, 24 * SS + fill_w, track_y + 3 * SS), radius=1.5 * SS, fill=theme["accent"])
        y += 34 * SS
    return image


def contributions_card(stats, theme):
    width, height = 880, 240
    image, draw = card(width, height, theme)
    label(draw, (24 * SS, 32 * SS), "CONTRIBUTIONS · LAST 12 MONTHS", theme)
    total = font("Anybody.ttf", 44 * SS, weight=700, width=108)
    draw_text(draw, (22 * SS, 92 * SS), "{:,}".format(stats["contributions"]), total, theme["ink"], tracking=0.5 * SS)
    mono = font("JetBrainsMono.ttf", 8 * SS, weight=500)
    draw_text(draw, (24 * SS, 112 * SS), "TOTAL CONTRIBUTIONS", mono, theme["dim"], tracking=1.5 * SS)

    weeks = stats["weeks"]
    chart_left, chart_right = 320, 856
    chart_bottom, chart_top = 196, 84
    if weeks:
        peak = max(week["total"] for week in weeks) or 1
        points = []
        count = len(weeks)
        for index, week in enumerate(weeks):
            x = chart_left + (chart_right - chart_left) * index / max(1, count - 1)
            y = chart_bottom - (chart_bottom - chart_top) * (week["total"] / peak)
            points.append((x * SS, y * SS))
        mask = Image.new("L", image.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        polygon = [(chart_left * SS, chart_bottom * SS)] + points + [(chart_right * SS, chart_bottom * SS)]
        mask_draw.polygon(polygon, fill=150)
        gradient = Image.new("RGBA", image.size, (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient)
        for row in range(chart_top * SS, chart_bottom * SS):
            t = (row - chart_top * SS) / max(1, (chart_bottom - chart_top) * SS)
            alpha = int(200 * (1 - t) ** 1.1)
            gradient_draw.line(((chart_left * SS, row), (chart_right * SS, row)), fill=theme["chart"] + (alpha,))
        image.alpha_composite(Image.composite(gradient, Image.new("RGBA", image.size, (0, 0, 0, 0)), mask))
        line = Image.new("RGBA", image.size, (0, 0, 0, 0))
        line_draw = ImageDraw.Draw(line)
        line_draw.line(points, fill=theme["chart"] + (255,), width=int(2.4 * SS), joint="curve")
        image.alpha_composite(line)

        month_font = font("JetBrainsMono.ttf", 7 * SS, weight=400)
        seen = set()
        for index, week in enumerate(weeks):
            month = week["start"][:7]
            if month in seen:
                continue
            seen.add(month)
            month_name = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][int(week["start"][5:7]) - 1]
            x = chart_left + (chart_right - chart_left) * index / max(1, count - 1)
            draw_text(draw, (x * SS, 220 * SS), month_name, month_font, theme["dim"], tracking=1.2 * SS)
    return image


def compose_row(cards, height):
    width = sum(width for width, _ in cards) + 16 * (len(cards) - 1)
    row = Image.new("RGBA", (width * SS, height * SS), (0, 0, 0, 0))
    x = 0
    for width_value, image in cards:
        row.alpha_composite(image, (x * SS, 0))
        x += width_value + 16
    return row.resize((width * FINAL, height * FINAL), Image.Resampling.LANCZOS)


def render(stats):
    for theme_name, theme in THEMES.items():
        grade = grade_card(stats, theme)
        stats_card_image = stats_card(stats, theme)
        streak = streak_card(stats, theme)
        languages = languages_card(stats, theme)
        contributions = contributions_card(stats, theme)

        row1 = compose_row([(288, grade), (576, stats_card_image)], 200)
        row2 = compose_row([(432, streak), (432, languages)], 220)
        row3 = compose_row([(880, contributions)], 240)
        row1.save(OUT_DIR / ("bento-1-%s.png" % theme_name), optimize=True)
        row2.save(OUT_DIR / ("bento-2-%s.png" % theme_name), optimize=True)
        row3.save(OUT_DIR / ("bento-3-%s.png" % theme_name), optimize=True)
        print("rendered", theme_name)


if __name__ == "__main__":
    stats = fetch()
    render(stats)
    print("done", stats["rank"], stats["commits"], stats["stars"], stats["contributions"])
