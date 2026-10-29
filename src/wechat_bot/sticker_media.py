"""Decode explicit sticker originals and build bounded native GIF copies."""
from io import BytesIO
import math
import warnings

from PIL import GifImagePlugin, Image

from .stickers import MAX_BYTES, MAX_DIMENSION, MAX_FRAMES, MAX_PIXELS, MAX_SOURCE_BYTES, StickerError


MAX_SOURCE_DIMENSION = 8192
MAX_SOURCE_PIXELS = 128 * 1024 * 1024
SOURCE_FORMATS = frozenset({"PNG", "GIF", "JPEG", "WEBP", "BMP"})
MEDIA_PUBLIC_REASONS = frozenset({
    "表情原件必须非空且不超过 20 MiB", "表情原件无法完整解码",
    "表情原件超出 8192 像素或累计 128 Mi 像素限制",
    "表情超过 300 帧；当前发送接口无法完整保留更多帧",
    "动态 PNG 或 WebP 尚未支持；请发送 GIF 原生表情",
    "表情转换时连接已结束", "表情无法在当前原生限制内转换为 GIF",
    "该原生表情原件格式尚未支持", "GIF 帧时长或循环信息无法完整保留",
    "原生表情资源必须是完整 GIF",
})


def _current(is_current):
    if not is_current():
        raise StickerError("表情转换时连接已结束")


def _inspect(data, is_current):
    """Fully decode once without keeping all full-resolution frames in memory."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_SOURCE_BYTES:
        raise StickerError("表情原件必须非空且不超过 20 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                kind = probe.format
                if kind not in SOURCE_FORMATS:
                    raise StickerError("该原生表情原件格式尚未支持")
                width, height = probe.size
                if min(width, height) < 1 or max(width, height) > MAX_SOURCE_DIMENSION:
                    raise StickerError("表情原件超出 8192 像素或累计 128 Mi 像素限制")
                if kind == "GIF" and not data.endswith(b";"):
                    raise StickerError("原生表情资源必须是完整 GIF")
                probe.verify()
            with Image.open(BytesIO(data)) as image:
                loop = image.info.get("loop")
                if loop is not None and (type(loop) is not int or not 0 <= loop <= 65535):
                    raise StickerError("GIF 帧时长或循环信息无法完整保留")
                durations, pixels = [], 0
                for index in range(MAX_FRAMES + 1):
                    _current(is_current)
                    try:
                        image.seek(index)
                    except EOFError:
                        break
                    if index == MAX_FRAMES:
                        raise StickerError("表情超过 300 帧；当前发送接口无法完整保留更多帧")
                    if index and kind != "GIF":
                        raise StickerError("动态 PNG 或 WebP 尚未支持；请发送 GIF 原生表情")
                    if image.size != (width, height):
                        raise StickerError("表情原件无法完整解码")
                    pixels += width * height
                    if pixels > MAX_SOURCE_PIXELS:
                        raise StickerError("表情原件超出 8192 像素或累计 128 Mi 像素限制")
                    image.load()
                    duration = image.info.get("duration", 0)
                    if kind == "GIF" and (not isinstance(duration, (int, float))
                            or not math.isfinite(duration) or not 0 <= duration <= 655350
                            or duration % 10):
                        raise StickerError("GIF 帧时长或循环信息无法完整保留")
                    durations.append(int(duration) if kind == "GIF" else 0)
            return kind, width, height, durations, loop
    except StickerError:
        raise
    except Exception:
        raise StickerError("表情原件无法完整解码") from None


def _palette(frame, size):
    rgba = frame.convert("RGBA")
    if rgba.size != size:
        rgba = rgba.resize(size, Image.Resampling.LANCZOS)
    alpha = rgba.getchannel("A")
    transparent = alpha.getextrema()[0] < 128
    rgb = Image.new("RGB", size, "white")
    rgb.paste(rgba, mask=alpha)
    palette = rgb.quantize(colors=255 if transparent else 256,
                           method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    if transparent:
        palette.paste(255, mask=alpha.point(lambda value: 255 if value < 128 else 0))
        colors = palette.getpalette()
        colors.extend([0] * (768 - len(colors)))
        palette.putpalette(colors)
        palette.info["transparency"] = 255
    return palette


def _encode(data, size, durations, loop, is_current):
    """Write each decoded frame explicitly: Pillow save_all can merge frames."""
    output = BytesIO()
    with Image.open(BytesIO(data)) as image:
        for index, duration in enumerate(durations):
            _current(is_current)
            image.seek(index)
            image.load()
            palette = _palette(image, size)
            if index == 0:
                info = {"optimize": False}
                if loop is not None:
                    info["loop"] = loop
                if "transparency" in palette.info:
                    info["transparency"] = palette.info["transparency"]
                    info["background"] = palette.info["transparency"]
                header, _ = GifImagePlugin.getheader(palette, info=info)
                for block in header:
                    output.write(block)
            options = {"duration": duration, "disposal": 2, "include_color_table": index > 0}
            if "transparency" in palette.info:
                options["transparency"] = palette.info["transparency"]
            for block in GifImagePlugin.getdata(palette, **options):
                output.write(block)
            if output.tell() >= MAX_BYTES:
                return None
    output.write(b";")
    return output.getvalue()


def convert_sticker(data, is_current=lambda: True):
    """Return a sendable GIF while the caller keeps the unchanged original.

    GIF inputs that already meet SDK bounds keep their encoded bytes. Larger
    GIFs retain decoded frame order/count, each duration and loop setting.
    Conversion can change colors/transparency and proportional dimensions.
    """
    kind, width, height, durations, loop = _inspect(data, is_current)
    count = len(durations)
    if kind == "GIF" and len(data) <= MAX_BYTES and max(width, height) <= MAX_DIMENSION \
            and width * height * count <= MAX_PIXELS:
        _current(is_current)
        return {"data": data, "source_format": kind, "converted": False, "note": "",
                "width": width, "height": height, "frames": count}
    scale = min(1.0, MAX_DIMENSION / max(width, height),
                math.sqrt(MAX_PIXELS / (width * height * count)))
    last_size = None
    try:
        for attempt in range(40):
            _current(is_current)
            factor = scale * 0.8 ** attempt
            size = (max(1, int(width * factor)), max(1, int(height * factor)))
            if size == last_size:
                continue
            last_size = size
            payload = _encode(data, size, durations, loop, is_current)
            if payload is None or len(payload) > MAX_BYTES:
                continue
            _, _, _, output_durations, output_loop = _inspect(payload, is_current)
            if output_durations != durations or output_loop != loop:
                raise StickerError("GIF 帧时长或循环信息无法完整保留")
            note = f"{kind}原件已保存；发送副本转为最多256色GIF，色彩与半透明效果可能变化"
            if size != (width, height):
                note += f"，尺寸从{width}×{height}缩至{size[0]}×{size[1]}"
            if count > 1:
                note += "，保留帧数、各帧时长及循环设置"
            return {"data": payload, "source_format": kind, "converted": True, "note": note,
                    "width": size[0], "height": size[1], "frames": count}
    except StickerError:
        raise
    except Exception:
        raise StickerError("表情原件无法完整解码") from None
    raise StickerError("表情无法在当前原生限制内转换为 GIF")
