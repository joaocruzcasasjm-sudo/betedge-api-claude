from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Optional
import os

app = FastAPI(title="BetEdge API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FD_API_KEY       = os.getenv("FD_API_KEY", "")        # football-data.org (grátis)
NEWS_API_KEY     = os.getenv("NEWS_API_KEY", "")       # newsapi.org (grátis)
RAPID_API_KEY    = os.getenv("RAPID_API_KEY", "")      # api-football.com (grátis 100/dia — registo em api-football.com)

# ── IDs das ligas no API-Football ──
APIFOOTBALL_LEAGUE_IDS = {
    "portugal 1":        94,
    "portugal 2":        95,
    "espanha 1":         140,
    "espanha 2":         141,
    "inglaterra 1":      39,
    "inglaterra 2":      40,
    "alemanha 1":        78,
    "alemanha 2":        79,
    "italia 1":          135,
    "italia 2":          136,
    "franca 1":          61,
    "frança 1":          61,
    "franca 2":          62,
    "frança 2":          62,
    "paises baixos":     88,
    "países baixos":     88,
    "escocia":           179,
    "escócia":           179,
    "belgica":           144,
    "bélgica":           144,
    "turquia":           203,
    "suica":             207,
    "suíça":             207,
    "austria":           218,
    "áustria":           218,
    "noruega":           103,
    "dinamarca":         119,
    "polonia":           106,
    "polónia":           106,
    "romenia":           283,
    "roménia":           283,
    "suecia":            113,
    "suécia":            113,
    "liga dos campeoes": 2,
    "liga dos campeões": 2,
    "liga europa":       3,
    "liga conferencia":  848,
    "liga conferência":  848,
    "europeu":           960,
    "mundial":           1,
    "liga das nações":   1015,
    "liga das nações":   1015,
}

# ── football-data.org — só grandes ligas ──
FD_LEAGUE_MAP = {
    "espanha 1":         "PD",
    "espanha 2":         "SD",
    "inglaterra 1":      "PL",
    "inglaterra 2":      "ELC",
    "alemanha 1":        "BL1",
    "alemanha 2":        "BL2",
    "italia 1":          "SA",
    "italia 2":          "SB",
    "franca 1":          "FL1",
    "frança 1":          "FL1",
    "franca 2":          "FL2",
    "paises baixos":     "DED",
    "países baixos":     "DED",
    "belgica":           "BSA",
    "bélgica":           "BSA",
    "liga dos campeoes": "CL",
    "liga dos campeões": "CL",
    "liga europa":       "EL",
    "liga conferencia":  "ECNL",
    "liga conferência":  "ECNL",
    "europeu":           "EC",
    "mundial":           "WC",
}

NATIONAL_COMPS = [
    "europeu", "mundial", "liga das nações", "taça das nações",
    "euro", "world cup", "nations league"
]

def is_national(liga: str) -> bool:
    l = liga.lower()
    return any(k in l for k in NATIONAL_COMPS)


# ════════════════════════════════════════
# HEALTH
# ════════════════════════════════════════
@app.get("/health")
async def health():
    return {
        "status": "online",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "fd_key":      "✅" if FD_API_KEY    else "❌ em falta",
        "news_key":    "✅" if NEWS_API_KEY  else "❌ em falta",
        "rapid_key":   "✅ api-football.com" if RAPID_API_KEY else "❌ em falta — regista em api-football.com (grátis)",
    }


# ════════════════════════════════════════
# xG
# ════════════════════════════════════════
@app.get("/xg")
async def get_xg(
    home:   str = Query(...),
    away:   str = Query(...),
    league: str = Query(""),
):
    league_key = league.lower().strip()
    xg_home = xg_away = xg_home_ht = xg_away_ht = None
    source = "estimativa"

    # 1. Understat
    understat_map = {
        "espanha 1": "La_liga", "espanha 2": "La_liga",
        "inglaterra 1": "EPL",  "inglaterra 2": "EPL",
        "alemanha 1": "Bundesliga", "alemanha 2": "Bundesliga",
        "italia 1": "Serie_A",  "italia 2": "Serie_A",
        "franca 1": "Ligue_1",  "frança 1": "Ligue_1",
        "franca 2": "Ligue_1",  "frança 2": "Ligue_1",
        "liga dos campeoes": "EPL", "liga dos campeões": "EPL",
    }
    us_league = understat_map.get(league_key)
    if us_league:
        try:
            xg_home, xg_away, xg_home_ht, xg_away_ht = await fetch_understat_xg(home, away, us_league)
            if xg_home: source = "understat"
        except Exception as e:
            print(f"Understat: {e}")

    # 2. API-Football xG (se tiver RAPID_API_KEY)
    if xg_home is None and RAPID_API_KEY:
        try:
            xg_home, xg_away, xg_home_ht, xg_away_ht = await fetch_apifootball_xg(home, away, league_key)
            if xg_home: source = "api-football"
        except Exception as e:
            print(f"API-Football xG: {e}")

    # 3. FBRef
    if xg_home is None:
        try:
            xg_home, xg_away = await fetch_fbref_xg(home, away)
            if xg_home:
                xg_home_ht = round(xg_home * 0.44, 2)
                xg_away_ht = round(xg_away * 0.44, 2)
                source = "fbref"
        except Exception as e:
            print(f"FBRef: {e}")

    # 4. Média histórica por liga
    if xg_home is None:
        xg_home, xg_away = estimate_xg_from_league(league_key)
        xg_home_ht = round(xg_home * 0.44, 2)
        xg_away_ht = round(xg_away * 0.44, 2)
        source = "média_liga"

    news = await fetch_news(home, away)

    return {
        "home": home, "away": away,
        "xg_home": xg_home, "xg_away": xg_away,
        "xg_home_ht": xg_home_ht, "xg_away_ht": xg_away_ht,
        "source": source, "news": news,
        "timestamp": datetime.now().isoformat()
    }


async def fetch_understat_xg(home, away, league):
    url = f"https://understat.com/league/{league}/2024"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200: return None, None, None, None
        match = re.search(r"var teamsData\s*=\s*JSON\.parse\('(.+?)'\)", resp.text)
        if not match: return None, None, None, None
        raw = match.group(1).encode().decode('unicode_escape')
        teams_data = json.loads(raw)
        home_xg = extract_team_xg(teams_data, home)
        away_xg = extract_team_xg(teams_data, away)
        if home_xg and away_xg:
            return (round(home_xg["xg_avg"], 2), round(away_xg["xg_avg"], 2),
                    round(home_xg["xg_avg"]*0.44, 2), round(away_xg["xg_avg"]*0.44, 2))
    return None, None, None, None


def extract_team_xg(teams_data, team_name):
    team_name_lower = team_name.lower()
    best_match = None
    best_score = 0
    for tid, tdata in teams_data.items():
        t = tdata.get("title", "").lower()
        score = sum(w in t for w in team_name_lower.split())
        if score > best_score or team_name_lower in t:
            best_score = score
            best_match = tdata
    if not best_match: return None
    history = best_match.get("history", [])[-5:]
    xg_vals = [float(g.get("xG", 0)) for g in history if g.get("xG")]
    if not xg_vals: return None
    return {"xg_avg": sum(xg_vals) / len(xg_vals)}


async def fetch_apifootball_xg(home, away, league_key):
    """API-Football — xG das últimas partidas de cada equipa."""
    league_id = APIFOOTBALL_LEAGUE_IDS.get(league_key)
    if not league_id: return None, None, None, None

    headers = {
        "x-apisports-key": RAPID_API_KEY,
    }
    season = datetime.now().year if datetime.now().month >= 7 else datetime.now().year - 1

    async with httpx.AsyncClient(timeout=15) as client:
        # Buscar stats das equipas
        home_xg = await apifootball_team_xg(client, headers, home, league_id, season)
        await asyncio.sleep(0.5)
        away_xg = await apifootball_team_xg(client, headers, away, league_id, season)

    if home_xg and away_xg:
        return (round(home_xg, 2), round(away_xg, 2),
                round(home_xg*0.44, 2), round(away_xg*0.44, 2))
    return None, None, None, None


async def apifootball_team_xg(client, headers, team_name, league_id, season):
    """Busca xG médio por jogo de uma equipa via API-Football."""
    try:
        # Procurar ID da equipa
        url = "https://v3.football.api-sports.io/teams"
        r = await client.get(url, headers=headers, params={"search": team_name})
        data = r.json()
        teams = data.get("response", [])
        if not teams: return None
        team_id = teams[0]["team"]["id"]

        # Buscar estatísticas
        url2 = "https://v3.football.api-sports.io/teams/statistics"
        r2 = await client.get(url2, headers=headers, params={
            "team": team_id, "league": league_id, "season": season
        })
        stats = r2.json().get("response", {})
        fixtures_played = stats.get("fixtures", {}).get("played", {}).get("total", 0)
        goals_for = stats.get("goals", {}).get("for", {}).get("total", {}).get("total", 0)

        if fixtures_played > 0:
            # API-Football free não dá xG direto — usar média de golos como proxy
            return goals_for / fixtures_played
    except Exception as e:
        print(f"API-Football team xG: {e}")
    return None


async def fetch_fbref_xg(home, away):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BetEdgeBot/1.0)"}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        home_xg = await fbref_team_xg(client, home, headers)
        await asyncio.sleep(1)
        away_xg = await fbref_team_xg(client, away, headers)
    if home_xg and away_xg:
        return round(home_xg, 2), round(away_xg, 2)
    return None, None


async def fbref_team_xg(client, team, headers):
    try:
        url = f"https://fbref.com/en/search/search.fcgi?search={team.replace(' ', '+')}&pid=search"
        resp = await client.get(url, headers=headers)
        xg_pattern = re.search(r'data-stat="xg"[^>]*>([0-9.]+)<', resp.text)
        if xg_pattern:
            total_xg = float(xg_pattern.group(1))
            matches_pattern = re.search(r'data-stat="games"[^>]*>(\d+)<', resp.text)
            games = int(matches_pattern.group(1)) if matches_pattern else 20
            if games > 0: return total_xg / games
    except: pass
    return None


def estimate_xg_from_league(league_key):
    defaults = {
        "portugal 1": (1.45, 1.05), "portugal 2": (1.35, 0.95),
        "espanha 1":  (1.52, 1.08), "espanha 2":  (1.38, 1.02),
        "inglaterra 1": (1.65, 1.15), "inglaterra 2": (1.48, 1.08),
        "alemanha 1": (1.72, 1.18), "alemanha 2":  (1.55, 1.12),
        "italia 1":   (1.42, 1.02), "italia 2":    (1.35, 0.98),
        "franca 1":   (1.48, 1.05), "frança 1":    (1.48, 1.05),
        "paises baixos": (1.68, 1.22), "países baixos": (1.68, 1.22),
        "escocia":    (1.52, 1.08), "escócia":     (1.52, 1.08),
        "belgica":    (1.55, 1.10), "bélgica":     (1.55, 1.10),
        "turquia":    (1.50, 1.05), "noruega":     (1.60, 1.10),
        "dinamarca":  (1.55, 1.08), "suecia":      (1.55, 1.05),
        "liga dos campeoes": (1.58, 1.15), "liga dos campeões": (1.58, 1.15),
        "liga europa": (1.52, 1.10), "liga conferencia": (1.45, 1.05),
        "europeu":    (1.30, 1.00), "mundial":     (1.25, 0.95),
        "liga das nações": (1.28, 0.98),
    }
    return defaults.get(league_key, (1.45, 1.05))


# ════════════════════════════════════════
# NOTÍCIAS
# ════════════════════════════════════════
async def fetch_news(home, away):
    news = []
    if NEWS_API_KEY:
        try: news = await fetch_newsapi(home, away)
        except Exception as e: print(f"NewsAPI: {e}")
    if not news:
        try: news = await fetch_google_news(home, away)
        except Exception as e: print(f"Google News: {e}")
    return news[:6]


async def fetch_newsapi(home, away):
    params = {
        "q": f'"{home}" OR "{away}" lesão suspensão injury suspension',
        "language": "pt", "sortBy": "publishedAt", "pageSize": 5,
        "from": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        "apiKey": NEWS_API_KEY,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://newsapi.org/v2/everything", params=params)
        articles = r.json().get("articles", [])
    return [classify_news(a["title"], a.get("source", {}).get("name", "")) for a in articles if a.get("title")]


async def fetch_google_news(home, away):
    query = f"{home} {away} lesão OR injury OR suspenso OR suspended"
    url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=pt-PT&gl=PT&ceid=PT:pt"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    titles = re.findall(r'<title><!\[CDATA\[(.+?)\]\]></title>', r.text)[1:6]
    return [classify_news(t, "Google News") for t in titles]


def classify_news(title, source):
    tl = title.lower()
    if any(k in tl for k in ["lesion","lesão","injury","injured","baixa","out","dúvida","muscular"]):
        t = "injury"
    elif any(k in tl for k in ["suspenso","suspension","banned","cartão","card","expulso"]):
        t = "suspension"
    else:
        t = "form"
    return {"type": t, "text": title[:80], "source": source}


# ════════════════════════════════════════
# RESULTADO — API-Football + football-data.org
# ════════════════════════════════════════
@app.get("/result")
async def get_result(
    match: str = Query(...),
    date:  str = Query(""),
):
    parts = match.split(" vs ")
    if len(parts) != 2:
        raise HTTPException(400, "Formato: 'Casa vs Fora'")
    home_team, away_team = parts[0].strip(), parts[1].strip()
    search_date = date or datetime.now().strftime("%Y-%m-%d")

    # 1. Tentar API-Football (cobre Liga Portugal e todas as outras)
    if RAPID_API_KEY:
        result = await fetch_result_apifootball(home_team, away_team, search_date)
        if result: return result

    # 2. Fallback: football-data.org (grandes ligas)
    if FD_API_KEY:
        result = await fetch_result_fd(home_team, away_team, search_date)
        if result: return result

    raise HTTPException(404, f"Resultado não encontrado para '{match}'. Verifica se o jogo já terminou.")


async def fetch_result_apifootball(home_team, away_team, search_date):
    """API-Football — cobre TODAS as ligas incluindo Liga Portugal."""
    if not RAPID_API_KEY: return None

    headers = {
        "x-apisports-key": RAPID_API_KEY,
    }
    # Pesquisar por data (±1 dia para compensar fusos horários)
    date_obj = datetime.fromisoformat(search_date)
    dates_to_try = [
        (date_obj - timedelta(days=1)).strftime("%Y-%m-%d"),
        search_date,
        (date_obj + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    async with httpx.AsyncClient(timeout=20) as client:
        for d in dates_to_try:
            try:
                r = await client.get(
                    "https://v3.football.api-sports.io/fixtures",
                    headers=headers,
                    params={"date": d, "status": "FT-AET-PEN"}  # Jogos terminados
                )
                fixtures = r.json().get("response", [])
                for f in fixtures:
                    h = f["teams"]["home"]["name"].lower()
                    a = f["teams"]["away"]["name"].lower()
                    if (home_team.lower() in h or h in home_team.lower()) and \
                       (away_team.lower() in a or a in away_team.lower()):
                        goals = f["goals"]
                        score = f["score"]
                        # xG se disponível
                        xg_home = f.get("statistics", [{}])[0].get("statistics", [])
                        fixture_id = f["fixture"]["id"]
                        ht = score.get("halftime", {})
                        # Tentar buscar xG das estatísticas do jogo
                        xg_home_real = xg_away_real = None
                        try:
                            r_stats = await client.get(
                                "https://v3.football.api-sports.io/fixtures/statistics",
                                headers=headers,
                                params={"fixture": fixture_id, "type": "Expected Goals"}
                            )
                            stats_data = r_stats.json().get("response", [])
                            for team_stat in stats_data:
                                for stat in team_stat.get("statistics", []):
                                    if stat.get("type") == "Expected Goals" and stat.get("value"):
                                        val = float(stat["value"])
                                        if xg_home_real is None:
                                            xg_home_real = val
                                        else:
                                            xg_away_real = val
                        except Exception as xe:
                            print(f"xG stats: {xe}")

                        return {
                            "home": f["teams"]["home"]["name"],
                            "away": f["teams"]["away"]["name"],
                            "home_goals":     goals.get("home", 0),
                            "away_goals":     goals.get("away", 0),
                            "home_goals_ht":  ht.get("home") if ht.get("home") is not None else None,
                            "away_goals_ht":  ht.get("away") if ht.get("away") is not None else None,
                            "xg_home":        xg_home_real,
                            "xg_away":        xg_away_real,
                            "status": f["fixture"]["status"]["long"],
                            "date":   f["fixture"]["date"][:10],
                            "source": "api-football",
                            "fixture_id": fixture_id,
                        }
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"API-Football result ({d}): {e}")
    return None


async def fetch_result_fd(home_team, away_team, search_date):
    """football-data.org — fallback para grandes ligas."""
    headers = {"X-Auth-Token": FD_API_KEY}
    date_obj = datetime.fromisoformat(search_date)
    date_from = (date_obj - timedelta(days=2)).strftime("%Y-%m-%d")
    date_to   = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
    leagues = ["PL","PD","BL1","SA","FL1","DED","CL","EL","ECNL","ELC","SD","SB","FL2","BL2","BSA"]

    async with httpx.AsyncClient(timeout=15) as client:
        for league in leagues:
            try:
                r = await client.get(
                    f"https://api.football-data.org/v4/competitions/{league}/matches",
                    headers=headers,
                    params={"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"}
                )
                if r.status_code != 200: continue
                for m in r.json().get("matches", []):
                    h = m["homeTeam"]["name"].lower()
                    a = m["awayTeam"]["name"].lower()
                    if (home_team.lower() in h or h in home_team.lower()) and \
                       (away_team.lower() in a or a in away_team.lower()):
                        ft = m["score"]["fullTime"]
                        ht = m["score"]["halfTime"]
                        return {
                            "home": m["homeTeam"]["name"],
                            "away": m["awayTeam"]["name"],
                            "home_goals":    ft.get("home", 0),
                            "away_goals":    ft.get("away", 0),
                            "home_goals_ht": ht.get("home", 0),
                            "away_goals_ht": ht.get("away", 0),
                            "status": "FINISHED",
                            "date":   m.get("utcDate", "")[:10],
                            "source": "football-data.org",
                        }
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"FD {league}: {e}")
    return None


# ════════════════════════════════════════
# xG REAL PÓS-JOGO — API-Football
# ════════════════════════════════════════
@app.get("/xg-result")
async def get_xg_result(fixture_id: int = Query(...)):
    """Busca xG real de um jogo já terminado via API-Football."""
    if not RAPID_API_KEY:
        raise HTTPException(503, "RAPID_API_KEY não configurada")

    headers = {
        "x-apisports-key": RAPID_API_KEY,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://v3.football.api-sports.io/fixtures/statistics",
            headers=headers,
            params={"fixture": fixture_id}
        )
        stats = r.json().get("response", [])

    xg_home = xg_away = None
    for team_stats in stats:
        for stat in team_stats.get("statistics", []):
            if stat["type"] == "Expected Goals":
                if team_stats.get("team", {}).get("id") == stats[0].get("team", {}).get("id"):
                    xg_home = stat["value"]
                else:
                    xg_away = stat["value"]

    return {"xg_home": xg_home, "xg_away": xg_away, "fixture_id": fixture_id}


# ════════════════════════════════════════
# FIXTURES
# ════════════════════════════════════════
@app.get("/fixtures")
async def get_fixtures(days_ahead: int = 0):
    target_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    all_fixtures = []

    # API-Football (cobre tudo)
    if RAPID_API_KEY:
        headers = {
            "x-apisports-key": RAPID_API_KEY,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                r = await client.get(
                    "https://v3.football.api-sports.io/fixtures",
                    headers=headers,
                    params={"date": target_date}
                )
                for f in r.json().get("response", []):
                    league_name = f["league"]["name"]
                    all_fixtures.append({
                        "liga": league_name,
                        "casa": f["teams"]["home"]["name"],
                        "fora": f["teams"]["away"]["name"],
                        "hora": f["fixture"]["date"][11:16],
                        "data": target_date,
                        "fixture_id": f["fixture"]["id"],
                    })
            except Exception as e:
                print(f"Fixtures API-Football: {e}")

    # Fallback football-data.org
    if not all_fixtures and FD_API_KEY:
        headers = {"X-Auth-Token": FD_API_KEY}
        leagues = ["PL","PD","BL1","SA","FL1","CL","EL","DED","BSA"]
        async with httpx.AsyncClient(timeout=20) as client:
            for league in leagues:
                try:
                    r = await client.get(
                        f"https://api.football-data.org/v4/competitions/{league}/matches",
                        headers=headers,
                        params={"dateFrom": target_date, "dateTo": target_date}
                    )
                    if r.status_code != 200: continue
                    for m in r.json().get("matches", []):
                        all_fixtures.append({
                            "liga": m["competition"]["name"],
                            "casa": m["homeTeam"]["name"],
                            "fora": m["awayTeam"]["name"],
                            "hora": m.get("utcDate", "")[11:16],
                            "data": target_date,
                        })
                    await asyncio.sleep(0.3)
                except: continue

    return {"fixtures": all_fixtures, "date": target_date, "count": len(all_fixtures)}
