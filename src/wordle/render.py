"""Draw the provided board without reading or changing the database."""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size):
    windows = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    for path in (Path(windows) / "Fonts" / name for name in ("arialbd.ttf", "segoeuib.ttf")) if windows else ():
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def render_board(board, output_path):
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cell, gap, margin, top = 66, 8, 24, 102
    width = max(330, margin * 2 + board["length"] * (cell + gap) - gap)
    # Old outbox snapshots used six turns; preserve them if the field is absent.
    max_guesses = board.get("max_guesses", 6)
    height = top + max_guesses * (cell + gap) - gap + 85
    image = Image.new("RGB", (width, height), "#121213")
    draw = ImageDraw.Draw(image)
    title_font, letter_font, small_font = _font(25), _font(36), _font(17)
    draw.text((margin, 20), f"WORDLE #{board['game_id']}", fill="white", font=title_font)
    used = len(board["guesses"])
    draw.text((margin, 58), f"{used}/{max_guesses} guesses | {board['status'].upper()}", fill="#d7dadc", font=small_font)
    colors = {"green": "#538d4e", "yellow": "#b59f3b", "gray": "#3a3a3c"}
    left = (width - (board["length"] * (cell + gap) - gap)) // 2
    for row in range(max_guesses):
        guess = board["guesses"][row] if row < used else None
        for column in range(board["length"]):
            x, y = left + column * (cell + gap), top + row * (cell + gap)
            fill = colors[guess["colors"][column]] if guess else "#121213"
            draw.rectangle((x, y, x + cell, y + cell), fill=fill, outline="#565758", width=2)
            if guess:
                draw.text((x + cell / 2, y + cell / 2), guess["word"][column].upper(),
                          fill="white", font=letter_font, anchor="mm")
    legend_font = _font(14)
    for offset, (color, label) in enumerate((
        ("green", "Letter + place correct"),
        ("yellow", "Letter in word, wrong place"),
    )):
        y = height - 63 + offset * 29
        draw.rectangle((margin, y, margin + 19, y + 19), fill=colors[color])
        draw.text((margin + 30, y + 2), label, fill="#d7dadc", font=legend_font)
    image.save(output_path, format="PNG")
    return output_path
