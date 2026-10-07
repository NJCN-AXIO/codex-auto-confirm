"""Generate docs/demo.gif — an animated schematic of codex-auto-confirm in action."""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 960, 600
BG = (12, 12, 12)
TITLEBAR = (32, 32, 32)
TEXT = (204, 204, 204)
DIM = (128, 128, 128)
GREEN = (34, 197, 94)
BLUE = (59, 130, 246)
RED = (239, 68, 68)
YELLOW = (234, 179, 8)
PANEL = (24, 24, 28)
BORDER = (60, 60, 60)

# Try to load a monospace font; fall back to default.
def load_font(size):
    for path in [
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\cour.ttf",
        r"C:\Windows\Fonts\lucon.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

F = load_font(18)
F_SM = load_font(14)
F_TITLE = load_font(15)

TERM_X, TERM_Y = 30, 60
TERM_W, TERM_H = 620, 500

PANEL_X, PANEL_Y = 680, 60
PANEL_W, PANEL_H = 250, 500


def base_frame():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # App title
    d.text((30, 20), "codex-auto-confirm — schematic", fill=TEXT, font=F_TITLE)
    # Terminal window
    d.rectangle([TERM_X, TERM_Y, TERM_X + TERM_W, TERM_Y + TERM_H], outline=BORDER, width=2)
    d.rectangle([TERM_X, TERM_Y, TERM_X + TERM_W, TERM_Y + 28], fill=TITLEBAR)
    d.text((TERM_X + 10, TERM_Y + 6), "my-laptop - Windows Terminal", fill=TEXT, font=F_TITLE)
    # Monitor panel
    d.rectangle([PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + PANEL_H], outline=BORDER, width=2)
    d.rectangle([PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + 28], fill=TITLEBAR)
    d.text((PANEL_X + 10, PANEL_Y + 6), "auto-confirm monitor", fill=TEXT, font=F_TITLE)
    return img, d


def term_lines(d, lines, y0=TERM_Y + 48):
    y = y0
    for ln in lines:
        text, color = ln
        d.text((TERM_X + 14, y), text, fill=color, font=F)
        y += 26
    return y


def panel(d, status, status_color, note):
    d.text((PANEL_X + 14, PANEL_Y + 48), "F9 = toggle", fill=DIM, font=F_SM)
    d.text((PANEL_X + 14, PANEL_Y + 72), "F10 = exit", fill=DIM, font=F_SM)
    d.text((PANEL_X + 14, PANEL_Y + 110), "Status:", fill=DIM, font=F_SM)
    d.text((PANEL_X + 14, PANEL_Y + 134), status, fill=status_color, font=F)
    d.text((PANEL_X + 14, PANEL_Y + 180), "Last action:", fill=DIM, font=F_SM)
    # wrap note
    words = note.split()
    line = ""
    yy = PANEL_Y + 204
    for w in words:
        if len(line) + len(w) + 1 > 30:
            d.text((PANEL_X + 14, yy), line, fill=TEXT, font=F_SM)
            yy += 20
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        d.text((PANEL_X + 14, yy), line, fill=TEXT, font=F_SM)


frames = []

# Frame 1: normal working state
img, d = base_frame()
term_lines(d, [
    ("OpenAI Codex (v0.156.1)", DIM),
    ("", TEXT),
    ("Working: analyzing 42 files", GREEN),
    ("  duration: 00:12 • esc to interrupt", DIM),
])
panel(d, "MONITORING", GREEN, "watching for prompts / errors")
frames.append(img)

# Frame 2: approval prompt appears
img, d = base_frame()
term_lines(d, [
    ("OpenAI Codex (v0.156.1)", DIM),
    ("", TEXT),
    ("", TEXT),
    ("Would you like to run the following command?", TEXT),
    ("  git status", DIM),
    ("", TEXT),
    ("> 1. Yes, proceed (y)", BLUE),
    ("  2. No, and tell Codex what to do differently", TEXT),
])
panel(d, "PROMPT DETECTED", YELLOW, "sending Enter via PostMessage")
frames.append(img)

# Frame 3: approved, running
img, d = base_frame()
term_lines(d, [
    ("OpenAI Codex (v0.156.1)", DIM),
    ("", TEXT),
    ("", TEXT),
    ("Running: git status", GREEN),
    ("  On branch main", DIM),
    ("  nothing to commit, working tree clean", DIM),
    ("", TEXT),
    ("Working: analyzing next task", GREEN),
])
panel(d, "MONITORING", GREEN, "prompt confirmed, back to work")
frames.append(img)

# Frame 4: 429 error
img, d = base_frame()
term_lines(d, [
    ("OpenAI Codex (v0.156.1)", DIM),
    ("", TEXT),
    ("  Working: generating...", GREEN),
    ("  duration: 00:08 • esc to interrupt", DIM),
    ("", TEXT),
    ("error: 429 Too Many Requests", RED),
    ("last status: 429 Too Many Requests", RED),
])
panel(d, "ERROR DETECTED", RED, "typing continue + Enter")
frames.append(img)

# Frame 5: recovered
img, d = base_frame()
term_lines(d, [
    ("OpenAI Codex (v0.156.1)", DIM),
    ("", TEXT),
    ("  continuing...", DIM),
    ("", TEXT),
    ("Working: generating", GREEN),
    ("  duration: 00:03 • esc to interrupt", DIM),
    ("", TEXT),
    ("  (no focus stolen from your other windows)", DIM),
])
panel(d, "RECOVERED", GREEN, "authoritative Working status seen")
frames.append(img)

out = os.path.join(os.path.dirname(__file__), "demo.gif")
frames[0].save(
    out,
    save_all=True,
    append_images=frames[1:],
    duration=1400,
    loop=0,
    optimize=True,
)
print("wrote", out, os.path.getsize(out), "bytes")
