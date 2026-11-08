# 🐤 Agente Iowa Hawkeyes

Agente automático que verifica **quando** e **onde assistir** os jogos do time de
**futebol americano universitário masculino do Iowa Hawkeyes** (University of Iowa,
NCAA FBS / Big Ten) e envia um e-mail com a identidade
visual do time (preto `#000000` e dourado `#FFCD00`, logo Tigerhawk) para
`geraldoschuetze@gmail.com`.

- **Fonte:** API pública do ESPN (calendário + emissoras de TV), sem chave.
- **Horários:** convertidos para Brasília (também mostra CT/ET).
- **Links:** cada canal vira um botão para o streaming americano correspondente
  (FOX One/FS1/BTN, Peacock, Paramount+, ESPN, HBO Max, B1G+…) — use VPN nos EUA.
- **Quando envia** (GitHub Actions, todo dia às 09:00 de Brasília):
  - **segunda-feira** → resumo com o jogo da semana (+ os próximos 3 jogos);
  - **dia de jogo** → lembrete “É dia de jogo!” com horário e canal.

## Configuração (uma vez)

1. Crie uma **senha de app** do Gmail: <https://myaccount.google.com/apppasswords>
   (precisa da verificação em 2 etapas ativa).
2. No GitHub: *Settings → Secrets and variables → Actions → New repository secret*:
   - `SMTP_USER` = `geraldoschuetze@gmail.com`
   - `SMTP_PASSWORD` = a senha de app de 16 caracteres
   - `MAIL_TO` (opcional) = outro destinatário
3. Teste: *Actions → Iowa Hawkeyes agent → Run workflow* (modo `digest`).

## Rodar localmente

```bash
DRY_RUN=1 MODE=digest python hawkeyes-agent/hawkeyes_agent.py   # gera preview.html
FIXTURE=hawkeyes-agent/fixture_nov2026.json DRY_RUN=1 MODE=digest python hawkeyes-agent/hawkeyes_agent.py
```

> O GitHub pausa agendamentos de repositórios sem atividade por 60 dias; se isso
> acontecer, basta reativar o workflow na aba *Actions*.
