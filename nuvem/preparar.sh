#!/usr/bin/env bash
# Prepara a máquina da nuvem: bibliotecas Python, Chromium (pros cards) e ffmpeg.
set -e
cd "$(dirname "$0")/.."
python3 -m pip install -q -r requirements.txt
python3 -m playwright install chromium >/dev/null 2>&1 || true   # se falhar, o navegador.py usa o google-chrome da máquina
if ! command -v ffmpeg >/dev/null 2>&1; then
  (sudo -n apt-get update -qq && sudo -n apt-get install -y -qq ffmpeg) >/dev/null 2>&1 || true
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERRO: ffmpeg não disponível"; exit 1
fi
ffmpeg -hide_banner -filters | grep -q " subtitles " || echo "AVISO: ffmpeg sem filtro subtitles (legenda do longo)"
mkdir -p ~/.fonts && cp modelo/fonts/*.ttf ~/.fonts/ 2>/dev/null && (fc-cache -f >/dev/null 2>&1 || true)
echo "ambiente pronto: $(python3 --version), $(ffmpeg -version | head -1 | cut -d' ' -f1-3)"
