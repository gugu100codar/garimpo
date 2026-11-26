---
name: garimpo
description: >
  Garimpa uma gravação longa (live, podcast, aula, vídeo do YouTube, Twitch ou Kick, ou um arquivo do computador)
  e entrega cortes verticais 9:16 prontos para postar, com título e legenda palavra por palavra. Ouve tudo no
  computador (Whisper), separa os trechos que merecem leitura com uma peneira automática (volume, ritmo, chat),
  lê só esses, dá nota, e monta cada corte com um único ffmpeg. Use quando pedirem "garimpa essa live",
  "faz cortes disso", "corta esse podcast", "tira os melhores momentos", "prepara o garimpo" ou mandarem um
  link ou arquivo longo para virar cortes.
---

# Garimpo

Pipeline em quatro passos. Cada passo é um script em `ferramentas/`; `$SKILL` é a pasta desta skill e a pasta atual é onde os cortes ficam.

| Passo | Script | Sai |
|---|---|---|
| 0. Onboarding (uma vez) | `perfil.py` | `~/.garimpo/perfil.json` (kit, cor, fonte, @) |
| 1. Preparar (uma vez) | `preparar.py` | ambiente próprio em `~/.garimpo` |
| 2. Ouvir | `ouvir.py <link ou arquivo>` | transcrição, volume, chat, `janelas/`, `resumo.md` |
| 3. Peneirar e escolher | `peneirar.py`, depois você lê e escreve `momentos.json`, depois `conferir.py` | `candidatos.md`, `momentos-conferidos.json` |
| 4. Cortar | `cortar.py` | `cortes/NN-titulo.mp4` + `.txt` + `-folha.jpg` |

## Começar

Se a pessoa já mandou link ou arquivo, comece sem perguntar. Se não, pergunte numa mensagem só: o link ou arquivo, e quantos cortes por gravação (sem resposta, três).

Antes de tudo, veja se a pessoa já escolheu o visual dos cortes:

```bash
python3 $SKILL/ferramentas/perfil.py --existe
```

`PERFIL` quer dizer que sim: siga em frente, o `cortar.py` usa o estilo salvo. `SEM PERFIL` quer dizer que é a primeira vez: faça o onboarding abaixo **enquanto** o resto roda.

## Onboarding do visual (só na primeira vez)

Objetivo: a pessoa escolhe o visual dos cortes em um minuto, uma vez só, e nunca mais é perguntada. O passo 1 (preparar) e o passo 2 (ouvir) levam minutos; o onboarding acontece nesse tempo, sem atrasar nada.

1. **Comece o trabalho demorado em segundo plano** (preparar, depois ouvir, se já há link ou arquivo). Não espere a resposta para isso.
2. **Mostre o catálogo.** As folhas já vêm prontas e não dependem do ambiente:

   ```bash
   python3 $SKILL/ferramentas/perfil.py --abrir kits
   ```

   Se o app mostra arquivos (`SendUserFile`), mande também `$SKILL/referencias/catalogo/kits.jpg`. A folha numera seis kits (Clássico, Neon, Sóbrio, Fogo, Suave, Limpo), cada um com cor, fonte e proporções prontas.
3. **Pergunte numa mensagem só**, curta, com tudo opcional:
   - o número do kit (1 a 6);
   - a cor de destaque, se quiser outra (um hex como `#FF3366`; sem resposta, a do kit);
   - um nome ou @ para o pé do vídeo (sem resposta, nenhum);
   - "pular" usa o Clássico. Diga que dá para mudar depois.
4. **Fonte só se a pessoa pedir** ("quero outra fonte", "ajustar mais"): `perfil.py --abrir fontes` mostra as seis, numeradas; ela responde o número. O kit já traz a fonte certa, então por padrão não pergunte.
5. **Grave a escolha:**

   ```bash
   python3 $SKILL/ferramentas/perfil.py --salvar --kit 2 [--cor "#FF3366"] [--fonte 4] [--marca "@meucanal"]
   ```

   `--kit` e `--fonte` aceitam o número da folha ou o nome (`perfil.py --listar` mostra os dois). "Pular" grava `--kit 1`. Cor inválida ou kit desconhecido dá erro: corrija e rode de novo.
6. Se a resposta ainda não veio quando chegar a hora do `cortar.py`, pergunte antes de cortar. Não corte sem perfil.

Na entrega do primeiro corte, diga qual estilo foi aplicado e como trocar ("Estilo Neon salvo. Para trocar, diga 'muda o estilo'"). Quem pedir para mudar: pergunte o novo kit com a mesma folha, rode `--salvar` de novo e refaça só os cortes pedidos (`cortar.py ... --so NN`; avise que escreve por cima, regra 7). `perfil.py --mostrar` diz o que está salvo; `perfil.py --limpar` apaga e a próxima gravação refaz o onboarding.

## Regras

1. **A fala é a fonte.** Título e legenda do post saem do que é dito no trecho. Nada inventado. Nome de quem fala e do jogo vêm de `info.json` e `resumo.md`, nunca da transcrição (o Whisper erra nomes).
2. **Nota é sua, não do script.** A `prioridade` do `peneirar.py` só ordena a leitura. Nota segue `referencias/criterios.md`, e zero candidatos num trecho é resposta normal.
3. **Olhe as imagens antes de dizer que está pronto.** Abra cada `-folha.jpg` (e o `trechos/NN-camera.jpg` se o enquadramento parecer estranho).
4. **Diga os números.** Duração ouvida, candidatos lidos, momentos que entraram na lista, cortes feitos, tempo gasto (`tempos.json`).
5. **Entregue arquivos, não poste.** Nenhuma rede social é tocada.
6. **O canal é de outra pessoa.** Na primeira gravação de um canal, avise para ver se ele aceita cortes (muitos têm regra ou programa próprio).
7. **Versão nova, nome novo.** Se a pessoa já viu um corte, mude o título ou use outra pasta antes de refazer; o `cortar.py` escreve por cima do mesmo nome.

## Passo a passo

No Windows o comando é `python` (ou `py`) no lugar de `python3`, com os caminhos entre aspas.

### 1. Preparar

```bash
python3 $SKILL/ferramentas/preparar.py
```

Cria o ambiente com yt-dlp, deno, OpenCV, NumPy, Pillow e o Whisper (mlx no Mac com chip Apple, faster-whisper no resto), mais o modelo de rostos e as seis fontes do catálogo (todas de licença livre). Se o Python do computador for novo ou velho demais (precisa ser 3.10 a 3.13), ele busca um 3.12 sozinho. Termina em `PRONTO`. `--conferir` diz o que falta; `--leve` pula o Whisper. Com `GARIMPO_MODELO=small` (ou `tiny`, `base`) troca o modelo do Whisper por um menor e mais rápido.

### 2. Ouvir

```bash
python3 $SKILL/ferramentas/ouvir.py "<link ou arquivo>" --canal "Nome de quem fala"
```

- Link: baixa só o áudio. Arquivo: ouve direto. `--canal` é útil em arquivo local, que não traz o nome.
- Live de quatro horas leva alguns minutos num Mac com chip Apple; em Windows ou Mac Intel o Whisper roda no processador e demora mais. Avise antes de começar uma gravação longa.
- A transcrição é salva a cada bloco de 10 min. Se cair no meio, rode o mesmo comando de novo e ela continua.
- Login ou restrição de idade: `--cookies chrome` (ou `safari`, `firefox`, `edge`). Língua: `--lingua pt`. Sem o replay do chat: `--sem-chat`.
- Uma gravação por vez (o Whisper usa o computador inteiro). Enquanto a próxima é ouvida, escolha os momentos da anterior.

### 3. Peneirar, ler, escolher

```bash
python3 $SKILL/ferramentas/peneirar.py garimpos/<id>
```

1. Leia `referencias/criterios.md` uma vez.
2. Leia `garimpos/<id>/resumo.md` e depois `candidatos.md`. Cada candidato traz o trecho (`>>`) com 25 s de contexto antes e depois. Anote de zero a três momentos por candidato; pode começar antes ou terminar depois do trecho sugerido.
3. **Cobertura:** em gravação com menos de 1h30, leia também as `janelas/` inteiras, porque a peneira pode deixar passar uma opinião dita baixo. Em gravação longa, leia as janelas ao redor dos picos do `resumo.md` que não viraram candidato, ou peça `--quantos` maior.
4. Escreva `garimpos/<id>/momentos.json` com tudo que merece nota 60 ou mais (formato em `referencias/criterios.md`).
5. Rode o conferidor:

```bash
python3 $SKILL/ferramentas/conferir.py garimpos/<id> --manter 3
```

6. Leia a fala exata de cada momento. Aviso de "começa no meio", "termina sem fechar", "cruza" ou "curto/longo" significa arrumar o `momentos.json` e rodar de novo. A transcrição tem erros de ouvido: o que importa é o sentido, e a legenda do corte é refeita do áudio do trecho.

### 4. Cortar

```bash
python3 $SKILL/ferramentas/cortar.py garimpos/<id>
```

Sai em `garimpos/<id>/cortes/`: `NN-titulo.mp4` (1080×1920, 30 fps, −14 LUFS), `NN-titulo.txt` (título, legenda, hashtags, link no segundo certo, fala) e `NN-titulo-folha.jpg` (seis quadros). Abra a folha e confira o enquadramento, o título legível e a legenda na palavra certa.

**Enquadramento (automático, 2 olhadas por segundo):**
- `empilhado`: câmera pequena do falante em cima, conteúdo embaixo.
- `seguir`: o rosto ocupa a tela; recorte vertical em volta dele.
- `desfocado`: sem rosto; o vídeo no meio com ele mesmo desfocado ao fundo.

Se errou, abra `trechos/NN-camera.jpg` (mostra as caixas escolhidas) e force: `--modo seguir|empilhado|desfocado` ou `--camera x,y,largura,altura` em pixels do vídeo original, junto com `--so NN` para refazer só aquele corte. Limite: um enquadramento por corte. Se o falante troca a tela no meio, divida em dois momentos.

**Visual:** vem do perfil salvo no onboarding (kit, cor, fonte, @). Para uma gravação só, `--estilo <kit>` usa outro kit do catálogo (`perfil.py --listar` mostra os nomes), e `garimpos/<id>/estilo.json` muda só o que for preciso, por cima de tudo (o `cortar.py` aplica nessa ordem: base, kit, perfil, `estilo.json`):

```json
{"cor_destaque": "#FFD60A", "fonte": "bebas", "tamanho_legenda": 92, "palavras_por_legenda": 3,
 "altura_legenda": 0.68, "titulo": true, "barra": true, "maiusculas": true, "marca": "@seu_nome"}
```

Os kits e as fontes ficam em `referencias/estilos.json`. Kit ou fonte que só você usa vai em `~/.garimpo/estilos-pessoais.json`, no mesmo formato, e não entra na folha; uma tag de título diferente da caixa lisa vai em `~/.garimpo/selos/<nome>.py` (o cabeçalho de um selo explica o formato) e o kit a chama com `"selo": "<nome>"`. Quem mexer no catálogo redesenha as folhas com `perfil.py --catalogo`.

**Legenda e margens:** a legenda nunca passa de `margem_lateral` (140 px de cada lado, contorno incluso) para não ficar sob os botões do Shorts, Reels e TikTok. Se uma frase não cabe, o `cortar.py` diminui a letra dela até caber. Para uma legenda ainda menor, baixe `tamanho_legenda` no `estilo.json`; para mais respiro, aumente `margem_lateral`.

O trecho baixado só é reaproveitado se o tempo pedido for o mesmo, então mudar o estilo é rápido e mudar o momento baixa de novo.

### 5. Entregar

Numa mensagem: os números (regra 4), cada corte com título, duração, nota e motivo, os outros momentos bons que ficaram de fora (para ela pedir), e onde estão os arquivos. Se for o primeiro corte de um canal, a regra 6. Se foi o primeiro uso, diga o estilo aplicado e como trocar (veja o onboarding).

## Notas da máquina

- No Mac com `faster-whisper` (chip Intel, ou `GARIMPO_MOTOR=faster`) o terminal pode mostrar `objc[...] Class AVF... is implemented in both`. É aviso do OpenCV e do PyAV carregando a mesma biblioteca; não afeta o resultado.
- O ffmpeg do Homebrew costuma vir sem `libass`/`drawtext`, por isso título e legenda são desenhados com Pillow e entram no ffmpeg como camada de vídeo, não como filtro de texto.
- Fonte só de áudio (mp3, podcast sem imagem) transcreve e peneira, mas não vira corte vertical.
