"""Base das ferramentas do garimpo: ambiente próprio, ffmpeg, yt-dlp, Whisper, áudio e tempos.

Nada aqui desenha ou corta vídeo. Quem corta é o cortar.py, e quem decide o que cortar é o Claude lendo.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CASA = Path(os.environ.get("GARIMPO_CASA", str(Path.home() / ".garimpo")))
AMBIENTE = CASA / "ambiente"
MODELOS = CASA / "modelos"
SKILL = Path(__file__).resolve().parent.parent
TAXA = 16000  # amostras por segundo de tudo que se analisa
WINDOWS = os.name == "nt"
PYTHON = "python" if WINDOWS else "python3"

# Consoles e arquivos do Windows usam uma página de código antiga: aqui tudo é UTF-8, inclusive os filhos.
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---------- ambiente ----------

def python_do_ambiente():
    return AMBIENTE / ("Scripts/python.exe" if WINDOWS else "bin/python3")


def no_ambiente():
    """Reexecuta o comando atual dentro do Python do garimpo (se ainda não estiver nele)."""
    py = python_do_ambiente()
    if not py.exists():
        sys.exit('Falta preparar o computador. Rode: %s "%s"' % (PYTHON, SKILL / "ferramentas" / "preparar.py"))
    fora = Path(sys.prefix).resolve() != AMBIENTE.resolve()
    if fora or (WINDOWS and not sys.flags.utf8_mode):
        sys.exit(subprocess.call([str(py)] + sys.argv))


def chip_apple():
    return sys.platform == "darwin" and platform.machine() == "arm64"


def motor():
    """mlx-whisper no Mac com chip Apple, faster-whisper no resto. GARIMPO_MOTOR=mlx|faster força um."""
    pedido = os.environ.get("GARIMPO_MOTOR", "")
    if pedido in ("mlx", "faster"):
        return pedido
    return "mlx" if chip_apple() else "faster"


def modelo_padrao():
    """GARIMPO_MODELO troca o modelo do Whisper (ex.: tiny, base, small, large-v3-turbo)."""
    pedido = os.environ.get("GARIMPO_MODELO", "")
    if pedido:
        return pedido
    return "large-v3-turbo" if motor() == "mlx" else "small"


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg não encontrado. Rode o preparar.py de novo.")


def ytdlp(*args, cookies="", captura=True, tempo=None):
    """yt-dlp do ambiente. O YouTube pede um runtime de JavaScript: o ambiente traz o deno ao lado do Python."""
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--ffmpeg-location", ffmpeg()]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    cmd += list(args)
    amb = dict(os.environ, PATH=str(python_do_ambiente().parent) + os.pathsep + os.environ.get("PATH", ""))
    try:
        return subprocess.run(cmd, capture_output=captura, text=True, encoding="utf-8", errors="replace", timeout=tempo, env=amb)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, e.stdout or "", "tempo esgotado")


def encoder_de_video():
    saida = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stdout
    if "libx264" in saida:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"]
    if "h264_videotoolbox" in saida:
        return ["-c:v", "h264_videotoolbox", "-b:v", "9M"]
    return ["-c:v", "mpeg4", "-q:v", "3"]


# ---------- tempo e arquivos ----------

def segundos(t):
    """'1:02:03', '62:03' ou 3723 viram segundos."""
    if isinstance(t, (int, float)):
        return float(t)
    s = 0.0
    for p in str(t).strip().split(":"):
        s = s * 60 + float(p)
    return s


def relogio(s, decimos=False):
    s = max(0.0, float(s))
    h, r = divmod(int(s), 3600)
    m, seg = divmod(r, 60)
    base = "%d:%02d:%02d" % (h, m, seg)
    return base + (".%d" % int((s % 1) * 10)) if decimos else base


def duracao_falada(s):
    s = int(round(s))
    h, r = divmod(s, 3600)
    m, seg = divmod(r, 60)
    if h:
        return "%d h %02d min" % (h, m)
    if m:
        return "%d min %02d s" % (m, seg)
    return "%d s" % seg


def ler_json(p, padrao=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else padrao


def escrever_json(p, dado):
    Path(p).write_text(json.dumps(dado, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(t, limite=50):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:limite] or "sem-nome"


def duracao_da_midia(arq):
    """Duração em segundos de qualquer áudio ou vídeo (lida do próprio ffmpeg)."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(arq)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


class Cronometro:
    """Quanto tempo cada passo levou, guardado em tempos.json ao lado da live."""

    def __init__(self, pasta):
        self.arquivo = Path(pasta) / "tempos.json"
        self.dado = ler_json(self.arquivo, {})
        self._nome = self._t = None

    def comeca(self, nome):
        self._nome, self._t = nome, time.time()

    def termina(self):
        self.dado[self._nome] = round(time.time() - self._t, 1)
        escrever_json(self.arquivo, self.dado)
        return self.dado[self._nome]


# ---------- áudio ----------

def audio_em_blocos(arquivo, inicio=None, duracao=None, bloco=TAXA * 30):
    """Decodifica áudio ou vídeo para 16 kHz mono e entrega em pedaços (numpy int16)."""
    import numpy as np
    cmd = [ffmpeg(), "-v", "error", "-nostdin"]
    if inicio is not None:
        cmd += ["-ss", "%.3f" % max(0.0, inicio)]
    cmd += ["-i", str(arquivo)]
    if duracao is not None:
        cmd += ["-t", "%.3f" % duracao]
    cmd += ["-vn", "-ac", "1", "-ar", str(TAXA), "-f", "s16le", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            dado = p.stdout.read(bloco * 2)
            if not dado:
                break
            yield np.frombuffer(dado[: len(dado) // 2 * 2], dtype=np.int16)
    finally:
        p.stdout.close()
        p.wait()


def audio(arquivo, inicio=None, duracao=None):
    import numpy as np
    partes = list(audio_em_blocos(arquivo, inicio, duracao))
    return np.concatenate(partes) if partes else np.zeros(0, dtype=np.int16)


def volume_por_segundo(arquivo):
    """Nível (dB) de cada segundo da gravação, contado no relógio dela: nenhum segundo é pulado."""
    import numpy as np
    niveis, resto = [], np.zeros(0, dtype=np.int16)
    for pedaco in audio_em_blocos(arquivo, bloco=TAXA * 60):
        junto = np.concatenate([resto, pedaco])
        n = len(junto) // TAXA * TAXA
        if n:
            x = junto[:n].astype(np.float32) / 32768.0
            rms = np.sqrt((x.reshape(-1, TAXA) ** 2).mean(axis=1) + 1e-10)
            niveis.extend((20 * np.log10(rms)).round(1).tolist())
        resto = junto[n:]
    if len(resto) >= TAXA // 2:
        x = resto.astype(np.float32) / 32768.0
        niveis.append(round(float(20 * np.log10(np.sqrt((x ** 2).mean() + 1e-10))), 1))
    return niveis


def mediana_movel(x, meia):
    """Mediana de uma janela de 2*meia+1 em volta de cada ponto (as pontas repetem o valor da borda)."""
    import numpy as np
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return x
    janelas = np.lib.stride_tricks.sliding_window_view(np.pad(x, meia, mode="edge"), 2 * meia + 1)
    return np.median(janelas, axis=1)


def agrupar(marcas, vao, minimo):
    """Índices ligados -> lista de (primeiro, último), juntando vãos de até `vao` e jogando fora trechos menores que `minimo`."""
    import numpy as np
    eventos = []
    for i in np.flatnonzero(marcas):
        if eventos and i - eventos[-1][1] <= vao:
            eventos[-1][1] = int(i)
        else:
            eventos.append([int(i), int(i)])
    return [(a, b) for a, b in eventos if b - a + 1 >= minimo]


# ---------- Whisper ----------

_MODELOS_FASTER = {}


def transcrever(amostras, lingua=None, palavras=False, modelo=None):
    """Whisper neste computador. amostras: numpy int16 a 16 kHz.
    Devolve (frases, língua). Cada frase é {"s", "e", "t"} e, com palavras=True, também "p": [{"w", "s", "e"}]."""
    import numpy as np
    som = amostras.astype(np.float32) / 32768.0
    modelo = modelo or modelo_padrao()
    if motor() == "mlx":
        try:
            import mlx_whisper
            repo = modelo if "/" in modelo else "mlx-community/whisper-" + modelo
            r = mlx_whisper.transcribe(som, path_or_hf_repo=repo, language=lingua, word_timestamps=palavras,
                                       condition_on_previous_text=False, verbose=None)
            frases = []
            for s in r["segments"]:
                item = {"s": float(s["start"]), "e": float(s["end"]), "t": s["text"].strip()}
                if palavras:
                    item["p"] = [{"w": w["word"].strip(), "s": float(w["start"]), "e": float(w["end"])} for w in s.get("words", [])]
                frases.append(item)
            return frases, r.get("language") or lingua
        except ImportError:
            pass
    from faster_whisper import WhisperModel
    if modelo not in _MODELOS_FASTER:
        # sempre no processador: placa de vídeo exige bibliotecas extras que a maioria dos computadores não tem
        _MODELOS_FASTER[modelo] = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=max(4, (os.cpu_count() or 8) // 2))
    achados, info = _MODELOS_FASTER[modelo].transcribe(som, language=lingua, word_timestamps=palavras,
                                                       condition_on_previous_text=False, vad_filter=True)
    frases = []
    for s in achados:
        item = {"s": float(s.start), "e": float(s.end), "t": s.text.strip()}
        if palavras:
            item["p"] = [{"w": w.word.strip(), "s": float(w.start), "e": float(w.end)} for w in (s.words or [])]
        frases.append(item)
    return frases, info.language
