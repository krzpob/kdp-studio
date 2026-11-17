"""Dopasowanie obrazu z modelu do wzorca przekształceniem afinicznym (FR-15).

Modele obrazu przerysowują cały obraz wejściowy, także to, co miało zostać bez zmian:
pokolorowany przód okładki i znany pas przodu przy dorysowaniu tyłu wracają lekko
przesunięte i przeskalowane (na próbach z 17.11: o ~1–4% wysokości i 2–3%). Program mierzy
to przesunięcie (OpenCV ECC na zmniejszonym obrazie) i cofa je, zanim nałoży ostre kontury
albo zestawi tył z przodem. Dopasowanie idzie w dwóch krokach: najpierw samo przesunięcie na
mocno rozmytym obrazie, potem pełne przekształcenie afiniczne. Bez pierwszego kroku ECC
startujące od tożsamości utyka przy przesunięciu ok. 6% wysokości (próba z 17.11).
"""

from __future__ import annotations

import cv2
import numpy as np

MIN_CC = 0.5  # słabsza zgodność (ECC) to nieudane dopasowanie
MAX_SCALE = 0.15  # dopuszczalna zmiana skali i pochylenia (±)
MAX_SHIFT = 0.1  # dopuszczalne przesunięcie (ułamek wysokości)
COARSE_BLUR = 0.01  # rozmycie przy zgrubnym przesunięciu (ułamek szerokości, min. 4 px)


def ecc_affine(
    template: np.ndarray, image: np.ndarray, downscale: int = 1
) -> tuple[np.ndarray, float] | None:
    """Macierz 2×3 (współrzędne wzorca → obrazu, w pełnej rozdzielczości) i zgodność ECC,
    albo None, gdy dopasowanie się nie zbiegło lub wyszło poza granice.

    `template` i `image` to jednokanałowe obrazy tej samej wielkości (np. odcienie szarości
    albo rozmyte maski konturów); `downscale` przyspiesza liczenie na dużych obrazach.
    """

    def small(img: np.ndarray) -> np.ndarray:
        data = np.ascontiguousarray(img, dtype=np.float32)
        if downscale == 1:
            return data
        resized = cv2.resize(
            data, None, fx=1 / downscale, fy=1 / downscale, interpolation=cv2.INTER_AREA
        )
        return np.asarray(resized, dtype=np.float32)

    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    fine_template, fine_image = small(template), small(image)
    sigma = max(4.0, COARSE_BLUR * fine_template.shape[1])

    def blurred(img: np.ndarray) -> np.ndarray:
        return np.asarray(cv2.GaussianBlur(img, (0, 0), sigma), dtype=np.float32)

    start = np.eye(2, 3, dtype=np.float32)
    try:
        _, coarse = cv2.findTransformECC(
            blurred(fine_template),
            blurred(fine_image),
            start,
            cv2.MOTION_TRANSLATION,
            criteria,
            None,
        )
        start = np.asarray(coarse, dtype=np.float32)
    except cv2.error:
        start = np.eye(2, 3, dtype=np.float32)  # bez zgrubnego kroku: od tożsamości
    try:
        cc, found = cv2.findTransformECC(
            fine_template, fine_image, start, cv2.MOTION_AFFINE, criteria, None
        )
    except cv2.error:
        return None
    matrix = np.asarray(found, dtype=np.float64)
    matrix[:, 2] *= downscale
    if (
        cc < MIN_CC
        or np.abs(matrix[:, :2] - np.eye(2)).max() > MAX_SCALE
        or np.abs(matrix[:, 2]).max() > MAX_SHIFT * template.shape[0]
    ):
        return None
    return matrix, round(float(cc), 3)


def shift_origin(matrix: np.ndarray, x: float) -> np.ndarray:
    """Ta sama macierz dla obrazu, w którym wzorzec zaczyna się w kolumnie `x`."""
    linear, offset = matrix[:, :2], matrix[:, 2]
    origin = np.array([x, 0.0])
    return np.hstack([linear, (offset + origin - linear @ origin)[:, None]])


def warp_back(image: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Obraz cofnięty do układu wzorca: wynik(p) = obraz(macierz · p)."""
    height, width = image.shape[:2]
    out = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return np.asarray(out, dtype=image.dtype)
