"""Export desktop and web assets from the RGBA icon masters; requires Pillow."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parent
with Image.open(root / 'icon.png') as source:
    icon = source.convert('RGBA')
    if icon.size != (1024, 1024):
        raise ValueError('icon.png must be 1024 × 1024 pixels')
    icon.save(root / 'icon.ico', format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

with Image.open(root / 'icon-macos.png') as source:
    icon = source.convert('RGBA')
    if icon.size != (1024, 1024):
        raise ValueError('icon-macos.png must be 1024 × 1024 pixels')
    icon.save(root / 'icon.icns', format='ICNS')
    web_icon = root.parents[2] / 'src' / 'management' / 'web' / 'app-icon.png'
    icon.resize((128, 128), Image.Resampling.LANCZOS).save(web_icon, optimize=True)
