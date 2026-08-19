from pathlib import Path
import re
import traceback
import pandas as pd
import LanusStats as ls

OUT = Path('output_sofascore')
OUT.mkdir(parents=True, exist_ok=True)

# We deliberately match names dynamically against LanusStats' SofaScore catalog.
# That avoids hard-coding provider IDs and lets us discover what is actually available.
TARGET_KEYWORDS = [
    'Eredivisie',
    'Portugal',
    'Primeira Liga',
    'Belgian',
    'Championship',
    'Denmark',
    'Danish',
    'Argentina',
    'Brasileirao',
    'Brazil',
    'Colombia',
    'Chile',
    'Peru',
    'Mexico',
    'Liga MX',
    'MLS',
    'Saudi',
    'J1',
    'Japan',
    'Austria',
    'Switzerland',
    'Norway',
    'Sweden',
]

PREFERRED_SEASONS = [
    '2025/2026', '2025-2026', '25/26', '2025/26',
    '2026', '2025', '2024/2025', '2024-2025', '24/25', '2024'
]


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', str(s).lower()).strip()


def pick_season(seasons):
    seasons = [str(x) for x in seasons]
    lookup = {norm(x): x for x in seasons}
    for pref in PREFERRED_SEASONS:
        if norm(pref) in lookup:
            return lookup[norm(pref)]
    return seasons[0] if seasons else None


def main():
    available = ls.get_available_leagues('Sofascore')
    if isinstance(available, dict):
        leagues = list(available.keys())
    else:
        leagues = list(available)

    pd.DataFrame({'league': leagues}).to_csv(OUT / 'available_sofascore_leagues.csv', index=False)

    matched = []
    seen = set()
    for league in leagues:
        nl = norm(league)
        if any(norm(k) in nl or nl in norm(k) for k in TARGET_KEYWORDS):
            if league not in seen:
                seen.add(league)
                matched.append(league)

    # If matching unexpectedly finds nothing, save catalog and fail loudly.
    if not matched:
        raise RuntimeError('No target leagues matched SofaScore catalog; inspect available_sofascore_leagues.csv')

    sofa = ls.SofaScore()
    frames = []
    status = []
    errors = []
    catalog_rows = []

    for league in matched:
        try:
            seasons = ls.get_available_season_for_leagues('Sofascore', league)
            if isinstance(seasons, dict):
                seasons = list(seasons.keys())
            else:
                seasons = list(seasons)
        except Exception as e:
            errors.append((league, '', 'season_catalog', repr(e)))
            status.append((league, '', 0, 0, 'season_catalog_failed'))
            continue

        for s in seasons:
            catalog_rows.append((league, str(s)))
        season = pick_season(seasons)
        if not season:
            status.append((league, '', 0, 0, 'no_season'))
            continue

        print(f'\n=== SofaScore {league} | {season} ===')
        try:
            df = sofa.scrape_league_stats(
                league=league,
                season=season,
                save_csv=False,
                accumulation='per90',
                selected_positions=['Defenders', 'Midfielders', 'Forwards'],
            )
            if df is None or df.empty:
                status.append((league, season, 0, 0, 'empty'))
                continue

            df = df.copy()
            df['league'] = league
            df['season'] = season
            df['source'] = 'SofaScore via LanusStats'

            # Keep all provider fields. This is much richer than the FotMob leaderboard approach.
            slug = re.sub(r'[^a-z0-9]+', '_', league.lower()).strip('_')
            df.to_csv(OUT / f'{slug}_{re.sub(r"[^a-z0-9]+", "_", str(season).lower()).strip("_")}_per90.csv', index=False)
            frames.append(df)
            status.append((league, season, len(df), len(df.columns), 'ok'))
        except Exception as e:
            traceback.print_exc(limit=2)
            errors.append((league, season, 'scrape_league_stats', repr(e)))
            status.append((league, season, 0, 0, 'failed'))

    pd.DataFrame(catalog_rows, columns=['league', 'season']).to_csv(OUT / 'sofascore_season_catalog.csv', index=False)
    pd.DataFrame(status, columns=['league', 'season', 'rows', 'columns', 'status']).to_csv(OUT / 'scrape_status.csv', index=False)
    pd.DataFrame(errors, columns=['league', 'season', 'stage', 'error']).to_csv(OUT / 'scrape_errors.csv', index=False)

    if frames:
        combined = pd.concat(frames, ignore_index=True, sort=False)
        combined.to_csv(OUT / 'sofascore_multi_league_players_per90.csv', index=False)
        combined.to_excel(OUT / 'sofascore_multi_league_players_per90.xlsx', index=False)
        print(f'Combined rows: {len(combined)} | columns: {len(combined.columns)} | leagues: {combined.league.nunique()}')
    else:
        print('No league data succeeded. Inspect scrape_errors.csv and available_sofascore_leagues.csv')


if __name__ == '__main__':
    main()
