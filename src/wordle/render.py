"""Draw the provided board without reading or changing the database."""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size):
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))
    for path in (windows / "Fonts" / "arialbd.ttf", windows / "Fonts" / "segoeuib.ttf"):
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
    height = top + 6 * (cell + gap) - gap + 60
    image = Image.new("RGB", (width, height), "#121213")
    draw = ImageDraw.Draw(image)
    title_font, letter_font, small_font = _font(25), _font(36), _font(17)
    draw.text((margin, 20), f"WORDLE #{board['game_id']}", fill="white", font=title_font)
    used = len(board["guesses"])
    draw.text((margin, 58), f"{used}/6 guesses | {board['status'].upper()}", fill="#d7dadc", font=small_font)
    colors = {"green": "#538d4e", "yellow": "#b59f3b", "gray": "#3a3a3c"}
    left = (width - (board["length"] * (cell + gap) - gap)) // 2
    for row in range(6):
        guess = board["guesses"][row] if row < used else None
        for column in range(board["length"]):
            x, y = left + column * (cell + gap), top + row * (cell + gap)
            fill = colors[guess["colors"][column]] if guess else "#121213"
            draw.rectangle((x, y, x + cell, y + cell), fill=fill, outline="#565758", width=2)
            if guess:
                draw.text((x + cell / 2, y + cell / 2), guess["word"][column].upper(),
                          fill="white", font=letter_font, anchor="mm")
    footer = "Shared turns: all players use this board."
    draw.text((margin, height - 35), footer, fill="#d7dadc", font=_font(14))
    image.save(output_path, format="PNG")
    return output_path
