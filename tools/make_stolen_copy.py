"""Simulate a scammer re-using a photo: resize + crop + brighten + recompress.
Usage: python tools/make_stolen_copy.py living_room.jpg   ->  living_room_stolen.jpg"""
import sys
from PIL import Image, ImageEnhance

src = sys.argv[1]
img = Image.open(src).convert("RGB")
w, h = img.size
img = img.crop((int(w * .04), int(h * .04), int(w * .96), int(h * .96)))
img = img.resize((int(img.width * .8), int(img.height * .8)))
img = ImageEnhance.Brightness(img).enhance(1.1)
out = src.rsplit(".", 1)[0] + "_stolen.jpg"
img.save(out, quality=55)
print("saved", out)
