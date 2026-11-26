#!/usr/bin/env python3
"""Primeira peneira: de uma gravação de horas, separa algumas dezenas de trechos que merecem ser lidos.

Uso:
  python3 peneirar.py <pasta da gravação> [--tamanho 40] [--passo 5] [--quantos 24] [--contexto 25]

Desliza uma janela de ~40 s pela gravação e dá a cada posição uma PRIORIDADE de 0 a 100, só para ordenar a leitura.
Quem dá a nota do corte é o Claude, lendo. A prioridade soma:
  volume    quanto o falante passou do volume normal dos minutos em volta
  chat      quanto o chat acelerou logo depois (só com replay)
  ritmo     fala bem mais rápida que a média da gravação
  expressão exclamações e perguntas por cem palavras
  abertura  o trecho começa depois de uma pausa ou de uma frase terminada

Janelas com pouca fala saem da disputa. Entre janelas que se cruzam fica a de maior prioridade.

Escreve em <pasta>/:
  candidatos.json   os trechos, com os sinais de cada um
  candidatos.md     o texto de cada trecho com o contexto antes e depois: é isso que o Claude lê
"""
import argparse
import bisect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402

comum.no_ambiente()
import numpy as np  # noqa: E402

PESOS_COM_CHAT = {"volume": 0.30, "chat": 0.25, "ritmo": 0.20, "expressao": 0.15, "abertura": 0.10}
PESOS_SEM_CHAT = {"volume": 0.38, "chat": 0.0, "ritmo": 0.27, "expressao": 0.22, "abertura": 0.13}


def limitar(x):
    return float(min(1.0, max(0.0, x)))


def palavras_por_segundo(frases, n):
    """Palavras ditas em cada segundo da gravação (a frase reparte as palavras por igual entre o início e o fim)."""
    v = np.zeros(n)
    for f in frases:
        a, b = int(f["s"]), min(n - 1, max(int(f["s"]), int(f["e"])))
        v[a:b + 1] += len(f["t"].split()) / float(b - a + 1)
    return v


def abre_limpo(frases, i):
    """A frase i começa depois de uma pausa ou depois de uma frase que terminou?"""
    if i == 0:
        return True
    ant = frases[i - 1]
    return frases[i]["s"] - ant["e"] >= 0.6 or ant["t"].rstrip()[-1:] in ".!?…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("--tamanho", type=int, default=40, help="segundos de cada janela")
    ap.add_argument("--passo", type=int, default=5)
    ap.add_argument("--quantos", type=int, default=0, help="quantos trechos guardar (vazio = 8 por hora, no mínimo 10)")
    ap.add_argument("--contexto", type=int, default=25, help="segundos de texto antes e depois, só para ler")
    a = ap.parse_args()
    pasta = Path(a.pasta)
    tr = comum.ler_json(pasta / "transcricao.json")
    if not tr:
        sys.exit("Rode antes o ouvir.py nessa pasta.")
    info = comum.ler_json(pasta / "info.json", {})
    sinais = comum.ler_json(pasta / "sinais.json", {"gritos": [], "chat": []})
    frases = tr["frases"]
    volume = np.array(tr["volume"])
    n = len(volume)
    horas = n / 3600.0
    quantos = a.quantos or max(10, int(round(horas * 8)))
    if n < a.tamanho * 2 or not frases:
        sys.exit("A gravação é curta demais (ou não tem fala) para peneirar. Leia as janelas direto.")

    sobra = volume - comum.mediana_movel(volume, 150)
    pps = palavras_por_segundo(frases, n)
    falando = pps > 0
    ritmo_normal = max(0.5, float(np.median(pps[falando]))) if falando.any() else 1.0
    tem_chat = bool(sinais["chat"])
    pesos = PESOS_COM_CHAT if tem_chat else PESOS_SEM_CHAT
    inicios = [f["s"] for f in frases]

    janelas = []
    for ini in range(0, n - a.tamanho + 1, a.passo):
        fim = ini + a.tamanho
        i0 = bisect.bisect_left(inicios, ini - 1.0)
        i1 = bisect.bisect_left(inicios, fim - 1.0)
        dentro = frases[i0:i1]
        if not dentro:
            continue
        cobertura = float(falando[ini:fim].mean())
        if cobertura < 0.5:
            continue
        texto = " ".join(f["t"] for f in dentro)
        n_pal = max(1, len(texto.split()))
        s = {
            "volume": limitar(float(sobra[ini:fim].max()) / 14.0),
            "chat": limitar((max([c["vezes"] for c in sinais["chat"] if c["s"] <= fim + 15 and c["e"] >= ini] or [1.0]) - 1.0) / 3.0),
            "ritmo": limitar((float(pps[ini:fim][falando[ini:fim]].mean()) / ritmo_normal - 1.0) / 0.8),
            "expressao": limitar((texto.count("!") + 0.6 * texto.count("?")) / (n_pal / 100.0) / 8.0),
            "abertura": 1.0 if abre_limpo(frases, i0) else 0.0,
        }
        prioridade = 100.0 * sum(pesos[k] * s[k] for k in pesos)
        janelas.append({"ini": ini, "fim": fim, "prioridade": prioridade, "sinais": s, "i0": i0, "i1": i1})

    # entre janelas que se cruzam, fica a de maior prioridade
    escolhidas = []
    for j in sorted(janelas, key=lambda x: -x["prioridade"]):
        if all(abs(j["ini"] - e["ini"]) >= a.tamanho for e in escolhidas):
            escolhidas.append(j)
        if len(escolhidas) >= quantos:
            break
    escolhidas.sort(key=lambda x: x["ini"])

    saida, linhas = [], ["# Candidatos de %s" % (info.get("titulo") or pasta.name),
                         "%s | %s | %d candidatos de %s de gravação" % (info.get("canal") or "sem canal", pasta.name, len(escolhidas), comum.duracao_falada(n)),
                         "", "A prioridade só ordena a leitura. A nota do corte é sua: siga referencias/criterios.md.",
                         "Linhas com `>>` são o trecho sugerido; as sem marca são só contexto.", ""]
    for k, j in enumerate(escolhidas, 1):
        dentro = frases[j["i0"]:j["i1"]]
        ini_t, fim_t = dentro[0]["s"], dentro[-1]["e"]
        sig = j["sinais"]
        resumo = ", ".join("%s %.0f%%" % (nome, 100 * sig[nome]) for nome in ("volume", "chat", "ritmo", "expressao") if sig[nome] >= 0.3 and (nome != "chat" or tem_chat))
        saida.append({"n": k, "inicio": comum.relogio(ini_t), "fim": comum.relogio(fim_t), "inicio_s": round(ini_t, 1), "fim_s": round(fim_t, 1),
                      "prioridade": round(j["prioridade"]), "sinais": {x: round(v, 2) for x, v in sig.items()}})
        linhas.append("## %d. %s a %s | prioridade %.0f%s" % (k, comum.relogio(ini_t), comum.relogio(fim_t), j["prioridade"], (" | " + resumo) if resumo else ""))
        for f in frases:
            if ini_t - a.contexto <= f["s"] < fim_t + a.contexto:
                dentro_do_trecho = ini_t - 0.01 <= f["s"] < fim_t
                linhas.append("%s[%s] %s" % (">> " if dentro_do_trecho else "   ", comum.relogio(f["s"]), f["t"]))
        linhas.append("")
    comum.escrever_json(pasta / "candidatos.json", {"candidatos": saida, "janela_s": a.tamanho, "com_chat": tem_chat})
    (pasta / "candidatos.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print("%d candidatos em %s (de %d janelas com fala)" % (len(escolhidas), comum.duracao_falada(n), len(janelas)))
    print("Leia %s" % (pasta / "candidatos.md"))
    if horas < 1.5:
        print("A gravação tem menos de 1h30: leia também as janelas/ inteiras, a peneira pode deixar passar uma opinião dita baixo.")


if __name__ == "__main__":
    main()
