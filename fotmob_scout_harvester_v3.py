import re, time, traceback, importlib
from pathlib import Path
import pandas as pd
import LanusStats as ls

# Import the actual LanusStats.fotmob module, not the FotMob class re-exported by package __init__.
fotmob_module = importlib.import_module('LanusStats.fotmob')

# GitHub Actions is a headless Linux runner. Force Chromium into a mode that
# nodriver supports there: headless + sandbox disabled.
_original_start = fotmob_module.uc.start
async def _start_actions_browser(*args, **kwargs):
    kwargs['headless'] = True
    kwargs['sandbox'] = False
    return await _original_start(*args, **kwargs)
fotmob_module.uc.start = _start_actions_browser

OUT = Path('output_v3')
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = {
    'La Liga 2': '2025/2026',
    'Argentina Primera Division': '2025',
    'Primera Division Colombia': '2025-Clausura',
    'Primera Division Chile': '2025',
    'Brasileirao': '2025',
    'Primera Division Peru': '2025',
}

METRICS = [
    'rating','goals_per_90','expected_goals_per_90','expected_assists_per_90',
    '_expected_goals_and_expected_assists_per_90','total_scoring_att',
    'ontarget_scoring_att','total_att_assist','big_chance_created',
    'accurate_pass','accurate_long_balls','won_contest','won_tackle',
    'interception','poss_won_att_3rd'
]
META = {'player_id','player','team','league','season','merge_key'}

def keycols(df):
    cols=list(df.columns); low={str(c).lower():c for c in cols}
    def pick(opts):
        for o in opts:
            if o in low: return low[o]
        for c in cols:
            lc=str(c).lower()
            if any(o in lc for o in opts): return c
        return None
    return pick(['participantid','playerid','player_id','id']), pick(['participantname','playername','player_name','name']), pick(['teamname','team_name','team'])

def tidy(df, metric, league, season):
    pid,pname,team=keycols(df)
    if pname is None: raise RuntimeError(f'No player-name column: {list(df.columns)}')
    excluded={x for x in [pid,pname,team,'statValue'] if x is not None}
    candidates=[]
    for c in df.columns:
        if c in excluded: continue
        n=pd.to_numeric(df[c],errors='coerce')
        if n.notna().sum() >= max(3,len(df)//4): candidates.append(c)
    if not candidates: raise RuntimeError(f'No numeric value column: {list(df.columns)}')
    preferred=None
    for token in ['value','stat','per90','per_90','total']:
        for c in candidates:
            if token in str(c).lower(): preferred=c; break
        if preferred is not None: break
    value_col=preferred or candidates[-1]
    out=pd.DataFrame({
        'player_id':df[pid] if pid is not None else pd.NA,
        'player':df[pname].astype(str),
        'team':df[team].astype(str) if team is not None else pd.NA,
        'league':league,'season':str(season),
        metric:pd.to_numeric(df[value_col],errors='coerce')
    })
    out['merge_key']=out['player_id'].astype(str)
    missing=out['player_id'].isna()|out['merge_key'].isin(['<NA>','nan','None',''])
    out.loc[missing,'merge_key']=out.loc[missing,'player'].str.lower().str.strip()+'||'+out.loc[missing,'league'].str.lower().str.strip()
    return out

def merge_frames(frames):
    base=None
    for f in frames:
        metric_cols=[c for c in f.columns if c not in META]
        if not metric_cols: continue
        metric=metric_cols[0]
        if base is None: base=f.copy()
        else: base=base.merge(f[['merge_key',metric]],on='merge_key',how='outer')
    return base if base is not None else pd.DataFrame()

def main():
    fm=ls.FotMob(request_delay=1.5)
    all_frames=[]; errors=[]; status=[]
    try:
        for league,season in TARGETS.items():
            print(f'\n=== {league} | {season} ===')
            lf=[]; ok=0
            for metric in METRICS:
                try:
                    print('pulling',metric)
                    df=fm.get_players_stats_season(league,season,metric)
                    if df is None or df.empty:
                        errors.append((league,season,metric,'empty')); continue
                    t=tidy(df,metric,league,season)
                    lf.append(t); all_frames.append(t); ok+=1
                    time.sleep(1.5)
                except Exception as e:
                    errors.append((league,season,metric,repr(e)))
                    traceback.print_exc(limit=1)
            if lf:
                wide=merge_frames(lf)
                slug=re.sub(r'[^a-z0-9]+','_',league.lower()).strip('_')
                wide.to_csv(OUT/f'wide_{slug}.csv',index=False)
            status.append((league,season,ok))
        combined=merge_frames(all_frames)
        if not combined.empty:
            combined.to_csv(OUT/'fotmob_multi_league_players_wide.csv',index=False)
            combined.to_excel(OUT/'fotmob_multi_league_players_wide.xlsx',index=False)
        pd.DataFrame(errors,columns=['league','season','metric','error']).to_csv(OUT/'scrape_errors.csv',index=False)
        pd.DataFrame(status,columns=['league','season','successful_metrics']).to_csv(OUT/'scrape_status.csv',index=False)
        print('combined rows:',len(combined))
        print(pd.DataFrame(status,columns=['league','season','successful_metrics']))
    finally:
        try: fm.close()
        except Exception: pass

if __name__=='__main__': main()
