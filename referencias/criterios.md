# Como escolher e dar nota

## O que você recebe

`peneirar.py` entrega `candidatos.md`: trechos de ~40 s que subiram na **prioridade** (volume, ritmo de fala, exclamações e perguntas, abertura limpa e, com replay, chat). Marcas no texto das janelas:

- `ALTO+9dB`: o falante ficou 9 dB acima do volume normal daqueles minutos (grito, risada, susto).
- `CHAT x3.1`: o chat andou 3,1 vezes mais rápido; alguma coisa aconteceu uns segundos antes.

As marcas dizem onde olhar. Quem decide é a leitura: grito sem contexto não vira corte, e opinião forte dita baixo vira.

## Os quatro portões

O momento só segue se as quatro respostas forem sim.

1. **Entende em três segundos?** Quem nunca viu a gravação entende sem "como eu falei antes".
2. **Abre limpo?** Começa na frase que arma a cena, não em "então", "aí", "tipo", nem no meio de um raciocínio. Volte até a frase que apresenta o assunto.
3. **Fecha no alto?** Termina na risada, no grito, na frase de efeito, sem a explicação que vem depois.
4. **É uma ideia só?** Dois assuntos são dois cortes, ou nenhum.

## A nota, de 0 a 100

| Vale | Pergunta |
|---|---|
| 25 | **Gancho:** os três primeiros segundos seguram quem está rolando o feed? |
| 25 | **Entrega:** o que o começo promete, o final paga? |
| 20 | **Autonomia:** funciona sem contexto, sem imagem, só com a fala e a legenda? |
| 20 | **Reação:** dá vontade de comentar, discordar ou mandar para alguém? |
| 10 | **Sinal:** tem marca de volume ou de chat que confirma a leitura? |

Seja duro. Numa live de quatro horas a maioria dos trechos fica abaixo de 70. Nota alta para tudo estraga a escolha. Só entram no `momentos.json` as notas de 60 para cima.

## Tipos que costumam render

primeira reação · descoberta (segredo, bug, jeito de fazer) · surto (perdeu a linha de raiva, medo ou riso) · falha engraçada · opinião forte · história curta (começo, meio e fim em menos de um minuto) · resposta ao chat (doação, pergunta ou provocação que rende) · explicação que cabe em 30 s (aula, podcast).

## Tamanho

20 a 45 s é o ideal. Menos de 15 s não dá tempo de entender. Mais de 60 s só para história que não se parte.

## Título, legenda e hashtags

- **Título** (aparece no corte): até 45 letras, diz quem e o que acontece sem entregar o final, só com o que é dito no trecho.
- **Legenda do post:** uma ou duas frases no jeito da pessoa, com pergunta no fim quando couber.
- **Hashtags:** de quatro a seis: assunto, quem fala, o tema do momento, `#cortes`.
- Nomes: de `info.json` e `resumo.md`, como estão lá.

## O arquivo

`garimpos/<id>/momentos.json`. `inicio` e `fim` são os tempos entre colchetes de `candidatos.md` e das janelas; o `conferir.py` acerta os dois nas bordas das frases.

```json
{"momentos": [
  {"inicio": "1:23:45", "fim": "1:24:20", "nota": 87, "tipo": "primeira reação",
   "titulo": "Fulano vê o mapa pela primeira vez",
   "por_que": "espanto de verdade, fecha numa frase que todo mundo vai repetir",
   "legenda": "A cara dele quando o mapa abriu. Você também ficou assim?",
   "hashtags": ["#jogo", "#fulano", "#cortes", "#live"]}
]}
```
