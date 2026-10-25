"""Sube un vídeo privado de 3 s al canal indicado para comprobar a qué canal apunta la autorización."""
import subprocess, sys
from pathlib import Path
from tiempo import youtube
canal = sys.argv[1] if len(sys.argv) > 1 else "historias"
v = Path("/tmp/prueba.mp4")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=3",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(v)], check=True)
import os
os.environ["YT_PRIVACIDAD"] = "private"
try:
    r = youtube.subir(v, "Prueba de conexión (borrar)", "Prueba automática. Se puede borrar.", [], canal=canal)
except Exception as e:  # noqa: BLE001
    print(f"::error::{e}")
    raise
print(f"::notice::Canal de YouTube autorizado para '{canal}': {r['canal']} · vídeo privado {r['url']}")
