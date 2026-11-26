#!/usr/bin/env python3
"""Faz os cortes: vertical 1080x1920, com título e legenda palavra por palavra.

Uso:
  python3 cortar.py <pasta da gravação> [--so 2] [--estilo <kit>]
                    [--modo empilhado|seguir|desfocado] [--camera x,y,largura,altura] [--cookies chrome]

Lê <pasta>/momentos-conferidos.json (do conferir.py) e, para cada momento marcado:
  1. Pega só aquele trecho (link: baixa a parte; arquivo: corta a parte).
  2. Acerta o trecho com o áudio da gravação, para o corte começar na palavra certa.
  3. Escolhe o enquadramento olhando 2 quadros por segundo:
       empilhado  câmera do falante em cima, conteúdo embaixo (live de jogo, tela com câmera pequena)
       seguir     o rosto ocupa a tela: recorte vertical em volta dele (podcast, conversa)
       desfocado  não achou rosto: o vídeo no meio, com o próprio vídeo desfocado ao fundo
  4. Transcreve o trecho palavra por palavra para a legenda.
  5. Monta tudo com UM ffmpeg: ele recorta, escala, compõe e acerta o volume. O Python só desenha
     título e legenda, numa faixa pequena que entra como uma camada de vídeo.

Escreve em <pasta>/cortes/:
  NN-titulo.mp4           o corte
  NN-titulo.txt           título, legenda do post, hashtags, de onde veio e a fala
  NN-titulo-folha.jpg     seis quadros do corte, para olhar antes de postar
  cortes.json             a lista
E em <pasta>/trechos/: NN.mp4 (o trecho) e NN-camera.jpg (o enquadramento escolhido, com as caixas desenhadas).

O visual: vem do perfil da pessoa (~/.garimpo/perfil.json, feito no onboarding); --estilo <kit> usa outro kit do catálogo
(referencias/estilos.json); <pasta>/estilo.json muda chaves soltas (veja BASE em estilo.py), inclusive "fonte".
Se o enquadramento sair errado, olhe trechos/NN-camera.jpg e passe --camera x,y,largura,altura (em pixels do vídeo original).
"""
import argparse
import io
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402
import estilo  # noqa: E402

comum.no_ambiente()
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass

L, A, FPS = 1080, 1920, 30
FPS_LEGENDA = 20   # a faixa de legendas entra a 20 quadros por segundo; o ffmpeg repete o último até o próximo
FAIXA = 380        # altura da faixa de legendas
MARGEM = 8         # segundos a mais, antes e depois, no trecho que se pega
GRANDE = 0.16      # um rosto com esta largura (fração da tela) quer dizer que a câmera é a tela inteira

BASE = estilo.BASE   # as chaves e o que cada uma faz estão em estilo.py; os kits, em referencias/estilos.json
FONTES = [str(comum.MODELOS / "Anton-Regular.ttf"), "/System/Library/Fonts/Supplemental/Impact.ttf",
          "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arialbd.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


# ---------- pequenos auxiliares ----------

@lru_cache(maxsize=64)
def fonte(tamanho, arquivo=""):
    """`arquivo` é a fonte escolhida (est["fonte_arquivo"]); sem ela, ou se não abrir, vale a primeira da lista FONTES."""
    for f in ([arquivo] if arquivo else []) + FONTES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, tamanho)
            except OSError:
                continue
    return ImageFont.load_default()


@lru_cache(maxsize=8)
def selo_pessoal(nome):
    """Um selo só desta pessoa: ~/.garimpo/selos/<nome>.py (veja o cabeçalho de um deles). O selo "caixa" é o da skill."""
    arq = comum.CASA / "selos" / (nome + ".py")
    if nome == "caixa" or not arq.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("selo_" + nome, str(arq))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def cor(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def par(v):
    return int(v) // 2 * 2


def para_cv(p):
    """O caminho como o OpenCV abre. No Windows ele não abre caminho com acento: recebe o relativo, que não tem."""
    p = str(p)
    if comum.WINDOWS and not p.isascii():
        try:
            curto = os.path.relpath(p)
            if curto.isascii():
                return curto
        except ValueError:
            pass
    return p


def gravar_imagem(caminho, imagem_bgr, qualidade=90):
    """cv2.imwrite falha calado em caminho com acento no Windows: codifica aqui e grava com o Python."""
    ok, dado = cv2.imencode(".jpg", imagem_bgr, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    if ok:
        Path(caminho).write_bytes(dado.tobytes())


# ---------- o trecho ----------

def obter_trecho(info, trechos, n, ini, fim, cookies):
    """Baixa (link) ou corta (arquivo) só o pedaço. Só reaproveita um trecho antigo se o tempo pedido for o mesmo."""
    destino, marca = trechos / ("%02d.mp4" % n), trechos / ("%02d.json" % n)
    a, b = max(0.0, ini - MARGEM), fim + MARGEM
    if destino.exists() and destino.stat().st_size > 100000 and comum.ler_json(marca) == {"a": round(a, 2), "b": round(b, 2)}:
        return destino, a
    destino.unlink(missing_ok=True)
    if info.get("arquivo"):
        cmd = [comum.ffmpeg(), "-v", "error", "-y", "-ss", "%.3f" % a, "-i", info["arquivo"], "-t", "%.3f" % (b - a),
               "-vf", "scale=-2:'min(1080,ih)'"] + comum.encoder_de_video() + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(destino)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode or not destino.exists():
            sys.exit("Não consegui cortar o trecho %d:\n%s" % (n, r.stderr[-1200:]))
    else:
        r = comum.ytdlp("-f", "bv*[height<=1080][fps<=30]+ba/bv*[height<=1080]+ba/b[height<=1080]/b",
                        "--download-sections", "*%s-%s" % (comum.relogio(a), comum.relogio(b + 1)), "--force-keyframes-at-cuts",
                        "--merge-output-format", "mp4", "-o", str(trechos / ("%02d.%%(ext)s" % n)), info["link"], cookies=cookies)
        if r.returncode or not destino.exists():
            sys.exit("Não consegui baixar o trecho %d:\n%s" % (n, (r.stderr or "")[-1200:]))
    comum.escrever_json(marca, {"a": round(a, 2), "b": round(b, 2)})
    return destino, a


def envelope(x):
    x = np.abs(x.astype(np.float32))
    n = len(x) // 160 * 160
    e = x[:n].reshape(-1, 160).mean(axis=1)  # 100 valores por segundo
    return (e - e.mean()) / (e.std() + 1e-9)


def alinhar(trecho, audio_da_live, pedido):
    """Em que segundo da gravação o trecho baixado realmente começa, achado casando o som dele com o som da gravação.
    Devolve (segundo, som do trecho, certeza). Certeza abaixo de 6: fica o tempo pedido."""
    som = comum.audio(trecho)
    if audio_da_live is None or len(som) < comum.TAXA * 5:
        return pedido, som, 0.0
    folga = 25.0
    base = max(0.0, pedido - folga)
    regiao = comum.audio(audio_da_live, inicio=base, duracao=len(som) / comum.TAXA + 2 * folga)
    x, y = envelope(som), envelope(regiao)
    if len(y) <= len(x):
        return pedido, som, 0.0
    c = np.correlate(y, x, mode="valid") / len(x)
    k = int(np.argmax(c))
    certeza = float((c[k] - c.mean()) / (c.std() + 1e-9))
    return (pedido, som, certeza) if certeza < 6 else (base + k / 100.0, som, certeza)


# ---------- o enquadramento ----------

class Rostos:
    def __init__(self):
        modelo = comum.MODELOS / "face_detection_yunet_2023mar.onnx"
        self.yunet = self.haar = None
        if modelo.exists() and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.yunet = cv2.FaceDetectorYN.create(str(modelo), "", (320, 320), 0.7, 0.3, 50)
            except Exception:
                try:  # caminho que o OpenCV não abre (acento, no Windows): entrega os bytes do arquivo
                    dado = np.frombuffer(modelo.read_bytes(), np.uint8)
                    self.yunet = cv2.FaceDetectorYN.create("onnx", dado, np.zeros(0, np.uint8), (320, 320), 0.7, 0.3, 50)
                except Exception:
                    self.yunet = None
        if self.yunet is None:
            try:
                haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                self.haar = None if haar.empty() else haar
            except Exception:
                self.haar = None

    def em(self, quadro):
        h, w = quadro.shape[:2]
        if self.yunet is not None:
            self.yunet.setInputSize((w, h))
            _, achados = self.yunet.detect(quadro)
            return [tuple(float(v) for v in f[:4]) for f in (achados if achados is not None else [])]
        if self.haar is None:
            return []
        cinza = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
        return [tuple(float(v) for v in f) for f in self.haar.detectMultiScale(cinza, 1.1, 5, minSize=(30, 30))]


def amostrar(trecho, t0, dur, rostos, passo):
    """Olha o trecho a cada `passo` segundos. Devolve (W, H, escala, quadros pequenos, rostos achados em cada um).
    Os rostos são procurados no quadro reduzido a 960 de largura; as coordenadas ficam na escala reduzida."""
    cap = cv2.VideoCapture(para_cv(trecho))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    escala = min(1.0, 960.0 / max(1, W))
    alvos = [int(round((t0 + (i + 0.5) * passo) * fps)) for i in range(max(1, int(dur / passo)))]
    quadros, achados, i = [], [], 0
    for alvo in alvos:
        ok = True
        while i < alvo and ok:
            ok = cap.grab()
            i += 1
        ok = cap.grab() and ok
        i += 1
        if not ok:
            break
        ok, q = cap.retrieve()
        if not ok:
            continue
        q = cv2.resize(q, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA) if escala < 1 else q
        quadros.append(q)
        achados.append(rostos.em(q))
    cap.release()
    return W, H, escala, quadros, achados


def rosto_parado(quadros, achados):
    """A câmera do falante: um rosto que fica no mesmo lugar na maior parte do trecho e está VIVO.
    Um rosto pintado na arte do jogo também fica parado, mas os pixels dele nunca mudam."""
    if not quadros:
        return None
    Ws = quadros[0].shape[1]
    grupos = []
    for qi, caixas in enumerate(achados):
        for (x, y, w, h) in caixas:
            cx, cy = x + w / 2, y + h / 2
            alvo = next((g for g in grupos if abs(cx - g["cx"]) < 0.06 * Ws and abs(cy - g["cy"]) < 0.06 * Ws and 0.5 < w / g["w"] < 2.0), None)
            if alvo is None:
                grupos.append({"cx": cx, "cy": cy, "w": w, "caixas": [(x, y, w, h)], "quadros": [qi]})
            elif qi not in alvo["quadros"]:
                alvo["caixas"].append((x, y, w, h))
                alvo["quadros"].append(qi)
                alvo["cx"], alvo["cy"], alvo["w"] = np.median([[b[0] + b[2] / 2, b[1] + b[3] / 2, b[2]] for b in alvo["caixas"]], axis=0)
    grupos = [g for g in grupos if len(g["caixas"]) >= max(3, 0.35 * len(quadros))]
    if not grupos:
        return None
    Hs = quadros[0].shape[0]
    for g in grupos:
        x, y, w, h = [int(v) for v in np.median(np.array(g["caixas"]), axis=0)]
        x, y = max(0, x), max(0, y)
        w, h = max(8, min(w, Ws - x)), max(8, min(h, Hs - y))
        minis = [cv2.resize(cv2.cvtColor(quadros[i][y:y + h, x:x + w], cv2.COLOR_BGR2GRAY), (48, 48), interpolation=cv2.INTER_AREA).astype(np.float32)
                 for i in g["quadros"]]
        g["vida"] = float(np.median([np.abs(minis[i + 1] - minis[i]).mean() for i in range(len(minis) - 1)])) if len(minis) > 1 else 0.0
    vivos = [g for g in grupos if g["vida"] >= 1.5]
    melhor = max(vivos or grupos, key=lambda g: (len(g["caixas"]), g["w"]))
    return tuple(float(v) for v in np.median(np.array(melhor["caixas"]), axis=0))


def caixa_da_camera(rosto, W, H):
    """Da caixa do rosto para a caixa da câmera inteira: 1,7 rosto para cada lado, 0,9 acima (a testa) e 0,7 abaixo (o ombro)."""
    fx, fy, fw, fh = rosto
    cx = fx + fw / 2
    esq, dir_ = max(0.0, cx - 1.7 * fw), min(float(W), cx + 1.7 * fw)
    topo, base = max(0.0, fy - 0.9 * fh), min(float(H), fy + 1.7 * fh)
    return [int(esq), int(topo), int(dir_ - esq), int(base - topo)]


def planejar(W, H, escala, quadros, achados, modo, camera):
    """Escolhe o enquadramento do trecho: {"modo", "camera", "rosto"}. Coordenadas em pixels do vídeo original."""
    if camera:
        return {"modo": "empilhado", "camera": camera, "rosto": None}
    if modo == "desfocado":
        return {"modo": "desfocado", "camera": None, "rosto": None}
    Ws = quadros[0].shape[1]
    grandes = [max([f for f in fs if f[2] >= GRANDE * Ws], key=lambda f: f[2], default=None) for fs in achados]
    if modo == "seguir" or (not modo and sum(g is not None for g in grandes) >= 0.5 * len(quadros)):
        caixas = [g for g in grandes if g is not None]
        rosto = np.median(np.array(caixas), axis=0) / escala if caixas else np.array([W / 2 - 100, H / 3, 200, 240])
        return {"modo": "seguir", "camera": None, "rosto": [float(v) for v in rosto]}
    pequenos = [[f for f in fs if f[2] < GRANDE * Ws] for fs in achados]
    r = rosto_parado(quadros, pequenos)
    if r is None:
        return {"modo": "desfocado", "camera": None, "rosto": None}
    rosto = [v / escala for v in r]
    caixa = caixa_da_camera(rosto, W, H)
    if rosto[2] >= 0.085 * W or caixa[2] >= 0.45 * W:  # a câmera é quase a tela inteira: não há conteúdo para pôr embaixo
        return {"modo": "seguir", "camera": None, "rosto": rosto}
    return {"modo": "empilhado", "camera": caixa, "rosto": rosto}


def geometria(pl, W, H):
    """Os retângulos de origem (em pixels do vídeo) e onde o título assenta, para cada enquadramento."""
    if pl["modo"] == "empilhado":
        x, y, w, h = pl["camera"]
        prop = min(1.8, max(1.35, w / float(h)))
        if w / float(h) > prop:   # larga demais: apara dos lados, em volta do rosto
            nw = h * prop
            centro = (pl["rosto"][0] + pl["rosto"][2] / 2) if pl["rosto"] else x + w / 2
            x, w = min(max(x, centro - nw / 2), x + w - nw), nw
        else:                      # alta demais: apara em cima e embaixo
            nh = w / prop
            centro = (pl["rosto"][1] + pl["rosto"][3] * 0.5) if pl["rosto"] else y + h / 2
            y, h = min(max(y, centro - nh * 0.45), y + h - nh), nh
        th = par(round(L / prop))
        bh = A - th
        gh, gw = float(H), H * L / float(bh)
        if gw > W:
            gw, gh = float(W), W * bh / float(L)
        gx, gy = (W - gw) / 2, (H - gh) / 2
        if x < gx + gw and x + w > gx and y < gy + gh and y + h > gy:  # a câmera cai dentro do recorte do conteúdo: afasta
            gx = min(W - gw, x + w) if (x + w / 2) < W / 2 else max(0.0, x - gw)
        return {"modo": "empilhado", "cam": (par(x), par(y), par(w), par(h)), "jogo": (par(gx), par(gy), par(gw), par(gh)),
                "th": th, "bh": bh, "emenda": th}
    if pl["modo"] == "seguir":
        if W * 16 <= H * 9:  # a origem já é mais estreita que 9:16: só apara em cima e embaixo
            ch = par(W * 16 / 9.0)
            return {"modo": "seguir", "corte": (0, par((H - ch) / 2), par(W), ch), "emenda": int(A * 0.14)}
        cw = par(H * 9 / 16.0)
        cx = (pl["rosto"][0] + pl["rosto"][2] / 2) if pl["rosto"] else W / 2
        return {"modo": "seguir", "corte": (par(min(max(0, cx - cw / 2), W - cw)), 0, cw, par(H)), "emenda": int(A * 0.14)}
    fh = min(A, int(L * H / float(W)))
    return {"modo": "desfocado", "emenda": max(150, (A - fh) // 2 - 70)}


def filtro_da_imagem(g):
    """A parte do filtro do ffmpeg que vai do vídeo original à tela 1080x1920 (sem título nem legenda)."""
    if g["modo"] == "empilhado":
        return ("[0:v]split=2[s1][s2];"
                "[s1]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos[top];"
                "[s2]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos[bot];"
                "[top][bot]vstack=inputs=2[base]" % (g["cam"][2], g["cam"][3], g["cam"][0], g["cam"][1], L, g["th"],
                                                     g["jogo"][2], g["jogo"][3], g["jogo"][0], g["jogo"][1], L, g["bh"]))
    if g["modo"] == "seguir":
        x, y, w, h = g["corte"]
        return "[0:v]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos[base]" % (w, h, x, y, L, A)
    return ("[0:v]split=2[s1][s2];"
            "[s1]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,scale=108:192,boxblur=5:2,scale=%d:%d,eq=brightness=-0.15[bg];"
            "[s2]scale=%d:%d:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]" % (L, A, L, A, L, A, L, A))


def previa(quadro, escala, pl, g, destino):
    """O quadro do meio com as caixas desenhadas: é por aqui que se confere o enquadramento antes de montar."""
    img = quadro.copy()
    def cx(c):
        x, y, w, h = [int(v * escala) for v in c]
        return (x, y), (x + w, y + h)
    if g["modo"] == "empilhado":
        cv2.rectangle(img, *cx(g["cam"]), (0, 200, 0), 3)
        cv2.rectangle(img, *cx(g["jogo"]), (230, 120, 0), 3)
    elif g["modo"] == "seguir":
        cv2.rectangle(img, *cx(g["corte"]), (0, 200, 0), 3)
    cv2.putText(img, g["modo"], (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
    gravar_imagem(destino, img)


# ---------- título e legenda ----------

def limpar(p):
    return re.sub(r"[\"“”]", "", p).strip()


def juntar_numeros(palavras):
    """O Whisper às vezes parte '209.8' em '209' e '.8': volta a ser um número só."""
    out = []
    for w in palavras:
        if out and re.match(r"^[.,]\d", w["w"]):
            out[-1] = {"w": out[-1]["w"] + w["w"], "s": out[-1]["s"], "e": w["e"]}
        else:
            out.append(w)
    return out


def grupos_de_legenda(palavras, est):
    grupos, atual = [], []
    for p in palavras:
        w = limpar(p["w"])
        if not w:
            continue
        txt = (w.upper() if est["maiusculas"] else w).rstrip(",.;:")
        if not txt:
            continue
        item = {"w": txt, "s": p["s"], "e": p["e"], "fim": bool(re.search(r"[.!?]$", w))}
        letras = sum(len(x["w"]) for x in atual) + len(txt)
        if atual and (len(atual) >= est["palavras_por_legenda"] or letras > est["letras_por_legenda"]
                      or p["s"] - atual[-1]["e"] > 0.5 or atual[-1]["fim"]):
            grupos.append(atual)
            atual = []
        atual.append(item)
    if atual:
        grupos.append(atual)
    for i, g in enumerate(grupos):
        proximo = grupos[i + 1][0]["s"] if i + 1 < len(grupos) else g[-1]["e"] + 0.6
        g[-1]["ate"] = min(proximo, g[-1]["e"] + 0.6)
    return grupos


def desenhar_legenda(grupo, ativo, est):
    tam = est["tamanho_legenda"]
    while True:
        f = fonte(tam, est["fonte_arquivo"])
        esp = f.getlength(" ")
        larguras = [f.getlength(p["w"]) for p in grupo]
        total = sum(larguras) + esp * (len(grupo) - 1)
        borda = max(6, tam // 10)
        if (total + 2 * borda) * 1.04 <= L - 2 * est["margem_lateral"] or tam <= 40:   # cabe na área segura (contorno incluso, 4% de folga)
            break
        tam -= 6
    img = Image.new("RGBA", (L, FAIXA), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x, y = (L - total) / 2, (FAIXA - tam * 1.25) / 2
    for i, p in enumerate(grupo):
        d.text((x, y), p["w"], font=f, fill=cor(est["cor_destaque"] if i == ativo else est["cor_legenda"]) + (255,),
               stroke_width=borda, stroke_fill=cor(est["cor_contorno"]) + (255,))
        x += larguras[i] + esp
    return img


def quadros_da_legenda(grupos, dur, est):
    """Os bytes RGBA de cada quadro da faixa de legendas, em ordem. O estado (grupo, palavra ativa) nunca volta, então basta guardar o último."""
    vazio = bytes(FAIXA * L * 4)
    ultimo_estado, ultimo = None, vazio
    for k in range(int(dur * FPS_LEGENDA) + 1):
        t = k / float(FPS_LEGENDA)
        estado = None
        for gi, g in enumerate(grupos):
            if g[0]["s"] - 0.03 <= t < g[-1]["ate"]:
                estado = (gi, max([i for i, p in enumerate(g) if p["s"] - 0.03 <= t] or [0]))
                break
        if estado != ultimo_estado:
            ultimo = vazio if estado is None else desenhar_legenda(grupos[estado[0]], estado[1], est).tobytes()
            ultimo_estado = estado
        yield ultimo


def desenhar_selo(titulo, emenda, est):
    """Uma camada 1080x1920 transparente com o título (e a marca). Fica parada o corte inteiro."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if est["titulo"] and titulo:
        texto = titulo.upper() if est["maiusculas"] else titulo
        tam = est["tamanho_titulo"]
        pessoal = selo_pessoal(est.get("selo", "caixa"))
        while True:
            f = (pessoal.fonte(tam) if pessoal else None) or fonte(tam, est["fonte_arquivo"])
            linhas, atual = [], ""
            for p in texto.split():
                tenta = (atual + " " + p).strip()
                if f.getlength(tenta) <= L - 200 or not atual:
                    atual = tenta
                else:
                    linhas.append(atual)
                    atual = p
            linhas.append(atual)
            if len(linhas) <= 2 or tam <= 40:
                break
            tam -= 4
        if pessoal:
            tag = pessoal.desenhar(linhas, tam, lambda t: fonte(t, est["fonte_arquivo"]))
            x0 = (L - tag.width) // 2
            y0 = int(min(max(emenda - tag.height / 2, 20), A - tag.height - 20))
            sombra = Image.new("RGBA", tag.size, (0, 0, 0, 0))
            sombra.putalpha(tag.getchannel("A").point(lambda v: v * 120 // 255))
            img.alpha_composite(sombra, (x0 + 10, y0 + 12))
            img.alpha_composite(tag, (x0, y0))
        else:
            alt_linha = int(tam * 1.28)
            larg, alt = int(max(f.getlength(x) for x in linhas)) + 72, alt_linha * len(linhas) + 40
            x0, y0 = (L - larg) // 2, int(min(max(emenda - alt / 2, 20), A - alt - 20))
            d.rounded_rectangle((x0 + 8, y0 + 8, x0 + larg + 8, y0 + alt + 8), radius=22, fill=(0, 0, 0, 110))
            d.rounded_rectangle((x0, y0, x0 + larg, y0 + alt), radius=22, fill=cor(est["cor_titulo_fundo"]) + (255,))
            for i, linha in enumerate(linhas):
                d.text((x0 + (larg - f.getlength(linha)) / 2, y0 + 14 + i * alt_linha), linha, font=f, fill=cor(est["cor_titulo_texto"]) + (255,))
    if est["marca"]:
        f = fonte(38, est["fonte_arquivo"])
        d.text(((L - f.getlength(est["marca"])) / 2, A - 96), est["marca"], font=f, fill=(255, 255, 255, 200), stroke_width=3, stroke_fill=(0, 0, 0, 220))
    return img


# ---------- a montagem ----------

def montar(trecho, t0, dur, g, grupos, titulo, est, saida, selo_png):
    """Um ffmpeg só. Entradas: 0 o trecho, 1 a faixa de legendas (vem do Python), 2 o selo com o título, 3 a barra de progresso."""
    entradas = ["-ss", "%.3f" % t0, "-t", "%.3f" % dur, "-i", str(trecho),
                "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (L, FAIXA), "-r", str(FPS_LEGENDA), "-i", "-"]
    capy = int(min(max(A * est["altura_legenda"] - FAIXA / 2, 0), A - FAIXA))
    partes = [filtro_da_imagem(g), "[base][1:v]overlay=0:%d:format=auto:eof_action=pass[v1]" % capy]
    ultimo, proximo = "v1", 2
    if selo_png is not None:
        entradas += ["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % dur, "-i", str(selo_png)]
        partes.append("[%s][%d:v]overlay=0:0:format=auto:eof_action=pass[v%d]" % (ultimo, proximo, proximo))
        ultimo, proximo = "v%d" % proximo, proximo + 1
    if est["barra"]:
        entradas += ["-f", "lavfi", "-i", "color=c=0x%s:s=%dx12:r=%d:d=%.3f" % (est["cor_destaque"].lstrip("#"), L, FPS, dur)]
        partes.append("[%s][%d:v]overlay=x='-w+w*t/%.3f':y=%d:eof_action=pass[v%d]" % (ultimo, proximo, dur, A - 12, proximo))
        ultimo = "v%d" % proximo
    partes.append("[0:a]afade=t=in:d=0.04,afade=t=out:st=%.3f:d=0.12,loudnorm=I=%d:TP=-1.5:LRA=11,aresample=48000[a]" % (max(0.0, dur - 0.12), est["volume"]))
    cmd = [comum.ffmpeg(), "-v", "error", "-y"] + entradas + ["-filter_complex", ";".join(partes), "-map", "[%s]" % ultimo, "-map", "[a]"] + \
          comum.encoder_de_video() + ["-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", "%.3f" % dur, str(saida)]
    log = Path(str(saida) + ".log")
    with open(log, "wb") as erro:
        enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=erro)
        try:
            for q in quadros_da_legenda(grupos, dur, est):
                enc.stdin.write(q)
            enc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        enc.wait()
    ok = enc.returncode == 0 and Path(saida).exists()
    if ok:
        log.unlink(missing_ok=True)
    else:
        print("    ffmpeg disse:\n%s" % log.read_text(encoding="utf-8", errors="replace")[-1500:])
    return ok


def folha_de_contato(video, dur, destino):
    """Seis quadros do corte lado a lado, para olhar antes de dizer que está pronto."""
    quadros = []
    for i in range(6):
        r = subprocess.run([comum.ffmpeg(), "-v", "error", "-ss", "%.2f" % (dur * (i + 0.5) / 6), "-i", str(video), "-frames:v", "1",
                            "-vf", "scale=360:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        if r.stdout:
            quadros.append(Image.open(io.BytesIO(r.stdout)).convert("RGB"))
    if quadros:
        folha = Image.new("RGB", (360 * len(quadros), quadros[0].height))
        for i, q in enumerate(quadros):
            folha.paste(q, (360 * i, 0))
        folha.save(str(destino), quality=88)


# ---------- o programa ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("--so", type=int, default=0, help="só o momento com este número")
    ap.add_argument("--estilo", default=None, choices=list(estilo.carregar_catalogo()["kits"]), help="um kit do catálogo (sem isso vale o do perfil)")
    ap.add_argument("--modo", default="", choices=["", "empilhado", "seguir", "desfocado"])
    ap.add_argument("--camera", default="", help="a caixa da câmera na tela original: x,y,largura,altura")
    ap.add_argument("--cookies", default="")
    a = ap.parse_args()
    pasta = Path(a.pasta)
    info = comum.ler_json(pasta / "info.json")
    dado = comum.ler_json(pasta / "momentos-conferidos.json")
    if not info or not dado:
        sys.exit("Rode antes o ouvir.py e o conferir.py nessa pasta.")
    est = estilo.resolver(a.estilo)
    est.update(comum.ler_json(pasta / "estilo.json", {}))
    estilo.fechar(est)
    print("estilo: %s, fonte %s%s" % (est["kit"], est["fonte"], "" if est["fonte_arquivo"] else " (não achei o arquivo: uso a fonte do sistema; rode o preparar.py)"), flush=True)
    audio_da_live = None
    if not info.get("arquivo"):
        audio_da_live = next((p for p in pasta.glob("audio.*") if p.suffix not in (".part", ".ytdl")), None)
    lingua = comum.ler_json(pasta / "transcricao.json").get("lingua")
    trechos, cortes = pasta / "trechos", pasta / "cortes"
    trechos.mkdir(exist_ok=True)
    cortes.mkdir(exist_ok=True)
    cron = comum.Cronometro(pasta)
    escolhidos = [m for m in dado["momentos"] if (m["n"] == a.so if a.so else m.get("manter"))]
    if not escolhidos:
        sys.exit("Nenhum momento marcado para o corte.")
    forcada = [int(v) for v in a.camera.split(",")] if a.camera else None
    rostos = Rostos()
    cron.comeca("cortar")
    feitos = comum.ler_json(cortes / "cortes.json", [])

    # primeira volta: pega o trecho, alinha e escolhe o enquadramento de todos, para os cortes da mesma live concordarem
    prontos = []
    for m in escolhidos:
        n = m["n"]
        print("momento %d: %s a %s (%s)" % (n, m["inicio"], m["fim"], m.get("titulo", "")), flush=True)
        trecho, pedido = obter_trecho(info, trechos, n, m["inicio_s"], m["fim_s"], a.cookies)
        comeco, som, certeza = alinhar(trecho, audio_da_live, pedido)
        dur = m["fim_s"] - m["inicio_s"]
        t0 = m["inicio_s"] - comeco
        if t0 < 0 or t0 + dur > len(som) / comum.TAXA + 0.5:
            t0, certeza = min(MARGEM, m["inicio_s"]), 0.0
        print("    trecho pronto; começa em %s (%s)" % (comum.relogio(comeco, True),
              "som conferido" if certeza >= 6 else ("tempo pedido" if audio_da_live is None else "sem conferir pelo som")), flush=True)
        W, H, escala, quadros, achados = amostrar(trecho, t0, dur, rostos, 0.5 if dur <= 75 else 1.0)
        if not quadros:
            sys.exit("Não consegui ler o vídeo do trecho %d. A fonte tem imagem? (só áudio não vira corte vertical)" % n)
        pl = planejar(W, H, escala, quadros, achados, a.modo, forcada)
        prontos.append({"m": m, "trecho": trecho, "t0": t0, "dur": dur, "som": som, "pl": pl, "W": W, "H": H, "escala": escala,
                        "meio": quadros[len(quadros) // 2]})
    caixas = [p["pl"]["camera"] for p in prontos if p["pl"]["modo"] == "empilhado"]
    if caixas and not forcada and not a.modo:  # um trecho sem rosto, de uma live que tem câmera: usa o lugar dela
        comum_ = [int(v) for v in np.median(np.array(caixas), axis=0)]
        for p in prontos:
            if p["pl"]["modo"] == "desfocado":
                p["pl"] = {"modo": "empilhado", "camera": comum_, "rosto": None}
    camera = {}
    for p in prontos:
        p["g"] = geometria(p["pl"], p["W"], p["H"])
        previa(p["meio"], p["escala"], p["pl"], p["g"], trechos / ("%02d-camera.jpg" % p["m"]["n"]))
        camera[str(p["m"]["n"])] = p["pl"]
    comum.escrever_json(pasta / "camera.json", camera)

    # segunda volta: as palavras e a montagem
    for p in prontos:
        m, n = p["m"], p["m"]["n"]
        a0 = int(p["t0"] * comum.TAXA)
        frases, _ = comum.transcrever(p["som"][a0:a0 + int(p["dur"] * comum.TAXA)], lingua=lingua, palavras=True)
        palavras = juntar_numeros([w for s in frases for w in s.get("p", [])])
        grupos = grupos_de_legenda(palavras, est)
        base = "%02d-%s" % (n, comum.slug(m.get("titulo", ""), 40) if m.get("titulo") else "corte")
        saida = cortes / (base + ".mp4")
        selo = desenhar_selo(m.get("titulo", ""), p["g"]["emenda"], est)
        selo_png = None
        if est["titulo"] and m.get("titulo") or est["marca"]:
            selo_png = trechos / ("%02d-selo.png" % n)
            selo.save(str(selo_png))
        if not montar(p["trecho"], p["t0"], p["dur"], p["g"], grupos, m.get("titulo", ""), est, saida, selo_png):
            sys.exit("O ffmpeg não fechou o corte %d." % n)
        folha_de_contato(saida, p["dur"], cortes / (base + "-folha.jpg"))
        link = ""
        if info.get("link"):
            link = info["link"] + ("&" if "?" in info["link"] else "?") + "t=%ds" % int(m["inicio_s"])
        (cortes / (base + ".txt")).write_text(
            "TÍTULO\n%s\n\nLEGENDA DO POST\n%s\n\nHASHTAGS\n%s\n\nDE ONDE VEIO\n%s, %s a %s\n%s\n\nO QUE É DITO\n%s\n" % (
                m.get("titulo", ""), m.get("legenda", ""), " ".join(m.get("hashtags", [])), info.get("canal") or info.get("titulo"),
                m["inicio"], m["fim"], link or info.get("arquivo", ""), " ".join(w["w"] for w in palavras)), encoding="utf-8")
        feitos = [f for f in feitos if f["n"] != n]
        feitos.append({"n": n, "arquivo": saida.name, "titulo": m.get("titulo", ""), "inicio": m["inicio"], "fim": m["fim"],
                       "duracao": round(p["dur"], 1), "modo": p["pl"]["modo"], "nota": m.get("nota"), "link": link})
        print("    corte pronto: %s (%.0f s, %s, %d palavras)" % (saida.name, p["dur"], p["pl"]["modo"], len(palavras)), flush=True)
    comum.escrever_json(cortes / "cortes.json", sorted(feitos, key=lambda f: f["n"]))
    levou = cron.termina()
    print("\n%d cortes em %s: %s" % (len(prontos), comum.duracao_falada(levou), cortes))
    print("Abra cada NN-...-folha.jpg e veja: o enquadramento, o título legível, a legenda na palavra certa.")


if __name__ == "__main__":
    main()
