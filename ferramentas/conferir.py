#!/usr/bin/env python3
"""Confere os momentos que o Claude escolheu, antes de gastar tempo cortando.

Uso:
  python3 conferir.py <pasta da gravação> [--manter 3] [--minimo 15] [--maximo 60]

Lê <pasta>/momentos.json (escrito depois de ler candidatos.md):
  {"momentos": [{"inicio": "1:23:45", "fim": "1:24:20", "nota": 87, "tipo": "primeira reação",
                 "titulo": "o que aparece no corte", "por_que": "por que alguém compartilharia",
                 "legenda": "legenda do post", "hashtags": ["#jogo", "#cortes"]}]}

Para cada momento: puxa começo e fim para as bordas da frase, mede, avisa do que costuma dar errado
(começa no meio de um raciocínio, termina sem fechar a frase, cruza com outro, título grande) e mostra a fala exata.
Escreve momentos-conferidos.json, com os melhores marcados para o corte (--manter).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402

# começos que quase sempre são o meio de um raciocínio (primeira palavra, ou as duas primeiras)
MULETAS = {"então", "aí", "e", "tipo", "mas", "enfim", "porque", "pois", "daí", "né", "and", "but", "so", "uh", "um",
           "because", "anyway", "só que", "ou seja", "quer dizer"}
# começos que apontam para algo dito antes: quem nunca viu a live pode não entender
REFERENCIAS = {"ele", "ela", "eles", "elas", "isso", "isto", "aquilo", "esse", "essa", "he", "she", "they", "that", "this"}
BLOQUEIOS = ("cruza", "não há fala", "demais")


def primeiras(texto):
    """As duas primeiras palavras, sem pontuação: ('então', 'então eu')."""
    p = [w.strip(",.…!?;:\"'") for w in texto.lower().lstrip("¿¡-– ").split()[:2]]
    return (p[0] if p else ""), " ".join(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("--manter", type=int, default=3)
    ap.add_argument("--minimo", type=float, default=15)
    ap.add_argument("--maximo", type=float, default=60)
    a = ap.parse_args()
    pasta = Path(a.pasta)
    dado = comum.ler_json(pasta / "momentos.json")
    if not dado or not dado.get("momentos"):
        sys.exit("Não achei momentos em %s" % (pasta / "momentos.json"))
    frases = comum.ler_json(pasta / "transcricao.json")["frases"]
    sinais = comum.ler_json(pasta / "sinais.json", {"gritos": [], "chat": []})
    saida = []
    for n, m in enumerate(dado["momentos"], 1):
        ini, fim = comum.segundos(m["inicio"]), comum.segundos(m["fim"])
        avisos = []
        dentro = [f for f in frases if f["e"] > ini + 0.5 and f["s"] < fim - 0.5]
        if not dentro:
            avisos.append("não há fala nesse trecho")
        else:
            # o começo vai para o início da frase que o contém, o fim para o final da frase que o contém
            if abs(dentro[0]["s"] - ini) <= 4:
                ini = dentro[0]["s"]
            if abs(dentro[-1]["e"] - fim) <= 4:
                fim = dentro[-1]["e"]
        ini, fim = max(0.0, ini - 0.25), fim + 0.35
        dur = fim - ini
        texto = " ".join(f["t"] for f in dentro)
        p1, p2 = primeiras(texto)
        if dur < a.minimo:
            avisos.append("curto demais (%.0f s)" % dur)
        if dur > a.maximo:
            avisos.append("longo demais (%.0f s): tire o que não precisa" % dur)
        if p1 in MULETAS or p2 in MULETAS:
            avisos.append("começa no meio de um raciocínio (\"%s\")" % texto[:28])
        elif p1 in REFERENCIAS:
            avisos.append("começa apontando para algo dito antes (\"%s\"): confira se se entende sozinho" % texto[:28])
        if texto and texto.rstrip()[-1] not in ".!?…\"":
            avisos.append("termina sem fechar a frase (\"...%s\")" % texto[-28:])
        titulo = m.get("titulo", "")
        if not titulo:
            avisos.append("sem título")
        elif len(titulo) > 45:
            avisos.append("título com %d letras (o limite é 45)" % len(titulo))
        if not m.get("legenda"):
            avisos.append("sem legenda do post")
        if float(m.get("nota", 0)) < 60:
            avisos.append("nota abaixo de 60: não deveria estar na lista")
        for outro in saida:
            if ini < outro["fim_s"] and fim > outro["inicio_s"]:
                avisos.append("cruza com o momento %d" % outro["n"])
        grito = max([g["db"] for g in sinais["gritos"] if g["s"] <= fim and g["e"] >= ini] or [0])
        chat = max([c["vezes"] for c in sinais["chat"] if c["s"] <= fim + 15 and c["e"] >= ini] or [0])
        item = dict(m)
        item.update({"n": n, "inicio_s": round(ini, 2), "fim_s": round(fim, 2), "duracao": round(dur, 1),
                     "inicio": comum.relogio(ini), "fim": comum.relogio(fim), "grito_db": grito, "chat_vezes": chat,
                     "texto": texto, "avisos": avisos, "nota": float(m.get("nota", 0))})
        saida.append(item)
    ordem = sorted(saida, key=lambda x: -x["nota"])
    bons = [x for x in ordem if not any(b in w for w in x["avisos"] for b in BLOQUEIOS)]
    mantidos = {x["n"] for x in bons[: a.manter]}
    for x in saida:
        x["manter"] = x["n"] in mantidos
    comum.escrever_json(pasta / "momentos-conferidos.json", {"momentos": saida})
    print("%d momentos conferidos, %d marcados para o corte\n" % (len(saida), len(mantidos)))
    for x in ordem:
        sinal = ("ALTO+%.0fdB " % x["grito_db"] if x["grito_db"] else "") + ("CHAT x%.1f" % x["chat_vezes"] if x["chat_vezes"] else "")
        print("%s %2d | nota %3.0f | %s a %s | %2.0f s | %s %s" % ("CORTA" if x["manter"] else "     ", x["n"], x["nota"], x["inicio"], x["fim"],
                                                                x["duracao"], x.get("tipo", ""), sinal))
        print("        título: %s" % x.get("titulo", ""))
        print("        fala:   %s" % x["texto"])
        for w in x["avisos"]:
            print("        AVISO:  %s" % w)
        print()
    if any(x["avisos"] for x in saida):
        print("Há avisos. Arrume momentos.json (ou troque o momento) e rode de novo antes de cortar.")


if __name__ == "__main__":
    main()
