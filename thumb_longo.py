"""Thumbnail 1280x720 do vídeo longo no estilo aprovado (2 jogadores recortados + 2 círculos + torcida desfocada).

Uso: python thumb_longo.py dia-XX   -> saida/dia-XX/thumb.jpg
Pessoas: as dos shorts 01 e 02 (grandes) e 03 e 04 (círculos). Fotos só do nosso banco (livres).
"""
import json
import os
import sys
import urllib.parse

import numpy as np
from PIL import Image

if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

import banco
import navegador
import recorte

BASE = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(BASE, "modelo", "thumb-longo.html")


def nome_pessoa(s):
    for b in s.get("foto_busca", []):
        if not b.startswith(("#", "~")):
            return b
    return None


def fotos_da_pessoa(nome, contexto=None):
    """Fotos do banco; primeiro as de uniforme (seleção/clube, na ordem do contexto), as "gerais" (roupa comum) por último."""
    try:
        ent = banco.abastecer(nome, log=lambda *a: None)
    except Exception as e:
        print(f"  ! banco falhou para {nome}: {str(e)[:80]}")
        return []
    fs = [f for f in ent.get("fotos", []) if os.path.exists(os.path.join(banco.PASTA_FOTOS, f["arquivo"]))]
    ordem = {"selecao": 0 if contexto == "selecao" else 1, "clube": 0 if contexto != "selecao" else 1, "geral": 2}
    fs.sort(key=lambda f: (ordem.get(f.get("tipo"), 2), -float(f.get("nota") or 0)))
    uniforme = [f for f in fs if f.get("tipo") != "geral"]
    return [os.path.join(banco.PASTA_FOTOS, f["arquivo"]) for f in (uniforme or fs)]


def avaliar(foto):
    """(recorte, nota, fração da foto ocupada pela pessoa). Nota alta = pessoa grande, em pé, inteira."""
    try:
        rec = recorte.recortar(foto)
    except Exception as e:
        print(f"  ! recorte falhou {os.path.basename(foto)}: {str(e)[:60]}")
        return None, -1, 1
    r = Image.open(rec)
    w, h = r.size
    W, H = Image.open(foto).size
    a = np.array(r.getchannel("A")) > 40
    cobertura = a.mean() * (w * h) / (W * H)
    razao = h / max(w, 1)
    nota = min(h, 1400) / 1400 + (0.8 if 1.3 <= razao <= 2.6 else 0) + a.mean() * 0.5   # rosto só (largo) fica gigante: evita
    return rec, nota, cobertura


def melhor_recorte(nome, contexto=None):
    melhores = [(avaliar(f), f) for f in fotos_da_pessoa(nome, contexto)[:6]]
    melhores = [(r, n, c, f) for (r, n, c), f in melhores if r]
    if not melhores:
        return None, []
    melhores.sort(key=lambda x: -x[1])
    r = Image.open(melhores[0][0])
    if not (1.15 <= r.height / max(r.width, 1) <= 2.8):     # só rosto ou foto de grupo: essa pessoa vai pro círculo
        return None, melhores
    return melhores[0][0], melhores


def busto(rec):
    """Corpo inteiro fica pequeno na thumb: corta da cabeça até a cintura (como o Cracks)."""
    im = Image.open(rec)
    w, h = im.size
    if h / max(w, 1) < 1.45:
        return rec
    destino = rec.replace(".png", "-busto.png")
    if not os.path.exists(destino):
        corte = im.crop((0, 0, w, int(h * 0.6)))
        caixa = corte.getchannel("A").point(lambda v: 255 if v > 30 else 0).getbbox()
        (corte.crop(caixa) if caixa else corte).save(destino)
    return destino


def rosto(foto):
    """Quadrado centrado na cabeça da pessoa (pro círculo), a partir do recorte."""
    try:
        rec = recorte.recortar(foto)
    except Exception:
        return foto
    destino = rec.replace(".png", "-rosto.jpg")
    if os.path.exists(destino):
        return destino
    im = Image.open(foto).convert("RGB")
    im.thumbnail((1400, 1400))
    from rembg import remove  # noqa: F401  (só pra garantir que o recorte veio do mesmo tamanho)
    r = Image.open(rec)
    a = np.array(r.getchannel("A")) > 40
    # o recorte foi cortado na caixa da pessoa: reencontra a posição dela na foto pelo tamanho
    W, H = im.size
    mask_full = np.array(recorte_mascara(foto, im.size))
    ys, xs = np.nonzero(mask_full)
    if len(xs) == 0:
        return foto
    if mask_full.mean() > 0.25 or (ys.max() - ys.min()) > 0.75 * H:   # já é um close: usa a foto quase inteira
        lado = min(W, H)
        x0 = int(min(max(xs.mean() - lado / 2, 0), W - lado))
        y0 = 0
        im.crop((x0, y0, x0 + lado, y0 + lado)).resize((500, 500), Image.LANCZOS).save(destino, quality=92)
        return destino
    topo, base, esq, dir_ = ys.min(), ys.max(), xs.min(), xs.max()
    larg, alt = dir_ - esq, base - topo
    if alt > 0.6 * H and larg > 0.45 * W:   # foto de busto/rosto: quase a foto inteira
        lado = int(min(W, H) * 0.85)
    else:                                   # corpo inteiro pequeno: só cabeça e ombros
        lado = int(min(max(min(larg * 0.75, alt * 0.42), 120), W, H))
    linha_cabeca = mask_full[topo:topo + max(lado // 2, 1)]
    cx = int(np.nonzero(linha_cabeca.any(axis=0))[0].mean()) if linha_cabeca.any() else (esq + dir_) // 2
    x0 = int(min(max(cx - lado / 2, 0), W - lado))
    y0 = int(min(max(topo - lado * 0.06, 0), H - lado))
    im.crop((x0, y0, x0 + lado, y0 + lado)).resize((500, 500), Image.LANCZOS).save(destino, quality=92)
    return destino


def recorte_mascara(foto, tamanho):
    from rembg import remove, new_session
    global _sess
    try:
        _sess
    except NameError:
        _sess = new_session("u2net_human_seg")
    im = Image.open(foto).convert("RGB").resize(tamanho)
    m = np.array(remove(im, session=_sess, only_mask=True, post_process_mask=True)) > 100
    try:
        import cv2
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
        if n > 2:
            w = m.shape[1]
            melhor = max(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_AREA] / (1 + abs((stats[i, 0] + stats[i, 2] / 2) / w - 0.5) * 2))
            m = lab == melhor
    except ImportError:
        pass
    return m


def escudo_png(clube):
    """Escudo oficial (Wikidata P154) em PNG transparente, guardado em banco/escudos-png/."""
    import urllib.parse
    pasta = os.path.join(BASE, "banco", "escudos-png")
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, banco._nome_arquivo(clube) + ".png")
    if os.path.exists(arq):
        return arq
    try:
        nome, logo = banco._info_clube(clube)
        if not logo:
            print(f"  ! sem escudo no Wikidata: {clube}")
            return None
        url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(logo.replace(" ", "_")) + "?width=600"
        import io
        im = Image.open(io.BytesIO(banco.fotos._get(url))).convert("RGBA")
    except Exception as e:
        print(f"  ! escudo {clube} falhou: {str(e)[:80]}")
        return None
    caixa = im.getchannel("A").getbbox()
    (im.crop(caixa) if caixa else im).save(arq)
    return arq


PAISES = {"españa": "Spain", "francia": "France", "inglaterra": "England", "alemania": "Germany", "italia": "Italy",
          "portugal": "Portugal", "brasil": "Brazil", "argentina": "Argentina", "países bajos": "the Netherlands",
          "bélgica": "Belgium", "croacia": "Croatia", "uruguay": "Uruguay", "colombia": "Colombia", "méxico": "Mexico",
          "estados unidos": "the United States", "marruecos": "Morocco", "noruega": "Norway", "polonia": "Poland",
          "suiza": "Switzerland", "dinamarca": "Denmark", "turquía": "Turkey", "japón": "Japan", "escocia": "Scotland",
          "serbia": "Serbia", "senegal": "Senegal", "ecuador": "Ecuador", "chile": "Chile", "perú": "Peru", "paraguay": "Paraguay",
          "costa de marfil": "Côte d'Ivoire", "nigeria": "Nigeria", "egipto": "Egypt", "corea del sur": "South Korea"}


def bandeira_png(selecao):
    """Seleção → bandeira do país (livre no Commons), em PNG."""
    import io
    import urllib.parse
    nome = selecao.lower().replace("selección de fútbol de ", "").replace("selección de ", "").replace("selección ", "").strip()
    pais = PAISES.get(nome)
    if not pais:
        return None
    pasta = os.path.join(BASE, "banco", "escudos-png")
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, "bandeira-" + banco._nome_arquivo(pais) + ".png")
    if not os.path.exists(arq):
        try:
            url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(f"Flag_of_{pais.replace(' ', '_')}.svg") + "?width=600"
            Image.open(io.BytesIO(banco.fotos._get(url))).convert("RGBA").save(arq)
        except Exception as e:
            print(f"  ! bandeira {pais} falhou: {str(e)[:60]}")
            return None
    return arq


def simbolo(clube):
    """Escudo do clube ou, se for seleção, a bandeira."""
    if "selecci" in clube.lower():
        return bandeira_png(clube) or escudo_png(clube)
    return escudo_png(clube)


def cores_de(png, n=3):
    """As cores mais fortes da imagem (escudo/bandeira/camisa) pra pintar as pinceladas."""
    im = Image.open(png).convert("RGBA")
    im.thumbnail((160, 160))
    a = np.array(im)
    px = a[a[:, :, 3] > 200][:, :3].astype(np.float32)
    if len(px) < 50:
        return []
    import cv2
    _, rot, centros = cv2.kmeans(px, 5, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 3, cv2.KMEANS_PP_CENTERS)
    conta = np.bincount(rot.flatten(), minlength=5)
    cores = []
    for i in np.argsort(-conta):
        r, g, b = centros[i]
        sat = max(r, g, b) - min(r, g, b)
        luz = (r + g + b) / 3
        if conta[i] < len(px) * 0.04 or (sat < 40 and 60 < luz < 215):   # descarta cinzas sujos
            continue
        cores.append("#%02x%02x%02x" % (int(r), int(g), int(b)))
    return cores[:n]


def nitido(caminho):
    """Mais nitidez, contraste e cor (como thumb profissional)."""
    from PIL import ImageEnhance, ImageFilter
    base, ext = os.path.splitext(caminho)
    destino = base + "-hd" + (".png" if ext.lower() == ".png" else ".jpg")
    if os.path.exists(destino):
        return destino
    im = Image.open(caminho)
    alfa = im.getchannel("A") if im.mode == "RGBA" else None
    rgb = im.convert("RGB").filter(ImageFilter.UnsharpMask(radius=2.2, percent=150, threshold=2))
    rgb = ImageEnhance.Contrast(ImageEnhance.Color(rgb).enhance(1.18)).enhance(1.08)
    if alfa:
        rgb.putalpha(alfa)
        rgb.save(destino)
    else:
        rgb.save(destino, quality=93)
    return destino


def escolhas(rot):
    """Quem aparece: o bloco longo.thumb do roteiro (escolhido pela rotina) ou, sem ele, as pessoas dos shorts."""
    t = (rot.get("longo") or {}).get("thumb") or {}
    ctx = {nome_pessoa(s): s.get("contexto") for s in rot["shorts"]}
    pessoas = [nome_pessoa(s) for s in rot["shorts"] if nome_pessoa(s)]
    grandes = t.get("grandes") or pessoas[:3]
    circulos = t.get("circulos") or [p for p in pessoas if p not in grandes][:3]
    escudos = t.get("escudos") or []
    return grandes, circulos, escudos, ctx


def escrever_prompt_flow(pasta, rot, grandes, circulos, escudos):
    """Prompt pronto pra melhorar a thumbnail no Flow (Google), usando a nossa como base."""
    longo = rot.get("longo") or {}
    clubes = ", ".join(f"{e.get('clube')} ({'red X over it' if e.get('marca') == 'x' else 'green check mark' if e.get('marca') == 'v' else 'no mark'})"
                       for e in escudos if e.get("clube")) or "none"
    txt = f"""COMO USAR NO FLOW
1. Imagem 1: thumb.jpg (esta pasta) = a base. Imagens 2 e 3: duas thumbnails do Cracks (só como referência de estilo).
2. Cole o prompt abaixo. Gere 4 versões e escolha a melhor; se mudar o rosto de alguém, descarte.
3. Suba no YouTube Studio > vídeo longo do dia > Miniatura.

PROMPT (cole tudo):
Edit image 1 into a high-impact YouTube thumbnail for a Spanish football news video, 16:9, 1280x720.
Keep EXACTLY the same people, faces, hair, kits and positions from image 1 - do not change anyone's face or identity, do not add new people.
Main figure in the center: {grandes[0] if grandes else ''}. Other large figures: {', '.join(grandes[1:]) or 'none'}. Small circle portraits: {', '.join(circulos) or 'none'}.
Copy only the LOOK of images 2 and 3 (style references, do not copy their people, logos or text):
- background: packed football stadium crowd at night, strong depth-of-field blur, warm stadium lights and soft light flares
- every cut-out person has a thin clean white outline, crisp edges, strong rim light, punchy saturated colors and high contrast
- circle portraits with thick white borders and drop shadows, faces centered and sharp
- club crests: {clubes}; keep crests flat and accurate
- keep the "AREA PEQUEÑA" badge in the bottom-left corner exactly as it is
No other text, no titles, no watermarks. Photorealistic, sharp, professional sports-news thumbnail.

Título do vídeo (pra conferir que a imagem combina): {longo.get('titulo_yt', '')}
"""
    with open(os.path.join(pasta, "prompt-flow.txt"), "w", encoding="utf-8") as f:
        f.write(txt)


def gerar(dia):
    rot = json.load(open(os.path.join(BASE, "roteiros", f"{dia}.json"), encoding="utf-8"))
    g_nomes, c_nomes, escudos, ctx = escolhas(rot)
    t = (rot.get("longo") or {}).get("thumb") or {}
    grandes, todas, usados = [], [], set()
    for nome in g_nomes:
        if len(grandes) == 2 or nome in usados:          # 2 grandes; o 3º vira círculo
            continue
        rec, lista = melhor_recorte(nome, ctx.get(nome))
        todas += lista
        if rec:
            usados.add(nome)
            grandes.append((nome, rec))
    circulos, c_usados = [], []
    for nome in [n for n in g_nomes if n not in usados] + c_nomes:
        if len(circulos) == 3 or nome in usados:
            continue
        fs = fotos_da_pessoa(nome, ctx.get(nome))
        if fs:
            usados.add(nome)
            circulos.append(fs[0])
            c_usados.append(nome)
    if not grandes:
        raise SystemExit("sem recorte de nenhum jogador: thumbnail não gerada")
    fundo = min(todas, key=lambda x: x[2])[3] if todas else os.path.join(BASE, "assets", "estadio-fundo.jpg")
    u = navegador.url_arquivo
    d = {"fundo": u(fundo), "layout": {}, "alerta": bool(t.get("alerta"))}
    for k, (_, rec) in zip(("p1", "p2"), grandes):
        d[k] = u(nitido(busto(rec)))
    for k, f in zip(("c1", "c2", "c3"), circulos):
        d[k], d[k + "pos"] = u(nitido(rosto(f))), "50% 40%"
    cores = []
    if escudos and escudos[0].get("clube"):
        png = simbolo(escudos[0]["clube"])
        if png:
            cores = cores_de(png)
            if "bandeira-" not in os.path.basename(png):          # bandeira retangular fica feia: vira só as cores
                d["e1"], d["e1marca"] = u(png), escudos[0].get("marca", "")
    if len(cores) < 2:                                   # sem escudo: cores da camisa do principal
        cores = cores_de(busto(grandes[0][1])) or cores
    d["cores"] = cores
    pasta = os.path.join(BASE, "saida", dia)
    os.makedirs(pasta, exist_ok=True)
    png = os.path.join(pasta, "_thumb.png")
    navegador.print_pagina(navegador.url_arquivo(MODELO, urllib.parse.quote(json.dumps(d, ensure_ascii=False))), png, 1280, 720)
    destino = os.path.join(pasta, "thumb.jpg")
    Image.open(png).convert("RGB").save(destino, "JPEG", quality=90)
    os.remove(png)
    escrever_prompt_flow(pasta, rot, [g[0] for g in grandes], c_usados, escudos[:1])
    print(f"thumb: {destino}  (grandes: {[g[0] for g in grandes]}, círculos: {c_usados}, "
          f"símbolo: {escudos[0].get('clube') if escudos else None}, cores: {cores}, alerta: {d['alerta']})")
    return destino


if __name__ == "__main__":
    gerar(sys.argv[1])
