from pathlib import Path
import pandas as pd
import re

SRC=Path('external/football-datasets/datalake/transfermarkt')
OUT=Path('output_transfermarkt')
OUT.mkdir(parents=True, exist_ok=True)

PERF=SRC/'player_performances/player_performances.csv'
PROF=SRC/'player_profiles/player_profiles.csv'
VAL=SRC/'player_latest_market_value/player_latest_market_value.csv'

RECENT={'24/25','25/26','2025','2026'}

def clean_num(s):
    if s is None: return 0.0
    x=str(s).strip().replace("'",'').replace('.','').replace(',','.')
    if x in {'','-','nan','None'}: return 0.0
    try:return float(x)
    except:return 0.0

def main():
    print('Reading profiles...')
    prof=pd.read_csv(PROF,low_memory=False)
    prof['player_id']=pd.to_numeric(prof['player_id'],errors='coerce')

    keep_prof=[c for c in ['player_id','player_name','Date of birth','Citizenship','player_main_position','player_sub_position','Current club','Foot','Height'] if c in prof.columns]
    prof=prof[keep_prof].drop_duplicates('player_id')

    print('Reading latest market values...')
    val=pd.read_csv(VAL,low_memory=False)
    val['player_id']=pd.to_numeric(val['player_id'],errors='coerce')
    value_col=next((c for c in ['value','market_value','latest_market_value'] if c in val.columns),None)
    if value_col:
        val=val[['player_id',value_col]].rename(columns={value_col:'market_value_eur'})
        val['market_value_eur']=pd.to_numeric(val['market_value_eur'],errors='coerce')
    else:
        val=val[['player_id']]
        val['market_value_eur']=pd.NA
    val=val.drop_duplicates('player_id',keep='last')

    print('Streaming 1.8M performance rows...')
    chunks=[]
    for chunk in pd.read_csv(PERF,chunksize=200000,low_memory=False):
        if 'season' not in chunk.columns: continue
        chunk=chunk[chunk['season'].astype(str).isin(RECENT)]
        if chunk.empty: continue
        chunk['player_id']=pd.to_numeric(chunk['player_id'],errors='coerce')
        for c in ['nb_on_pitch','goals','assists','minutes_played']:
            if c in chunk.columns:
                chunk[c+'_num']=chunk[c].map(clean_num)
        chunks.append(chunk)

    if not chunks:
        raise RuntimeError('No recent performance rows found')
    perf=pd.concat(chunks,ignore_index=True)

    # Aggregate across competitions within each player-season while preserving the most-used club/competition labels.
    numeric=[c for c in ['nb_on_pitch_num','goals_num','assists_num','minutes_played_num'] if c in perf.columns]
    agg=perf.groupby(['player_id','season'],as_index=False)[numeric].sum()

    def mode_map(col):
        if col not in perf.columns:return None
        m=(perf.dropna(subset=[col]).groupby(['player_id','season'])[col]
             .agg(lambda x: x.value_counts().index[0]).reset_index())
        return m
    for col in ['team_name','competition_name']:
        m=mode_map(col)
        if m is not None: agg=agg.merge(m,on=['player_id','season'],how='left')

    agg=agg.merge(prof,on='player_id',how='left').merge(val,on='player_id',how='left')

    # Basic scouting usefulness: actual production + minutes; this is NOT an advanced event-data grade.
    mins=agg.get('minutes_played_num',pd.Series(0,index=agg.index)).replace(0,pd.NA)
    agg['goals_per90']=agg.get('goals_num',0)/mins*90
    agg['assists_per90']=agg.get('assists_num',0)/mins*90
    agg['ga_per90']=agg['goals_per90'].fillna(0)+agg['assists_per90'].fillna(0)

    # DOB parsing enables a youth discovery slice.
    if 'Date of birth' in agg.columns:
        dob=pd.to_datetime(agg['Date of birth'],dayfirst=True,errors='coerce')
        ref=pd.Timestamp('2026-08-19')
        agg['age']=((ref-dob).dt.days/365.25).round(1)
    else:
        agg['age']=pd.NA

    agg.to_csv(OUT/'transfermarkt_recent_player_seasons.csv',index=False)

    youth=agg[(agg['age'].notna()) & (agg['age']<=23) & (agg.get('minutes_played_num',0)>=600)].copy()
    youth=youth.sort_values(['ga_per90','minutes_played_num'],ascending=[False,False])
    youth.to_csv(OUT/'transfermarkt_u23_discovery.csv',index=False)

    status=pd.DataFrame([{
        'source':'salimt/football-datasets (Transfermarkt-derived open dataset)',
        'profile_rows':len(prof),'recent_performance_rows':len(perf),'player_seasons':len(agg),
        'u23_600min_rows':len(youth),'status':'ok'
    }])
    status.to_csv(OUT/'source_status.csv',index=False)
    print(status.to_string(index=False))
    print(youth.head(25).to_string(index=False))

if __name__=='__main__':
    main()
