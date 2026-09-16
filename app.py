"""A plain-language guide from weather to estimated natural gas demand."""
import json
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import (REGIONS, BCF_PER_NATIONAL_HDD, BCF_PER_NATIONAL_CDD,
                    REFRESH_HOURS, STALE_HOURS, DISPLAY_CHANGE_BCF_PER_DAY)
from storage.database import Database, parse_time, utcnow
from data_sources.refresh import refresh, source_status, CONNECTORS
from data_sources.normals import fetch_normals, attach_degree_day_normals
from models.hdd import regional_frame, national_daily, compare_forecasts, heating_degree_days, cooling_degree_days
from models.interpretation import (daily_demand, revision_demand, summarize_demand,
                                   demand_direction, combined_signal)
from components.charts import style, GREEN, RED, BLUE, AMBER, MUTED
from components.demand_charts import demand_components, degree_days_chart, regional_demand_map
from components.context_views import render_outlooks, render_cold_context, render_market, render_glossary
from components.noaa_map_views import render_home_outlooks
from components.vortex_guide import render_vortex_guide
from data_sources.noaa_dates import previous_noaa_date

st.set_page_config(page_title='Gas Weather | Weather, explained',page_icon='◈',layout='wide',initial_sidebar_state='expanded')
st.markdown('''<style>
.block-container{padding-top:1.8rem;padding-bottom:2rem;padding-left:2rem;padding-right:2rem;max-width:1350px}
h1{font-size:2.25rem!important;letter-spacing:-.7px}h2{font-size:1.35rem!important}h3{font-size:1.08rem!important}
[data-testid="stMetric"]{background:#141e2d;border:1px solid #2a374b;border-radius:10px;padding:15px 17px;min-height:110px}
[data-testid="stMetricLabel"]{font-size:13px!important;color:#b4c3d6}
[data-testid="stMetricValue"]{font-size:1.65rem!important;font-variant-numeric:tabular-nums}
[data-testid="stCaptionContainer"]{color:#a2b2c8}
.eyebrow{font-size:11px;font-weight:700;color:#56dbc0;letter-spacing:1.6px;margin-bottom:8px}
.hero{border:1px solid #345366;background:linear-gradient(110deg,#142536,#152a2b);border-radius:12px;padding:22px 25px;margin:15px 0 20px}
.hero h2{font-size:1.65rem!important;font-weight:600;margin:6px 0 10px!important;letter-spacing:-.3px}
.hero p{color:#bbcadb;line-height:1.65;margin:0;font-size:15px}.hero .eyebrow{color:#adbed1}
.lesson{border:1px solid #2d3b50;border-radius:10px;padding:16px 18px;background:#141e2b;min-height:120px}
.lesson b{display:block;margin-bottom:7px;color:#e1ebf7}.lesson p{font-size:14px;line-height:1.6;margin:0;color:#aebed1}
[data-testid="stSidebar"] [role="radiogroup"]{gap:4px}
</style>''',unsafe_allow_html=True)

ROUTES=['Overview','Heating & cooling','What changed','Longer-range outlook','Cold-weather clues','Gas market','Data & assumptions']
FRIENDLY={'gfs':'Daily weather forecast','cpc':'Longer-range outlooks','noaa_maps':'NOAA archive and seasonal maps','snow':'Snow cover','ice':'Arctic sea ice','eia':'Gas prices and storage'}


def fmt(value,precision=2,signed=False):
    if value is None or pd.isna(value):return '—'
    return format(float(value),f'{"+" if signed else ""},.{precision}f')


def stamp(value,date_only=False):
    if not value:return 'not available'
    try:
        if len(str(value))==10 or date_only:return parse_time(value).strftime('%b %d, %Y')
        return parse_time(value).strftime('%b %d, %Y at %H:%M UTC')
    except ValueError:return str(value)


def source_stamp(payload):
    return stamp(payload.get('observed_at'),payload.get('timestamp_precision')=='date')


def plot(fig):
    st.plotly_chart(fig,width='stretch',config={'displaylogo':False,'modeBarButtonsToRemove':['lasso2d','select2d']})


def describe_effect(value):
    if value is None or not np.isfinite(value):return 'Not available'
    return 'More gas use ↑' if value>=DISPLAY_CHANGE_BCF_PER_DAY else 'Less gas use ↓' if value<=-DISPLAY_CHANGE_BCF_PER_DAY else 'Little change'


def show_effect_cards(summary,baseline):
    for col,key,label,explanation in zip(st.columns(3),['heating','cooling','total'],
        ['Heating effect','Air-conditioning effect','Combined effect'],
        ['Cold weather can raise gas use for heating.','Hot weather raises electricity demand; gas plants supply part of that power.','This adds the heating and air-conditioning effects.']):
        with col:
            value=summary[key] if summary else None
            st.metric(label,f'{fmt(value,signed=True)} Bcf/day' if value is not None else 'Not available')
            st.markdown('**'+describe_effect(value)+'**')
            st.caption(explanation)
    st.caption(f'All three numbers compare with {baseline}. Bcf means one billion cubic feet of gas. “+” means more gas use; “−” means less. These are rough estimates using the adjustable assumptions.')


@st.cache_resource
def database():return Database()


@st.cache_data(ttl=86400,show_spinner=False)
def fixed_normals():
    return fetch_normals(REGIONS)


db=database()
with st.sidebar:
    st.markdown('<div class="eyebrow">WEATHER → ENERGY USE</div>',unsafe_allow_html=True)
    st.title('Gas Weather')
    st.caption('Understand what the weather could mean for natural gas.')
    route=st.radio('Explore',ROUTES,key='navigation')
    st.divider()
    do_refresh=st.button('↻  Update the data',type='primary',width='stretch')
    st.caption('Uses free NOAA, CPC, Rutgers, NSIDC and EIA data.')
    with st.expander('Advanced: demand assumptions'):
        st.write('These settings change the rough conversion from weather to gas use. They have not been fitted to actual gas demand.')
        heating_coefficient=st.number_input('Heating: Bcf per HDD',min_value=0.0,max_value=10.0,value=BCF_PER_NATIONAL_HDD,step=.05,format='%.2f',key='heating_coefficient',help='Gas-use change for one additional population-weighted heating degree day.')
        cooling_coefficient=st.number_input('Cooling: Bcf per CDD',min_value=0.0,max_value=10.0,value=BCF_PER_NATIONAL_CDD,step=.05,format='%.2f',key='cooling_coefficient',help='Illustrative gas-for-electricity change for one additional population-weighted cooling degree day. This is not all air-conditioning electricity.')
        st.caption('HDD and CDD are explained in Heating & cooling. Adjusting these inputs changes the estimate, not the weather forecast.')

map_date=previous_noaa_date()
saved_maps=db.latest('noaa_maps')
map_day_changed=not saved_maps or saved_maps['payload'].get('requested_previous_date')!=map_date
retry_maps=map_day_changed and st.session_state.get('map_refresh_attempt_date')!=map_date
if do_refresh or 'initialized' not in st.session_state or retry_maps:
    if do_refresh:fixed_normals.clear()
    slot=st.empty()
    with slot.status('Checking the latest available data…',expanded=True) as status:
        refresh_sources=['noaa_maps'] if 'initialized' in st.session_state and not do_refresh else None
        results=refresh(db,force=do_refresh,sources=refresh_sources,progress=lambda r:st.write(f"{'✓' if r['success'] else '⚠'} {FRIENDLY.get(r['source'],r['source'])}: {'ready' if r['success'] else 'could not update'}"))
        failed=any(not r['success'] for r in results)
        status.update(label='Data checked; some sources could not update' if failed else 'Data ready',state='complete',expanded=failed)
    if not failed:slot.empty()
    st.session_state['initialized']=True
    st.session_state['map_refresh_attempt_date']=map_date

snapshots={name:db.latest(name) for name in CONNECTORS}
data={name:s['payload'] if s else {} for name,s in snapshots.items()}
gfs,cpc,eia=data['gfs'],data['cpc'],data['eia']
current=snapshots['gfs']
regional=pd.DataFrame();daily=pd.DataFrame();normal_frame=pd.DataFrame();normals_warnings=[]
comparisons={};comparison_snapshots={};revision_frames={};comparison_warnings={};forecast_error=None
if gfs.get('rows'):
    try:
        rows=gfs['rows']
        # Upgrade a legacy heating-only snapshot in memory, leaving SQLite history intact.
        if any(r.get('normal_cdd') is None for r in rows):
            normals=fixed_normals();normals_warnings=normals.get('warnings',[])
            rows=attach_degree_day_normals(rows,normals=normals)
        regional=regional_frame(rows)
        regional=regional[regional.date>utcnow().date().isoformat()]
        daily=national_daily(regional)
        normal_frame=daily_demand(daily,heating_coefficient,cooling_coefficient)
        for label,hours in [('Previous update',None),('24 hours earlier',24),('48 hours earlier',48)]:
            try:
                earlier=db.comparison(current,hours)
                comparison_snapshots[label]=earlier
                comparison=compare_forecasts(regional,regional_frame(earlier['payload']['rows'])) if earlier else pd.DataFrame()
                comparison_impact=revision_demand(comparison,heating_coefficient,cooling_coefficient)
                comparisons[label]=comparison
                revision_frames[label]=comparison_impact
            except Exception as exc:
                comparison_warnings[label]=str(exc)
                comparisons[label]=pd.DataFrame()
                revision_frames[label]=pd.DataFrame()
    except Exception as exc:
        forecast_error=str(exc)
        regional=pd.DataFrame();daily=pd.DataFrame();normal_frame=pd.DataFrame()

fresh=bool(not daily.empty and len(daily)==15 and source_status('gfs',current)=='Current')
normal_summary=summarize_demand(normal_frame)
revision_summary=summarize_demand(revision_frames.get('24 hours earlier',pd.DataFrame()))
headline_summary=normal_summary if fresh else None
headline_revision=revision_summary if fresh else None
score_table,score,score_label,score_coverage=combined_signal(
    headline_summary['total'] if headline_summary else None,
    headline_revision['total'] if headline_revision else None)

PAGE_TITLES={'Overview':'What does the weather mean for gas?', 'Heating & cooling':'Why both cold and heat matter',
             'What changed':'What changed in the forecast?', 'Longer-range outlook':'What might happen a few weeks from now?',
             'Cold-weather clues':'Clues about a possible cold spell', 'Gas market':'Put the weather in market context',
             'Data & assumptions':'Where the numbers come from'}
if route!='Overview':
    st.markdown('<div class="eyebrow">GAS WEATHER / EXPLAINED</div>',unsafe_allow_html=True)
    st.title(PAGE_TITLES[route])
if gfs and route in ['Heating & cooling','What changed']:
    st.caption(f"Weather forecast issued {stamp(gfs.get('model_run'))}. "
               +(f"Covers {stamp(daily.date.min())}–{stamp(daily.date.max())}." if not daily.empty else 'No complete future dates available.'))
if forecast_error:st.warning('The daily weather data could not be checked. Other sections still work. Details: '+forecast_error)
if current and not fresh:st.warning('The saved daily forecast is old or incomplete. Update the data before relying on its estimates.')
for attempt in db.attempts():
    if not attempt['success']:
        st.warning(f"{FRIENDLY.get(attempt['source'],attempt['source'])} could not update. The last saved reading may still be shown; check its date in Data & assumptions.")

if route=='Overview':
    if headline_summary:
        net=headline_summary['total'];direction=demand_direction(net)
        title=('Weather points to more gas demand than usual.' if direction=='More gas demand' else
               'Weather points to less gas demand than usual.' if direction=='Less gas demand' else
               'Weather points to little overall change from usual demand.')
        note=f"Under the current assumptions, the combined effect is about {abs(net):.2f} billion cubic feet {'more' if net>=0 else 'less'} gas per day over the next {headline_summary['days']} forecast days."
        if headline_summary['heating']*headline_summary['cooling']<0:
            if abs(net)<DISPLAY_CHANGE_BCF_PER_DAY:
                note+=' The heating and air-conditioning effects nearly cancel out.'
            elif headline_summary['heating']<0:
                note+=(' Extra air conditioning outweighs the drop in heating.' if net>0 else 'The drop in heating outweighs extra air conditioning.')
            else:
                note+=(' Extra heating outweighs the drop in air conditioning.' if net>0 else 'The drop in air conditioning outweighs extra heating.')
        st.markdown(f'<div class="hero"><div class="eyebrow">THE SIMPLE READ</div><h2>{title}</h2><p>{note}</p></div>',unsafe_allow_html=True)
    else:
        st.markdown('## The simple read')
        st.info('We need a fresh forecast and both heating and cooling baselines to estimate the overall effect. Missing data are not treated as zero demand.')
    render_home_outlooks(data.get('noaa_maps'))
    st.divider()
    render_vortex_guide(gfs,cpc)
    st.divider()
    st.markdown('## The gas-demand details')
    show_effect_cards(headline_summary,'usual weather for these dates, based on 1991–2020 averages')
    st.markdown('### Has the outlook changed?')
    if headline_revision:
        v=headline_revision['total'];d=headline_revision['days']
        earlier=comparison_snapshots['24 hours earlier']
        gap=(parse_time(current['model_run'])-parse_time(earlier['model_run'])).total_seconds()/3600
        st.write(f"**{describe_effect(v)} compared with the earlier forecast:** about **{abs(v):.2f} Bcf/day {'more' if v>=0 else 'less'}**, across {d} matching future dates.")
        st.caption(f"The comparison forecast was issued {stamp(earlier['model_run'])}, {gap:.0f} hours before the current one. This compares two predictions for the same dates—not today’s temperature with yesterday’s temperature.")
    else:st.info('A matching earlier forecast is not available yet. The app will keep saving forecasts as you update it.')
    st.markdown('### How to use the estimate')
    a,b=st.columns(2)
    with a:st.markdown('<div class="lesson"><b>What it tells you</b><p>Whether the forecast calls for more or less heating and air conditioning than usual, and how that expectation has changed.</p></div>',unsafe_allow_html=True)
    with b:st.markdown('<div class="lesson"><b>What is still uncertain</b><p>The forecast can change. The gas conversion is a rough assumption. Prices also depend on supply, storage, exports and what traders already expect.</p></div>',unsafe_allow_html=True)
    st.caption('More demand can support prices if other things stay the same. This is not a prediction that prices will rise. Confidence generally falls farther into the forecast; the last week deserves more caution.')
    st.markdown('### A simple way to use this dashboard')
    st.markdown('1. **Start here:** read the combined effect and what changed.\n2. **Open Longer-range outlook:** look for where warmer or colder weather is favored.\n3. **Use Cold-weather clues for context:** they do not prove a cold outbreak is coming.')
    if not normal_frame.empty and normal_frame.total.notna().all():
        with st.expander('See which days drive the estimate'):
            st.write('Bars show the separate heating and cooling effects. The green line adds them. Above zero means more gas use than usual; below zero means less.')
            plot(demand_components(normal_frame))
    with st.expander('A quick guide to the words used here'):
        render_glossary()

elif route=='Heating & cooling':
    st.write('Think of the weather as creating two kinds of energy demand. A cold region may need heating while a hot region needs air conditioning on the same day.')
    a,b=st.columns(2)
    with a:st.markdown('<div class="lesson"><b>Cold → heating → gas use</b><p>Many buildings burn gas to stay warm. More cold weather usually increases heating needs.</p></div>',unsafe_allow_html=True)
    with b:st.markdown('<div class="lesson"><b>Heat → air conditioning → electricity</b><p>Air conditioners mainly use electricity. Some of that power comes from gas plants, so hot weather can also increase gas use.</p></div>',unsafe_allow_html=True)
    st.markdown('### Try a simple temperature example')
    st.caption('This is a teaching example for one place, not a live forecast.')
    example=st.slider('Daily average temperature (°F)',min_value=20,max_value=100,value=75,step=1,key='temperature_example')
    heating=float(heating_degree_days(example));cooling=float(cooling_degree_days(example))
    a,b,c=st.columns(3)
    a.metric('Daily average',f'{example}°F');b.metric('Heating need',f'{heating:.0f} HDD');c.metric('Cooling need',f'{cooling:.0f} CDD')
    st.write(f"At **{example}°F**, this method counts **{heating:.0f} heating degree days (HDD)** and **{cooling:.0f} cooling degree days (CDD)**. Despite the name, these numbers measure how far the daily average is from 65°F; they do not count calendar days.")
    st.caption('65°F is a common calculation reference, not a thermostat recommendation or a switch that every building follows. HDD = max(65 − temperature, 0); CDD = max(temperature − 65, 0).')
    st.markdown('### What does the actual forecast show?')
    if daily.empty:st.info('The daily forecast is unavailable. The example above still explains the method.')
    else:
        kind=st.radio('Which type of demand?', ['Heating','Cooling'],horizontal=True,key='degree_day_kind')
        st.write('A higher line means more '+('heating' if kind=='Heating' else 'air conditioning')+' is likely to be needed. The dotted line is usual weather for the same dates.')
        plot(degree_days_chart(daily,kind))
        unit='hdd' if kind=='Heating' else 'cdd';normal_col='normal_hdd' if kind=='Heating' else 'normal_cdd'
        if daily[normal_col].notna().all():
            difference=float((daily[unit]-daily[normal_col]).sum())
            st.write(f"Across these {len(daily)} days, the forecast has **{abs(difference):.1f} {'more' if difference>=0 else 'fewer'} {unit.upper()} than usual**. These are national averages weighted toward places with more people.")
        else:st.info('The usual-weather comparison is incomplete. Missing station normals are not replaced with zero.')
        st.markdown('### Turn those weather differences into a rough gas estimate')
        show_effect_cards(normal_summary,'usual weather for the same dates')
        if normal_summary:
            st.write(f"**Over all {normal_summary['days']} days:** approximately **{normal_summary['cumulative']:+.1f} Bcf** combined, or **{normal_summary['total']:+.2f} Bcf/day** on average.")
            plot(demand_components(normal_frame))
        st.caption('Blue bars are heating; orange bars are air conditioning. The green line is their sum. Gas demand elsewhere still exists even when the weather contribution is zero.')
        with st.expander('See the exact math, assumptions and regional values'):
            st.code(f'Daily change in gas use = (HDD difference × {heating_coefficient:.2f})\n                         + (CDD difference × {cooling_coefficient:.2f})\nUnits: billion cubic feet per day (Bcf/day)',language='text')
            st.write('Both coefficients are illustrative. Cooling is only a temperature-based proxy for gas burned to make electricity. Humidity, wind and solar output, power-plant choices and regional differences are not modeled.')
            st.dataframe(daily,hide_index=True,width='stretch')
            heat=regional.pivot(index='region',columns='date',values='anomaly' if kind=='Heating' else 'cdd_anomaly')
            plot(style(px.imshow(heat,aspect='auto',color_continuous_scale=[[0,RED],[.5,'#182336'],[1,GREEN]],color_continuous_midpoint=0,labels={'color':f'{unit.upper()} vs usual'}),330))
            st.caption('Green = more heating/cooling need than usual; pink = less. Each region is represented by one weather station in this version.')
            st.download_button('Download the regional forecast',regional.to_csv(index=False),'regional_forecast.csv','text/csv')

elif route=='What changed':
    st.write('A forecast is a prediction made at a particular time. The important comparison is what two forecasts said about **the same future dates**. A warmer forecast can lower heating demand and raise cooling demand at the same time.')
    selected=st.radio('Compare the current forecast with…',['24 hours earlier','Previous update','48 hours earlier'],horizontal=True,key='comparison_choice')
    earlier=comparison_snapshots.get(selected)
    if selected in comparison_warnings:st.warning('This earlier forecast could not be compared: '+comparison_warnings[selected])
    comp=comparisons.get(selected,pd.DataFrame());frame=revision_frames.get(selected,pd.DataFrame());summary=summarize_demand(frame)
    if summary and earlier:
        gap=(parse_time(current['model_run'])-parse_time(earlier['model_run'])).total_seconds()/3600
        st.caption(f"Current prediction: {stamp(current['model_run'])}. Earlier prediction: {stamp(earlier['model_run'])}. Actual gap: {gap:.0f} hours; {summary['days']} matching dates.")
        show_effect_cards(summary,'the earlier forecast for the same dates')
        st.write(f"**Across all matching dates:** the estimated change is **{summary['cumulative']:+.1f} Bcf**. We leave out dates the older forecast did not reach.")
        first_week=frame[frame.date.isin(daily.date.head(7))]
        st.caption(f"Within the current forecast’s first week: {first_week.total.sum():+.1f} Bcf across {len(first_week)} matching days. Across all {summary['days']} matching days: {summary['cumulative']:+.1f} Bcf.")
        st.markdown('### Which days changed most?')
        st.write('Above zero means the newer forecast suggests more gas use. Below zero means less. The colored bars show why.')
        plot(demand_components(frame))
        with st.expander('Where did the change happen?'):
            geo=comp.groupby('region',as_index=False).agg(heating=('weighted_change','sum'),cooling=('weighted_cdd_change','sum'))
            geo['gas_change']=(geo.heating*heating_coefficient+geo.cooling*cooling_coefficient)/summary['days']
            geo=geo.merge(pd.DataFrame(REGIONS).rename(columns={'name':'region'})[['region','latitude','longitude']],on='region')
            plot(regional_demand_map(geo))
            st.caption('Green = more gas use; pink = less. Each marker is a regional proxy station. Contributions add to the national estimate, not to actual regional total consumption.')
            st.dataframe(geo[['region','gas_change']].rename(columns={'region':'Region','gas_change':'Contribution to change (Bcf/day)'}),hide_index=True,width='stretch')
        with st.expander('Show weather units and all daily changes'):
            st.write(f"Heating: {comp.weighted_change.sum():+.1f} HDD. Cooling: {comp.weighted_cdd_change.sum():+.1f} CDD across {summary['days']} matching days.")
            st.dataframe(frame.rename(columns={'heating':'Heating effect (Bcf/day)','cooling':'Cooling effect (Bcf/day)','total':'Combined effect (Bcf/day)'}),hide_index=True,width='stretch')
    else:st.info('There is no saved forecast that matches this comparison yet. Missing history does not mean the weather was unchanged.')
    with st.expander('Saved forecasts and archive import'):
        if st.button('Import missing recent NOAA forecasts'):
            from storage.bootstrap import seed_recent_history
            with st.spinner('Retrieving the original archived forecasts…'):imported=seed_recent_history(db)
            for result in imported:
                if not result['success']:st.warning(result['error'])
            if any(r['success'] for r in imported):st.rerun()
        st.dataframe(pd.DataFrame(db.history()),hide_index=True,width='stretch')
        st.caption('Model run means when NOAA made the prediction. Retrieved means when this app downloaded it. Archived predictions keep both dates; nothing is invented or rewritten.')

elif route=='Longer-range outlook':
    render_outlooks(cpc)

elif route=='Cold-weather clues':
    render_cold_context(gfs,cpc,data['snow'],data['ice'])

elif route=='Gas market':
    render_market(eia)

elif route=='Data & assumptions':
    st.write('The weather data are real. The translation into gas demand is a simple, editable estimate. This page shows both the sources and the shortcuts.')
    st.markdown('### How current is each source?')
    audit=[]
    for name,snapshot in snapshots.items():
        state=source_status(name,snapshot)
        label={'Current':'Within age limit','Stale':'Older than our age limit','Unavailable':'Not available','Age unknown':'Date unknown'}[state]
        audit.append({'Source':FRIENDLY[name],'Status':label,'Observation / issue':source_stamp(data[name]),
                      'Downloaded':stamp(snapshot['fetched_at']) if snapshot else 'not available'})
    st.dataframe(pd.DataFrame(audit),hide_index=True,width='stretch')
    st.caption('“Within age limit” does not mean today’s weather was measured today. Read the observation date. Downloading an old observation does not make it new. UTC is the common world time used to align weather forecasts.')
    for name,payload in data.items():
        with st.expander(FRIENDLY[name]+' — source and details'):
            for warning in payload.get('warnings',[]):st.warning(warning)
            if payload.get('source_url'):st.markdown(f"[Open the original source]({payload['source_url']})")
            st.write(payload.get('methodology','No successful download yet.'))
            st.caption(f"Check for updates after {REFRESH_HOURS[name]} hours; mark old after {STALE_HOURS[name]} hours. Individual CPC and EIA products also have their own dates.")
    st.markdown('### What does “usual weather” mean?')
    st.write('It means NOAA’s average heating and cooling needs for the same calendar dates during 1991–2020. It is not yesterday’s weather, a comfortable temperature, or a promise about this year.')
    st.markdown('[NOAA daily climate normals](https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/) · [EIA degree-day explanation](https://www.eia.gov/energyexplained/units-and-calculators/degree-days.php)')
    for warning in normals_warnings:st.warning(warning)
    st.markdown('### What is simplified?')
    st.markdown('''
- **Eight stations represent a large country.** Regions are weighted using 2020 population counts for the lower 48 states and Washington, DC. Gas-heating prevalence and regional power-plant mixes are not included.
- **Gas use is estimated, not measured.** The heating and cooling coefficients are illustrative. Cooling includes a temperature-based gas-for-electricity estimate, not a full power-system model. Other uses of gas still exist.
- **Daily temperatures are approximated.** We average four NOAA forecast samples per UTC day. Station normals use climatological days; this mismatch has not been corrected.
- **Forecasts are uncertain.** The daily temperature path is one GFS forecast. The NAO chart uses a set of possible forecasts; CPC maps show probabilities. They are different products.
- **A mild month can contain a cold week.** Snow, ice and atmospheric patterns are background clues, not guarantees. They are not converted into extra gas demand.
''')
    with st.expander('Advanced: exact demand formula and optional signal score'):
        st.code(f'Change in gas use for each day (Bcf/day)\n  = {heating_coefficient:.2f} × population-weighted HDD difference\n  + {cooling_coefficient:.2f} × population-weighted CDD difference\n\nTotal Bcf = sum of the daily differences\nAverage Bcf/day = total / number of matching days',language='text')
        st.write('The optional score combines the estimated demand difference from usual weather (65% weight) and the change from the 24h-old forecast (35%). It includes both heating and cooling. It is an untested display rule, not a trading system.')
        st.dataframe(score_table,hide_index=True,width='stretch')
        st.caption(f"Score {score:+.2f} out of ±1 · {score_label} · available weight {score_coverage:.0%}. Each contribution = weight × clip(estimate / scale, −1, +1). Missing inputs contribute zero; weights are not redistributed. Scale and weights are in config.py.")
        st.caption('Score labels: supportive ≥ +0.20; weaker ≤ −0.20; otherwise mixed/small. On the main page, a magnitude below 0.10 Bcf/day is called little change. These cutoffs are display choices, not confidence levels or statistically meaningful thresholds.')
    with st.expander('Regional stations and population weights'):
        st.dataframe(pd.DataFrame(REGIONS)[['name','city','population','weight','normal_station']],hide_index=True,width='stretch')
    with st.expander('A plain-English glossary'):
        render_glossary()
    st.download_button('Download the source audit',json.dumps({'sources':audit,'forecast_history':db.history()},indent=2),'source_audit.json','application/json')
    st.caption('Forecasts update on a new session or when you press Update the data. Leaving the page open does not start a background schedule. Historical snapshots stay in the server’s local database; a hosted restart may reset them. Available recent comparisons can be rebuilt from NOAA archives.')

st.divider()
st.caption('Gas Weather · Heating + air conditioning · Real public data, simple assumptions · No paid feeds or API keys')
