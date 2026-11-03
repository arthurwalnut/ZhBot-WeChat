"""Local Windows OCR for an explicitly supplied image; no screen capture here."""

import base64
from importlib.resources import files
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image


class OcrError(RuntimeError):
    """OCR is unavailable, failed, or could not recognize text in this image."""


def recognize_image(image: Image.Image, language: str = "en-US", *, timeout: float = 8.0) -> list[dict]:
    """Return recognized lines with text and image-relative bounding boxes.

    Coordinates are pixels in the supplied image. OCR text is an observation,
    not a verified sender identity. No image is written to disk or uploaded.
    Empty recognition is reported as OcrError so callers can retain unknowns.
    """
    if sys.platform != "win32":
        raise OcrError("Windows OCR 需要 Windows。")
    if not isinstance(language, str) or not language.strip():
        raise OcrError("OCR language 不能为空。")
    if timeout <= 0:
        raise OcrError("OCR timeout 必须为正数。")
    if not image.width or not image.height:
        raise OcrError("OCR 图片宽高必须大于零。")
    windows = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if not windows:
        raise OcrError("无法定位 Windows 系统目录；请检查 WINDIR/SystemRoot")
    powershell = Path(windows) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        script = files("wechat_reader").joinpath("windows_ocr.ps1").read_text(encoding="utf-8")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        payload = json.dumps({
            "language": language,
            "png": base64.b64encode(buffer.getvalue()).decode("ascii"),
        })
        # Windows PowerShell 5.1 exposes WinRT; PowerShell 7 does not provide this bridge.
        # Passing code as an argument avoids changing the user's script execution policy.
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
            input=payload, capture_output=True, encoding="utf-8", timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError(f"Windows OCR 超过 {timeout:g} 秒，未取得结果。") from exc
    except (OSError, ValueError) as exc:
        raise OcrError(f"Windows OCR 无法运行：{exc}") from exc
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        detail = result.stderr.strip() or result.stdout.strip() or "无输出"
        raise OcrError(f"Windows OCR 返回无效响应（退出码 {result.returncode}）：{detail[:500]}") from exc
    if not isinstance(response, dict):
        raise OcrError("Windows OCR 返回的响应结构无效。")
    if result.returncode or response.get("ok") is not True:
        raise OcrError(f"Windows OCR：{response.get('error', '执行失败，未取得结果')}")
    lines = response.get("lines")
    if not isinstance(lines, list) or not lines:
        raise OcrError("Windows OCR 未识别到文本；无法据此确定发送者。")
    return lines


def extract_sender_labels(image: Image.Image, row_rectangles, scale: float = 1.0) -> list[str | None]:
    """OCR visible gray row headers, returning one raw label or None per row.

    Rectangles are image-relative (left, top, right, bottom); scale is the UI
    scale (e.g. 1.5 at 150%). This layout is for the observed dark WeChat chat
    view. The caller must confirm the capture belongs to the selected window.
    OCR errors propagate as OcrError; labels remain uncertain display text.
    """
    if scale <= 0:
        raise OcrError("OCR scale 必须为正数。")
    rectangles = list(row_rectangles)
    labels = [None] * len(rectangles)
    strips = []
    inset, strip_height = round(60 * scale), max(1, round(24 * scale))
    for index, (left, top, right, bottom) in enumerate(rectangles):
        # A clipped row may begin with the message body instead of its header.
        if top < 0 or top >= image.height:
            continue
        bounds = (
            max(0, round(left) + inset), round(top),
            min(image.width, round(right) - inset),
            min(image.height, round(bottom), round(top) + strip_height),
        )
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            continue
        crop = image.crop(bounds).convert("RGB")
        # Keep neutral gray header glyphs; dark backgrounds and green own-message
        # bubbles are discarded. This filtering does not establish identity.
        mask = Image.new("L", crop.size, 255)
        ink = []
        has_ink = False
        for red, green, blue in crop.getdata():
            high, low = max(red, green, blue), min(red, green, blue)
            keep = 70 <= high <= 200 and high - low < 12
            ink.append(0 if keep else 255)
            has_ink = has_ink or keep
        if not has_ink:
            continue
        mask.putdata(ink)
        strips.append((index, mask))
    if not strips:
        return labels

    # One OCR call per snapshot; separated rows retain their original association.
    padding = 16
    width = max(strip.width for _, strip in strips) + 2 * padding
    height = sum(strip.height + padding for _, strip in strips) + padding
    atlas = Image.new("L", (width, height), 255)
    positions = []
    y = padding
    for index, strip in strips:
        atlas.paste(strip, (padding, y))
        positions.append((index, y, y + strip.height))
        y += strip.height + padding
    enlargement = 2
    atlas = atlas.resize((width * enlargement, height * enlargement), Image.Resampling.LANCZOS)
    recognized = recognize_image(atlas)
    for index, top, bottom in positions:
        matches = [line["text"] for line in recognized
                   if top * enlargement <= (line["top"] + line["bottom"]) / 2 < bottom * enlargement]
        if len(matches) == 1:
            labels[index] = matches[0]
    return labels
