"""Banco de fotos do canal: banco/fotos/<Pessoa>/<Pessoa> - <Clube ou Selección> - N.jpg

- Até 3 fotos por clube e 3 por seleção de cada pessoa (jogador, treinador, presidente...).
- Toda foto já está recortada no tamanho do card (1920x1040), com o rosto conferido.
- Ao escolher, pega a que foi usada há mais tempo (ou nunca usada), pra não repetir.
- Sem foto da pessoa: usa o escudo do clube atual dela (banco/escudos/<Clube>.jpg).
Índice em banco/indice.json.
"""
import datetime
import json
import os
import re
import urllib.parse

import cv2
import numpy as np

import fotos

BASE = os.path.dirname(os.path.abspath(__file__))
BANCO = os.path.join(BASE, "banco")
PASTA_FOTOS = os.path.join(BANCO, "fotos")
PASTA_ESCUDOS = os.path.join(BANCO, "escudos")
INDICE = os.path.join(BANCO, "indice.json")
POR_CONTEXTO = 3
MAX_BAIXAR = 30            # fotos analisadas por pessoa na primeira vez
REABASTECER_DIAS = 30      # tenta completar de novo depois de 30 dias
WD = "https://www.wikidata.org/w/api.php"
GENERICAS = {"fc", "cf", "club", "de", "del", "la", "el", "futbol", "football", "association", "soccer", "team",
             "national", "nacional", "seleccion", "masculina", "men", "mens", "s", "sad", "the", "and", "y", "of"}


def _hoje():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _ler():
    return json.load(open(INDICE, encoding="utf-8")) if os.path.exists(INDICE) else {"pessoas": {}, "escudos": {}}


def _gravar(idx):
    os.makedirs(BANCO, exist_ok=True)
    tmp = INDICE + ".tmp"
    json.dump(idx, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, INDICE)


def _salvar_jpg(img, caminho):
    """cv2.imwrite não aceita acento no caminho no Windows: codifica e grava com open()."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("falha ao codificar jpg")
    with open(caminho, "wb") as f:
        f.write(buf.tobytes())


def _nome_arquivo(s):
    return re.sub(r'[<>:"/\\|?*]+', "", s).strip()


def _palavras(s):
    return [t for t in re.split(r"[^a-z0-9]+", fotos._norm(s or "")) if t and t not in GENERICAS and not re.fullmatch(r"(sub|under)?\d+", t)]


# ---------------------------------------------------------------- times da pessoa (Wikidata)

def times(qid):
    """Clubes e seleções (P54 jogador, P6087 treinador). Atuais primeiro."""
    c = fotos._api(WD, action="wbgetentities", ids=qid, props="claims", format="json")["entities"][qid].get("claims", {})
    lista = []
    for prop in ("P54", "P6087"):
        for x in c.get(prop, []):
            v = x["mainsnak"].get("datavalue", {}).get("value", {})
            if v.get("id") and v["id"] not in [t["id"] for t in lista]:
                lista.append({"id": v["id"], "atual": not x.get("qualifiers", {}).get("P582")})
    if not lista:
        return []
    ents = {}
    ids = [t["id"] for t in lista]
    for i in range(0, len(ids), 40):
        ents.update(fotos._api(WD, action="wbgetentities", ids="|".join(ids[i:i + 40]), props="labels|claims",
                               languages="es|en", format="json")["entities"])
    for t in lista:
        e = ents.get(t["id"], {})
        en = e.get("labels", {}).get("en", {}).get("value", "")
        es = e.get("labels", {}).get("es", {}).get("value", "") or en
        t["selecao"] = bool(re.search(r"national|selecci", fotos._norm(en + " " + es)))
        t["base"] = bool(re.search(r"under|sub-?\d|u-?\d\d|youth|juvenil|\bb\b|reserves|olymp", fotos._norm(en + " " + es)))
        t["nome"] = re.sub(r"\s+de f[uú]tbol|\s+masculina", "", es).strip()
        if t["selecao"]:
            t["nome"] = t["nome"][0].upper() + t["nome"][1:]
        t["chaves"] = [k for k in (_palavras(en), _palavras(es)) if k]
        logo = e.get("claims", {}).get("P154", [])
        t["logo"] = logo[0]["mainsnak"].get("datavalue", {}).get("value") if logo else None
    lista.sort(key=lambda t: (not t["atual"], t["base"]))
    return lista


def _contexto_da_foto(texto, ts):
    txt = fotos._norm(texto)
    for t in ts:
        if t["base"]:
            continue
        if any(all(re.search(rf"\b{re.escape(k)}\b", txt) for k in chave) for chave in t["chaves"]):
            return t
    return None


# ---------------------------------------------------------------- abastecer o banco

def _entrada(idx, nome):
    p = idx["pessoas"].setdefault(nome, {"fotos": [], "abastecido": None})
    return p


def abastecer(nome, log=print, forcar=False):
    idx = _ler()
    ent = _entrada(idx, nome)
    if ent.get("abastecido") and not forcar:
        dias = (datetime.datetime.now() - datetime.datetime.strptime(ent["abastecido"][:10], "%Y-%m-%d")).days
        if dias < REABASTECER_DIAS:
            return ent
    info = fotos.pessoa(nome)
    if not info.get("id"):
        log(f"    ! {nome} não está no Wikidata")
        ent["abastecido"] = _hoje()
        _gravar(idx)
        return ent
    ent["wikidata"] = info["id"]
    ts = times(info["id"])
    ent["times"] = [{k: t[k] for k in ("id", "nome", "atual", "selecao", "base", "logo")} for t in ts]
    ref = fotos.rosto_oficial(nome, info)
    ja = {f["origem"] for f in ent["fotos"]}
    conta = {}
    for f in ent["fotos"]:
        conta[f["contexto"]] = conta.get(f["contexto"], 0) + 1
    principais = [t for t in ts if t["atual"] and not t["base"]]      # clube atual e seleção
    vistos, grupos = set(), {}

    def juntar(lista):
        for c in lista:
            if c["pagina"] in vistos or c["pagina"] in ja:
                continue
            vistos.add(c["pagina"])
            t = _contexto_da_foto(c["titulo"] + " " + c.get("categorias", ""), ts)
            grupos.setdefault(t["nome"] if t else "Geral", []).append((c, t))

    juntar(fotos.candidatos(nome, False, info.get("cat")))
    for t in principais:                      # busca extra "Pedri Barcelona" se faltar foto daquele time
        if len(grupos.get(t["nome"], [])) < POR_CONTEXTO * 2 and t["chaves"]:
            juntar(fotos.candidatos(f"{nome} {' '.join(t['chaves'][0])}", False, None))
    ordem_ctx = [t["nome"] for t in principais] + [k for k in grupos if k not in [t["nome"] for t in principais]]
    baixadas = 0
    for ctx in ordem_ctx:
        for c, t in grupos.get(ctx, []):
            if conta.get(ctx, 0) >= POR_CONTEXTO or baixadas >= MAX_BAIXAR:
                break
            img = fotos._imagem(c["url"])
            baixadas += 1
            if img is None:
                continue
            av = fotos._avaliar_jogador(img, ref, c)
            if not av:
                continue
            caixa = fotos.recorte(img, av[1])
            corte = img[caixa[1]:caixa[1] + caixa[3], caixa[0]:caixa[0] + caixa[2]]
            interp = cv2.INTER_AREA if corte.shape[1] >= fotos.SAIDA_L else cv2.INTER_CUBIC
            corte = cv2.resize(corte, (fotos.SAIDA_L, fotos.SAIDA_A), interpolation=interp)
            conta[ctx] = conta.get(ctx, 0) + 1
            arq = _nome_arquivo(f"{nome} - {ctx} - {conta[ctx]}.jpg")
            _salvar_jpg(corte, os.path.join(PASTA_FOTOS, _nome_arquivo(nome), arq))
            ent["fotos"].append({
                "arquivo": f"{_nome_arquivo(nome)}/{arq}", "contexto": ctx,
                "tipo": ("selecao" if t["selecao"] else "clube") if t else "geral",
                "credito": c["credito"], "origem": c["pagina"], "nota": round(float(av[0]), 2),
                "ultimo_uso": None, "usos": 0, "adicionada": _hoje(),
            })
            log(f"    banco + {arq}")
    ent["abastecido"] = _hoje() if ent["fotos"] else None   # sem foto: tenta de novo na próxima
    _gravar(idx)
    return ent


# ---------------------------------------------------------------- escudos

def _info_clube(nome_clube):
    r = fotos._api(WD, action="wbsearchentities", search=nome_clube, language="es", uselang="es", limit=5, format="json")
    for e in r.get("search", []):
        d = fotos._norm(e.get("description", ""))
        if any(p in d for p in ("club", "football", "futbol", "equipo", "team", "seleccion")):
            c = fotos._api(WD, action="wbgetentities", ids=e["id"], props="claims|labels", languages="es",
                           format="json")["entities"][e["id"]]
            logo = c.get("claims", {}).get("P154", [])
            nome = c.get("labels", {}).get("es", {}).get("value", nome_clube)
            return nome, (logo[0]["mainsnak"].get("datavalue", {}).get("value") if logo else None)
    return nome_clube, None


def escudo(nome_clube=None, logo=None, log=print):
    """Imagem 1920x1040 com o escudo do clube num fundo com a cor dele. Devolve (caminho, crédito) ou (None, None)."""
    idx = _ler()
    if nome_clube in idx["escudos"] and os.path.exists(os.path.join(BANCO, idx["escudos"][nome_clube]["arquivo"])):
        e = idx["escudos"][nome_clube]
        return os.path.join(BANCO, e["arquivo"]), e["credito"]
    if not logo:
        nome_clube, logo = _info_clube(nome_clube)
    if not logo:
        log(f"    ! sem escudo para {nome_clube}")
        return None, None
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(logo.replace(" ", "_")) + "?width=900"
    try:
        dados = fotos._get(url)
    except Exception as e:
        log(f"    ! escudo de {nome_clube} não baixou ({e})")
        return None, None
    img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None, None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    alfa = img[:, :, 3:4].astype(np.float32) / 255
    # cor principal do escudo (pixels visíveis e saturados) para o fundo
    px = img[:, :, :3][img[:, :, 3] > 200].reshape(-1, 3)
    hsv = cv2.cvtColor(px.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3) if len(px) else np.zeros((0, 3))
    sat = px[hsv[:, 1] > 90] if len(px) else px
    cor = np.median(sat if len(sat) > 50 else px, axis=0) if len(px) else np.array([60, 40, 30])
    W, H = fotos.SAIDA_L, fotos.SAIDA_A
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H / 2) / H) ** 2)
    luz = np.clip(0.85 - dist * 1.1, 0.18, 0.85)[..., None]
    fundo = (cor[None, None, :] * luz + 8 * (1 - luz)).astype(np.float32)
    # escudo centralizado, 78% da altura, com sombra suave
    alt = int(H * 0.78)
    larg = int(img.shape[1] * alt / img.shape[0])
    if larg > W * 0.8:
        larg = int(W * 0.8)
        alt = int(img.shape[0] * larg / img.shape[1])
    esc = cv2.resize(img, (larg, alt), interpolation=cv2.INTER_AREA)
    a = esc[:, :, 3:4].astype(np.float32) / 255
    x0, y0 = (W - larg) // 2, (H - alt) // 2
    sombra = cv2.GaussianBlur(a[:, :, 0], (0, 0), 18)[..., None] * 0.55
    reg = fundo[y0 + 14:y0 + 14 + alt, x0:x0 + larg]
    reg[:] = reg * (1 - sombra[:reg.shape[0]])
    reg = fundo[y0:y0 + alt, x0:x0 + larg]
    reg[:] = reg * (1 - a) + esc[:, :, :3].astype(np.float32) * a
    final = np.clip(fundo, 0, 255).astype(np.uint8)
    arq = f"escudos/{_nome_arquivo(nome_clube)}.jpg"
    _salvar_jpg(final, os.path.join(BANCO, arq))
    credito = "Escudo: Wikimedia Commons"
    idx = _ler()
    idx["escudos"][nome_clube] = {"arquivo": arq, "logo": logo, "credito": credito}
    _gravar(idx)
    log(f"    banco + escudo {nome_clube}")
    return os.path.join(BANCO, arq), credito


# ---------------------------------------------------------------- escolher a foto do short

def foto(nome, contexto=None, log=print):
    """Foto da pessoa para o short. contexto: 'selecao', 'clube', nome do time ou None.
    Devolve (caminho, crédito, descrição) e marca o uso; sem foto, cai no escudo do clube atual."""
    ent = abastecer(nome, log=log)
    fs = ent.get("fotos", [])

    def filtro(f):
        if not contexto:
            return True
        if contexto == "selecao":
            return f["tipo"] == "selecao"
        if contexto == "clube":
            atuais = [t["nome"] for t in ent.get("times", []) if t["atual"] and not t["selecao"]]
            return f["tipo"] == "clube" and (not atuais or f["contexto"] in atuais)
        return fotos._norm(contexto) in fotos._norm(f["contexto"])

    opcoes = [f for f in fs if filtro(f)] or [f for f in fs if f["tipo"] == "geral"] or fs
    if opcoes:
        f = min(opcoes, key=lambda f: (f["ultimo_uso"] or "", f["usos"]))
        idx = _ler()
        for g in idx["pessoas"][nome]["fotos"]:
            if g["arquivo"] == f["arquivo"]:
                g["ultimo_uso"], g["usos"] = _hoje(), g["usos"] + 1
        _gravar(idx)
        return os.path.join(PASTA_FOTOS, f["arquivo"]), f["credito"], f"{f['arquivo']}"
    # sem foto: escudo do time certo (seleção ou clube atual)
    ts = [t for t in ent.get("times", []) if t["atual"] and not t["base"]]
    if contexto == "selecao":
        ts = [t for t in ts if t["selecao"]] + [t for t in ts if not t["selecao"]]
    else:
        ts = [t for t in ts if not t["selecao"]] + [t for t in ts if t["selecao"]]
    for t in ts:
        caminho, credito = escudo(t["nome"], t.get("logo"), log=log)
        if caminho:
            return caminho, credito, f"escudo {t['nome']}"
    return None, None, None
