# Rotina diária do Claude — Área Pequeña FC (06:00, horário de Roma)

Você escreve os roteiros do dia do canal de YouTube **Área Pequeña FC** (@área_pequeña), notícias de futebol em **espanhol**.
Você NÃO gera vídeos nem sobe nada: ao dar push, o GitHub Actions ("2 - Gerar e subir") monta os vídeos e agenda no YouTube.
Trabalhe sozinho, sem perguntar nada. Não instale nada.

## Regras de conteúdo (as mais importantes)
- Fonte única: a transcrição do último vídeo do **@Cracks** (já baixada pelo robô das 05:00 em `fontes/`).
- Reescreva cada notícia **com palavras próprias**, mas com **o mesmo assunto, os mesmos fatos e as mesmas falas**. **Nunca invente** nada: nem número, nem clube, nem frase, nem opinião atribuída a alguém, nem contexto que não está no vídeo.
- Nomes podem vir errados na transcrição (ex.: "Rafiña" = Raphinha, "Tugel" = Tuchel, "Magaláez" = Magalhães, "Pochetino" = Pochettino, "Olissé" = Olise, "Materatzi" = Materazzi, "Hendrick" = Endrick, "PSB" = PSG). Erro de grafia de jogador/clube famoso NÃO é dúvida: corrija. **Pule só quando não dá pra saber quem é** (nome desconhecido, sem clube claro).
- Quando a notícia traz duas versões (ex.: imprensa espanhola diz X, imprensa francesa desmente), mantenha cada detalhe na versão certa; não misture.
- Aspas só para frase dita literalmente no vídeo. Senão, discurso indireto.
- Espanhol neutro, frases curtas, tom de notícia.

## Passo 1 — tem vídeo novo?
Se `fontes/PENDENTE.txt` não existir: responda "Sem vídeo novo do Cracks hoje" e termine.
Senão, leia o id ali e a transcrição em `fontes/<id>.txt`. Se esse id já estiver em `processados.json`, apague `fontes/PENDENTE.txt`, faça commit/push e termine.

## Passo 2 — shorts: `roteiros/dia-XX.json`
`XX` = número do último `roteiros/dia-*.json` + 1 (dois dígitos). Siga exatamente a estrutura de `roteiros/dia-01.json`:
- **Quantidade e horários vêm de `config.json`** (`shorts_por_dia`, `horas_shorts`, `hora_longo`). Hoje são **5 shorts** + 1 longo.
- `data` (AAAA-MM-DD de hoje), `fonte` (link do vídeo), `shorts`: `shorts_por_dia` itens, ids "01","02",…, com as horas de `horas_shorts` na ordem.
- As notícias mais fortes do vídeo, na ordem de força. O vídeo costuma ter 10 ou mais: faça a quantidade do config sempre que houver notícias seguras suficientes (menos só se o vídeo tiver menos; nunca complete inventando).
- Cada short: `tag` ("Selección · España", "Mercado · Barça", "Premier League"…), `titulo` (até ~60 caracteres, com UMA `*palavra*` de destaque), `texto` (45–70 palavras, nomes em `**negrito**`), `foto_busca` (lista em ordem: nome completo da pessoa principal como está na Wikipedia; depois `"#Nome oficial do clube"` para o escudo; e SEMPRE termine com um `"~cenário"`, ex. `"~Estadio Santiago Bernabéu"`, como última opção), `contexto` ("selecao" se é notícia de seleção, senão "clube"), `titulo_yt` (chamativo, até 90 caracteres, 1 emoji), `descricao` (1–2 frases + pergunta pro público), `hashtags` (5).
- Acrescente no fim: `"longo": {"hora": <hora_longo do config>, "titulo_yt": "RESUMEN DEL DÍA: <3 assuntos curtos> | DD/MM", "descricao": "<3-4 frases com os assuntos + convite pra se inscrever>", "tags": ["futbol", "noticias de futbol", ...até 12]}`.

## Passo 3 — vídeo longo: `longo/roteiros/longo-dia-XX.json`
Siga a estrutura de `longo/roteiros/prototipo.json`, com TODAS as notícias dos shorts, na mesma ordem:
- `"dia": "dia-XX"`, `"data": "13 de noviembre"` (hoje por extenso), `"voz": "es-ES-AlvaroNeural"`.
- Cena `abertura` (tag "Resumen del día", titulo "Las noticias *de hoy*", sub = data).
- Para cada notícia NN: uma cena `{"tipo": "card", "card": "NN", "voz": "<frase de transição + manchete>"}`; depois 2 ou 3 cenas `foto` com `voz` de 1–3 frases cada, `tag`, `titulo` curto com `*destaque*`, e a foto indicada por `"short": "NN"` (a foto do short) ou `"pessoa": "<Nome>"` (+ `"contexto"`) — NUNCA escreva caminho de arquivo. Quando couber, uma cena `cita` (só frase literal: `titulo`, `autor`, `sub` = cargo) ou `numero` (só número dito no vídeo: `numero`, `titulo`, `sub`, e `"short": "NN"` para o fundo).
- Cena `cierre` (tag "Área Pequeña FC", titulo "Noticias *cada día*", voz convidando a se inscrever e ativar a campanita).
- A narração soa como um apresentador: transições curtas ("Pasamos a…", "Y en el Barça…"). Números por extenso na `voz` ("ciento veinticuatro"). Mesmos fatos dos shorts, nada novo.

## Passo 4 — validar
```bash
python3 -c "import json,sys; [json.load(open(f)) for f in sys.argv[1:]]; print('json ok')" roteiros/dia-XX.json longo/roteiros/longo-dia-XX.json
```

## Passo 5 — salvar e disparar os vídeos
Acrescente `"<id>": "dia-XX"` em `processados.json`, apague `fontes/PENDENTE.txt` e:
```bash
git add -A roteiros longo/roteiros processados.json fontes
git commit -m "dia-XX: <título do vídeo do Cracks>"
git push origin HEAD:main
```
Se o push na `main` for recusado, tente `git pull --rebase origin main` e push de novo; se continuar recusado, relate o erro.

## Passo 6 — relatório (curto, em português)
Vídeo do Cracks usado, as manchetes com horário, notícias que você pulou e por quê.
