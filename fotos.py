"""Busca a foto do short no Wikimedia Commons (licença livre) e recorta em volta do rosto do jogador.

Como escolhe:
  1. acha a pessoa no Wikidata: categoria do Commons (P373) e foto oficial (P18)
  2. candidatas = fotos da categoria dela + fotos com o nome no título (grandes, sem licença NC)
  3. ordena: título começando com o nome, horizontal, mais recente
  4. baixa até 8, detecta rostos (YuNet) e confere se o rosto é DELE (SFace x foto oficial)
  5. rosto tem que estar nítido; recorta 1,85:1 com o rosto no terço de cima, salva em 1920x1040
Busca começando com "~" (ex.: "~Estadio da Luz") = foto de cenário, sem rosto.
"""
import html
import json
import os
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
IA = os.path.join(BASE, "modelo", "ia")
MODELO_DETECTOR = os.path.join(IA, "face_detection_yunet_2023mar.onnx")
MODELO_RECONHECE = os.path.join(IA, "face_recognition_sface_2021dec.onnx")
CACHE_PESSOAS = os.path.join(BASE, "modelo", "pessoas.json")
PASTA_REF = os.path.join(BASE, "modelo", "rostos")
UA = "AreaPequenaShorts/1.0 (gerador local de shorts)"
SAIDA_L, SAIDA_A = 1920, 1040            # mesma proporção da foto do card (960x520)
PROP = SAIDA_L / SAIDA_A
NITIDEZ_ROSTO = 150                      # abaixo disso o rosto está desfocado
MIN_RECORTE = 1000                       # largura mínima do recorte na foto original
MESMA_PESSOA = 0.40                      # similaridade SFace (cosseno); 0,363 é o limite oficial
PROFISSOES = ("football", "futbol", "soccer", "coach", "manager", "entrenador", "president", "presidente")
try:
    import certifi
    # na nuvem o proxy tem certificado próprio (SSL_CERT_FILE); no PC usa o certifi
    SSL = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or next((c for c in ["/root/.ccr/ca-bundle.crt"] if os.path.exists(c)), certifi.where()))
except ImportError:
    SSL = ssl.create_default_context()


# ---------------------------------------------------------------- rede

_ultimo = [0.0]


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL) as r:
        return r.read()


def _api(url, **params):
    """GET em API da Wikimedia/Wikidata com pausa entre chamadas e nova tentativa se der 429."""
    for tentativa in range(4):
        espera = 1.0 - (time.time() - _ultimo[0])
        if espera > 0:
            time.sleep(espera)
        _ultimo[0] = time.time()
        try:
            return json.loads(_get(url + "?" + urllib.parse.urlencode(params), 30))
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == 3:
                raise
            time.sleep(5 * (tentativa + 1))


def _imagem(url):
    for tentativa in range(3):
        try:
            return cv2.imdecode(np.frombuffer(_get(url), np.uint8), cv2.IMREAD_COLOR)
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == 2:
                return None
            time.sleep(5 * (tentativa + 1))
        except Exception:
            return None


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _limpa(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


# ---------------------------------------------------------------- quem é a pessoa

def pessoa(nome):
    """{'cat': categoria do Commons, 'p18': arquivo da foto oficial} via Wikidata. Guardado em cache."""
    cache = json.load(open(CACHE_PESSOAS, encoding="utf-8")) if os.path.exists(CACHE_PESSOAS) else {}
    if nome in cache:
        return cache[nome]
    info = {"cat": None, "p18": None}
    r = _api("https://www.wikidata.org/w/api.php", action="wbsearchentities", search=nome,
             language="es", uselang="es", limit=5, format="json")
    for e in r.get("search", []):
        if not any(p in _norm(e.get("description", "")) for p in PROFISSOES):
            continue
        c = _api("https://www.wikidata.org/w/api.php", action="wbgetentities", ids=e["id"],
                 props="claims", format="json")["entities"][e["id"]].get("claims", {})
        val = lambda p: next((x["mainsnak"].get("datavalue", {}).get("value") for x in c.get(p, [])), None)
        info = {"id": e["id"], "cat": val("P373"), "p18": val("P18")}
        break
    cache[nome] = info
    json.dump(cache, open(CACHE_PESSOAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return info


# ---------------------------------------------------------------- rostos

_det, _rec = [None], [None]


def rostos(img):
    """Lista de rostos [x, y, w, h, 10 pontos, score] em coordenadas da imagem original."""
    h, w = img.shape[:2]
    esc = min(1.0, 1280 / max(w, h))
    peq = cv2.resize(img, (int(w * esc), int(h * esc))) if esc < 1 else img
    if _det[0] is None:
        _det[0] = cv2.FaceDetectorYN.create(MODELO_DETECTOR, "", (320, 320), 0.75)
    _det[0].setInputSize((peq.shape[1], peq.shape[0]))
    _, f = _det[0].detect(peq)
    if f is None:
        return []
    f = f.copy()
    f[:, :14] /= esc
    return sorted(f, key=lambda r: r[2] * r[3], reverse=True)


def assinatura(img, rosto):
    if _rec[0] is None:
        _rec[0] = cv2.FaceRecognizerSF.create(MODELO_RECONHECE, "")
    return _rec[0].feature(_rec[0].alignCrop(img, rosto)).copy()


def parecido(a, b):
    return float(_rec[0].match(a, b, cv2.FaceRecognizerSF_FR_COSINE))


def rosto_oficial(nome, info):
    """Assinatura do rosto da foto oficial (Wikidata P18), guardada em modelo/rostos."""
    os.makedirs(PASTA_REF, exist_ok=True)
    arq = os.path.join(PASTA_REF, re.sub(r"[^a-z0-9]+", "-", _norm(nome)).strip("-") + ".npy")
    if os.path.exists(arq):
        return np.load(arq)
    if not info.get("p18"):
        return None
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(info["p18"].replace(" ", "_")) + "?width=1000"
    img = _imagem(url)
    if img is None:
        return None
    rs = rostos(img)
    if not rs:
        return None
    sig = assinatura(img, rs[0])
    np.save(arq, sig)
    return sig


def nitidez_rosto(img, r):
    x, y, fw, fh = [int(v) for v in r[:4]]
    pedaco = img[max(y, 0):y + fh, max(x, 0):x + fw]
    if pedaco.size == 0:
        return 0.0
    pedaco = cv2.cvtColor(cv2.resize(pedaco, (160, max(1, int(160 * pedaco.shape[0] / max(pedaco.shape[1], 1))))), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(pedaco, cv2.CV_64F).var())


def recorte(img, r):
    """Caixa (x, y, w, h) 1,85:1 com o rosto no terço de cima e ~24% da altura."""
    H, W = img.shape[:2]
    if r is not None:
        x, y, fw, fh = r[:4]
        ch = fh / 0.24
        cw = max(ch * PROP, MIN_RECORTE)
        ch = cw / PROP
        cx, top = x + fw / 2, y + fh / 2 - ch * 0.38
    else:
        cw, ch = W, W / PROP
        cx, top = W / 2, H * 0.12
    if cw > W:
        cw, ch = W, W / PROP
    if ch > H:
        ch, cw = H, H * PROP
    left = min(max(cx - cw / 2, 0), W - cw)
    top = min(max(top, 0), H - ch)
    return int(left), int(top), int(cw), int(ch)


# ---------------------------------------------------------------- candidatas

def _commons(srsearch):
    d = _api("https://commons.wikimedia.org/w/api.php", action="query", format="json", generator="search",
             gsrnamespace=6, gsrsearch=f"{srsearch} filetype:bitmap", gsrlimit=50, prop="imageinfo|categories",
             clshow="!hidden", cllimit="max",
             iiprop="url|size|mime|extmetadata", iiurlwidth=2560,
             iiextmetadatafilter="Artist|LicenseShortName|DateTimeOriginal")
    return list((d.get("query") or {}).get("pages", {}).values())


def candidatos(nome, generica=False, cat=None):
    tokens = [t for t in re.split(r"\W+", _norm(nome)) if len(t) > 2]
    paginas = {}
    if cat:
        for pg in _commons(f'incategory:"{cat}"'):
            pg["_cat"] = True
            paginas[pg["title"]] = pg
    for pg in _commons(nome):
        paginas.setdefault(pg["title"], pg)
    lista = []
    for pg in paginas.values():
        ii = (pg.get("imageinfo") or [{}])[0]
        w, h = ii.get("width", 0), ii.get("height", 0)
        if ii.get("mime") not in ("image/jpeg", "image/png") or w < 1400 or h < 700:
            continue
        titulo = _norm(pg.get("title", ""))
        nome_no_titulo = all(t in titulo for t in tokens)
        comeca = bool(tokens) and re.sub(r"^file:\s*[\d\s_-]*", "", titulo).startswith(tokens[0])
        if not generica and not (nome_no_titulo or pg.get("_cat")):
            continue
        meta = ii.get("extmetadata") or {}
        lic = _limpa((meta.get("LicenseShortName") or {}).get("value"))
        if "nc" in re.split(r"[^a-z]+", lic.lower()):
            continue
        ano = re.search(r"(19|20)\d\d", (meta.get("DateTimeOriginal") or {}).get("value", "") or "")
        ano = int(ano.group(0)) if ano else 2000
        autor = re.sub(r"\[\d+\]|,?\s*Wikimedia Commons", "", _limpa((meta.get("Artist") or {}).get("value"))).strip(" ,/")[:50]
        lista.append({
            "url": ii.get("thumburl") or ii.get("url"), "pagina": ii.get("descriptionurl", ""),
            "titulo": pg.get("title", ""), "nome_no_titulo": nome_no_titulo,
            "categorias": " ".join(c.get("title", "")[9:] for c in pg.get("categories", [])),
            "ordem": (not comeca, not nome_no_titulo, "cropped" in titulo, w / h < 1.2, -ano, pg.get("index", 99)),
            "credito": (f"{autor} / " if autor else "") + "Wikimedia Commons" + (f", {lic}" if lic else ""),
        })
    lista.sort(key=lambda c: c["ordem"])
    return lista


def nitidez(img):
    cinza = cv2.cvtColor(cv2.resize(img, (960, int(960 * img.shape[0] / img.shape[1]))), cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(cinza, cv2.CV_64F).var()


# ---------------------------------------------------------------- escolha

def _avaliar_jogador(img, ref, c):
    """Devolve (nota, rosto) ou None se a foto não serve."""
    rs = [r for r in rostos(img)[:8] if r[3] >= 60]
    if not rs:
        return None
    if ref is not None:
        notas = [(parecido(ref, assinatura(img, r)), r) for r in rs]
        sim, r = max(notas, key=lambda t: t[0])
        if sim < MESMA_PESSOA:
            return None                    # nenhum rosto da foto é o do jogador
    else:
        # sem foto oficial pra comparar: só aceita foto com o nome no título e um rosto dominante
        r = rs[0]
        if not c["nome_no_titulo"] or (len(rs) > 1 and rs[1][2] * rs[1][3] > 0.4 * r[2] * r[3]):
            return None
        sim = 0.0
    nr = nitidez_rosto(img, r)
    if nr < NITIDEZ_ROSTO:
        return None
    caixa = recorte(img, r)
    nota = sim * 3 + min(nr, 600) / 300 + (1 if caixa[2] >= MIN_RECORTE else 0) + min(r[3] / img.shape[0], 0.25) * 4
    return nota, r


def melhor_foto(buscas, destino, log=print, max_baixar=8):
    """buscas: texto ou lista (tenta em ordem). Salva o recorte em destino. Devolve info ou None."""
    if isinstance(buscas, str):
        buscas = [buscas]
    for busca in buscas:
        generica = busca.startswith("~")
        busca = busca.lstrip("~").strip()
        try:
            info = {} if generica else pessoa(busca)
            ref = None if generica else rosto_oficial(busca, info)
            cands = candidatos(busca, generica, info.get("cat"))
        except Exception as e:
            log(f"   ! busca \"{busca}\" falhou ({e})")
            continue
        melhor = None
        for c in cands[:max_baixar]:
            img = _imagem(c["url"])
            if img is None:
                continue
            if generica:
                caixa = recorte(img, None)
                corte = img[caixa[1]:caixa[1] + caixa[3], caixa[0]:caixa[0] + caixa[2]]
                nota, r = min(nitidez(corte), 400) / 400 + (1 if caixa[2] >= MIN_RECORTE else 0), None
            else:
                av = _avaliar_jogador(img, ref, c)
                if not av:
                    continue
                nota, r = av
                caixa = recorte(img, r)
                corte = img[caixa[1]:caixa[1] + caixa[3], caixa[0]:caixa[0] + caixa[2]]
            if not melhor or nota > melhor[0]:
                melhor = (nota, corte, c)
            if not generica and nota >= 4.5:
                break                              # já é ótima
        if melhor:
            nota, corte, c = melhor
            interp = cv2.INTER_AREA if corte.shape[1] >= SAIDA_L else cv2.INTER_CUBIC
            cv2.imwrite(destino, cv2.resize(corte, (SAIDA_L, SAIDA_A), interpolation=interp), [cv2.IMWRITE_JPEG_QUALITY, 92])
            return {"busca": busca, "credito": c["credito"], "pagina": c["pagina"], "arquivo": c["titulo"],
                    "rosto": not generica, "conferido": bool(ref is not None and not generica), "nota": round(float(nota), 2)}
    return None
