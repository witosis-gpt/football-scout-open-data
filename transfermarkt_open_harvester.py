from pathlib import Path
import traceback
import re
import numbers
import pandas as pd

SRC=Path('external/football-datasets/datalake/transfermarkt')
OUT=Path('output_transfermarkt')
OUT.mkdir(parents=True, exist_ok=True)

PERF=SRC/'player_performances/player_performances.csv'
PROF=SRC/'player_profiles/player_profiles.csv'
VAL=SRC/'player_latest_market_value/player_latest_market_value.csv'
RECENT={'24/25','25/26','2025','2026'}


def clean_num(s):
    if s is None or (isinstance(s,float) and pd.isna(s)):
        return 0.0
    if isinstance(s,numbers.Number):
        return float(s)
    x=str(s).strip().replace("'",'')
    if x in {'','-','nan','None'}:
        return 0.0
    # Transfermarkt minutes can use dots as thousands separators: 1.470 = 1470.
    # Preserve ordinary decimals such as 8.0 instead of turning them into 80.
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+',x):
        x=x.replace('.','')
    elif ',' in x and '.' not in x:
        x=x.replace(',','.')
    try:
        return float(x)
    except Exception:
        return 0.0


def write_error(stage, exc):
    pd.DataFrame([{
        'stage': stage,
        'error_type': type(exc).__name__,
        'error': repr(exc),
        'traceback': traceback.format_exc()
    }]).to_csv(OUT/'source_error.csv', index=False)


def main():
    try:
        prof=pd.read_csv(PROF,low_memory=False)
        prof['player_id']=pd.to_numeric(prof['player_id'],errors='coerce')
        keep_prof=[c for c in [
            'player_id','player_name','date_of_birth','citizenship','position',
            'main_position','foot','height','current_club_name','current_club_id'
        ] if c in prof.columns]
        prof=prof[keep_prof].drop_duplicates('player_id')
    except Exception as e:
        write_error('profiles',e); raise

    try:
        val=pd.read_csv(VAL,low_memory=False)
        val['player_id']=pd.to_numeric(val['player_id'],errors='coerce')
        if 'value' in val.columns:
            keep=['player_id','value'] + (['date_unix'] if 'date_unix' in val.columns else [])
            val=val[keep].rename(columns={'value':'market_value_eur'})
            val['market_value_eur']=pd.to_numeric(val['market_value_eur'],errors='coerce')
            if 'date_unix' in val.columns:
                val['date_unix']=pd.to_datetime(val['date_unix'],errors='coerce')
                val=val.sort_values(['player_id','date_unix']).drop_duplicates('player_id',keep='last')
            else:
                val=val.drop_duplicates('player_id',keep='last')
        else:
            val=val[['player_id']].drop_duplicates('player_id')
            val['market_value_eur']=pd.NA
    except Exception as e:
        write_error('market_values',e); raise

    try:
        chunks=[]; perf_columns=None; season_col=None
        for chunk in pd.read_csv(PERF,chunksize=200000,low_memory=False):
            if perf_columns is None:
                perf_columns=list(chunk.columns)
                season_col='season_name' if 'season_name' in chunk.columns else ('season' if 'season' in chunk.columns else None)
                if season_col is None:
                    raise RuntimeError(f'No season column found. Columns={perf_columns}')
            chunk=chunk[chunk[season_col].astype(str).isin(RECENT)].copy()
            if chunk.empty:
                continue
            chunk['season']=chunk[season_col].astype(str)
            chunk['player_id']=pd.to_numeric(chunk['player_id'],errors='coerce')
            for c in ['nb_on_pitch','goals','assists','minutes_played']:
                if c in chunk.columns:
                    chunk[c+'_num']=chunk[c].map(clean_num)
            chunks.append(chunk)
        if not chunks:
            raise RuntimeError(f'No recent performance rows found in {season_col}. Columns={perf_columns}')
        perf=pd.concat(chunks,ignore_index=True)
    except Exception as e:
        write_error('performances',e); raise

    try:
        numeric=[c for c in ['nb_on_pitch_num','goals_num','assists_num','minutes_played_num'] if c in perf.columns]
        if not numeric:
            raise RuntimeError(f'No numeric performance fields available. Columns={list(perf.columns)}')

        group_cols=['player_id','season']
        for c in ['team_name','competition_name']:
            if c in perf.columns:
                group_cols.append(c)
        agg=perf.groupby(group_cols,as_index=False,dropna=False)[numeric].sum()

        agg=agg.merge(prof,on='player_id',how='left').merge(val,on='player_id',how='left')
        mins=agg['minutes_played_num'].replace(0,pd.NA)
        agg['goals_per90']=agg.get('goals_num',0)/mins*90
        agg['assists_per90']=agg.get('assists_num',0)/mins*90
        agg['ga_per90']=agg['goals_per90'].fillna(0)+agg['assists_per90'].fillna(0)

        if 'date_of_birth' in agg.columns:
            dob=pd.to_datetime(agg['date_of_birth'],errors='coerce')
            ref=pd.Timestamp('2026-08-19')
            agg['age']=((ref-dob).dt.days/365.25).round(1)
        else:
            agg['age']=pd.NA

        agg.to_csv(OUT/'transfermarkt_recent_player_seasons.csv',index=False)
        youth=agg[(agg['age'].notna()) & (agg['age']<=23) & (agg['minutes_played_num']>=600)].copy()
        youth=youth.sort_values(['ga_per90','minutes_played_num'],ascending=[False,False])
        youth.to_csv(OUT/'transfermarkt_u23_discovery.csv',index=False)

        pd.DataFrame([{
            'source':'salimt/football-datasets (Transfermarkt-derived open dataset)',
            'profile_rows':len(prof),'recent_performance_rows':len(perf),
            'player_competition_seasons':len(agg),'u23_600min_rows':len(youth),'status':'ok'
        }]).to_csv(OUT/'source_status.csv',index=False)
        print('SUCCESS',len(agg),'player-competition-seasons;',len(youth),'U23 rows')
    except Exception as e:
        write_error('build',e); raise


if __name__=='__main__':
    main()
