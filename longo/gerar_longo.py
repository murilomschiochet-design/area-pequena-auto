"""Vídeo longo do Área Pequeña FC (16:9) — protótipo. Sem API paga: voz edge-tts (grátis).

Lê longo/roteiros/<nome>.json (lista de cenas, cada uma com a fala em "voz") e monta:
  voz por cena -> tela da cena (modelo/cena.html pelo Edge) -> fundo com movimento lento -> legenda -> música baixa.
Tipos de cena: abertura | card (o card do short) | foto | cita | numero | cierre
Uso: python longo/gerar_longo.py prototipo [voz]
"""
import asyncio
import concurrent.futures
import json
import os
import subprocess
import sys
import urllib.parse

import edge_tts

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import navegador  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(AQUI)
CENA = os.path.join(AQUI, "modelo", "cena.html")
ESTADIO = os.path.join(BASE, "assets", "estadio-fundo.jpg")
MUSICA = os.path.join(BASE, "assets", "Monthaholic - Schwartzy.mp3")
FONTES = os.path.join(BASE, "modelo", "fonts")
EDGE = next((p for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"] if os.path.exists(p)), None)
FPS = 30
PAUSA = 0.45          # respiro depois de cada fala
SEM_JANELA = 0x08000000 if os.name == "nt" else 0


def rodar(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=SEM_JANELA, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-2000:])
    return r


def duracao(arq):
    return float(rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arq]).stdout)


async def falar(texto, voz, mp3):
    conector = None
    proxy_ca = "/root/.ccr/ca-bundle.crt"          # na nuvem o proxy troca o certificado: confia no CA dele
    if os.path.exists(proxy_ca):
        import ssl
        import aiohttp
        conector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=proxy_ca))
    com = edge_tts.Communicate(texto, voz, rate="+8%", boundary="WordBoundary", connector=conector)
    palavras = []
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                palavras.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    return palavras


def tela(c, png):
    url = navegador.url_arquivo(CENA, urllib.parse.quote(json.dumps(c, ensure_ascii=False)))
    navegador.print_pagina(url, png, 1920, 1080, espera_ms=4000)


SEG_FOTO = 4.2        # numa cena longa, troca de foto a cada ~4 s
FUNDE = 0.45          # duração da fusão entre uma foto e outra


def carregar_cobrindo(arq, w=1920, h=1080):
    """Lê a imagem (caminho com acento ok) e redimensiona pra cobrir w x h sem distorcer."""
    import cv2
    import numpy as np
    im = cv2.imdecode(np.fromfile(arq, dtype=np.uint8), cv2.IMREAD_COLOR)
    esc = max(w / im.shape[1], h / im.shape[0])
    im = cv2.resize(im, (round(im.shape[1] * esc + 0.5), round(im.shape[0] * esc + 0.5)), interpolation=cv2.INTER_AREA)
    return im


def quadros_ken_burns(im, n, entra, w=1920, h=1080, z0=1.0, z1=1.07):
    """Zoom lento com posição em subpixel (warpAffine) — não treme como o zoompan do ffmpeg."""
    import cv2
    import numpy as np
    cy, cx = im.shape[0] / 2, im.shape[1] / 2
    for k in range(n):
        t = k / max(n - 1, 1)
        t = t * t * (3 - 2 * t)                     # começa e termina macio
        z = z0 + (z1 - z0) * (t if entra else 1 - t)
        m = np.float32([[z, 0, w / 2 - z * cx], [0, z, h / 2 - z * cy]])
        yield cv2.warpAffine(im, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def resolver_foto(c, dia):
    """No roteiro diário a cena pode dizer só "short": "03" (usa a foto do short) ou "pessoa": "Pedri"
    (pega a foto menos usada no banco); aqui isso vira o caminho do arquivo."""
    if c.get("foto") or c.get("fotos"):
        return
    if c.get("short"):
        pasta = os.path.join(BASE, "fotos", dia)
        for nome in (f"{c['short']}.jpg", f"{c['short']}.png", f"{c['short']}-auto.jpg"):
            if os.path.exists(os.path.join(pasta, nome)):
                c["foto"] = os.path.relpath(os.path.join(pasta, nome), BASE)
                return
    if c.get("pessoa"):
        import banco
        caminho, _, _ = banco.foto(c["pessoa"], c.get("contexto"), log=lambda *a: None)
        if caminho:
            c["foto"] = os.path.relpath(caminho, BASE)
            return
    if c["tipo"] == "foto":                 # sem foto nenhuma: vira cena de estádio com o título
        c["tipo"] = "fotoless"


def fotos_da_cena(c):
    """A foto do roteiro + as outras da mesma pessoa no banco (pra ir trocando)."""
    if c.get("fotos"):
        return [os.path.join(BASE, f) for f in c["fotos"]]
    principal = os.path.join(BASE, c["foto"])
    pasta = os.path.dirname(principal)
    lista = [principal]
    if os.path.normpath(os.path.join(BASE, "banco", "fotos")) in os.path.normpath(pasta) and c["tipo"] == "foto":
        lista += sorted(os.path.join(pasta, f) for f in os.listdir(pasta)
                        if f.lower().endswith((".jpg", ".png")) and os.path.join(pasta, f) != principal)
    return lista


def fundo_frames(c, i, n):
    """Gera os quadros do fundo: estádio ou fotos, trocando de foto a cada ~4 s com fusão."""
    import numpy as np
    usa_foto = c.get("foto") and c["tipo"] in ("foto", "numero")
    if not usa_foto:
        yield from quadros_ken_burns(carregar_cobrindo(ESTADIO), n, i % 2 == 0)
        return
    fotos = fotos_da_cena(c)
    k = max(1, min(len(fotos), round(n / FPS / SEG_FOTO))) if c["tipo"] == "foto" else 1
    fus = int(FUNDE * FPS)
    tam = [(n + fus * (k - 1)) // k] * k
    tam[-1] = n + fus * (k - 1) - sum(tam[:-1])
    anterior = None
    for j in range(k):
        quadros = quadros_ken_burns(carregar_cobrindo(fotos[j % len(fotos)]), tam[j], (i + j) % 2 == 0)
        for q_idx, q in enumerate(quadros):
            if anterior is not None and q_idx < fus:
                a = (q_idx + 1) / (fus + 1)
                q = (anterior[q_idx].astype(np.float32) * (1 - a) + q.astype(np.float32) * a).astype(np.uint8)
            if j < k - 1 and q_idx >= tam[j] - fus:
                if q_idx == tam[j] - fus:
                    rabo = []
                rabo.append(q)
                if q_idx == tam[j] - 1:
                    anterior = rabo
                continue
            yield q


def fundo_cena(c, i, d, png, saida, card_png=None):
    """Fundo com movimento suave (Python/OpenCV) + tela da cena por cima, entrando com fade."""
    n = int(round(d * FPS))
    usa_foto = c.get("foto") and c["tipo"] in ("foto", "numero")
    escuro = c["tipo"] in ("cita", "numero", "abertura", "cierre", "card")
    base = "[0:v]setsar=1"
    if escuro:
        base += f",gblur=sigma={30 if usa_foto else 4},eq=brightness={-0.35 if usa_foto else -0.06}"
    entradas = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1920x1080", "-r", str(FPS), "-i", "-"]
    if card_png:
        # card do short em altura 900, com o vidro: fundo desfocado recortado pelo alfa do card
        filtro = (base + ",split[a][b];[b]gblur=sigma=26,eq=brightness=-0.05[bl];"
                  "[1:v]scale=-1:900,pad=1920:1080:(ow-iw)/2:36:color=black@0,format=rgba,"
                  "fade=in:st=0:d=0.35:alpha=1,split[c1][c2];[c1]alphaextract[m];[bl][m]alphamerge[g];"
                  "[a][g]overlay[t];[t][c2]overlay,format=yuv420p[v]")
        entradas += ["-loop", "1", "-t", f"{d:.3f}", "-i", card_png]
    else:
        filtro = (base + "[a];[1:v]format=rgba,fade=in:st=0:d=0.35:alpha=1[o];"
                  "[a][o]overlay,format=yuv420p[v]")
        entradas += ["-loop", "1", "-t", f"{d:.3f}", "-i", png]
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", *entradas, "-filter_complex", filtro, "-map", "[v]",
                             "-frames:v", str(n), "-r", str(FPS), "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                             saida], stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=SEM_JANELA)
    try:
        for q in fundo_frames(c, i, n):
            proc.stdin.write(q.tobytes())
    except BrokenPipeError:
        pass
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise RuntimeError(err[-2000:])


def recortar_card(origem, destino):
    """Corta o card do short no contorno (tira o transparente) pra ele aparecer grande no 16:9."""
    from PIL import Image
    im = Image.open(origem).convert("RGBA")
    im.crop(im.getchannel("A").getbbox()).save(destino)
    return destino


def ass_tempo(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def legendas(blocos, arq):
    """blocos: lista de (inicio, fim, texto). Estilo: Inter grossa, branca com contorno preto, embaixo."""
    cab = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: L,Inter,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,4,2,2,200,200,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(arq, "w", encoding="utf-8") as f:
        f.write(cab)
        for a, b, t in blocos:
            f.write(f"Dialogue: 0,{ass_tempo(a)},{ass_tempo(b)},L,,0,0,0,,{t}\n")


def agrupar(palavras, desloc, max_pal=7):
    blocos, atual = [], []
    for w in palavras:
        atual.append(w)
        fim_frase = w[2].endswith((".", ",", ":", "?", "!", ";"))
        if len(atual) >= max_pal or fim_frase and len(atual) >= 3:
            blocos.append(atual)
            atual = []
    if atual:
        blocos.append(atual)
    out = []
    for k, bl in enumerate(blocos):
        ini = bl[0][0] + desloc
        fim = (blocos[k + 1][0][0] if k + 1 < len(blocos) else bl[-1][1] + 0.3) + desloc
        out.append((ini, fim, " ".join(w[2] for w in bl).upper()))
    return out


def main():
    nome = sys.argv[1] if len(sys.argv) > 1 else "prototipo"
    rot = json.load(open(os.path.join(AQUI, "roteiros", f"{nome}.json"), encoding="utf-8"))
    voz = sys.argv[2] if len(sys.argv) > 2 else rot.get("voz", "es-ES-AlvaroNeural")
    trab = os.path.join(AQUI, "trabalho", f"{nome}-{voz}")
    os.makedirs(trab, exist_ok=True)
    cenas_mp4, audios, blocos, t = [], [], [], 0.0
    for i, c in enumerate(rot["cenas"]):
        resolver_foto(c, rot["dia"])
        mp3 = os.path.join(trab, f"{i:02d}.mp3")
        for tentativa in range(4):          # o serviço de voz às vezes falha à toa: tenta de novo
            try:
                # roda a voz numa thread própria: no Linux o navegador (playwright) já ocupa o loop asyncio desta
                with concurrent.futures.ThreadPoolExecutor(1) as ex:
                    palavras = ex.submit(asyncio.run, falar(c["voz"], voz, mp3)).result()
                break
            except edge_tts.exceptions.NoAudioReceived:
                if tentativa == 3:
                    raise
        d = duracao(mp3) + PAUSA
        print(f" cena {i:02d} {c['tipo']:8} {d:5.1f}s  {c['voz'][:60]}", flush=True)
        png = os.path.join(trab, f"{i:02d}.png")
        card = None
        if c["tipo"] == "card":
            card = recortar_card(os.path.join(BASE, "saida", rot["dia"], "_cards", f"{c['card']}.png"),
                                 os.path.join(trab, f"{i:02d}-card.png"))
        else:
            tela(c, png)
        mp4 = os.path.join(trab, f"{i:02d}.mp4")
        fundo_cena(c, i, d, png, mp4, card)
        cenas_mp4.append(mp4)
        audios.append((mp3, d))
        blocos += agrupar(palavras, t)
        t += d
    # junta vídeo
    lista = os.path.join(trab, "lista.txt")
    with open(lista, "w", encoding="utf-8") as f:
        f.writelines(f"file '{os.path.basename(m)}'\n" for m in cenas_mp4)
    rodar(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "lista.txt", "-c", "copy", "video.mp4"], cwd=trab)
    # junta voz (cada fala completada com silêncio até a duração da cena)
    ent, fil = [], []
    for k, (mp3, d) in enumerate(audios):
        ent += ["-i", mp3]
        fil.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={d:.3f}[a{k}]")
    fil.append("".join(f"[a{k}]" for k in range(len(audios))) + f"concat=n={len(audios)}:v=0:a=1[voz]")
    rodar(["ffmpeg", "-v", "error", "-y", *ent, "-filter_complex", ";".join(fil), "-map", "[voz]", "voz.wav"], cwd=trab)
    legendas(blocos, os.path.join(trab, "legendas.ass"))
    # final: legenda + voz + música baixinha que abaixa quando tem fala
    fontes = FONTES.replace("\\", "/").replace(":", "\\:")
    if nome.startswith("longo-"):          # vídeo do dia: vai junto dos shorts, pro subir.py achar
        final = os.path.join(BASE, "saida", rot["dia"], "longo.mp4")
    else:
        final = os.path.join(AQUI, f"{nome}-{voz}.mp4")
    rodar(["ffmpeg", "-v", "error", "-y", "-i", "video.mp4", "-i", "voz.wav", "-stream_loop", "-1", "-ss", "30", "-i", MUSICA,
           "-filter_complex",
           f"[0:v]subtitles=legendas.ass:fontsdir='{fontes}'[v];"
           "[1:a]volume=1.6,asplit[vz][sc];"
           f"[2:a]volume=0.22,afade=t=out:st={t - 1.5:.2f}:d=1.5[m];"
           "[m][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md];"
           "[vz][md]amix=inputs=2:duration=first:normalize=0[a]",
           "-map", "[v]", "-map", "[a]", "-t", f"{t:.3f}", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", final], cwd=trab)
    print(f"\npronto: {final}  ({t:.0f}s)")


if __name__ == "__main__":
    main()
