"""Draws the editor's icon (editor.ico): a few worlds joined by hyperlanes."""
from PIL import Image, ImageDraw

S = 256
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.ellipse((8, 8, S - 8, S - 8), fill=(14, 18, 30, 255), outline=(90, 110, 150, 255), width=6)
worlds = [(70, 80, (239, 139, 9)), (170, 60, (8, 160, 40)), (190, 160, (200, 60, 60)), (95, 185, (90, 140, 230)),
          (130, 120, (230, 230, 230))]
for a, b in [(0, 4), (1, 4), (2, 4), (3, 4), (0, 1), (2, 3), (1, 2)]:
    d.line(worlds[a][:2] + worlds[b][:2], fill=(120, 140, 180, 255), width=6)
for x, y, c in worlds:
    d.ellipse((x - 20, y - 20, x + 20, y + 20), fill=c + (255,), outline=(10, 10, 10, 255), width=3)
im.save("editor.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
