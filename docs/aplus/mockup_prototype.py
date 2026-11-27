"""Prototyp nagłówka A+ (sekcja 14a): książeczki leżące płasko w wachlarzu, przód nad tyłem.

Szkic do przyszłej implementacji, nie część programu. Użycie:
    uv run python docs/aplus/mockup_prototype.py output/<książka>/cover wynik.jpg
Czyta cover.png (geometria kwadratu 8.5", 104 strony) i front.png, zapisuje JPG 1940 × 1200
(970 × 600 w podwójnej rozdzielczości). Wymiary grzbietu są tu wpisane na sztywno; program
weźmie je z manifest.cover.geometry.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
B = str(Path(sys.argv[1])) + "/"
OUT = Path(sys.argv[2])
W, H = 1940, 1200
cover = Image.open(B + "cover.png").convert("RGB")
p = lambda i: round(i * 300)
back = cover.crop((p(0.125), p(0.125), p(8.625), p(8.625)))
front = Image.open(B + "front.png").convert("RGB")
spine = cover.crop((p(8.625), p(0.125), p(8.859208), p(8.625)))

size = 1000  # bok okładki w px przy wysokości 1200: największy, przy którym obrót mieści się w kadrze
edge = max(4, size // 120)        # widoczna krawędź bloku stron (grubość książki)

def flat_book(face, angle, spine_right=False):
    """Książka leżąca płasko: okładka, pod nią jasny blok stron przesunięty o `edge`, obrót w płaszczyźnie.
    Leżąca tyłem do góry ma grzbiet po prawej: tam krawędź to grzbiet okładki, nie kartki."""
    f = face.resize((size, size), Image.Resampling.LANCZOS)
    book = Image.new("RGBA", (size + edge, size + edge), (0, 0, 0, 0))
    d = ImageDraw.Draw(book)
    d.rectangle((edge, edge, size + edge - 1, size + edge - 1), fill=(232, 228, 220, 255))  # blok stron
    for i in range(0, edge, 2):  # delikatne linie kartek
        d.line((edge, size + i, size + edge - 1, size + i), fill=(205, 200, 192, 255))
        d.line((size + i, edge, size + i, size + edge - 1), fill=(205, 200, 192, 255))
    if spine_right:  # zgięcie okładki: kolor grzbietu, lekko w cieniu
        strip = spine.resize((1, size), Image.Resampling.BOX).resize((edge, size))  # kolor tła grzbietu, bez ściśniętego napisu
        strip = Image.eval(strip, lambda v: int(v * 0.85))
        book.paste(strip, (size, edge))
    book.paste(f, (0, 0))
    return book.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

def shadow(img, blur, opacity):
    """Cień z marginesem 3 × blur, żeby rozmycie nie urywało się na brzegu obrazu."""
    pad = blur * 3
    alpha = Image.new("L", (img.width + 2 * pad, img.height + 2 * pad), 0)
    alpha.paste(img.split()[3], (pad, pad))
    alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
    sh = Image.new("RGBA", alpha.size, (40, 30, 25, 0))
    sh.putalpha(alpha.point(lambda v: int(v * opacity)))
    return sh, pad

import cv2  # noqa: E402


def lab(rgb):
    a = np.asarray(rgb, np.float32).reshape(-1, 1, 3) / 255.0
    return cv2.cvtColor(a, cv2.COLOR_RGB2LAB).reshape(-1, 3)

# Tło: nie białe i wyraźnie inne niż brzegi okładek. Kandydaci z konfiguracji; wygrywa ten, którego
# najmniejsza odległość ΔE od kolorów pasa brzegowego obu okładek jest największa.
CANDIDATES = {
    "beż": (226, 212, 190), "szałwia": (200, 212, 190), "pudrowy róż": (232, 206, 200),
    "szaroniebieski": (200, 210, 222), "ciepły szary": (214, 208, 200),
}
def border(img, frac=0.04):
    a = np.asarray(img.resize((200, 200)))
    k = max(1, int(200 * frac))
    return np.concatenate([a[:k].reshape(-1, 3), a[-k:].reshape(-1, 3), a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3)])
edges = lab(np.concatenate([border(front), border(back)]))
scores = {}
for name, rgb in CANDIDATES.items():
    d = np.linalg.norm(edges - lab([rgb]), axis=1)
    scores[name] = float(np.percentile(d, 5))  # odporne na pojedyncze piksele
best = max(scores, key=scores.get)
print("tło:", best, {k: round(v, 1) for k, v in scores.items()})
top = np.array(CANDIDATES[best], float)
y = np.linspace(0, 1, H)[:, None, None]
bg = top * (1.04 - 0.08 * y)  # lekki gradient: jaśniej u góry, ciemniej na dole
bg = np.clip(bg, 0, 255)
canvas = Image.fromarray(np.broadcast_to(bg, (H, W, 3)).astype(np.uint8), "RGB").convert("RGBA")

b_img = flat_book(back, -9, spine_right=True)   # tył: obrócony w prawo, pod spodem
f_img = flat_book(front, 7)   # przód: obrócony w lewo, na wierzchu
fx = int(W * 0.04); fy = (H - f_img.height) // 2
bx = fx + int(size * 0.62); by = (H - b_img.height) // 2 + int(size * 0.02)
for img, (x, y0) in ((b_img, (bx, by)), (f_img, (fx, fy))):
    sh, pad = shadow(img, 22, 0.40)
    canvas.alpha_composite(sh, (x + 16 - pad, y0 + 24 - pad))
    canvas.alpha_composite(img, (x, y0))
out = canvas.convert("RGB")
out.save(OUT, quality=90, optimize=True)
print(size, f_img.size, b_img.size, (fx, fy), (bx, by))
