"""Quality Control pipeline for background images.

Cheap → expensive checks (ARCHITECTURE.md §7):
    Resolution → Brightness → Entropy → Blur → Duplicate → (Vision, optional)

Rejects go to ``tools/rejected/``, never the library.
Vision check is last and optional (requires API key).

Usage:
    python -m tools.qc backgrounds/technology/
    python -m tools.qc backgrounds/ --recursive
    python -m tools.qc backgrounds/ --vision-key $KEY
"""
from __future__ import annotations

import argparse
import hashlib
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageStat


# ------------------------------------------------------------------ Thresholds

MIN_RESOLUTION = (800, 400)  # minimum width × height
BRIGHTNESS_MIN = 0.02  # reject almost-black images
BRIGHTNESS_MAX = 0.95  # reject almost-white images
ENTROPY_MIN = 1.0  # reject solid-colour images
ENTROPY_MAX = 7.0  # reject pure noise
BLUR_THRESHOLD = 5.0  # variance-of-Laplacian threshold (below = blurry)
DUPLICATE_SIMILARITY = 0.98  # perceptual hash similarity threshold


# ------------------------------------------------------------------ Result


@dataclass
class QCResult:
    """Result of QC for a single image."""

    path: Path
    passed: bool = True
    reasons: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.reasons.append(reason)


# ------------------------------------------------------------------ Checks


def check_resolution(img: Image.Image, result: QCResult) -> None:
    """Check that the image meets minimum resolution."""
    w, h = img.size
    if w < MIN_RESOLUTION[0] or h < MIN_RESOLUTION[1]:
        result.fail(f"resolution {w}x{h} below minimum {MIN_RESOLUTION[0]}x{MIN_RESOLUTION[1]}")


def check_brightness(img: Image.Image, result: QCResult) -> None:
    """Check that brightness is in a reasonable range."""
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    brightness = stat.mean[0] / 255.0

    if brightness < BRIGHTNESS_MIN:
        result.fail(f"too dark (brightness={brightness:.3f})")
    elif brightness > BRIGHTNESS_MAX:
        result.fail(f"too bright (brightness={brightness:.3f})")


def check_entropy(img: Image.Image, result: QCResult) -> None:
    """Check that the image has enough visual information (not solid colour).

    Uses histogram-based entropy as a proxy.
    """
    gray = img.convert("L")
    hist = gray.histogram()

    # Normalise histogram to probabilities
    total = sum(hist)
    if total == 0:
        result.fail("empty histogram")
        return

    entropy = 0.0
    for count in hist:
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    if entropy < ENTROPY_MIN:
        result.fail(f"too uniform (entropy={entropy:.2f} bits)")
    elif entropy > ENTROPY_MAX:
        result.fail(f"too noisy (entropy={entropy:.2f} bits)")


def check_blur(img: Image.Image, result: QCResult) -> None:
    """Check that the image is not blurry.

    Uses variance of Laplacian (standard sharpness metric).
    """
    gray = img.convert("L")
    # Resize for speed — we only need a sample
    small = gray.resize((320, 180))

    # Compute variance of Laplacian manually
    import numpy as np

    arr = np.array(small, dtype=np.float64)
    # Laplacian kernel
    kernel = np.array([[0, -1, 0], [-1, 4, -1], [0, -1, 0]])
    padded = np.pad(arr, 1, mode="edge")
    convolved = np.zeros_like(arr)

    for ky in range(3):
        for kx in range(3):
            convolved += padded[ky : ky + arr.shape[0], kx : kx + arr.shape[1]] * kernel[ky, kx]

    variance = float(np.var(convolved))

    if variance < BLUR_THRESHOLD:
        result.fail(f"blurry (sharpness={variance:.1f})")


def perceptual_hash(img: Image.Image) -> int:
    """Compute a simple perceptual hash (average hash).

    Returns an integer hash for comparison.
    """
    small = img.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(small.get_flattened_data())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


def hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two integers."""
    return bin(a ^ b).count("1")


def check_duplicates(
    result: QCResult,
    known_hashes: dict[int, Path],
) -> None:
    """Check if the image is a near-duplicate of an already-accepted image."""
    current_hash = perceptual_hash(result.path.read_bytes() if False else None)  # placeholder
    # We need the actual PIL Image for phash — caller should pass it.
    # This is a simplified version; the real check is in run_qc().


def check_duplicate_with_image(
    img: Image.Image,
    result: QCResult,
    known_hashes: dict[str, Path],
) -> str | None:
    """Check if the image is a near-duplicate. Returns formatted hash string or None."""
    current_hash = perceptual_hash(img)
    current_key = format(current_hash, "016b")

    for known_key, known_path in known_hashes.items():
        distance = hamming_distance(current_hash, int(known_key, 2))
        similarity = 1.0 - (distance / 64)  # 64 bits in 8x8 phash

        if similarity >= DUPLICATE_SIMILARITY:
            result.fail(f"near-duplicate of {known_path.name} (similarity={similarity:.2f})")
            return current_key

    return current_key


# ------------------------------------------------------------------ Vision (optional)


async def check_vision(
    img_path: Path,
    api_key: str,
    result: QCResult,
) -> None:
    """Optional Vision API check for image quality.

    This is the most expensive check and is optional.
    Uses a Vision model to assess image quality.
    """
    import base64
    import httpx

    # Encode image
    img_data = img_path.read_bytes()
    b64 = base64.b64encode(img_data).decode("ascii")

    prompt = (
        "Evaluate this background image for a professional card design. "
        "Check: 1) Is the image visually appealing? "
        "2) Does it have enough negative space for text? "
        "3) Is it free of artifacts and distortions? "
        "Respond with 'ACCEPT' or 'REJECT: <reason>'."
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{b64}",
                                        "detail": "low",
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 50,
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )

        if response.status_code == 200:
            reply = response.json()["choices"][0]["message"]["content"].strip()
            if reply.startswith("REJECT"):
                reason = reply.split(":", 1)[1].strip() if ":" in reply else "Vision rejection"
                result.fail(f"Vision: {reason}")
        else:
            # Vision API failure — don't reject, just log
            print(f"  [WARNING] Vision API error: {response.status_code}")

    except Exception as e:
        print(f"  [WARNING] Vision check failed: {e}")


# ------------------------------------------------------------------ Pipeline


async def run_qc(
    img_path: Path,
    known_hashes: dict[str, Path],
    vision_key: str | None = None,
    skip_checks: set[str] | None = None,
) -> tuple[QCResult, str | None]:
    """Run the full QC pipeline on a single image.

    Args:
        img_path: Path to the image file.
        known_hashes: Already-accepted image hashes for duplicate detection.
        vision_key: Optional Vision API key.
        skip_checks: Set of check names to skip (e.g. {"blur"}).

    Returns (result, accepted_hash_string_or_None).
    """
    if skip_checks is None:
        skip_checks = set()

    result = QCResult(path=img_path)
    accepted_hash: str | None = None

    try:
        img = Image.open(img_path)
        img.load()  # force load so we catch corrupted files
    except Exception as e:
        result.fail(f"cannot open: {e}")
        return result, None

    # Cheap → expensive
    if "resolution" not in skip_checks:
        check_resolution(img, result)
    if "brightness" not in skip_checks:
        check_brightness(img, result)
    if "entropy" not in skip_checks:
        check_entropy(img, result)
    if "blur" not in skip_checks:
        check_blur(img, result)
    if "duplicate" not in skip_checks:
        accepted_hash = check_duplicate_with_image(img, result, known_hashes)

    # Vision (optional, last)
    if vision_key and result.passed and "vision" not in skip_checks:
        await check_vision(img_path, vision_key, result)

    return result, accepted_hash


def main() -> None:
    """CLI entry point."""
    import asyncio

    all_checks = {"resolution", "brightness", "entropy", "blur", "duplicate", "vision"}
    parser = argparse.ArgumentParser(
        description="QC pipeline for background images",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", help="Image files or directories to check")
    parser.add_argument("--recursive", action="store_true", help="Recurse into subdirectories")
    parser.add_argument("--vision-key", type=str, default=None, help="Vision API key (optional)")
    parser.add_argument("--reject-dir", type=str, default="tools/rejected", help="Directory for rejects")
    parser.add_argument(
        "--skip-checks", nargs="*", type=str, default=[],
        help=f"Checks to skip: {sorted(all_checks)}",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report results without moving rejected files",
    )
    args = parser.parse_args()
    skip_checks = set(args.skip_checks)

    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

    # Collect image paths
    image_paths: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_file() and path.suffix.lower() in _IMAGE_EXTS:
            image_paths.append(path)
        elif path.is_dir():
            if args.recursive:
                for ext in _IMAGE_EXTS:
                    image_paths.extend(path.glob(f"**/*{ext}"))
            else:
                for ext in _IMAGE_EXTS:
                    image_paths.extend(path.glob(f"*{ext}"))

    image_paths = sorted(set(image_paths))
    if not image_paths:
        print("No images found.")
        return

    reject_dir = Path(args.reject_dir)
    reject_dir.mkdir(parents=True, exist_ok=True)

    known_hashes: dict[str, Path] = {}
    accepted = 0
    rejected = 0
    errors = 0

    for img_path in image_paths:
        try:
            result, img_hash = asyncio.run(
                run_qc(img_path, known_hashes, vision_key=args.vision_key, skip_checks=skip_checks)
            )

            if result.passed:
                accepted += 1
                if img_hash is not None:
                    known_hashes[img_hash] = img_path
                print(f"  ✓ {img_path.name}")
            else:
                rejected += 1
                reasons = ", ".join(result.reasons)
                if args.dry_run:
                    print(f"  ✗ {img_path.name} — WOULD REJECT: {reasons}")
                else:
                    # Move to reject directory
                    reject_path = reject_dir / img_path.name
                    import shutil
                    shutil.move(str(img_path), str(reject_path))
                    print(f"  ✗ {img_path.name} — REJECTED: {reasons}")

        except Exception as e:
            errors += 1
            print(f"  ! {img_path.name} — ERROR: {e}", file=sys.stderr)

    print(f"\nQC complete: {accepted} accepted, {rejected} rejected, {errors} errors")


if __name__ == "__main__":
    main()
