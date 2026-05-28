import os
import gc
import time  # ← Already exists, use for cache
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

# ============ RAM LIMITS ============
MAX_IMAGE_PIXELS = 4096 * 4096
MAX_FILE_SIZE_MB = 20
AUTO_RESIZE_MAX = 2048

# ============ SMART CACHE ============
_info_cache = {}  # file_path → (info, timestamp)
CACHE_TTL = 60  # 60 seconds


def _enforce_limits(img):
    """Auto-downscale huge images to prevent OOM."""
    w, h = img.size
    if w * h > MAX_IMAGE_PIXELS:
        import math
        scale = math.sqrt(MAX_IMAGE_PIXELS / (w * h))
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return img, True
    if w > AUTO_RESIZE_MAX or h > AUTO_RESIZE_MAX:
        ratio = min(AUTO_RESIZE_MAX / w, AUTO_RESIZE_MAX / h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return img, True
    return img, False


def get_image_info(file_path):
    """Smart info with cache — avoids re-opening same file."""
    global _info_cache
    
    # Check cache first
    now = time.time()
    if file_path in _info_cache:
        cached_info, cached_time = _info_cache[file_path]
        if now - cached_time < CACHE_TTL:
            return cached_info
    
    # Fresh read
    try:
        fsize_mb = os.path.getsize(file_path) / (1024 * 1024)
        if fsize_mb > MAX_FILE_SIZE_MB:
            return {"error": f"File too large ({fsize_mb:.1f}MB). Max {MAX_FILE_SIZE_MB}MB allowed."}

        with Image.open(file_path) as img:
            img.load()
            width, height = img.size
            fmt = img.format or "UNKNOWN"
            mode = img.mode
            
            info = {
                "format": fmt,
                "width": width,
                "height": height,
                "size_bytes": int(fsize_mb * 1024 * 1024),
                "size_mb": round(fsize_mb, 2),
                "mode": mode,
                "pixels": width * height,
                "needs_resize": width * height > MAX_IMAGE_PIXELS or width > AUTO_RESIZE_MAX or height > AUTO_RESIZE_MAX,
            }
            
            # Cache it
            _info_cache[file_path] = (info, now)
            return info
            
    except Exception as e:
        return {"error": str(e)}


def convert_image(input_path, output_format, quality="high", resize=None, compress=False):
    """
    Smart convert — memory-optimized, auto-detects best settings.
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

        # Smart: Auto-downscale if needed
        img, was_resized = _enforce_limits(img)

        # Smart: Auto-detect best mode for format
        if output_format in ("JPEG", "BMP"):
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
        elif output_format == "ICO":
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")
            # Smart: ICO needs multiple sizes, but we use 256x256
            img = img.resize((256, 256), Image.LANCZOS)
        elif output_format == "GIF":
            if img.mode not in ("P", "L", "RGBA"):
                img = img.convert("P", palette=Image.ADAPTIVE, colors=256)
        elif output_format == "PNG":
            # Smart: Keep RGBA for PNG if it has transparency
            if img.mode == "P" and "transparency" in img.info:
                img = img.convert("RGBA")
            elif img.mode in ("RGB", "RGBA"):
                pass  # Keep as-is
            else:
                img = img.convert("RGB")

        # Smart: Resize only if different from current
        if resize and resize in RESIZE_PRESETS:
            target_size = RESIZE_PRESETS[resize]
            if img.size != target_size:
                img = img.resize(target_size, Image.LANCZOS)

        # Smart: Auto quality based on image size
        save_kwargs = {}
        q = COMPRESS_QUALITY.get(quality, 85)
        
        # Smart: For small images, use higher quality
        if img.size[0] * img.size[1] < 500000:  # < 0.5MP
            q = min(q + 5, 95)  # Boost quality slightly

        if output_format in ("JPEG", "WEBP"):
            save_kwargs["quality"] = q
            save_kwargs["optimize"] = True
            # Smart: Progressive JPEG for large images
            if output_format == "JPEG" and img.size[0] > 1000:
                save_kwargs["progressive"] = True
        elif output_format == "PNG":
            save_kwargs["optimize"] = True
        elif output_format == "GIF":
            save_kwargs["optimize"] = True

        img.save(output_path, format=output_format, **save_kwargs)

    # Smart: Force GC after heavy ops
    gc.collect()
    
    # Smart: Return metadata with path
    return {
        "path": output_path,
        "format": output_format,
        "quality": q,
        "resized": was_resized,
        "size": img.size,
    }


def batch_convert(input_paths, output_format, quality="high", resize=None):
    """Smart batch — converts in order, cleans up on error."""
    results = []
    for i, path in enumerate(input_paths, 1):
        try:
            result = convert_image(path, output_format, quality, resize)
            results.append({
                "input": path,
                "output": result["path"],
                "success": True,
                "info": result,
            })
        except Exception as e:
            results.append({
                "input": path,
                "output": None,
                "success": False,
                "error": str(e),
            })
        # Smart: Periodic GC every 3 images
        if i % 3 == 0:
            gc.collect()
    return results


def cleanup_file(file_path):
    """Safe delete + cache cleanup."""
    global _info_cache
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            # Smart: Remove from cache too
            if file_path in _info_cache:
                del _info_cache[file_path]
    except:
        pass


def cleanup_batch(file_paths):
    """Smart batch cleanup."""
    for f in file_paths:
        cleanup_file(f)
    # Smart: Final GC
    gc.collect()
    # Smart: Clear old cache entries
    now = time.time()
    expired = [k for k, (_, t) in _info_cache.items() if now - t > CACHE_TTL]
    for k in expired:
        del _info_cache[k]
