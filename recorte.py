"""Recorta a pessoa da foto (fundo transparente) com rembg; guarda em banco/recortes/ pra não refazer."""
import hashlib, os
import numpy as np
from PIL import Image
BASE = os.path.dirname(os.path.abspath(__file__))
PASTA = os.path.join(BASE, "banco", "recortes")
_sessao = None

def recortar(foto):
    global _sessao
    os.makedirs(PASTA, exist_ok=True)
    chave = hashlib.md5(os.path.abspath(foto).encode("utf-8")).hexdigest()[:12]
    destino = os.path.join(PASTA, chave + ".png")
    if os.path.exists(destino):
        return destino
    from rembg import remove, new_session
    if _sessao is None:
        _sessao = new_session("u2net_human_seg")
    im = Image.open(foto).convert("RGB")
    im.thumbnail((1400, 1400))
    out = remove(im, session=_sessao, post_process_mask=True)
    a = np.array(out.getchannel("A"))
    # fica só com a maior mancha (a pessoa principal), descarta gente do fundo
    try:
        import cv2
        n, lab, stats, _ = cv2.connectedComponentsWithStats((a > 40).astype(np.uint8), 8)
        if n > 2:
            # prefere a mancha grande mais perto do centro
            h, w = a.shape
            melhor = max(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_AREA] / (1 + abs((stats[i, 0] + stats[i, 2] / 2) / w - 0.5) * 2))
            a = np.where(lab == melhor, a, 0).astype(np.uint8)
            out.putalpha(Image.fromarray(a))
    except ImportError:
        pass
    caixa = out.getchannel("A").point(lambda v: 255 if v > 30 else 0).getbbox()
    if caixa:
        out = out.crop(caixa)
    out.save(destino)
    return destino
