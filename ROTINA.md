# Rotina diária do Claude — Área Pequeña FC (08:00, horário de Roma)

Você escreve os roteiros do dia do canal de YouTube **Área Pequeña FC** (@área_pequeña), notícias de futebol em **espanhol**.
Você NÃO gera vídeos nem sobe nada: ao dar push, o GitHub Actions ("2 - Gerar e subir") monta os vídeos e agenda no YouTube.
Trabalhe sozinho, sem perguntar nada. Não instale nada.

## Regras de conteúdo (as mais importantes)
- Fontes (o robô das 06:17 já baixou em `fontes/`):
  1. **`fontes/noticias-AAAA-MM-DD.txt`** (data de hoje): manchetes, resumos e texto das matérias da **MARCA, AS e Mundo Deportivo** das últimas ~26 h. É a fonte principal e existe todo dia.
  2. **Vídeo do @Cracks** (só se `fontes/PENDENTE.txt` existir): a transcrição em `fontes/<id>.txt`. Fonte extra.
- Escolha as notícias **mais fortes do dia** para o público de futebol em espanhol: estrelas (Mbappé, Lamine, Vini, Bellingham, Messi, Cristiano…), Real Madrid, Barça, Atlético, seleções grandes, mercado, polêmicas, frases fortes. Prefira o que aparece em **mais de uma fonte** (mais confiável e mais quente). Evite: futebol regional/base, notícias de serviço (horários, onde ver), opinião/coluna sem fato novo, outros esportes, matérias que não são de futebol.
- Reescreva cada notícia **com palavras próprias**, mas com **os mesmos fatos e as mesmas falas** da fonte. **Nunca invente** nada: nem número, nem clube, nem frase, nem opinião atribuída a alguém, nem contexto que não está na fonte. Não copie frases inteiras do jornal (só as aspas de quem falou).
- **Cite a fonte**: na `descricao` de cada short, termine com "Fuente: MARCA" / "Fuente: AS" / "Fuente: Mundo Deportivo" / "Fuente: Cracks" (a que você usou; se usou duas, as duas). No campo `fonte` de cada short ponha o link.
- **Fotos dos jornais NUNCA**: as imagens continuam vindo do nosso banco (o robô busca sozinho pela `foto_busca`).
- Nomes podem vir errados na transcrição (ex.: "Rafiña" = Raphinha, "Tugel" = Tuchel, "Magaláez" = Magalhães, "Pochetino" = Pochettino, "Olissé" = Olise, "Materatzi" = Materazzi, "Hendrick" = Endrick, "PSB" = PSG). Erro de grafia de jogador/clube famoso NÃO é dúvida: corrija. **Pule só quando não dá pra saber quem é** (nome desconhecido, sem clube claro).
- Quando a notícia traz duas versões (ex.: imprensa espanhola diz X, imprensa francesa desmente), mantenha cada detalhe na versão certa; não misture.
- Aspas só para frase dita literalmente (que está entre aspas na matéria ou falada no vídeo). Senão, discurso indireto.
- Espanhol neutro, frases curtas, tom de notícia.

## Passo 1 — já foi feito hoje? tem fonte?
- Data de hoje em Roma: `TZ=Europe/Rome date +%F`.
- Se algum `roteiros/dia-*.json` já tiver `"data": "<hoje>"`: responda "Roteiro de hoje já existe" e termine.
- Leia `fontes/noticias-<hoje>.txt`. Se não existir, use o mais recente `fontes/noticias-*.txt` de ontem só se tiver menos de 30 h; se não houver nenhum, rode `python3 noticias.py` (pode falhar por rede) e, sem fonte nenhuma, termine relatando.
- Se `fontes/PENDENTE.txt` existir, leia também a transcrição do Cracks `fontes/<id>.txt` (se o id já estiver em `processados.json`, ignore-a).

## Passo 2 — shorts: `roteiros/dia-XX.json`
`XX` = número do último `roteiros/dia-*.json` + 1 (dois dígitos). Siga exatamente a estrutura de `roteiros/dia-01.json`:
- **Quantidade e horários vêm de `config.json`** (`shorts_por_dia`, `horas_shorts`, `hora_longo`). Hoje são **5 shorts** + 1 longo.
- `data` (AAAA-MM-DD de hoje), `fonte` ("MARCA, AS, Mundo Deportivo" + link do Cracks se usou), `shorts`: `shorts_por_dia` itens, ids "01","02",…, com as horas de `horas_shorts` na ordem.
- As notícias mais fortes do dia, na ordem de força (a mais forte às 10:00). Sempre faça a quantidade do config: há notícias de sobra nas fontes; nunca complete inventando.
- Cada short: `tag` ("Selección · España", "Mercado · Barça", "Premier League"…), `titulo` (até ~60 caracteres, com UMA `*palavra*` de destaque), `texto` (45–70 palavras, nomes em `**negrito**`), `foto_busca` (lista em ordem: nome completo da pessoa principal como está na Wikipedia; depois `"#Nome oficial do clube"` para o escudo; e SEMPRE termine com um `"~cenário"`, ex. `"~Estadio Santiago Bernabéu"`, como última opção), `contexto` ("selecao" se é notícia de seleção, senão "clube"), `titulo_yt` (chamativo, até 90 caracteres, 1 emoji), `descricao` (1–2 frases + pergunta pro público + "Fuente: …"), `fonte` (link da matéria), `hashtags` (5).
- Acrescente no fim: `"longo": {"hora": <hora_longo do config>, "titulo_yt": "RESUMEN DEL DÍA: <3 assuntos curtos> | DD/MM", "descricao": "<3-4 frases com os assuntos + convite pra se inscrever>", "tags": ["futbol", "noticias de futbol", ...até 12]}`.

## Passo 3 — vídeo longo: `longo/roteiros/longo-dia-XX.json`
Siga a estrutura de `longo/roteiros/prototipo.json`, com TODAS as notícias dos shorts, na mesma ordem:
- `"dia": "dia-XX"`, `"data": "13 de noviembre"` (hoje por extenso), `"voz": "es-ES-AlvaroNeural"`.
- Cena `abertura` (tag "Resumen del día", titulo "Las noticias *de hoy*", sub = data).
- Para cada notícia NN: uma cena `{"tipo": "card", "card": "NN", "voz": "<frase de transição + manchete>"}`; depois 2 ou 3 cenas `foto` com `voz` de 1–3 frases cada, `tag`, `titulo` curto com `*destaque*`, e a foto indicada por `"short": "NN"` (a foto do short) ou `"pessoa": "<Nome>"` (+ `"contexto"`) — NUNCA escreva caminho de arquivo. Quando couber, uma cena `cita` (só frase literal: `titulo`, `autor`, `sub` = cargo) ou `numero` (só número dito no vídeo: `numero`, `titulo`, `sub`, e `"short": "NN"` para o fundo).
- Cena `cierre` (tag "Área Pequeña FC", titulo "Noticias *cada día*", voz convidando a se inscrever e ativar a campanita).
- A narração soa como um apresentador: transições curtas ("Pasamos a…", "Y en el Barça…"). Números por extenso na `voz` ("ciento veinticuatro"). Mesmos fatos dos shorts, nada novo (pode usar mais detalhes da MESMA matéria).

## Passo 4 — validar
```bash
python3 -c "import json,sys; [json.load(open(f)) for f in sys.argv[1:]]; print('json ok')" roteiros/dia-XX.json longo/roteiros/longo-dia-XX.json
```

## Passo 5 — salvar e disparar os vídeos
Se usou (ou ignorou) um vídeo do Cracks: acrescente `"<id>": "dia-XX"` em `processados.json` e apague `fontes/PENDENTE.txt`. Depois:
```bash
git add -A roteiros longo/roteiros processados.json fontes
git commit -m "dia-XX: <3 assuntos do dia>"
git push origin HEAD:main
```
Se o push na `main` for recusado, tente `git pull --rebase origin main` e push de novo; se continuar recusado, relate o erro.

## Passo 6 — relatório (curto, em português)
Fontes usadas (quantas de cada jornal, e se teve Cracks), as manchetes com horário e fonte, notícias fortes que você pulou e por quê.
