"""Gera os shorts do Área Pequeña FC (sem API paga, tudo no PC).

Para cada short em roteiros/dia-XX.json:
  1. foto: usa fotos/dia-XX/<id>.jpg|png|webp se você colocou uma; senão busca no Wikimedia Commons (licença livre)
  2. card estilo A (modelo/card.html) renderizado pelo Edge
  3. fundo em loop (5,54 s, zoom 8% sem a marca Veo) + vidro + card + música
  4. saida/dia-XX/<id>.mp4 + painel.html com horário, título, descrição e hashtags

Só gera o que falta. Para refazer um short: apague o .mp4 dele ou coloque uma foto nova (foto mais nova que o vídeo = refaz).
Uso: python gerar.py [dia-XX]   (sem argumento = todos os dias)
"""
import glob
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request

import banco
import fotos
import navegador

BASE = os.path.dirname(os.path.abspath(__file__))
FUNDO = os.path.join(BASE, "assets", "fundo futebol it.mp4")
MUSICA = os.path.join(BASE, "assets", "Monthaholic - Schwartzy.mp3")
CARD = os.path.join(BASE, "modelo", "card.html")
QUADROS = 133                 # 0..132 = 5,54 s; o quadro 133 é quase igual ao 0 (loop sem emenda)
DURACAO = QUADROS / 24
VOLUME = 0.8
EDGE = next((p for p in [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
] if os.path.exists(p)), None)
try:
    import certifi
    # na nuvem o proxy tem certificado próprio (SSL_CERT_FILE); no PC usa o certifi
    SSL = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or next((c for c in ["/root/.ccr/ca-bundle.crt"] if os.path.exists(c)), certifi.where()))
except ImportError:
    SSL = ssl.create_default_context()
UA = "AreaPequenaShorts/1.0 (gerador local de shorts)"
EXT_FOTO = (".jpg", ".jpeg", ".png", ".webp")
SEM_JANELA = 0x08000000 if os.name == "nt" else 0


def log(*a):
    print(*a, flush=True)


def rodar(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=SEM_JANELA)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-1500:])
    return r


# ---------------------------------------------------------------- fotos

def foto_manual(pasta, sid):
    for ext in EXT_FOTO:
        p = os.path.join(pasta, sid + ext)
        if os.path.exists(p):
            return p
    return None


def foto_do_short(pasta_fotos, s):
    """Ordem: foto manual > foto já escolhida pra esse short > banco/busca.
    foto_busca (lista, tenta em ordem):  "Pedri" = pessoa (banco)  |  "#FC Barcelona" = escudo  |  "~Camp Nou" = cenário"""
    sid = s["id"]
    manual = foto_manual(pasta_fotos, sid)
    if manual:
        return manual, s.get("credito_foto", "")
    auto = os.path.join(pasta_fotos, f"{sid}-auto.jpg")
    info = os.path.join(pasta_fotos, f"{sid}-auto.json")
    if os.path.exists(auto) and os.path.exists(info):
        return auto, json.load(open(info, encoding="utf-8"))["credito"]
    buscas = s.get("foto_busca") or []
    if isinstance(buscas, str):
        buscas = [buscas]
    contexto = s.get("contexto") or ("selecao" if "selecci" in s.get("tag", "").lower() else "clube")
    for b in buscas:
        try:
            if b.startswith("~"):
                r = fotos.melhor_foto([b], auto, log=log)
                origem, credito = (r["arquivo"], r["credito"]) if r else (None, None)
                caminho = auto if r else None
            elif b.startswith("#"):
                caminho, credito = banco.escudo(b[1:].strip(), log=log)
                origem = f"escudo {b[1:].strip()}"
            else:
                caminho, credito, origem = banco.foto(b, contexto, log=log)
        except Exception as e:
            log(f"   ! foto \"{b}\" falhou ({e})")
            continue
        if caminho:
            if os.path.abspath(caminho) != os.path.abspath(auto):
                shutil.copyfile(caminho, auto)
            json.dump({"busca": b, "credito": credito or "", "origem": origem}, open(info, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            log(f"    foto: {origem}")
            return auto, credito or ""
    log("   ! nenhuma foto — usei o estádio; para trocar, coloque uma em "
        + os.path.join("fotos", os.path.basename(pasta_fotos), sid + ".jpg"))
    return os.path.join(BASE, "assets", "estadio-fundo.jpg"), ""     # nunca deixa o card com a foto vazia


# ---------------------------------------------------------------- card e vídeo

def renderizar_card(s, foto, credito, destino):
    dados = {
        "foto": navegador.url_arquivo(foto) if foto else "",
        "credito": credito, "tag": s.get("tag", "Última hora"),
        "titulo": s["titulo"], "texto": s["texto"],
    }
    url = navegador.url_arquivo(CARD, urllib.parse.quote(json.dumps(dados, ensure_ascii=False)))
    navegador.print_pagina(url, destino, 1080, 1920)


def montar_video(card_png, destino, n):
    inicio_musica = (12 + n * 19) % 150          # cada short pega um trecho diferente da música
    filtro = (
        f"[0:v]trim=end_frame={QUADROS},setpts=PTS-STARTPTS,scale=1168:2076:flags=lanczos,crop=1080:1920:44:0,setsar=1,split[a][b];"
        "[b]gblur=sigma=28,eq=brightness=-0.05[bl];"
        "[1:v]format=rgba,split[c1][c2];[c1]alphaextract[m];[bl][m]alphamerge[g];"
        "[a][g]overlay=shortest=1[t];[t][c2]overlay=shortest=1,format=yuv420p[v];"
        f"[2:a]afade=t=in:d=0.15,afade=t=out:st={DURACAO - 0.2:.3f}:d=0.2,volume={VOLUME}[au]"
    )
    rodar(["ffmpeg", "-v", "error", "-y", "-i", FUNDO, "-loop", "1", "-i", card_png,
           "-ss", str(inicio_musica), "-i", MUSICA, "-filter_complex", filtro,
           "-map", "[v]", "-map", "[au]", "-t", f"{DURACAO:.4f}",
           "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", destino])


# ---------------------------------------------------------------- textos e painel

def textos_yt(s, dados_dia):
    tags = " ".join(s.get("hashtags", []))
    desc = s.get("descricao", "").strip()
    return s["titulo_yt"], f"{desc}\n\n{tags}".strip()


def painel(pasta_saida, dia, dados_dia, shorts):
    cards = []
    for s in shorts:
        titulo, desc = textos_yt(s, dados_dia)
        mp4 = f"{s['id']}.mp4"
        existe = os.path.exists(os.path.join(pasta_saida, mp4))
        cards.append(f"""
<article>
  <div class="hora">{html.escape(s.get('hora', ''))}<small>#{s['id']}</small></div>
  {'<video src="' + mp4 + '" autoplay loop muted playsinline></video>' if existe else '<div class="falta">não gerado</div>'}
  <label>Título <button data-c="t{s['id']}">copiar</button></label>
  <textarea id="t{s['id']}" rows="2" readonly>{html.escape(titulo)}</textarea>
  <label>Descrição <button data-c="d{s['id']}">copiar</button></label>
  <textarea id="d{s['id']}" rows="5" readonly>{html.escape(desc)}</textarea>
</article>""")
    fonte = html.escape(dados_dia.get("fonte", ""))
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Área Pequeña — {dia}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#0d1117;--card:#161b22;--line:#2a313c;--tx:#e6edf3;--mut:#8b949e;--ac:#d7ff3a;--red:#ff2d3d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);font:15px/1.4 system-ui,Segoe UI,sans-serif;padding:24px}}
h1{{margin:0 0 4px;font-size:22px}}p.sub{{margin:0 0 22px;color:var(--mut)}}p.sub a{{color:var(--mut)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px}}
article{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;display:flex;flex-direction:column;gap:6px}}
.hora{{font-weight:800;font-size:20px;color:var(--ac);display:flex;justify-content:space-between;align-items:baseline}}.hora small{{color:var(--mut);font-size:13px}}
video,.falta{{width:100%;aspect-ratio:9/16;border-radius:10px;background:#000;object-fit:cover}}.falta{{display:grid;place-items:center;color:var(--mut)}}
label{{display:flex;justify-content:space-between;align-items:center;color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-top:4px}}
textarea{{width:100%;resize:vertical;background:#0d1117;color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:8px;font:13px/1.4 system-ui,sans-serif}}
button{{background:var(--red);color:#fff;border:0;border-radius:999px;padding:4px 12px;font-weight:700;cursor:pointer;font-size:12px}}button.ok{{background:#2ea043}}
</style></head><body>
<h1>Área Pequeña FC — {dia}</h1>
<p class="sub">{len(shorts)} shorts · fonte: <a href="{fonte}">{fonte}</a> · agende cada um no horário marcado</p>
<div class="grid">{''.join(cards)}</div>
<script>
document.querySelectorAll('button[data-c]').forEach(b=>b.onclick=async()=>{{
  const t=document.getElementById(b.dataset.c);try{{await navigator.clipboard.writeText(t.value)}}catch(e){{t.select();document.execCommand('copy')}}
  b.textContent='copiado';b.classList.add('ok');setTimeout(()=>{{b.textContent='copiar';b.classList.remove('ok')}},1200)}});
</script></body></html>"""
    with open(os.path.join(pasta_saida, "painel.html"), "w", encoding="utf-8") as f:
        f.write(pagina)


# ---------------------------------------------------------------- principal

def gerar_dia(arq):
    dia = os.path.splitext(os.path.basename(arq))[0]
    dados = json.load(open(arq, encoding="utf-8"))
    shorts = dados["shorts"]
    pasta_fotos = os.path.join(BASE, "fotos", dia)
    pasta_saida = os.path.join(BASE, "saida", dia)
    pasta_cards = os.path.join(pasta_saida, "_cards")
    for p in (pasta_fotos, pasta_cards):
        os.makedirs(p, exist_ok=True)
    log(f"\n== {dia}: {len(shorts)} shorts")
    for n, s in enumerate(shorts):
        sid = s["id"]
        mp4 = os.path.join(pasta_saida, f"{sid}.mp4")
        manual = foto_manual(pasta_fotos, sid)
        if os.path.exists(mp4) and not (manual and os.path.getmtime(manual) > os.path.getmtime(mp4)):
            log(f" {sid} já existe")
            continue
        log(f" {sid} {s['titulo'][:60]}")
        try:
            foto, credito = foto_do_short(pasta_fotos, s)
            card = os.path.join(pasta_cards, f"{sid}.png")
            renderizar_card(s, foto, credito, card)
            montar_video(card, mp4, n)
            titulo, desc = textos_yt(s, dados)
            with open(os.path.join(pasta_saida, f"{sid}-textos.txt"), "w", encoding="utf-8") as f:
                f.write(f"HORÁRIO: {s.get('hora', '')}\n\nTÍTULO:\n{titulo}\n\nDESCRIÇÃO:\n{desc}\n")
            log(f"    ok{'' if foto else ' (sem foto)'}")
        except Exception as e:
            log(f"    ERRO: {e}")
    painel(pasta_saida, dia, dados, shorts)
    log(f" painel: {os.path.join(pasta_saida, 'painel.html')}")


def main():
    alvo = sys.argv[1] if len(sys.argv) > 1 else None
    arquivos = sorted(glob.glob(os.path.join(BASE, "roteiros", "dia-*.json")))
    if alvo:
        arquivos = [a for a in arquivos if os.path.basename(a).startswith(alvo)]
    if not arquivos:
        raise SystemExit("Nenhum roteiro em roteiros\\dia-XX.json")
    for a in arquivos:
        gerar_dia(a)


if __name__ == "__main__":
    main()
