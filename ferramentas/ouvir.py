#!/usr/bin/env python3
"""Ouve uma gravação inteira no seu computador e deixa tudo pronto para garimpar.

Uso:
  python3 ouvir.py <link ou arquivo> [--pasta garimpos] [--lingua pt] [--cookies chrome] [--sem-chat]
                   [--canal "Nome"] [--janela 12] [--modelo small]

A fonte pode ser um link (YouTube, Twitch, Kick: só o áudio é baixado) ou um arquivo de vídeo ou áudio do computador.

Escreve em <pasta>/<id>/:
  info.json          título, canal, duração, link ou arquivo
  transcricao.json   cada frase com início e fim, e o volume de cada segundo
  sinais.json        os picos de volume e, se houver replay, os picos do chat
  janelas/           a transcrição em janelas de texto, com as marcas ALTO e CHAT
  resumo.md          os números da gravação e os maiores picos
  tempos.json        quanto tempo cada passo levou

A transcrição é salva a cada bloco: se o computador dormir ou o terminal fechar, rodar de novo continua de onde parou.
"""
import argparse
import json
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402

comum.no_ambiente()
import numpy as np  # noqa: E402

BLOCO = 600  # segundos de áudio que o Whisper recebe por vez
FOLGA = 20   # o corte entre dois blocos cai no segundo mais quieto desta folga, para não partir uma frase


def eh_arquivo(fonte):
    try:
        return Path(fonte).expanduser().is_file()
    except OSError:
        return False


def ler_fonte(fonte, pasta, cookies, canal):
    if eh_arquivo(fonte):
        arq = Path(fonte).expanduser().resolve()
        info = {"id": comum.slug(arq.stem), "titulo": arq.stem, "canal": canal, "duracao": comum.duracao_da_midia(arq),
                "link": "", "arquivo": str(arq), "site": "local", "lingua": None}
    else:
        r = comum.ytdlp("-J", "--skip-download", fonte, cookies=cookies)
        if r.returncode:
            sys.exit("Não consegui ler o link:\n" + r.stderr[-1200:] +
                     "\nSe o site pede login ou a live tem restrição de idade, rode de novo com --cookies chrome")
        d = json.loads(r.stdout)
        info = {"id": d.get("id"), "titulo": d.get("title"), "canal": canal or d.get("channel") or d.get("uploader") or "",
                "duracao": d.get("duration"), "link": d.get("webpage_url") or fonte, "arquivo": "", "site": d.get("extractor_key"),
                "lingua": (d.get("language") or "")[:2] or None, "ao_vivo": d.get("live_status")}
        if info["ao_vivo"] == "is_live":
            sys.exit("Essa live ainda está no ar. Espere ela terminar e o replay aparecer.")
    destino = Path(pasta) / re.sub(r"[^A-Za-z0-9_-]", "_", str(info["id"]))
    destino.mkdir(parents=True, exist_ok=True)
    comum.escrever_json(destino / "info.json", info)
    return info, destino


def audio_da_fonte(info, destino, cookies):
    """O arquivo que vai ser ouvido. Link: só o áudio (nunca o formato 'drc', que achata os picos que se procuram)."""
    if info["arquivo"]:
        return Path(info["arquivo"]), False
    prontos = [p for p in destino.glob("audio.*") if p.suffix not in (".part", ".ytdl")]
    if prontos:
        return prontos[0], False
    r = comum.ytdlp("-f", "ba[abr<=70][format_id!*=drc][protocol^=http]/ba[format_id!*=drc][protocol^=http]/ba[format_id!*=drc]/ba/w",
                    "-o", str(destino / "audio.%(ext)s"), info["link"], cookies=cookies)
    prontos = [p for p in destino.glob("audio.*") if p.suffix not in (".part", ".ytdl")]
    if r.returncode or not prontos:
        sys.exit("Não consegui baixar o áudio:\n" + r.stderr[-1200:])
    return prontos[0], True


# ---------- chat ----------

def baixar_chat(info, destino, cookies, limite):
    """YouTube e Twitch guardam o replay do chat de algumas lives. Melhor esforço: nunca para o resto."""
    if any(p.suffix == ".json" and p.name != "chat-contagem.json" for p in destino.glob("chat*")):
        return
    lingua = {"Youtube": "live_chat", "TwitchVod": "rechat"}.get(info.get("site") or "", "live_chat")
    comum.ytdlp("--skip-download", "--write-subs", "--sub-langs", lingua, "-o", str(destino / "chat"),
                info["link"], cookies=cookies, tempo=limite)


def tempos_do_chat(destino):
    """Segundo da live em que cada mensagem do chat apareceu, de qualquer arquivo de chat que o yt-dlp deixou."""
    tempos = []
    for arq in sorted(destino.glob("chat*")):
        if arq.suffix == ".md" or arq.name == "chat-contagem.json":
            continue
        try:
            texto = arq.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "rechat" in arq.name:  # Twitch: uma lista JSON
            try:
                tempos += [float(m.get("content_offset_seconds", 0)) for m in json.loads(texto)]
            except Exception:
                pass
            continue
        for linha in texto.splitlines():  # YouTube: um JSON por linha
            m = re.search(r'"videoOffsetTimeMsec":\s*"?(-?\d+)', linha)
            if m and int(m.group(1)) >= 0 and '"addChatItemAction"' in linha:
                tempos.append(int(m.group(1)) / 1000.0)
    return sorted(tempos)


# ---------- transcrição ----------

def pontos_de_corte(volume, passo=BLOCO, folga=FOLGA):
    """Segundos em que a transcrição é partida: perto de cada múltiplo de `passo`, no segundo mais quieto."""
    total = len(volume)
    cortes, t = [0.0], float(passo)
    while t < total - passo / 4:
        a, b = int(max(cortes[-1] + 60, t - folga)), int(min(total, t + folga))
        k = a + int(np.argmin(volume[a:b])) if b > a else int(t)
        cortes.append(k + 0.5)
        t = k + passo
    return cortes


def transcrever_tudo(arq, volume, destino, lingua, modelo):
    cortes = pontos_de_corte(volume)
    parcial = comum.ler_json(destino / "transcricao-parcial.json", {})
    if parcial.get("cortes") != cortes or parcial.get("modelo") != (modelo or comum.modelo_padrao()):
        parcial = {"cortes": cortes, "modelo": modelo or comum.modelo_padrao(), "feitos": 0, "frases": [], "lingua": lingua}
    lingua = lingua or parcial.get("lingua")
    total = len(volume)
    if parcial["feitos"]:
        print("    retomando do bloco %d de %d" % (parcial["feitos"] + 1, len(cortes)), flush=True)
    for i in range(parcial["feitos"], len(cortes)):
        a = cortes[i]
        b = cortes[i + 1] if i + 1 < len(cortes) else None
        amostras = comum.audio(arq, inicio=a, duracao=(b - a) if b else None)
        if len(amostras):
            achadas, achada = comum.transcrever(amostras, lingua=lingua, modelo=modelo or None)
            lingua = lingua or achada
            for s in achadas:
                if s["t"]:
                    parcial["frases"].append({"s": round(a + s["s"], 2), "e": round(a + s["e"], 2), "t": s["t"]})
        parcial.update({"feitos": i + 1, "lingua": lingua})
        comum.escrever_json(destino / "transcricao-parcial.json", parcial)
        print("    ouvido até %s de %s" % (comum.relogio(b or total), comum.relogio(total)), flush=True)
    return parcial["frases"], lingua


# ---------- sinais ----------

def sinais_de_volume(volume):
    """Onde o falante ficou muito mais alto que os minutos em volta. Devolve (lista de picos, limite em dB)."""
    sobra = volume - comum.mediana_movel(volume, 150)
    falado = volume > np.percentile(volume, 40)
    limite = max(6.0, float(np.percentile(sobra[falado], 97))) if falado.any() else 6.0
    picos = [{"s": a, "e": b + 1, "db": round(float(sobra[a:b + 1].max()), 1)}
             for a, b in comum.agrupar((sobra >= limite) & falado, 2, 1)]
    return picos, limite


def sinais_de_chat(marcas, segundos_totais):
    """Onde o chat andou muito mais rápido que os minutos em volta (caixas de 10 s)."""
    caixas = np.bincount((np.array(marcas) // 10).astype(int), minlength=int(segundos_totais // 10) + 1).astype(float)
    normal = np.maximum(comum.mediana_movel(caixas, 15), 1.0)
    vezes = caixas / normal
    minimo = max(5.0, float(np.percentile(caixas[: int(max(marcas) // 10) + 1], 90)))
    caixas[0] = 0  # tudo que foi digitado antes da live começar cai no segundo zero
    picos = [{"s": a * 10, "e": (b + 1) * 10, "vezes": round(float(vezes[a:b + 1].max()), 1), "mensagens": int(caixas[a:b + 1].sum())}
             for a, b in comum.agrupar((vezes >= 2.5) & (caixas >= minimo), 1, 1)]
    return picos, caixas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fonte", help="link da live ou arquivo do computador")
    ap.add_argument("--pasta", default="garimpos")
    ap.add_argument("--lingua", default="", help="pt, en, es... (vazio = a da live, ou descobre sozinho)")
    ap.add_argument("--cookies", default="", help="navegador de onde ler o login: chrome, safari, firefox")
    ap.add_argument("--canal", default="", help="nome de quem fala (obrigatório em arquivo local se quiser no post)")
    ap.add_argument("--sem-chat", action="store_true")
    ap.add_argument("--tempo-chat", type=int, default=900, help="segundos no máximo esperando o replay do chat")
    ap.add_argument("--janela", type=int, default=12, help="minutos por janela de texto")
    ap.add_argument("--modelo", default="", help="modelo do Whisper (vazio = o melhor para este computador)")
    a = ap.parse_args()

    info, destino = ler_fonte(a.fonte, a.pasta, a.cookies, a.canal)
    cron = comum.Cronometro(destino)
    print("Fonte: %s | %s | %s" % (info["canal"] or "sem canal", info["titulo"], comum.duracao_falada(info["duracao"] or 0)))

    fio = None
    if not a.sem_chat and info["link"]:
        fio = threading.Thread(target=baixar_chat, args=(info, destino, a.cookies, a.tempo_chat), daemon=True)
        fio.start()

    cron.comeca("baixar_audio")
    arq, novo = audio_da_fonte(info, destino, a.cookies)
    if novo:
        print("1/4 áudio baixado: %.0f MB em %s" % (arq.stat().st_size / 1e6, comum.duracao_falada(cron.termina())))
    else:
        print("1/4 áudio pronto: %s" % arq.name)

    feito = comum.ler_json(destino / "transcricao.json")
    if feito and feito.get("completa"):
        frases, lingua, volume = feito["frases"], feito["lingua"], np.array(feito["volume"])
        levou = cron.dado.get("ouvir", 0)
    else:
        cron.comeca("ouvir")
        volume = np.array(comum.volume_por_segundo(arq))
        frases, lingua = transcrever_tudo(arq, volume, destino, a.lingua or info.get("lingua") or None, a.modelo)
        comum.escrever_json(destino / "transcricao.json", {"completa": True, "lingua": lingua, "frases": frases, "volume": volume.tolist()})
        (destino / "transcricao-parcial.json").unlink(missing_ok=True)
        levou = cron.termina()
    horas = len(volume) / 3600.0
    print("2/4 ouvido: %s de áudio, %d frases, em %s" % (comum.duracao_falada(len(volume)), len(frases), comum.duracao_falada(levou)))

    gritos, limite = sinais_de_volume(volume)
    print("3/4 volume: %d momentos bem acima do normal (%.1f dB ou mais)" % (len(gritos), limite))

    picos, mensagens = [], 0
    if fio is not None:
        fio.join(timeout=a.tempo_chat + 30)
        marcas = tempos_do_chat(destino)
        mensagens = len(marcas)
        if mensagens >= 200:
            picos, caixas = sinais_de_chat(marcas, len(volume))
            comum.escrever_json(destino / "chat-contagem.json", {"mensagens": mensagens, "por_10s": caixas.astype(int).tolist()})
            print("4/4 chat: %d mensagens, %d picos" % (mensagens, len(picos)))
        else:
            print("4/4 sem replay do chat (ou ele não veio): sigo com transcrição e volume")
    else:
        print("4/4 chat pulado")
    comum.escrever_json(destino / "sinais.json", {"gritos": gritos, "chat": picos, "limite_db": round(limite, 1), "mensagens": mensagens})

    # a transcrição em janelas, com as marcas nas linhas
    def marca(s, e):
        m = ""
        g = [x for x in gritos if x["s"] <= e and x["e"] >= s]
        if g:
            m += "ALTO+%.0fdB " % max(x["db"] for x in g)
        c = [x for x in picos if x["s"] <= e + 15 and x["e"] >= s]
        if c:
            m += "CHAT x%.1f " % max(x["vezes"] for x in c)
        return m + "| " if m else ""

    pasta_j = destino / "janelas"
    pasta_j.mkdir(exist_ok=True)
    for velha in pasta_j.glob("janela-*.md"):
        velha.unlink()
    passo = a.janela * 60
    n = int(np.ceil(len(volume) / passo)) or 1
    for i in range(n):
        ini, fim = i * passo, (i + 1) * passo
        linhas = ["# Janela %d de %d: %s a %s" % (i + 1, n, comum.relogio(ini), comum.relogio(min(fim, len(volume)))),
                  "%s | %s" % (info["canal"], info["titulo"]), "",
                  "ALTO+9dB = ficou 9 dB acima do normal daqueles minutos. CHAT x3.1 = o chat andou 3,1 vezes mais rápido.", ""]
        linhas += ["[%s] %s%s" % (comum.relogio(s["s"]), marca(s["s"], s["e"]), s["t"]) for s in frases if ini <= s["s"] < fim]
        (pasta_j / ("janela-%02d.md" % (i + 1))).write_text("\n".join(linhas) + "\n", encoding="utf-8")

    def frase_em(t):
        perto = [s for s in frases if s["s"] - 4 <= t <= s["e"] + 4]
        return (perto[0]["t"] if perto else "")[:90]

    linhas = ["# %s" % info["titulo"], "", "- Canal: %s" % (info["canal"] or "sem canal"),
              "- Fonte: %s" % (info["link"] or info["arquivo"]), "- Duração: %s" % comum.duracao_falada(len(volume)),
              "- Frases transcritas: %d" % len(frases), "- Picos de volume: %d" % len(gritos),
              "- Chat: %s" % ("%d mensagens, %d picos" % (mensagens, len(picos)) if picos or mensagens >= 200 else "sem replay"),
              "- Janelas de texto: %d (pasta janelas/)" % n, "", "## Os 25 maiores picos de volume", ""]
    linhas += ["- [%s] +%.0f dB, %d s: %s" % (comum.relogio(g["s"]), g["db"], g["e"] - g["s"], frase_em(g["s"]))
               for g in sorted(gritos, key=lambda x: -x["db"])[:25]]
    if picos:
        linhas += ["", "## Os 25 maiores picos do chat", ""]
        linhas += ["- [%s] %.1fx o normal, %d mensagens: %s" % (comum.relogio(c["s"]), c["vezes"], c["mensagens"], frase_em(c["s"] - 8))
                   for c in sorted(picos, key=lambda x: -x["vezes"])[:25]]
    (destino / "resumo.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    gasto = sum(v for k, v in cron.dado.items() if k in ("baixar_audio", "ouvir"))
    print("\nPronto: %s" % destino)
    print("Próximo passo: python3 peneirar.py %s" % destino)
    print("Baixar e ouvir levou %s (%.0fx mais rápido que assistir)" % (comum.duracao_falada(gasto), horas * 3600 / max(1.0, gasto)))


if __name__ == "__main__":
    main()
