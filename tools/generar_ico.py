import os, sys
from PIL import Image
carpeta, destino = sys.argv[1], sys.argv[2]
tam = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
capas = [Image.open(os.path.join(carpeta, f"icono-{t}.png")).convert("RGBA") for t in tam]
capas[-1].save(destino, format="ICO", sizes=[(t, t) for t in tam], append_images=capas[:-1])
