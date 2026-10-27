#!/usr/bin/env bash
# Instala ffmpeg/ffprobe sin quedarse colgado: apt con límite de tiempo y, si falla, binario estático.
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then exit 0; fi
if timeout 240 sudo apt-get update -q -o Acquire::Retries=2 -o Acquire::http::Timeout=20 && \
   timeout 300 sudo apt-get install -y -q ffmpeg; then exit 0; fi
echo "::warning::apt no instaló ffmpeg a tiempo: se usa el binario estático"
mkdir -p /tmp/ffmpeg && cd /tmp/ffmpeg
for url in https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
           https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz; do
  if timeout 240 curl -sfL -o f.tar.xz "$url" && tar xf f.tar.xz; then
    sudo cp "$(find . -type f -name ffmpeg | head -1)" "$(find . -type f -name ffprobe | head -1)" /usr/local/bin/ && exit 0
  fi
done
echo "::error::No se pudo instalar ffmpeg"; exit 1
