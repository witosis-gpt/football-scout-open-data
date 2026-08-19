from pathlib import Path
import re
import numpy as np
import pandas as pd

SRC=Path('data/latest/transfermarkt_u23_discovery.csv')
OUT=Path('output_hidden_gems')
OUT.mkdir(parents=True, exist_ok=True)

YOUTH_PATTERNS = [
    r'\bu\s?17\b', r'\bu\s?18\b', r'\bu\s?19\b', r'\bu\s?20\b', r'\bu\s?21\b', r'\bu\s?23\b',
    r'under\s*17', r'under\s*18', r'under\s*19', r'under\s*20', r'under\s*21', r'under\s*23',
    r'primavera', r'nachwuchs', r'youth', r'academy', r'junior', r'juniors', r'boys league',
    r'reserve', r'reserves', r'\bb team\b', r'\bb liga\b'
]


def pct(s, ascending=True):
    return s.rank(pct=True, ascending=ascending, method='average').fillna(0.5)


def is_youth_comp(name):
    text=str(name or '').lower()
    return any(re.search(p,text) for p in YOUTH_PATTERNS)


def main():
    df=pd.read_csv(SRC,low_memory=False)

    for c in ['age','minutes_played_num','goals_per90','assists_per90','ga_per90','market_value_eur']:
        if c in df.columns:
            df[c]=pd.to_numeric(df[c],errors='coerce')

    if 'main_position' in df.columns:
        pool=df[df['main_position'].isin(['Attack','Midfield'])].copy()
    else:
        pool=df.copy()

    if 'competition_name' in pool.columns:
        pool['is_youth_competition']=pool['competition_name'].map(is_youth_comp)
        pool=pool[~pool['is_youth_competition']].copy()

    pool=pool[pool['minutes_played_num'].fillna(0)>=900].copy()

    pos_key='position' if 'position' in pool.columns else ('main_position' if 'main_position' in pool.columns else None)
    if pos_key:
        pool['production_pct']=pool.groupby(pos_key)['ga_per90'].rank(pct=True,method='average').fillna(0.5)
    else:
        pool['production_pct']=pct(pool['ga_per90'],ascending=True)

    pool['goals_pct']=pct(pool['goals_per90'],ascending=True)
    pool['assists_pct']=pct(pool['assists_per90'],ascending=True)
    pool['age_upside']=((23.5-pool['age'])/7.0).clip(0,1).fillna(0.5)
    pool['minutes_confidence']=(pool['minutes_played_num']/2500.0).clip(0,1).fillna(0)

    mv=pool['market_value_eur']
    known=mv.notna() & (mv>0)
    pool['affordability']=0.5
    if known.any():
        logv=np.log1p(mv[known])
        pool.loc[known,'affordability']=1-logv.rank(pct=True,method='average')

    pool['spike_score']=pool[['production_pct','goals_pct','assists_pct']].max(axis=1)
    pool['hidden_gem_score']=(
        0.38*pool['spike_score']+
        0.22*pool['production_pct']+
        0.16*pool['age_upside']+
        0.14*pool['affordability']+
        0.10*pool['minutes_confidence']
    )*100

    pool['value_band']=pd.cut(
        pool['market_value_eur'],
        bins=[-1,500000,2000000,5000000,10000000,float('inf')],
        labels=['<=0.5m','0.5-2m','2-5m','5-10m','10m+']
    )

    cols=[c for c in [
        'player_id','player_name','age','position','main_position','current_club_name',
        'team_name','competition_name','season','minutes_played_num','goals_per90',
        'assists_per90','ga_per90','market_value_eur','value_band','spike_score',
        'production_pct','age_upside','affordability','minutes_confidence','hidden_gem_score'
    ] if c in pool.columns]

    ranked=pool.sort_values('hidden_gem_score',ascending=False)[cols]
    ranked.to_csv(OUT/'u23_hidden_gems_ranked.csv',index=False)

    cheap=pool[(pool['market_value_eur'].isna()) | (pool['market_value_eur']<=5_000_000)].copy()
    cheap=cheap.sort_values('hidden_gem_score',ascending=False)[cols]
    cheap.to_csv(OUT/'u23_hidden_gems_under_5m.csv',index=False)

    if 'main_position' in pool.columns:
        mids=pool[pool['main_position'].eq('Midfield')].sort_values('hidden_gem_score',ascending=False)[cols]
        mids.to_csv(OUT/'u23_midfield_hidden_gems.csv',index=False)

    summary=pd.DataFrame([{
        'input_rows':len(df),
        'senior_attack_midfield_900min_pool':len(pool),
        'under_5m_or_unknown_pool':len(cheap),
        'status':'ok',
        'note':'Senior competitions only; heuristic based on production, age, minutes and market value; no dribble/pass/carry event data.'
    }])
    summary.to_csv(OUT/'hidden_gem_status.csv',index=False)

    print(summary.to_string(index=False))
    print('\nTOP 30 SENIOR')
    print(ranked.head(30).to_string(index=False))

if __name__=='__main__':
    main()
