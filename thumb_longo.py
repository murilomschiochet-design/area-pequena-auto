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
    fs.sort(key=lambda f: ordem.get(f.get("tipo"), 2))
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
    nota = min(h, 1400) / 1400 + (0.6 if 0.9 <= razao <= 2.4 else 0) + a.mean() * 0.5
    return rec, nota, cobertura


def melhor_recorte(nome, contexto=None):
    melhores = [(avaliar(f), f) for f in fotos_da_pessoa(nome, contexto)[:6]]
    melhores = [(r, n, c, f) for (r, n, c), f in melhores if r]
    if not melhores:
        return None, []
    melhores.sort(key=lambda x: -x[1])
    return melhores[0][0], melhores


def gerar(dia):
    rot = json.load(open(os.path.join(BASE, "roteiros", f"{dia}.json"), encoding="utf-8"))
    shorts = rot["shorts"]
    usados, grandes, todas = set(), [], []
    for s in shorts:
        nome = nome_pessoa(s)
        if not nome or nome in usados:
            continue
        rec, lista = melhor_recorte(nome, s.get("contexto"))
        todas += lista
        if rec:
            usados.add(nome)
            grandes.append((nome, rec, lista))
        if len(grandes) == 2:
            break
    circulos = []
    for s in shorts:
        nome = nome_pessoa(s)
        if not nome or nome in usados:
            continue
        fs = fotos_da_pessoa(nome, s.get("contexto"))
        if fs:
            usados.add(nome)
            circulos.append(fs[0])
        if len(circulos) == 2:
            break
    if not grandes:
        raise SystemExit("sem recorte de nenhum jogador: thumbnail não gerada")
    # fundo: a foto com MENOS gente na frente (mais torcida/estádio)
    fundo = min(todas, key=lambda x: x[2])[3] if todas else os.path.join(BASE, "assets", "estadio-fundo.jpg")
    u = navegador.url_arquivo
    d = {"fundo": u(fundo), "p1": u(grandes[0][1]),
         "layout": {"p1x": "370px", "p2x": "10px", "p1h": "700px", "p2h": "640px"}}
    if len(grandes) > 1:
        d["p2"] = u(grandes[1][1])
    else:
        d["layout"]["p1x"] = "240px"
    for k, f in zip(("c1", "c2"), circulos):
        d[k], d[k + "pos"] = u(f), "50% 28%"
    pasta = os.path.join(BASE, "saida", dia)
    os.makedirs(pasta, exist_ok=True)
    png = os.path.join(pasta, "_thumb.png")
    navegador.print_pagina(navegador.url_arquivo(MODELO, urllib.parse.quote(json.dumps(d, ensure_ascii=False))), png, 1280, 720)
    destino = os.path.join(pasta, "thumb.jpg")
    Image.open(png).convert("RGB").save(destino, "JPEG", quality=90)
    os.remove(png)
    print(f"thumb: {destino}  (grandes: {[g[0] for g in grandes]}, círculos: {len(circulos)}, fundo: {os.path.basename(fundo)})")
    return destino


if __name__ == "__main__":
    gerar(sys.argv[1])
