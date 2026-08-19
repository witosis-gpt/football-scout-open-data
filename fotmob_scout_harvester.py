import re, time, traceback
from pathlib import Path
import pandas as pd
import LanusStats as ls

OUT=Path('output'); OUT.mkdir(parents=True,exist_ok=True)
LEAGUE_KEYS=['Eredivisie','Liga Portugal','Primeira Liga','Belgian','Pro League','Championship','Super Lig','Premiership','Allsvenskan','Eliteserien','Super League','Ekstraklasa','HNL','Liga Profesional','Brasileirao','MLS','Liga MX']
METRICS=['rating','goals_per_90','expected_goals_per_90','expected_assists_per_90','_expected_goals_and_expected_assists_per_90','total_scoring_att','ontarget_scoring_att','total_att_assist','big_chance_created','accurate_pass','accurate_long_balls','won_contest','won_tackle','interception','poss_won_att_3rd']

def leagues_list(raw):
    return list(raw.keys()) if isinstance(raw,dict) else list(raw)

def latest_season(raw):
    xs=list(raw.keys()) if isinstance(raw,dict) else list(raw)
    def k(x):
        y=[int(v) for v in re.findall(r'\d{4}',str(x))]
        return max(y) if y else -1
    return sorted(xs,key=k,reverse=True)[0]

def keycols(df):
    cols=list(df.columns); low={str(c).lower():c for c in cols}
    def pick(opts):
        for o in opts:
            if o in low:return low[o]
        for c in cols:
            if any(o in str(c).lower() for o in opts):return c
    return pick(['participantid','playerid','player_id','id']),pick(['participantname','playername','player_name','name']),pick(['teamname','team_name','team'])

def tidy(df,metric,league,season):
    pid,pname,team=keycols(df)
    if pname is None: raise RuntimeError('no player name col '+str(list(df.columns)))
    exclude={x for x in [pid,pname,team,'statValue'] if x is not None}
    nums=[]
    for c in df.columns:
        if c in exclude:continue
        n=pd.to_numeric(df[c],errors='coerce')
        if n.notna().sum()>=max(3,len(df)//4): nums.append(c)
    if not nums: raise RuntimeError('no numeric value col')
    value=nums[-1]
    out=pd.DataFrame({'player_id':df[pid] if pid else pd.NA,'player':df[pname].astype(str),'team':df[team].astype(str) if team else pd.NA,'league':league,'season':str(season),metric:pd.to_numeric(df[value],errors='coerce')})
    out['merge_key']=out['player_id'].astype(str)
    miss=out['player_id'].isna()|out['merge_key'].isin(['<NA>','nan','None',''])
    out.loc[miss,'merge_key']=out.loc[miss,'player'].str.lower().str.strip()+'||'+out.loc[miss,'league'].str.lower().str.strip()
    return out

def merge(frames):
    base=None
    for f in frames:
        metric=[c for c in f.columns if c not in ['player_id','player','team','league','season','merge_key']][0]
        if base is None: base=f.copy()
        else: base=base.merge(f[['merge_key',metric]],on='merge_key',how='outer')
    return base if base is not None else pd.DataFrame()

def main():
    available=leagues_list(ls.get_available_leagues('Fotmob'))
    targets=[]
    for lg in available:
        if any(k.lower() in lg.lower() for k in LEAGUE_KEYS): targets.append(lg)
    print('targets',targets)
    fm=ls.FotMob(request_delay=1.5)
    allf=[]; errors=[]
    try:
        for league in targets:
            try: season=latest_season(ls.get_available_season_for_leagues('Fotmob',league))
            except Exception as e:
                errors.append((league,'season',repr(e))); continue
            lf=[]
            for metric in METRICS:
                try:
                    print(league,season,metric)
                    df=fm.get_players_stats_season(league,season,metric)
                    if df is None or df.empty: continue
                    t=tidy(df,metric,league,season); lf.append(t); allf.append(t)
                    time.sleep(1.5)
                except Exception as e:
                    errors.append((league,metric,repr(e))); traceback.print_exc(limit=1)
            if lf:
                merge(lf).to_csv(OUT/f'wide_{re.sub("[^a-z0-9]+","_",league.lower()).strip("_")}.csv',index=False)
        combined=merge(allf)
        if not combined.empty:
            combined.to_csv(OUT/'fotmob_multi_league_players_wide.csv',index=False)
            combined.to_excel(OUT/'fotmob_multi_league_players_wide.xlsx',index=False)
        pd.DataFrame(errors,columns=['league','step','error']).to_csv(OUT/'scrape_errors.csv',index=False)
        print('rows',len(combined))
    finally:
        try: fm.close()
        except: pass

if __name__=='__main__': main()
