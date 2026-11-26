#!/usr/bin/env python3
"""Prepara o computador uma vez: um Python só do garimpo, com tudo que as outras ferramentas usam.

Uso (no Windows o comando é python no lugar de python3):
  python3 preparar.py            instala o que falta e testa
  python3 preparar.py --conferir só diz o que já está instalado
  python3 preparar.py --leve     tudo menos o Whisper (para testar o resto)

Instala dentro de ~/.garimpo (ou GARIMPO_CASA), sem tocar no resto do computador:
  yt-dlp + deno   baixa a live (o YouTube exige um runtime de JavaScript)
  OpenCV, NumPy   acham a câmera do streamer
  Pillow          desenha título e legenda
  ffmpeg          só se o computador não tiver
  Whisper         mlx-whisper no Mac com chip Apple, faster-whisper no resto
Baixa também o modelo de rostos (YuNet) e as fontes das legendas (as do catálogo em referencias/estilos.json, todas de licença livre).
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import venv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402
import estilo  # noqa: E402

TEXTO = dict(text=True, encoding="utf-8", errors="replace")
ROSTO = ("face_detection_yunet_2023mar.onnx", [
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
])
SE_FALTAR_PYTHON = ("\nInstale o Python 3.12 e rode de novo. No Mac: brew install python@3.12. "
                    "No Windows: winget install -e --id Python.Python.3.12.")


def versao_de(exe):
    r = subprocess.run([str(exe), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True, **TEXTO)
    try:
        a, b = r.stdout.strip().split(".")
        return int(a), int(b)
    except Exception:
        return (0, 0)


def serve(v):
    """Os pacotes de hoje (yt-dlp, Whisper, OpenCV) têm rodas prontas do Python 3.10 ao 3.13."""
    return (3, 10) <= tuple(v) <= (3, 13)


def baixar(nome, links, minimo):
    destino = comum.MODELOS / nome
    if destino.exists() and destino.stat().st_size >= minimo:
        return True
    for link in links:
        try:
            req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
            dado = urllib.request.urlopen(req, timeout=60).read()
            if len(dado) >= minimo:
                destino.write_bytes(dado)
                return True
        except Exception:
            continue
    return False


def criar_ambiente():
    """Usa o Python deste computador se servir; senão outro que já exista; senão busca um dentro da pasta do garimpo."""
    if serve(sys.version_info[:2]):
        venv.create(str(comum.AMBIENTE), with_pip=True)
        return "o Python %d.%d deste computador" % sys.version_info[:2]
    candidatos = []
    for nome in ("python3.12", "python3.13", "python3.11", "python3.10"):
        candidatos += [shutil.which(nome)] + [str(Path(d) / nome) for d in ("/opt/homebrew/bin", "/usr/local/bin")]
    if comum.WINDOWS and shutil.which("py"):
        for v in ("3.12", "3.13", "3.11", "3.10"):
            r = subprocess.run(["py", "-" + v, "-c", "import sys; print(sys.executable)"], capture_output=True, **TEXTO)
            if r.returncode == 0:
                candidatos.append(r.stdout.strip())
    for exe in candidatos:
        if exe and Path(exe).exists() and serve(versao_de(exe)):
            subprocess.run([exe, "-m", "venv", str(comum.AMBIENTE)], check=True)
            return exe
    # nenhum serve: o uv busca um Python 3.12 e guarda na pasta do garimpo
    partida = comum.CASA / "partida"
    if not partida.exists():
        venv.create(str(partida), with_pip=True)
    bin_ = partida / ("Scripts" if comum.WINDOWS else "bin")
    py = bin_ / ("python.exe" if comum.WINDOWS else "python3")
    r = subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip", "uv"], capture_output=True, **TEXTO)
    if r.returncode:
        sys.exit("Não consegui instalar o uv, que busca um Python novo:\n" + r.stderr[-1200:] + SE_FALTAR_PYTHON)
    amb = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(comum.CASA / "python"))
    r = subprocess.run([str(bin_ / ("uv.exe" if comum.WINDOWS else "uv")), "venv", "--seed", "--python", "3.12", str(comum.AMBIENTE)],
                       capture_output=True, env=amb, **TEXTO)
    if r.returncode:
        sys.exit("Não consegui buscar o Python 3.12:\n" + r.stderr[-1200:] + SE_FALTAR_PYTHON)
    return "um Python 3.12 só do garimpo (este computador tem o %d.%d)" % sys.version_info[:2]


def pip(*pacotes):
    r = subprocess.run([str(comum.python_do_ambiente()), "-m", "pip", "install", "-q", "--upgrade"] + list(pacotes),
                       capture_output=True, **TEXTO)
    if r.returncode:
        sys.exit("Não consegui instalar %s:\n%s" % (" ".join(pacotes), r.stderr[-1500:]))


def tem(modulo):
    return subprocess.run([str(comum.python_do_ambiente()), "-c", "import " + modulo], capture_output=True).returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conferir", action="store_true")
    ap.add_argument("--leve", action="store_true", help="não instala o Whisper")
    a = ap.parse_args()
    whisper = "mlx_whisper" if comum.motor() == "mlx" else "faster_whisper"
    if a.conferir:
        ok = comum.python_do_ambiente().exists()
        print("ambiente:", "ok" if ok else "falta")
        for m in ("yt_dlp", "cv2", "numpy", "PIL", whisper):
            print("  %-15s %s" % (m, "ok" if ok and tem(m) else "falta"))
        print("  %-15s %s" % ("ffmpeg", "ok" if shutil.which("ffmpeg") or (ok and tem("imageio_ffmpeg")) else "falta"))
        return
    t0 = time.time()
    comum.MODELOS.mkdir(parents=True, exist_ok=True)
    py = comum.python_do_ambiente()
    if py.exists() and not serve(versao_de(py)):
        shutil.rmtree(str(comum.AMBIENTE))  # criado com um Python velho ou novo demais
    if not py.exists():
        print("1/5 criando o ambiente em", comum.AMBIENTE)
        print("    com", criar_ambiente())
    else:
        print("1/5 o ambiente já existe")
    print("2/5 instalando yt-dlp, deno, OpenCV, NumPy e Pillow")
    pip("pip")
    pip("yt-dlp[default,curl-cffi]", "deno", "opencv-python-headless", "numpy", "pillow")  # curl-cffi: o Kick só responde a navegador
    if not shutil.which("ffmpeg"):
        print("    este computador não tem ffmpeg: instalando um só para o garimpo")
        pip("imageio-ffmpeg")
    print("3/5 modelo de rostos e fontes das legendas")
    if not baixar(ROSTO[0], ROSTO[1], 100000):
        print("    sem o modelo de rostos: o corte usa o detector simples do OpenCV")
    for f in estilo.carregar_catalogo()["fontes"].values():
        if f.get("url") and not baixar(f["arquivo"], [f["url"]], 20000):
            print("    sem a fonte %s: os kits que usam ela caem numa fonte do sistema" % f["nome"])
    if a.leve:
        print("PRONTO (leve, sem Whisper) em %s." % comum.duracao_falada(time.time() - t0))
        return
    print("4/5 instalando o Whisper (%s)" % whisper.replace("_", "-"))
    pip(whisper.replace("_", "-"))
    print("5/5 testando o Whisper (na primeira vez ele baixa o modelo %s)" % comum.modelo_padrao())
    teste = ("import sys; sys.path.insert(0, %r); import comum, numpy as np; "
             "comum.transcrever(np.zeros(comum.TAXA * 2, dtype=np.int16), lingua='pt'); print('whisper ok')"
             % str(Path(__file__).resolve().parent))
    r = subprocess.run([str(py), "-c", teste], capture_output=True, **TEXTO)
    if "whisper ok" not in r.stdout:
        sys.exit("O Whisper não rodou:\n" + r.stderr[-1500:] + (
            "\nNo Windows, instale o Microsoft Visual C++ Redistributable (https://aka.ms/vs/17/release/vc_redist.x64.exe)."
            if comum.WINDOWS else ""))
    print("PRONTO em %s. Modelo: %s." % (comum.duracao_falada(time.time() - t0), comum.modelo_padrao()))


if __name__ == "__main__":
    main()
