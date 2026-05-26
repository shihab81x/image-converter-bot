import os
import gc
from PIL import Image

SUPPORTED_FORMATS = ["PNG", "JPG", "JPEG", "WEBP", "BMP", "GIF", "ICO", "TIFF"]
RESIZE_PRESETS = {
    "512x512": (512, 512),
    "1024x1024": (1024, 1024),
    "1280x720": (1280, 720),
    "1920x1080": (1920, 1080),
}
COMPRESS_QUALITY = {
    "low": 40,
    "medium": 65,
    "high": 85,
    "maximum": 95,
}

# ============ RAM LIMITS (for 512MB Render free tier) ============
MAX_IMAGE_PIXELS = 4096 * 4096  # ~16MP max — prevents OOM on huge images
MAX_FILE_SIZE_MB = 20  # reject files bigger than this
AUTO_RESIZE_MAX = 2048  # auto-downscale if any dimension exceeds this


def _enforce_limits(img):
    """Auto-downscale huge images to prevent OOM. Returns (img, was_resized)."""
    w, h = img.size
    if w * h > MAX_IMAGE_PIXELS:
        # Scale down to fit within MAX_IMAGE_PIXELS
        import math
        scale = math.sqrt(MAX_IMAGE_PIXELS / (w * h))
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return img, True
    if w > AUTO_RESIZE_MAX or h > AUTO_RESIZE_MAX:
        ratio = min(AUTO_RESIZE_MAX / w, AUTO_RESIZE_MAX / h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return img, True
    return img, False


def get_image_info(file_path):
    """Detect image format, size, resolution."""
    try:
        fsize_mb = os.path.getsize(file_path) / (1024 * 1024)
        if fsize_mb > MAX_FILE_SIZE_MB:
            return {"error": f"File too large ({fsize_mb:.1f}MB). Max {MAX_FILE_SIZE_MB}MB allowed."}

        with Image.open(file_path) as img:
            img.load()  # force load into memory so we can close the file
            width, height = img.size
            fmt = img.format or "UNKNOWN"
            mode = img.mode
            return {
                "format": fmt,
                "width": width,
                "height": height,
                "size_bytes": int(fsize_mb * 1024 * 1024),
                "size_mb": round(fsize_mb, 2),
                "mode": mode,
            }
    except Exception as e:
        return {"error": str(e)}


def convert_image(input_path, output_format, quality="high", resize=None, compress=False):
    """
    Convert image to target format.
    Memory-optimized: auto-downscales huge images, uses streaming saves.
    Returns output file path or raises error.
    """
    output_format = output_format.upper()
    if output_format == "JPG":
        output_format = "JPEG"

    ext_map = {
        "JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp",
        "BMP": ".bmp", "GIF": ".gif", "ICO": ".ico", "TIFF": ".tiff",
    }

    ext = ext_map.get(output_format, f".{output_format.lower()}")
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_dir = os.path.dirname(input_path)
    output_path = os.path.join(output_dir, f"{base_name}_converted{ext}")

    with Image.open(input_path) as img:
        img.load()

        # Auto-downscale huge images to prevent OOM
        img, was_resized = _enforce_limits(img)

        # Convert RGBA/P for formats that don't support alpha
        if output_format in ("JPEG", "BMP"):
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
        elif output_format == "ICO":
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")
            img = img.resize((256, 256), Image.LANCZOS)
        elif output_format == "GIF":
            if img.mode not in ("P", "L", "RGBA"):
                img = img.convert("P", palette=Image.ADAPTIVE, colors=256)

        # Resize if requested
        if resize and resize in RESIZE_PRESETS:
            target_size = RESIZE_PRESETS[resize]
            img = img.resize(target_size, Image.LANCZOS)

        # Save with quality/compression
        save_kwargs = {}
        q = COMPRESS_QUALITY.get(quality, 85)

        if output_format in ("JPEG", "WEBP"):
            save_kwargs["quality"] = q
            save_kwargs["optimize"] = True
        elif output_format == "PNG":
            save_kwargs["optimize"] = True
        elif output_format == "GIF":
            save_kwargs["optimize"] = True

        img.save(output_path, format=output_format, **save_kwargs)

    # Force garbage collection after heavy image ops
    gc.collect()
    return output_path


def batch_convert(input_paths, output_format, quality="high", resize=None):
    """Convert multiple images. Returns list of (input, output, error) tuples."""
    results = []
    for path in input_paths:
        try:
            out = convert_image(path, output_format, quality, resize)
            results.append((path, out, None))
        except Exception as e:
            results.append((path, None, str(e)))
    return results


def cleanup_file(file_path):
    """Delete a temporary file safely."""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except:
        pass


def cleanup_batch(file_paths):
    """Delete multiple temp files."""
    for f in file_paths:
        cleanup_file(f)
