#!/usr/bin/env python3
"""O perfil visual da pessoa: o que o onboarding pergunta e grava, uma vez, em ~/.garimpo/perfil.json.

Uso (no Windows o comando é python no lugar de python3). Tudo abaixo roda sem o ambiente do garimpo, menos --catalogo:
  python3 perfil.py --existe                       diz se já há perfil (código de saída 0 = há, 1 = não há)
  python3 perfil.py --mostrar                      o perfil salvo e o estilo que ele resulta
  python3 perfil.py --listar                       os kits e as fontes, com o número que a pessoa vê nas folhas
  python3 perfil.py --abrir kits|fontes            abre a folha pronta (referencias/catalogo/) no visualizador do computador
  python3 perfil.py --salvar --kit neon [--cor "#39FF14"] [--fonte bebas] [--marca "@meucanal"]
                                                   grava o perfil (kit e fonte aceitam o nome ou o número da folha)
  python3 perfil.py --limpar                       apaga o perfil (a próxima gravação refaz o onboarding)
  python3 perfil.py --catalogo                     redesenha as folhas kits.jpg e fontes.jpg (precisa do ambiente e das fontes
                                                   baixadas pelo preparar.py; é para quem mexeu em referencias/estilos.json)
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402
import estilo  # noqa: E402

PASTA_FOLHAS = comum.SKILL / "referencias" / "catalogo"
TITULO = "A reação que ninguém previu"
PALAVRAS = ["Ninguém", "esperava", "essa"]


def kits_publicos():
    return list(estilo.carregar_catalogo(pessoais=False)["kits"])


def fontes_publicas():
    return list(estilo.carregar_catalogo(pessoais=False)["fontes"])


def por_numero(valor, lista, o_que):
    """'3' vira o terceiro da lista; um nome fica como está."""
    if valor is not None and str(valor).strip().isdigit():
        n = int(valor)
        if not 1 <= n <= len(lista):
            sys.exit("Não há %s número %d (vai de 1 a %d)." % (o_que, n, len(lista)))
        return lista[n - 1]
    return valor


def listar():
    cat = estilo.carregar_catalogo()
    pub = kits_publicos()
    print("KITS (o número é o da folha kits.jpg)")
    for i, k in enumerate(pub, 1):
        d = cat["kits"][k]
        print("  %d  %-9s %-10s %s | fonte %s | cor %s" % (i, k, d["nome"], d["para"], cat["fontes"][d["fonte"]]["nome"],
              estilo.resolver(k, usar_perfil=False)["cor_destaque"]))
    for k, d in cat["kits"].items():
        if k not in pub:
            print("  -  %-9s %-10s %s (só desta pessoa; não aparece na folha)" % (k, d["nome"], d["para"]))
    print("FONTES (o número é o da folha fontes.jpg)")
    for i, f in enumerate(fontes_publicas(), 1):
        print("  %d  %-18s %s" % (i, f, cat["fontes"][f]["nome"]))
    print("CORES SUGERIDAS:", " ".join(cat.get("cores", [])))
    print("PADRÃO:", cat["padrao"])


def abrir(caminho):
    if not Path(caminho).exists():
        sys.exit("Não achei %s. Rode: %s perfil.py --catalogo" % (caminho, comum.PYTHON))
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(caminho)])
    elif comum.WINDOWS:
        os.startfile(str(caminho))  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(caminho)])
    print("aberto:", caminho)


def salvar(a):
    cat = estilo.carregar_catalogo()
    kit = por_numero(a.kit, kits_publicos(), "kit")
    if kit not in cat["kits"]:
        sys.exit("Kit desconhecido: %s. Rode --listar." % a.kit)
    perfil = {"versao": 1, "kit": kit}
    if a.cor:
        c = estilo.cor_valida(a.cor)
        if not c:
            sys.exit("Cor inválida: %s. Use 6 dígitos, como #FFD60A." % a.cor)
        perfil["cor_destaque"] = c
    if a.fonte:
        f = por_numero(a.fonte, fontes_publicas(), "fonte")
        if f not in cat["fontes"]:
            sys.exit("Fonte desconhecida: %s. Rode --listar." % a.fonte)
        perfil["fonte"] = f
    if a.marca:
        perfil["marca"] = a.marca.strip()
    estilo.salvar_perfil(perfil)
    est = estilo.fechar(estilo.resolver())
    print("perfil salvo em %s" % estilo.PERFIL)
    print("  kit %s | cor %s | fonte %s | marca %s" % (est["kit"], est["cor_destaque"], est["fonte"], est["marca"] or "(sem)"))
    if not est["fonte_arquivo"]:
        print("  aviso: a fonte %s ainda não está baixada; o preparar.py baixa." % est["fonte"])


def mostrar():
    p = estilo.ler_perfil()
    if not p:
        print("SEM PERFIL (vale o kit padrão: %s)" % estilo.carregar_catalogo()["padrao"])
        return
    est = estilo.fechar(estilo.resolver())
    print("perfil:", p)
    print("estilo:", {k: est[k] for k in ("kit", "cor_destaque", "cor_titulo_fundo", "cor_titulo_texto", "fonte", "marca")})
    print("fonte no computador:", est["fonte_arquivo"] or "NÃO BAIXADA")


# ---------- as folhas (precisam do Pillow e das fontes) ----------

def quadro(est):
    """Um quadro 1080x1920 de exemplo, desenhado pelas mesmas funções do cortar.py."""
    import cortar
    from PIL import Image, ImageDraw
    L, A, emenda = cortar.L, cortar.A, 640
    img = Image.new("RGB", (L, A), (23, 23, 28))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, L, emenda), fill=(38, 38, 46))
    d.rectangle((0, emenda, L, A), fill=(29, 29, 36))
    rot = cortar.fonte(40, str(comum.MODELOS / "Poppins-SemiBold.ttf"))
    for texto, y in (("câmera do falante", 250), ("conteúdo da tela", 900)):
        d.text(((L - rot.getlength(texto)) / 2, y), texto, font=rot, fill=(120, 120, 132))
    grupo = [{"w": (w.upper() if est["maiusculas"] else w)} for w in PALAVRAS]
    faixa = cortar.desenhar_legenda(grupo, 2, est)
    capy = int(min(max(A * est["altura_legenda"] - cortar.FAIXA / 2, 0), A - cortar.FAIXA))
    img.paste(faixa, (0, capy), faixa)
    if est["barra"]:
        d.rectangle((0, A - 12, int(L * 0.42), A), fill=cortar.cor(est["cor_destaque"]))
    selo = cortar.desenhar_selo(TITULO if est["titulo"] else "", emenda, est)
    img.paste(selo, (0, 0), selo)
    return img


def folha_dos_kits(destino):
    import cortar
    from PIL import Image, ImageDraw
    cat = estilo.carregar_catalogo(pessoais=False)
    kits = list(cat["kits"])
    colunas, lw, lh, borda, rotulo = 3, 360, 640, 28, 96
    linhas = (len(kits) + colunas - 1) // colunas
    folha = Image.new("RGB", (colunas * (lw + borda) + borda, linhas * (lh + rotulo + borda) + borda), (14, 14, 18))
    d = ImageDraw.Draw(folha)
    pop = str(comum.MODELOS / "Poppins-SemiBold.ttf")
    negrito, leve = cortar.fonte(34, pop), cortar.fonte(24, pop)
    for i, k in enumerate(kits):
        est = estilo.fechar(estilo.resolver(k, usar_perfil=False))
        est["marca"] = ""
        x = borda + (i % colunas) * (lw + borda)
        y = borda + (i // colunas) * (lh + rotulo + borda)
        folha.paste(quadro(est).resize((lw, lh), Image.LANCZOS), (x, y))
        d.rounded_rectangle((x, y + lh + 14, x + 44, y + lh + 58), radius=8, fill=cortar.cor(est["cor_destaque"]))
        d.text((x + 22 - negrito.getlength(str(i + 1)) / 2, y + lh + 18), str(i + 1), font=negrito, fill=(17, 17, 17))
        d.text((x + 58, y + lh + 18), cat["kits"][k]["nome"], font=negrito, fill=(255, 255, 255))
        d.text((x, y + lh + 64), cat["kits"][k]["para"], font=leve, fill=(160, 160, 172))
    PASTA_FOLHAS.mkdir(parents=True, exist_ok=True)
    folha.save(str(destino), quality=88)


def folha_das_fontes(destino):
    import cortar
    from PIL import Image, ImageDraw
    cat = estilo.carregar_catalogo(pessoais=False)
    fontes = list(cat["fontes"])
    larg, alt_linha, borda = 1080, 164, 32
    folha = Image.new("RGB", (larg, borda * 2 + alt_linha * len(fontes)), (14, 14, 18))
    d = ImageDraw.Draw(folha)
    miudo = cortar.fonte(28, str(comum.MODELOS / "Poppins-SemiBold.ttf"))
    ouro = cortar.cor("#FFD60A")
    for i, k in enumerate(fontes):
        arquivo = comum.MODELOS / cat["fontes"][k]["arquivo"]
        y = borda + i * alt_linha
        d.text((borda, y + 8), "%d   %s" % (i + 1, cat["fontes"][k]["nome"]), font=miudo, fill=(160, 160, 172))
        tam = 84
        while True:
            f = cortar.fonte(tam, str(arquivo))
            if f.getlength(TITULO) <= larg - 2 * borda or tam <= 40:
                break
            tam -= 4
        d.text((borda, y + 50), TITULO, font=f, fill=ouro, stroke_width=max(3, tam // 12), stroke_fill=(0, 0, 0))
    folha.save(str(destino), quality=88)


def catalogo():
    comum.no_ambiente()
    faltam = [f["nome"] for f in estilo.carregar_catalogo(pessoais=False)["fontes"].values() if not (comum.MODELOS / f["arquivo"]).exists()]
    if faltam:
        sys.exit("Faltam fontes: %s. Rode o preparar.py." % ", ".join(faltam))
    PASTA_FOLHAS.mkdir(parents=True, exist_ok=True)
    folha_dos_kits(PASTA_FOLHAS / "kits.jpg")
    folha_das_fontes(PASTA_FOLHAS / "fontes.jpg")
    print("folhas em", PASTA_FOLHAS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--existe", action="store_true")
    ap.add_argument("--mostrar", action="store_true")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--abrir", choices=["kits", "fontes"])
    ap.add_argument("--salvar", action="store_true")
    ap.add_argument("--limpar", action="store_true")
    ap.add_argument("--catalogo", action="store_true")
    ap.add_argument("--kit")
    ap.add_argument("--cor")
    ap.add_argument("--fonte")
    ap.add_argument("--marca")
    a = ap.parse_args()
    if a.existe:
        ok = estilo.ler_perfil() is not None
        print("PERFIL" if ok else "SEM PERFIL")
        sys.exit(0 if ok else 1)
    if a.mostrar:
        return mostrar()
    if a.listar:
        return listar()
    if a.abrir:
        return abrir(PASTA_FOLHAS / (a.abrir + ".jpg"))
    if a.salvar:
        if not a.kit:
            sys.exit("Falta --kit (nome ou número da folha).")
        return salvar(a)
    if a.limpar:
        estilo.apagar_perfil()
        return print("perfil apagado")
    if a.catalogo:
        return catalogo()
    ap.print_help()


if __name__ == "__main__":
    main()
