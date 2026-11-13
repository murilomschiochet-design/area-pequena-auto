"""Junta as notícias de futebol das últimas horas da MARCA, do AS e do Mundo Deportivo (feeds RSS oficiais).

Uso: python noticias.py [horas=26]
Salva fontes/noticias-AAAA-MM-DD.txt (data de Roma): uma ficha por notícia com fonte, hora, título, link,
resumo e o começo do texto da matéria. A rotina do Claude escolhe as mais fortes e reescreve com palavras próprias.
Só texto: as FOTOS desses jornais são de agências (EFE, Getty, AFP...) e NÃO podem ser usadas.
"""
import concurrent.futures as cf
import datetime as dt
import email.utils
import html
import os
import re
import ssl
import sys
import urllib.request
from zoneinfo import ZoneInfo

if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
FONTES = os.path.join(BASE, "fontes")
UA = {"User-Agent": "AreaPequenaShorts/1.0 (+https://area-pequena-fc.pages.dev/)"}
# (fonte, url, só_links_de_futebol) — os de "portada/home" misturam outros assuntos
FEEDS = [
    ("MARCA", "https://www.marca.com/rss/futbol.xml", False),
    ("MARCA", "https://www.marca.com/rss/portada.xml", True),
    ("AS", "https://feeds.as.com/mrss-s/pages/as/site/as.com/section/futbol/portada/", False),
    ("Mundo Deportivo", "https://www.mundodeportivo.com/rss/futbol.xml", False),
    ("Mundo Deportivo", "https://www.mundodeportivo.com/rss/home.xml", True),
]
E_FUTEBOL = re.compile(r"/(futbol|seleccion-espanola|real-madrid|fc-barcelona|atletico)", re.I)
# serviço, não notícia
LIXO = re.compile(r"(a qu[eé] hora|d[oó]nde ver|en directo|en vivo|resultado(s)? de|horario y|alineaciones? (de|del|confirmadas)|"
                  r"quiniela|apuestas?|cuotas|cr[oó]nica del|minuto a minuto|\| ?directo|ofertas?|descuento|black friday)", re.I)
NAO_FUTEBOL = re.compile(r"/(baloncesto|nba|tenis|motor|f1|formula-1|motogp|ciclismo|golf|atletismo|balonmano|nfl|boxeo|"
                         r"mma|ufc|padel|otros-deportes|esports|juegos|television|tiramillas|loterias|cultura)/", re.I)
FUSO = ZoneInfo("Europe/Rome")


def baixar(url, timeout=20):
    ctx = ssl.create_default_context()
    if os.path.exists("/root/.ccr/ca-bundle.crt"):
        ctx = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "replace")


def limpar(t):
    t = re.sub(r"<!\[CDATA\[|\]\]>", "", t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(html.unescape(t))).strip()


def campo(item, nome):
    m = re.search(rf"<{nome}[^>]*>(.*?)</{nome}>", item, re.S)
    return limpar(m.group(1)) if m else ""


def ler_feed(fonte, url):
    try:
        x = baixar(url)
    except Exception as e:
        print(f"  ! {fonte}: feed falhou ({str(e)[:60]})")
        return []
    itens = []
    for it in re.findall(r"<item\b.*?</item>", x, re.S):
        titulo, link = campo(it, "title"), campo(it, "link") or campo(it, "guid")
        data = campo(it, "pubDate") or campo(it, "dc:date")
        try:
            quando = email.utils.parsedate_to_datetime(data)
        except Exception:
            try:
                quando = dt.datetime.fromisoformat(data.replace("Z", "+00:00"))
            except Exception:
                quando = None
        resumo = campo(it, "description")
        if titulo and link:
            itens.append(dict(fonte=fonte, titulo=titulo, link=link.strip(), quando=quando, resumo=resumo[:500]))
    return itens


def texto_materia(link):
    """Começo do texto da matéria (parágrafos <p>), sem menus nem legendas."""
    try:
        h = baixar(link, 15)
    except Exception:
        return ""
    h = re.sub(r"<(script|style|figure|figcaption|aside|nav|footer|header)\b.*?</\1>", " ", h, flags=re.S | re.I)
    ps = [limpar(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", h, re.S | re.I)]
    ps = [p for p in ps if len(p) > 60 and not re.search(r"(cookies|suscr[ií]b|newsletter|©|todos los derechos|"
                                                          r"inicia sesi[oó]n|reg[ií]strate|whatsapp|s[ií]guenos)", p, re.I)]
    return " ".join(ps)[:1800]


def main():
    horas = float(sys.argv[1]) if len(sys.argv) > 1 else 26
    agora = dt.datetime.now(dt.timezone.utc)
    vistos, itens = set(), []
    for fonte, url, so_futebol in FEEDS:
        for it in ler_feed(fonte, url):
            chave = re.sub(r"[?#].*", "", it["link"])
            if so_futebol and not E_FUTEBOL.search(it["link"]):
                continue
            if chave in vistos or LIXO.search(it["titulo"]) or NAO_FUTEBOL.search(it["link"]):
                continue
            if it["quando"] and agora - it["quando"] > dt.timedelta(hours=horas):
                continue
            vistos.add(chave)
            itens.append(it)
    itens.sort(key=lambda i: i["quando"] or agora, reverse=True)
    por_fonte = {}
    itens = [i for i in itens if por_fonte.setdefault(i["fonte"], []).append(i) or len(por_fonte[i["fonte"]]) <= 25]
    print(f"{len(itens)} notícias de futebol nas últimas {horas:g} h")
    with cf.ThreadPoolExecutor(8) as ex:
        for it, txt in zip(itens, ex.map(lambda i: texto_materia(i["link"]), itens)):
            it["texto"] = txt
    hoje = dt.datetime.now(FUSO).date().isoformat()
    os.makedirs(FONTES, exist_ok=True)
    arq = os.path.join(FONTES, f"noticias-{hoje}.txt")
    with open(arq, "w", encoding="utf-8") as f:
        f.write(f"NOTICIAS DE FÚTBOL — {hoje} — MARCA, AS, Mundo Deportivo (últimas {horas:g} h)\n"
                "Use só os fatos e as frases entre aspas que estão aqui. Cite a fonte. Não use fotos destes jornais.\n\n")
        for n, it in enumerate(itens, 1):
            hora = it["quando"].astimezone(FUSO).strftime("%d/%m %H:%M") if it["quando"] else "?"
            f.write(f"[{n}] {it['fonte']} | {hora} | {it['titulo']}\nLINK: {it['link']}\n")
            if it["resumo"]:
                f.write(f"RESUMEN: {it['resumo']}\n")
            if it["texto"]:
                f.write(f"TEXTO: {it['texto']}\n")
            f.write("\n")
    com_texto = sum(1 for i in itens if i["texto"])
    print(f"salvo {arq} ({com_texto} com texto da matéria)")


if __name__ == "__main__":
    main()
