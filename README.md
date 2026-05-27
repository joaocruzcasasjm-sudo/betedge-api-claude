# BetEdge API

Backend do BetEdge — análise de apostas com Dixon-Coles + xG.

## Endpoints

| Endpoint | Descrição |
|----------|-----------|
| `GET /health` | Estado do servidor |
| `GET /xg?home=X&away=Y&league=Z` | xG das equipas + notícias |
| `GET /result?match=X vs Y&date=YYYY-MM-DD` | Resultado final de um jogo |
| `GET /fixtures?days_ahead=0` | Jogos de hoje/amanhã |
| `GET /standings?league=X` | Classificação de uma liga |

## Deploy no Render (Grátis)

1. Faz fork/upload deste repositório no GitHub
2. Vai a render.com → New Web Service → liga ao repositório
3. Adiciona as variáveis de ambiente:
   - `FD_API_KEY` — em football-data.org (grátis)
   - `NEWS_API_KEY` — em newsapi.org (grátis)
4. Deploy automático!

## Fontes de Dados

- **Understat** — xG real por jogo (scraping, grátis)
- **FBRef** — xG histórico (scraping, grátis)
- **football-data.org** — resultados e classificações (API grátis)
- **NewsAPI** — notícias (API grátis, 100 req/dia)
- **Google News RSS** — fallback de notícias (sem chave)
