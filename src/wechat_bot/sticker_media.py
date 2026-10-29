"""Bounded PNG-to-GIF copies; original bytes are persisted by StickerService."""
from io import BytesIO
import warnings

from PIL import Image

from .stickers import MAX_BYTES, MAX_DIMENSION, MAX_PIXELS, MAX_SOURCE_BYTES, StickerError


PNG_PUBLIC_REASONS = frozenset({
    "PNG 原件必须非空且不超过 20 MiB", "PNG 原件无法完整解码",
    "PNG 原件超出 4096 像素或累计像素限制",
    "动态 PNG 尚未支持；请发送 GIF 原生表情",
    "表情转换时连接已结束", "PNG 无法在当前原生限制内转换为 GIF",
})


def png_to_gif(data, is_current=lambda: True):
    """Use up to 256 colors and shrink proportionally only to meet send limits.

    APNG is rejected explicitly: silently flattening its animation is not an
    acceptable substitute. GIF has binary transparency; partial alpha is
    composited over white, and alpha below 128 maps to a transparent index.
    """
    if (not isinstance(data, bytes) or not 0 < len(data) <= MAX_SOURCE_BYTES
            or not data.startswith(b"\x89PNG\r\n\x1a\n")):
        raise StickerError("PNG 原件必须非空且不超过 20 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                if max(width, height) > 4096 or width * height > MAX_PIXELS:
                    raise StickerError("PNG 原件超出 4096 像素或累计像素限制")
                if image.format != "PNG":
                    raise StickerError("PNG 原件无法完整解码")
                if image.n_frames != 1:
                    raise StickerError("动态 PNG 尚未支持；请发送 GIF 原生表情")
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                original = image.convert("RGBA")
    except StickerError:
        raise
    except Exception:
        raise StickerError("PNG 原件无法完整解码") from None

    scale = min(1.0, MAX_DIMENSION / max(width, height))
    last_size = None
    for attempt in range(40):
        if not is_current():
            raise StickerError("表情转换时连接已结束")
        factor = scale * 0.8 ** attempt
        size = (max(1, round(width * factor)), max(1, round(height * factor)))
        if size == last_size:
            continue
        last_size = size
        rgba = original if size == original.size else original.resize(size, Image.Resampling.LANCZOS)
        alpha = rgba.getchannel("A")
        transparent = alpha.getextrema()[0] < 128
        rgb = Image.new("RGB", size, "white")
        rgb.paste(rgba, mask=alpha)
        palette = rgb.quantize(colors=255 if transparent else 256,
                               method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        if transparent:
            palette.paste(255, mask=alpha.point(lambda value: 255 if value < 128 else 0))
            palette.info["transparency"] = 255
        output = BytesIO()
        palette.save(output, format="GIF", optimize=False)
        payload = output.getvalue()
        if len(payload) <= MAX_BYTES:
            if not is_current():
                raise StickerError("表情转换时连接已结束")
            note = "PNG原件已保存；发送副本转为最多256色GIF，色彩与半透明效果可能变化"
            if size != original.size:
                note += f"，尺寸从{width}×{height}缩至{size[0]}×{size[1]}"
            return payload, note
    raise StickerError("PNG 无法在当前原生限制内转换为 GIF")
