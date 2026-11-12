"""Baixa a legenda (transcrição) de um vídeo do YouTube, de graça, sem API.

Uso:
  python transcricao.py <link do vídeo>
  python transcricao.py ultimo          -> pega o vídeo longo mais recente do @Cracks
Salva em fontes/<id>.txt (título + data + texto limpo).
"""
import glob
import json
import os
import re
import sys
import tempfile

import yt_dlp

BASE = os.path.dirname(os.path.abspath(__file__))
FONTES = os.path.join(BASE, "fontes")
CANAL = "https://www.youtube.com/@Cracks/videos"


TITULOS = {}
EXTRA = {}   # --cliente tv: outro "cliente" do YouTube (ajuda quando o servidor é bloqueado)


def supadata(caminho, **params):
    """Chamada à API do Supadata (plano B quando o YouTube bloqueia o servidor)."""
    import certifi
    import json
    import ssl
    import urllib.parse
    import urllib.request
    chave = os.environ.get("SUPADATA_API_KEY")
    if not chave:
        raise SystemExit("O YouTube bloqueou e não há SUPADATA_API_KEY para o plano B.")
    ca = next((c for c in [os.environ.get("SSL_CERT_FILE"), "/root/.ccr/ca-bundle.crt"] if c and os.path.exists(c)),
              certifi.where())
    url = f"https://api.supadata.ai/v1/{caminho}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"x-api-key": chave, "User-Agent": "AreaPequenaShorts/1.0"})
    return json.load(urllib.request.urlopen(req, context=ssl.create_default_context(cafile=ca), timeout=120))


def ultimo_video():
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "playlistend": 5, **EXTRA}) as y:
            info = y.extract_info(CANAL, download=False)
    except Exception as e:
        print(f"yt-dlp não listou o canal ({str(e)[:120]}); usando o Supadata")
        ids = supadata("youtube/channel/videos", id="@Cracks", limit=3, type="video").get("videoIds") or []
        if not ids:
            raise SystemExit("Não achei vídeos no canal.")
        return f"https://www.youtube.com/watch?v={ids[0]}"
    for e in info.get("entries") or []:
        TITULOS[e["id"]] = e.get("title", "")
        return f"https://www.youtube.com/watch?v={e['id']}"
    raise SystemExit("Não achei vídeos no canal.")


def limpar_vtt(caminho):
    linhas, ultima = [], None
    for ln in open(caminho, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln == "WEBVTT" or "-->" in ln or ln.startswith(("Kind:", "Language:", "NOTE")):
            continue
        ln = re.sub(r"<[^>]+>", "", ln).strip()
        if ln and ln != ultima:
            linhas.append(ln)
            ultima = ln
    # legendas automáticas repetem pedaços: junta e remove repetição de linhas consecutivas
    texto = " ".join(linhas)
    return re.sub(r"\s+", " ", texto).strip()


def via_servico(url, erro):
    """Plano B (nuvem): o YouTube bloqueia legenda pra servidores; pega a transcrição pelo Supadata (SUPADATA_API_KEY)."""
    import datetime
    vid = re.search(r"v=([\w-]{11})", url).group(1)
    print(f"yt-dlp não pegou a legenda ({erro[:120]}); usando o Supadata")
    dados = supadata("transcript", url=url, lang="es", text="true", mode="native")
    texto = dados["content"] if isinstance(dados.get("content"), str) else " ".join(c["text"] for c in dados["content"])
    texto = re.sub(r"\s+", " ", texto).strip()
    titulo = TITULOS.get(vid, "")          # a página do vídeo também é bloqueada: usa o título da lista do canal
    data = datetime.date.today().isoformat()
    saida = os.path.join(FONTES, f"{vid}.txt")
    with open(saida, "w", encoding="utf-8") as f:
        f.write(f"TITULO: {titulo}\nDATA: {data}\nLINK: {url}\n\n{texto}\n")
    print(saida)
    print(f"{titulo} | {data} | {len(texto.split())} palavras (via Supadata)")


def baixar(url):
    try:
        return baixar_ytdlp(url)
    except Exception as e:                  # inclui o "Sign in to confirm you're not a bot"
        os.makedirs(FONTES, exist_ok=True)
        return via_servico(url, str(e)[:200])


def baixar_ytdlp(url):
    os.makedirs(FONTES, exist_ok=True)
    tmp = tempfile.mkdtemp()
    opts = {
        "quiet": True, "skip_download": True,
        "writesubtitles": True, "writeautomaticsub": True,
        "subtitleslangs": ["es", "es-orig", "es.*"], "subtitlesformat": "vtt",
        "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"), **EXTRA,
    }
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
    vtts = sorted(glob.glob(os.path.join(tmp, "*.vtt")), key=lambda p: ("orig" not in p, p))
    if not vtts:
        raise RuntimeError("Esse vídeo não tem legenda em espanhol (yt-dlp).")
    texto = limpar_vtt(vtts[0])
    data = info.get("upload_date") or ""
    if data:
        data = f"{data[:4]}-{data[4:6]}-{data[6:]}"
    saida = os.path.join(FONTES, f"{info['id']}.txt")
    with open(saida, "w", encoding="utf-8") as f:
        f.write(f"TITULO: {info.get('title')}\nDATA: {data}\nLINK: {url}\n\n{texto}\n")
    print(saida)
    print(f"{info.get('title')} | {data} | {len(texto.split())} palavras")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if "--cliente" in sys.argv:
        cli = sys.argv[sys.argv.index("--cliente") + 1]
        EXTRA["extractor_args"] = {"youtube": {"player_client": cli.split(",")}}
    alvo = sys.argv[1]
    url = ultimo_video() if alvo == "ultimo" else alvo
    vid = re.search(r"v=([\w-]{11})", url).group(1)
    proc_arq = os.path.join(BASE, "processados.json")
    processados = json.load(open(proc_arq, encoding="utf-8")) if os.path.exists(proc_arq) else {}
    if alvo == "ultimo" and vid in processados:
        print(f"SEM_VIDEO_NOVO: o último vídeo ({vid}) já foi usado no {processados[vid]}")
        sys.exit(0)
    if alvo == "ultimo" and os.path.exists(os.path.join(FONTES, f"{vid}.txt")):
        print(f"já baixado: fontes/{vid}.txt")
    else:
        baixar(url)
    with open(os.path.join(FONTES, "PENDENTE.txt"), "w", encoding="utf-8") as f:
        f.write(vid + "\n")          # a rotina do Claude escreve o roteiro deste vídeo
