from pathlib import Path
import re
import time
import traceback
import pandas as pd
import requests
import LanusStats as ls

OUT = Path('output_sofascore')
OUT.mkdir(parents=True, exist_ok=True)

TARGET_KEYWORDS = [
    'Argentina','Brasileirão','Brazil','Chile','Colombia','Peru','Mexico','LigaMX',
    'MLS','Saudi','J1','USL Championship','La Liga 2','Primera RFEF'
]

PREFERRED_SEASONS = [
    '2026','25/26','2025/2026','2025-2026','2025/26','2025-Clausura',
    '2025-Apertura','2025','24/25','2024/2025','2024-2025','2024'
]

def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', str(s).lower()).strip()

def _flatten_season_value(v):
    if isinstance(v, dict):
        return [str(k) for k in v.keys()]
    if isinstance(v, (list, tuple, set, pd.Series)):
        out=[]
        for x in v:
            out.extend(_flatten_season_value(x))
        return out
    return [str(v)] if v is not None else []

def season_values(obj):
    if isinstance(obj, pd.DataFrame):
        for c in ['seasons','season','Season','SEASON']:
            if c in obj.columns:
                out=[]
                for v in obj[c].dropna().tolist():
                    out.extend(_flatten_season_value(v))
                return out
        cols=[c for c in obj.columns if str(c).lower() != 'id']
        if cols:
            out=[]
            for v in obj[cols[0]].dropna().tolist():
                out.extend(_flatten_season_value(v))
            return out
        return []
    if isinstance(obj, dict):
        if 'seasons' in obj:
            return _flatten_season_value(obj['seasons'])
        return [str(x) for x in obj.keys()]
    return _flatten_season_value(obj)

def pick_season(seasons):
    seasons=[str(x) for x in seasons]
    lookup={norm(x):x for x in seasons}
    for pref in PREFERRED_SEASONS:
        if norm(pref) in lookup:
            return lookup[norm(pref)]
    return seasons[-1] if seasons else None

def build_http_requester():
    session=requests.Session()
    session.headers.update({
        'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/127 Safari/537.36',
        'Accept':'application/json,text/plain,*/*',
        'Accept-Language':'en-US,en;q=0.8',
        'Referer':'https://www.sofascore.com/'
    })

    def requester(path):
        url='https://www.sofascore.com/' + path.lstrip('/')
        r=session.get(url,timeout=30)
        if r.status_code in (401,403,429):
            raise RuntimeError(f'SofaScore HTTP {r.status_code}; access denied/rate limited, not bypassing access controls')
        r.raise_for_status()
        ctype=r.headers.get('content-type','')
        if 'json' not in ctype.lower():
            raise RuntimeError(f'Unexpected SofaScore content-type {ctype!r} for {url}')
        time.sleep(0.8)
        return r.json()
    return requester

def main():
    available=ls.get_available_leagues('Sofascore')
    if isinstance(available,pd.DataFrame):
        col='league' if 'league' in available.columns else available.columns[0]
        leagues=[str(x) for x in available[col].dropna().tolist()]
    elif isinstance(available,dict):
        leagues=list(available.keys())
    else:
        leagues=[str(x) for x in list(available)]

    pd.DataFrame({'league':leagues}).to_csv(OUT/'available_sofascore_leagues.csv',index=False)

    matched=[]; seen=set()
    for league in leagues:
        nl=norm(league)
        if any(norm(k) in nl or nl in norm(k) for k in TARGET_KEYWORDS):
            if league not in seen:
                seen.add(league); matched.append(league)

    if not matched:
        raise RuntimeError('No target leagues matched SofaScore catalog; inspect available_sofascore_leagues.csv')

    sofa=ls.SofaScore()
    # LanusStats normally uses Selenium here. On GitHub Actions that driver path
    # is raising PermissionError, so use the same public JSON endpoints directly.
    sofa.sofascore_request=build_http_requester()

    frames=[]; status=[]; errors=[]; catalog_rows=[]

    for league in matched:
        try:
            raw_seasons=ls.get_available_season_for_leagues('Sofascore',league)
            seasons=season_values(raw_seasons)
        except Exception as e:
            errors.append((league,'','season_catalog',repr(e)))
            status.append((league,'',0,0,'season_catalog_failed'))
            continue

        for s in seasons:
            catalog_rows.append((league,s))
        season=pick_season(seasons)
        if not season:
            status.append((league,'',0,0,'no_season'))
            continue

        print(f'\n=== SofaScore {league} | {season} ===')
        try:
            df=sofa.scrape_league_stats(
                league=league,
                season=season,
                save_csv=False,
                accumulation='per90',
                selected_positions=['Defenders','Midfielders','Forwards'],
            )
            if df is None or df.empty:
                status.append((league,season,0,0,'empty'))
                continue
            df=df.copy()
            df['league']=league
            df['season']=season
            df['source']='SofaScore via LanusStats direct JSON'
            slug=re.sub(r'[^a-z0-9]+','_',league.lower()).strip('_')
            sslug=re.sub(r'[^a-z0-9]+','_',str(season).lower()).strip('_')
            df.to_csv(OUT/f'{slug}_{sslug}_per90.csv',index=False)
            frames.append(df)
            status.append((league,season,len(df),len(df.columns),'ok'))
        except Exception as e:
            traceback.print_exc(limit=3)
            errors.append((league,season,'scrape_league_stats',repr(e)))
            status.append((league,season,0,0,'failed'))

    pd.DataFrame(catalog_rows,columns=['league','season']).to_csv(OUT/'sofascore_season_catalog.csv',index=False)
    pd.DataFrame(status,columns=['league','season','rows','columns','status']).to_csv(OUT/'scrape_status.csv',index=False)
    pd.DataFrame(errors,columns=['league','season','stage','error']).to_csv(OUT/'scrape_errors.csv',index=False)

    if frames:
        combined=pd.concat(frames,ignore_index=True,sort=False)
        combined.to_csv(OUT/'sofascore_multi_league_players_per90.csv',index=False)
        combined.to_excel(OUT/'sofascore_multi_league_players_per90.xlsx',index=False)
        print(f'Combined rows: {len(combined)} | columns: {len(combined.columns)} | leagues: {combined.league.nunique()}')
    else:
        print('No league data succeeded. Inspect scrape_errors.csv and available_sofascore_leagues.csv')

if __name__=='__main__':
    main()
