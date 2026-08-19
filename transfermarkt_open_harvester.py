from pathlib import Path
import traceback
import pandas as pd

SRC=Path('external/football-datasets/datalake/transfermarkt')
OUT=Path('output_transfermarkt')
OUT.mkdir(parents=True, exist_ok=True)

PERF=SRC/'player_performances/player_performances.csv'
PROF=SRC/'player_profiles/player_profiles.csv'
VAL=SRC/'player_latest_market_value/player_latest_market_value.csv'
RECENT={'24/25','25/26','2025','2026'}


def clean_num(s):
    if s is None:
        return 0.0
    x=str(s).strip().replace("'",'').replace('.','').replace(',','.')
    if x in {'','-','nan','None'}:
        return 0.0
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
        print('Reading profiles...')
        prof=pd.read_csv(PROF,low_memory=False)
        print('PROFILE COLUMNS:', list(prof.columns))
        prof['player_id']=pd.to_numeric(prof['player_id'],errors='coerce')
        keep_prof=[c for c in [
            'player_id','player_name','date_of_birth','citizenship','position',
            'main_position','foot','height','current_club_name','current_club_id'
        ] if c in prof.columns]
        prof=prof[keep_prof].drop_duplicates('player_id')
    except Exception as e:
        write_error('profiles',e)
        raise

    try:
        print('Reading latest market values...')
        val=pd.read_csv(VAL,low_memory=False)
        print('VALUE COLUMNS:', list(val.columns))
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
        write_error('market_values',e)
        raise

    try:
        print('Streaming performance rows...')
        chunks=[]
        perf_columns=None
        for chunk in pd.read_csv(PERF,chunksize=200000,low_memory=False):
            if perf_columns is None:
                perf_columns=list(chunk.columns)
                print('PERFORMANCE COLUMNS:', perf_columns)
            if 'season' not in chunk.columns:
                continue
            chunk=chunk[chunk['season'].astype(str).isin(RECENT)].copy()
            if chunk.empty:
                continue
            chunk['player_id']=pd.to_numeric(chunk['player_id'],errors='coerce')
            for c in ['nb_on_pitch','goals','assists','minutes_played']:
                if c in chunk.columns:
                    chunk[c+'_num']=chunk[c].map(clean_num)
            chunks.append(chunk)
        if not chunks:
            raise RuntimeError(f'No recent performance rows found. Columns={perf_columns}')
        perf=pd.concat(chunks,ignore_index=True)
    except Exception as e:
        write_error('performances',e)
        raise

    try:
        numeric=[c for c in ['nb_on_pitch_num','goals_num','assists_num','minutes_played_num'] if c in perf.columns]
        if not numeric:
            raise RuntimeError(f'No numeric performance fields available. Columns={list(perf.columns)}')
        agg=perf.groupby(['player_id','season'],as_index=False)[numeric].sum()

        def mode_map(col):
            if col not in perf.columns:
                return None
            return (perf.dropna(subset=[col]).groupby(['player_id','season'])[col]
                    .agg(lambda x: x.value_counts().index[0]).reset_index())

        for col in ['team_name','competition_name']:
            m=mode_map(col)
            if m is not None:
                agg=agg.merge(m,on=['player_id','season'],how='left')

        agg=agg.merge(prof,on='player_id',how='left').merge(val,on='player_id',how='left')

        mins=agg['minutes_played_num'].replace(0,pd.NA) if 'minutes_played_num' in agg.columns else pd.Series(pd.NA,index=agg.index)
        goals=agg['goals_num'] if 'goals_num' in agg.columns else 0
        assists=agg['assists_num'] if 'assists_num' in agg.columns else 0
        agg['goals_per90']=goals/mins*90
        agg['assists_per90']=assists/mins*90
        agg['ga_per90']=agg['goals_per90'].fillna(0)+agg['assists_per90'].fillna(0)

        if 'date_of_birth' in agg.columns:
            dob=pd.to_datetime(agg['date_of_birth'],errors='coerce')
            ref=pd.Timestamp('2026-08-19')
            agg['age']=((ref-dob).dt.days/365.25).round(1)
        else:
            agg['age']=pd.NA

        agg.to_csv(OUT/'transfermarkt_recent_player_seasons.csv',index=False)
        minutes=agg['minutes_played_num'] if 'minutes_played_num' in agg.columns else pd.Series(0,index=agg.index)
        youth=agg[(agg['age'].notna()) & (agg['age']<=23) & (minutes>=600)].copy()
        youth=youth.sort_values(['ga_per90','minutes_played_num'],ascending=[False,False])
        youth.to_csv(OUT/'transfermarkt_u23_discovery.csv',index=False)

        pd.DataFrame([{
            'source':'salimt/football-datasets (Transfermarkt-derived open dataset)',
            'profile_rows':len(prof),'recent_performance_rows':len(perf),
            'player_seasons':len(agg),'u23_600min_rows':len(youth),'status':'ok'
        }]).to_csv(OUT/'source_status.csv',index=False)
        print('SUCCESS', len(agg), 'player-seasons;', len(youth), 'U23 rows')
        print(youth.head(20).to_string(index=False))
    except Exception as e:
        write_error('build',e)
        raise


if __name__=='__main__':
    main()
