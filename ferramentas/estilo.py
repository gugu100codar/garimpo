"""Os estilos do garimpo: o catálogo de kits, o perfil da pessoa e a mistura de tudo no visual que o cortar.py usa.

Só biblioteca padrão, para rodar antes de o ambiente existir (o onboarding acontece enquanto o preparar.py instala).

Camadas, da mais fraca para a mais forte:
  BASE  <  kit (referencias/estilos.json, mais ~/.garimpo/estilos-pessoais.json)  <  perfil (~/.garimpo/perfil.json)  <  <gravação>/estilo.json
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comum  # noqa: E402

CATALOGO = comum.SKILL / "referencias" / "estilos.json"
PESSOAIS = comum.CASA / "estilos-pessoais.json"   # kits só desta pessoa (não vão na skill)
PERFIL = comum.CASA / "perfil.json"

BASE = {
    "cor_destaque": "#FFD60A",      # a palavra que está sendo dita, a caixa do título e a barra
    "cor_legenda": "#FFFFFF",
    "cor_contorno": "#000000",
    "cor_titulo_fundo": "#FFD60A",
    "cor_titulo_texto": "#111111",
    "fonte": "anton",               # o id de uma fonte do catálogo
    "tamanho_legenda": 76,
    "margem_lateral": 140,          # a legenda fica longe das bordas: os botões do Shorts, Reels e TikTok ocupam a direita
    "tamanho_titulo": 62,
    "palavras_por_legenda": 3,
    "letras_por_legenda": 18,
    "altura_legenda": 0.68,         # centro da legenda: 0 = topo do vídeo, 1 = pé
    "titulo": True,
    "barra": True,
    "maiusculas": True,
    "volume": -14,                  # LUFS
    "marca": "",                    # um @ ou nome pequeno no pé do vídeo
    "selo": "caixa",                # o desenho da tag do título: "caixa" (lisa) ou o nome de um selo pessoal em ~/.garimpo/selos/
    "fonte_arquivo": "",            # preenchido por fechar(): o caminho da fonte no computador
}
CHAVES_DE_COR = ("cor_destaque", "cor_titulo_fundo", "cor_titulo_texto")


def carregar_catalogo(pessoais=True):
    """O catálogo da skill; com `pessoais`, mais os kits e fontes de ~/.garimpo/estilos-pessoais.json."""
    cat = comum.ler_json(CATALOGO, {"padrao": "classico", "cores": [], "fontes": {}, "kits": {}})
    extra = (comum.ler_json(PESSOAIS, {}) or {}) if pessoais else {}
    cat["fontes"] = dict(cat.get("fontes", {}), **extra.get("fontes", {}))
    cat["kits"] = dict(cat.get("kits", {}), **extra.get("kits", {}))
    return cat


def ler_perfil():
    p = comum.ler_json(PERFIL)
    return p if isinstance(p, dict) and p.get("kit") else None


def salvar_perfil(perfil):
    comum.CASA.mkdir(parents=True, exist_ok=True)
    comum.escrever_json(PERFIL, perfil)


def apagar_perfil():
    if PERFIL.exists():
        PERFIL.unlink()


def cor_valida(texto):
    """'ffd60a' ou '#FFD60A' viram '#FFD60A'; qualquer outra coisa vira None."""
    t = str(texto or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", t):
        return "#" + t.lstrip("#").upper()
    return None


def contraste(hexcor):
    """Texto escuro sobre fundo claro e o contrário."""
    h = hexcor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"


def aplicar_cor(est, nova):
    """Troca a cor de destaque do kit e, junto, o que no kit tinha a mesma cor (a tag do título, por exemplo)."""
    antiga = est["cor_destaque"].upper()
    trocou = {k for k in CHAVES_DE_COR if est[k].upper() == antiga}
    for k in trocou:
        est[k] = nova
    if "cor_titulo_fundo" in trocou and "cor_titulo_texto" not in trocou:
        est["cor_titulo_texto"] = contraste(nova)   # fundo novo: o texto da tag tem que continuar legível


def resolver(kit=None, usar_perfil=True):
    """O visual pronto de um kit. Sem `kit`, vale o do perfil (ou o padrão do catálogo).

    Se `kit` é de outro kit que não o do perfil, a cor e a fonte escolhidas no perfil não valem (eram para o kit antigo)."""
    cat = carregar_catalogo()
    perfil = ler_perfil() if usar_perfil else None
    nome = kit or (perfil or {}).get("kit") or cat["padrao"]
    if nome not in cat["kits"]:
        nome = cat["padrao"]
    est = dict(BASE)
    est.update(cat["kits"][nome].get("estilo", {}))
    est["fonte"] = cat["kits"][nome].get("fonte", est["fonte"])
    if perfil:
        if nome == perfil.get("kit"):
            if cor_valida(perfil.get("cor_destaque")):
                aplicar_cor(est, cor_valida(perfil["cor_destaque"]))
            if perfil.get("fonte") in cat["fontes"]:
                est["fonte"] = perfil["fonte"]
        est["marca"] = perfil.get("marca", "") or ""
    est["kit"] = nome
    return est


def fechar(est):
    """Depois do estilo.json da gravação: acha o arquivo da fonte escolhida."""
    cat = carregar_catalogo()
    f = cat["fontes"].get(est.get("fonte"))
    caminho = comum.MODELOS / f["arquivo"] if f else None
    est["fonte_arquivo"] = str(caminho) if caminho and caminho.exists() else ""
    return est
