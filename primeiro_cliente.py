"""@primeirocliente.site: publica no Instagram o post do dia (carrossel ou Reel) + os stories prontos, sozinho.

  python primeiro_cliente.py publicar        -> (workflow diário 12:07 de Brasília) publica o item de HOJE da fila
  python primeiro_cliente.py ver [AAAA-MM-DD]  -> mostra o que sai no dia (não publica)

Fila: primeiro-cliente/fila.json (gerada no PC a partir do painel). Mídia pública em MIDIA (Cloudflare Pages, noindex).
Credenciais: PC_IG_TOKEN e PC_IG_USER_ID (Secrets) ou credenciais/instagram-primeirocliente.txt no PC.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
PASTA = os.path.join(BASE, "primeiro-cliente")
FILA = os.path.join(PASTA, "fila.json")
FUSO = ZoneInfo("America/Sao_Paulo")
GRAPH = "https://graph.facebook.com/v23.0"
UA = {"User-Agent": "AreaPequenaShorts/1.0"}


def credencial():
    tok, uid = os.environ.get("PC_IG_TOKEN"), os.environ.get("PC_IG_USER_ID")
    if not tok:
        tok = open(os.path.join(BASE, "credenciais", "instagram-primeirocliente.txt"), encoding="utf-8").read().strip().strip("()<>\"' ")
        uid = uid or json.load(open(FILA, encoding="utf-8"))["user_id"]
    return tok, uid


def api(metodo, caminho, tok, **params):
    url = f"{GRAPH}/{caminho}"
    corpo = None
    if metodo == "GET":
        url += "?" + urllib.parse.urlencode(dict(params, access_token=tok))
    else:
        corpo = urllib.parse.urlencode(dict(params, access_token=tok)).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=corpo, headers=UA, method=metodo), timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Instagram {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def esperar(tok, cid, limite=900):
    fim = time.time() + limite
    while time.time() < fim:
        st = api("GET", cid, tok, fields="status_code").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {cid}: {st}")
        time.sleep(10)
    raise RuntimeError(f"container {cid} não ficou pronto")


def publicar_item(tok, uid, it, base):
    url = lambda arq: f"{base}/{it['pasta']}/{arq}"
    if it["tipo"] == "carrossel":
        filhos = [api("POST", f"{uid}/media", tok, image_url=url(f"carrossel-{i}.jpg"), is_carousel_item="true")["id"]
                  for i in range(1, it["slides"] + 1)]
        for f in filhos:
            esperar(tok, f, 300)
        c = api("POST", f"{uid}/media", tok, media_type="CAROUSEL", children=",".join(filhos), caption=it["legenda"])["id"]
    else:
        c = api("POST", f"{uid}/media", tok, media_type="REELS", video_url=url("reel.mp4"), cover_url=url("capa-reel.jpg"),
                caption=it["legenda"], share_to_feed="true")["id"]
    esperar(tok, c)
    pid = api("POST", f"{uid}/media_publish", tok, creation_id=c)["id"]
    print(f" post publicado ({it['tipo']}): {pid}")
    for n in it.get("stories", []):
        try:
            s = api("POST", f"{uid}/media", tok, media_type="STORIES", image_url=url(f"story-{n}.jpg"))["id"]
            esperar(tok, s, 300)
            print(f" story {n}: {api('POST', f'{uid}/media_publish', tok, creation_id=s)['id']}")
        except Exception as e:
            print(f" story {n}: erro {e}")
    return pid


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    fila = json.load(open(FILA, encoding="utf-8"))
    hoje = sys.argv[2] if len(sys.argv) > 2 else dt.datetime.now(FUSO).date().isoformat()
    it = next((x for x in fila["itens"] if x["publicar"] == hoje), None)
    if sys.argv[1] == "ver":
        print(json.dumps(it, ensure_ascii=False, indent=1) if it else f"nada na fila para {hoje}")
        return
    if not it:
        print(f"nada na fila para {hoje}")
        return
    if it.get("publicado"):
        print(f"{hoje} já publicado ({it['publicado']})")
        return
    tok, uid = credencial()
    it["publicado"] = publicar_item(tok, uid, it, fila["midia"])
    json.dump(fila, open(FILA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
