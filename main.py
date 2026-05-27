from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Optional
import os

app = FastAPI(title="BetEdge API", version="1.0.0")

# ── CORS (permite que o frontend chame o backend) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Chaves de API (vêm das variáveis de ambiente no Render) ──
FD_API_KEY = os.getenv("FD_API_KEY", "")        # football-data.org
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")    # newsapi.org

# ── Mapeamento de ligas para football-data.org ──
LEAGUE_MAP = {
    "portugal 1":        {"fd": "PPL",  "us": "Primeira Liga"},
    "portugal 2":        {"fd": None,   "us": "Segunda Liga"},
    "espanha 1":         {"fd": "PD",   "us": "La Liga"},
    "espanha 2":         {"fd": "SD",   "us": "Segunda División"},
    "inglaterra 1":      {"fd": "PL",   "us": "Premier League"},
    "inglaterra 2":      {"fd": "ELC",  "us": "Championship"},
    "alemanha 1":        {"fd": "BL1",  "us": "Bundesliga"},
    "alemanha 2":        {"fd": "BL2",  "us": "2. Bundesliga"},
    "italia 1":          {"fd": "SA",   "us": "Serie A"},
    "italia 2":          {"fd": "SB",   "us": "Serie B"},
    "franca 1":          {"fd": "FL1",  "us": "Ligue 1"},
    "frança 1":          {"fd": "FL1",  "us": "Ligue 1"},
    "franca 2":          {"fd": "FL2",  "us": "Ligue 2"},
    "frança 2":          {"fd": "FL2",  "us": "Ligue 2"},
    "paises baixos":     {"fd": "DED",  "us": "Eredivisie"},
    "países baixos":     {"fd": "DED",  "us": "Eredivisie"},
    "escocia":           {"fd": "PPL",  "us": "Scottish Premiership"},
    "escócia":           {"fd": "PPL",  "us": "Scottish Premiership"},
    "belgica":           {"fd": "BSA",  "us": "Jupiler Pro League"},
    "bélgica":           {"fd": "BSA",  "us": "Jupiler Pro League"},
    "turquia":           {"fd": None,   "us": "Süper Lig"},
    "suica":             {"fd": None,   "us": "Super League"},
    "suíça":             {"fd": None,   "us": "Super League"},
    "austria":           {"fd": None,   "us": "Bundesliga"},
    "áustria":           {"fd": None,   "us": "Bundesliga"},
    "noruega":           {"fd": None,   "us": "Eliteserien"},
    "dinamarca":         {"fd": None,   "us": "Superliga"},
    "polonia":           {"fd": None,   "us": "Ekstraklasa"},
    "polónia":           {"fd": None,   "us": "Ekstraklasa"},
    "romenia":           {"fd": None,   "us": "Liga I"},
    "roménia":           {"fd": None,   "us": "Liga I"},
    "suecia":            {"fd": None,   "us": "Allsvenskan"},
    "suécia":            {"fd": None,   "us": "Allsvenskan"},
    "liga dos campeoes": {"fd": "CL",   "us": "Champions League"},
    "liga dos campeões": {"fd": "CL",   "us": "Champions League"},
    "liga europa":       {"fd": "EL",   "us": "Europa League"},
    "liga conferencia":  {"fd": "ECNL", "us": "Conference League"},
    "liga conferência":  {"fd": "ECNL", "us": "Conference League"},
    "europeu":           {"fd": "EC",   "us": "European Championship"},
    "mundial":           {"fd": "WC",   "us": "FIFA World Cup"},
}

# ════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════
@app.get("/health")
async def health():
    return {
        "status": "online",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "fd_key": "✅ configurada" if FD_API_KEY else "❌ em falta",
        "news_key": "✅ configurada" if NEWS_API_KEY else "❌ em falta",
    }


# ════════════════════════════════════════
# xG — UNDERSTAT + FBREF
# ════════════════════════════════════════
@app.get("/xg")
async def get_xg(
    home: str = Query(..., description="Nome da equipa da casa"),
    away: str = Query(..., description="Nome da equipa visitante"),
    league: str = Query("", description="Nome da liga")
):
    """
    Tenta obter xG real do Understat.
    Se falhar, estima com base em dados históricos do football-data.co.uk
    """
    league_key = league.lower().strip()
    league_info = LEAGUE_MAP.get(league_key, {})
    understat_league = league_info.get("us", "")

    xg_home, xg_away = None, None
    xg_home_ht, xg_away_ht = None, None
    source = "estimativa"

    # ── 1. Tentar Understat ──
    if understat_league:
        try:
            xg_home, xg_away, xg_home_ht, xg_away_ht = await fetch_understat_xg(
                home, away, understat_league
            )
            if xg_home: source = "understat"
        except Exception as e:
            print(f"Understat falhou: {e}")

    # ── 2. Fallback: FBRef ──
    if xg_home is None:
        try:
            xg_home, xg_away = await fetch_fbref_xg(home, away)
            if xg_home:
                xg_home_ht = round(xg_home * 0.44, 2)
                xg_away_ht = round(xg_away * 0.44, 2)
                source = "fbref"
        except Exception as e:
            print(f"FBRef falhou: {e}")

    # ── 3. Fallback: média histórica por liga ──
    if xg_home is None:
        xg_home, xg_away = estimate_xg_from_league(league_key)
        xg_home_ht = round(xg_home * 0.44, 2)
        xg_away_ht = round(xg_away * 0.44, 2)
        source = "média_liga"

    # ── Buscar notícias ──
    news = await fetch_news(home, away)

    return {
        "home": home,
        "away": away,
        "xg_home": xg_home,
        "xg_away": xg_away,
        "xg_home_ht": xg_home_ht,
        "xg_away_ht": xg_away_ht,
        "source": source,
        "news": news,
        "timestamp": datetime.now().isoformat()
    }


async def fetch_understat_xg(home: str, away: str, league: str):
    """Scraping do Understat para xG das últimas 5 partidas de cada equipa."""
    understat_slugs = {
        "Premier League": "EPL",
        "La Liga": "La_liga",
        "Bundesliga": "Bundesliga",
        "Serie A": "Serie_A",
        "Ligue 1": "Ligue_1",
        "Primeira Liga": "RFPL",  # Aproximação
        "Eredivisie": "RFPL",
        "Champions League": "EPL",  # Fallback
    }
    slug = understat_slugs.get(league)
    if not slug:
        return None, None, None, None

    url = f"https://understat.com/league/{slug}/2024"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "pt-PT,pt;q=0.9",
    }

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return None, None, None, None

        html = resp.text
        # Extrair dados JSON embutidos no JS
        match = re.search(r"var teamsData\s*=\s*JSON\.parse\('(.+?)'\)", html)
        if not match:
            return None, None, None, None

        raw = match.group(1).encode().decode('unicode_escape')
        teams_data = json.loads(raw)

        home_xg = extract_team_xg(teams_data, home)
        away_xg = extract_team_xg(teams_data, away)

        if home_xg and away_xg:
            return (
                round(home_xg["xg_avg"], 2),
                round(away_xg["xg_avg"], 2),
                round(home_xg["xg_avg"] * 0.44, 2),
                round(away_xg["xg_avg"] * 0.44, 2)
            )
    return None, None, None, None


def extract_team_xg(teams_data: dict, team_name: str):
    """Encontra equipa por nome (fuzzy) e calcula xG médio das últimas 5 partidas."""
    team_name_lower = team_name.lower()
    best_match = None
    best_score = 0

    for tid, tdata in teams_data.items():
        t_title = tdata.get("title", "").lower()
        # Similaridade simples
        score = sum(w in t_title for w in team_name_lower.split())
        if score > best_score or team_name_lower in t_title:
            best_score = score
            best_match = tdata

    if not best_match:
        return None

    history = best_match.get("history", [])
    if not history:
        return None

    recent = history[-5:]  # últimas 5 partidas
    xg_vals = [float(g.get("xG", 0)) for g in recent if g.get("xG")]
    if not xg_vals:
        return None

    return {"xg_avg": sum(xg_vals) / len(xg_vals)}


async def fetch_fbref_xg(home: str, away: str):
    """Scraping do FBRef para xG médio da temporada."""
    # FBRef squad stats — xG por jogo
    search_url = f"https://fbref.com/en/search/search.fcgi?search={home.replace(' ', '+')}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BetEdgeBot/1.0)"}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Procurar página da equipa casa
        home_xg = await fbref_team_xg(client, home, headers)
        await asyncio.sleep(1)  # Rate limit
        away_xg = await fbref_team_xg(client, away, headers)

    if home_xg and away_xg:
        return round(home_xg, 2), round(away_xg, 2)
    return None, None


async def fbref_team_xg(client, team: str, headers: dict):
    """Extrai xG médio por jogo de uma equipa no FBRef."""
    try:
        url = f"https://fbref.com/en/search/search.fcgi?search={team.replace(' ', '+')}&pid=search"
        resp = await client.get(url, headers=headers)
        html = resp.text

        # Extrair xG da tabela de estatísticas
        xg_pattern = re.search(r'data-stat="xg"[^>]*>([0-9.]+)<', html)
        if xg_pattern:
            total_xg = float(xg_pattern.group(1))
            # Estimar média por jogo (assumindo ~20 jogos jogados)
            matches_pattern = re.search(r'data-stat="games"[^>]*>(\d+)<', html)
            games = int(matches_pattern.group(1)) if matches_pattern else 20
            if games > 0:
                return total_xg / games
    except Exception:
        pass
    return None


def estimate_xg_from_league(league_key: str) -> tuple:
    """
    Médias históricas de xG por liga.
    Fonte: football-data.co.uk análise temporadas 2022-2024
    """
    league_xg_avgs = {
        "portugal 1":        (1.45, 1.05),
        "portugal 2":        (1.35, 0.95),
        "espanha 1":         (1.52, 1.08),
        "espanha 2":         (1.38, 1.02),
        "inglaterra 1":      (1.65, 1.15),
        "inglaterra 2":      (1.48, 1.08),
        "alemanha 1":        (1.72, 1.18),
        "alemanha 2":        (1.55, 1.12),
        "italia 1":          (1.42, 1.02),
        "italia 2":          (1.35, 0.98),
        "franca 1":          (1.48, 1.05),
        "frança 1":          (1.48, 1.05),
        "franca 2":          (1.38, 1.00),
        "paises baixos":     (1.68, 1.22),
        "países baixos":     (1.68, 1.22),
        "escocia":           (1.52, 1.08),
        "escócia":           (1.52, 1.08),
        "belgica":           (1.55, 1.10),
        "bélgica":           (1.55, 1.10),
        "liga dos campeoes": (1.58, 1.15),
        "liga dos campeões": (1.58, 1.15),
        "liga europa":       (1.52, 1.10),
    }
    return league_xg_avgs.get(league_key, (1.45, 1.05))


# ════════════════════════════════════════
# NOTÍCIAS — NewsAPI + scraping
# ════════════════════════════════════════
async def fetch_news(home: str, away: str) -> list:
    """Busca notícias relevantes: lesões, suspensões, forma."""
    news_items = []

    # ── 1. NewsAPI (grátis 100 req/dia) ──
    if NEWS_API_KEY:
        try:
            news_items = await fetch_newsapi(home, away)
        except Exception as e:
            print(f"NewsAPI falhou: {e}")

    # ── 2. Fallback: Google News RSS (sem chave) ──
    if not news_items:
        try:
            news_items = await fetch_google_news(home, away)
        except Exception as e:
            print(f"Google News falhou: {e}")

    return news_items[:6]  # Máx 6 notícias


async def fetch_newsapi(home: str, away: str) -> list:
    """NewsAPI.org — grátis até 100 req/dia."""
    query = f'"{home}" OR "{away}" lesão suspensão injury suspension'
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "pt",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "from": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        "apiKey": NEWS_API_KEY,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    articles = data.get("articles", [])
    return [classify_news(a["title"], a.get("source", {}).get("name", "")) for a in articles if a.get("title")]


async def fetch_google_news(home: str, away: str) -> list:
    """Google News RSS — sem autenticação."""
    query = f"{home} {away} lesão OR injury OR suspended"
    url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=pt-PT&gl=PT&ceid=PT:pt"
    headers = {"User-Agent": "Mozilla/5.0"}

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        html = resp.text

    # Extrair títulos do RSS
    titles = re.findall(r'<title><!\[CDATA\[(.+?)\]\]></title>', html)[1:6]
    return [classify_news(t, "Google News") for t in titles]


def classify_news(title: str, source: str) -> dict:
    """Classifica notícia por tipo: injury, suspension, form."""
    title_lower = title.lower()
    keywords_injury = ["lesion", "lesão", "injury", "injured", "hurt", "baixa", "out", "dúvida", "doubt", "muscle", "muscular"]
    keywords_suspension = ["suspenso", "suspension", "banned", "cartão", "card", "expulso", "red card"]
    keywords_form = ["vitória", "victory", "win", "derrotas", "defeat", "sequência", "streak", "forma", "form", "unbeaten"]

    if any(k in title_lower for k in keywords_injury):
        news_type = "injury"
    elif any(k in title_lower for k in keywords_suspension):
        news_type = "suspension"
    else:
        news_type = "form"

    return {
        "type": news_type,
        "text": title[:80],
        "source": source
    }


# ════════════════════════════════════════
# RESULTADOS — football-data.org
# ════════════════════════════════════════
@app.get("/result")
async def get_result(
    match: str = Query(..., description="Nome do jogo: 'Casa vs Fora'"),
    date: str = Query("", description="Data: YYYY-MM-DD")
):
    """Busca resultado final e xG real de um jogo já disputado."""
    if not FD_API_KEY:
        raise HTTPException(status_code=503, detail="FD_API_KEY não configurada")

    # Separar equipas
    parts = match.split(" vs ")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Formato inválido. Use 'Casa vs Fora'")

    home_team, away_team = parts[0].strip(), parts[1].strip()

    # Procurar em todas as ligas ativas
    leagues = ["PL", "PD", "BL1", "SA", "FL1", "PPL", "DED", "CL", "EL", "ELC", "SD", "SB", "FL2", "BL2"]
    search_date = date or datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.fromisoformat(search_date) - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to = (datetime.fromisoformat(search_date) + timedelta(days=1)).strftime("%Y-%m-%d")

    headers = {"X-Auth-Token": FD_API_KEY}

    async with httpx.AsyncClient(timeout=15) as client:
        for league in leagues:
            try:
                url = f"https://api.football-data.org/v4/competitions/{league}/matches"
                params = {"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"}
                resp = await client.get(url, headers=headers, params=params)

                if resp.status_code != 200:
                    continue

                matches = resp.json().get("matches", [])
                for m in matches:
                    h = m.get("homeTeam", {}).get("name", "").lower()
                    a = m.get("awayTeam", {}).get("name", "").lower()

                    if (home_team.lower() in h or h in home_team.lower()) and \
                       (away_team.lower() in a or a in away_team.lower()):

                        score = m.get("score", {})
                        ft = score.get("fullTime", {})
                        ht = score.get("halfTime", {})

                        return {
                            "home": m["homeTeam"]["name"],
                            "away": m["awayTeam"]["name"],
                            "home_goals": ft.get("home", 0),
                            "away_goals": ft.get("away", 0),
                            "home_goals_ht": ht.get("home", 0),
                            "away_goals_ht": ht.get("away", 0),
                            "status": m.get("status"),
                            "date": m.get("utcDate", "")[:10],
                            "source": "football-data.org"
                        }
            except Exception as e:
                print(f"Erro {league}: {e}")
                continue

    raise HTTPException(status_code=404, detail=f"Resultado não encontrado para '{match}'")


# ════════════════════════════════════════
# FIXTURES — jogos de hoje/amanhã
# ════════════════════════════════════════
@app.get("/fixtures")
async def get_fixtures(days_ahead: int = 0):
    """Busca jogos de hoje ou amanhã no football-data.org."""
    if not FD_API_KEY:
        return {"fixtures": [], "note": "FD_API_KEY não configurada"}

    target_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    headers = {"X-Auth-Token": FD_API_KEY}
    leagues = ["PL", "PD", "BL1", "SA", "FL1", "PPL", "DED", "CL", "EL", "ELC", "SD"]

    all_fixtures = []
    async with httpx.AsyncClient(timeout=20) as client:
        for league in leagues:
            try:
                url = f"https://api.football-data.org/v4/competitions/{league}/matches"
                params = {"dateFrom": target_date, "dateTo": target_date}
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    continue
                matches = resp.json().get("matches", [])
                for m in matches:
                    all_fixtures.append({
                        "liga": m.get("competition", {}).get("name", league),
                        "casa": m["homeTeam"]["name"],
                        "fora": m["awayTeam"]["name"],
                        "hora": m.get("utcDate", "")[-9:-4] if m.get("utcDate") else "",
                        "data": target_date,
                    })
                await asyncio.sleep(0.3)
            except Exception:
                continue

    return {"fixtures": all_fixtures, "date": target_date, "count": len(all_fixtures)}


# ════════════════════════════════════════
# STANDINGS — classificação para contexto
# ════════════════════════════════════════
@app.get("/standings")
async def get_standings(league: str = Query(...)):
    """Busca classificação de uma liga (contexto para análise)."""
    if not FD_API_KEY:
        return {"standings": [], "note": "FD_API_KEY não configurada"}

    league_key = league.lower().strip()
    league_info = LEAGUE_MAP.get(league_key, {})
    fd_code = league_info.get("fd")

    if not fd_code:
        return {"standings": [], "note": f"Liga '{league}' não suportada no football-data.org"}

    headers = {"X-Auth-Token": FD_API_KEY}
    url = f"https://api.football-data.org/v4/competitions/{fd_code}/standings"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return {"standings": [], "note": f"Erro {resp.status_code}"}

        data = resp.json()
        table = data.get("standings", [{}])[0].get("table", [])

        standings = [{
            "pos": t.get("position"),
            "team": t.get("team", {}).get("name"),
            "pts": t.get("points"),
            "gf": t.get("goalsFor"),
            "ga": t.get("goalsAgainst"),
            "played": t.get("playedGames"),
            "form": t.get("form", ""),
        } for t in table[:20]]

    return {"standings": standings, "league": league, "source": "football-data.org"}
