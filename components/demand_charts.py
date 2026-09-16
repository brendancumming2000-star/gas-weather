"""Charts whose labels explain the comparison before showing the units."""
import plotly.graph_objects as go
import plotly.express as px
from components.charts import style, GREEN, RED, BLUE, AMBER, MUTED


def demand_components(frame):
    fig=go.Figure()
    fig.add_trace(go.Bar(x=frame.date,y=frame.heating,name='Heating effect',marker_color=BLUE))
    fig.add_trace(go.Bar(x=frame.date,y=frame.cooling,name='Air-conditioning effect',marker_color=AMBER))
    fig.add_trace(go.Scatter(x=frame.date,y=frame.total,name='Combined effect',line=dict(color=GREEN,width=3),mode='lines+markers'))
    fig.update_layout(barmode='relative')
    fig.add_hline(y=0,line_color=MUTED,line_width=1)
    fig.update_yaxes(title='Estimated change in gas use · Bcf/day')
    return style(fig,330)


def degree_days_chart(daily,kind):
    cooling=kind=='Cooling'
    value='cdd' if cooling else 'hdd'
    normal='normal_cdd' if cooling else 'normal_hdd'
    color=AMBER if cooling else BLUE
    unit='CDD' if cooling else 'HDD'
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=daily.date,y=daily[value],name='Forecast',line=dict(color=color,width=3)))
    if daily[normal].notna().any():
        fig.add_trace(go.Scatter(x=daily.date,y=daily[normal],name='Usual for these dates',line=dict(color=MUTED,dash='dot',width=2)))
    fig.update_yaxes(title=f'{kind} need · {unit} per day')
    return style(fig,315)


def regional_demand_map(frame):
    limit=max(float(frame.gas_change.abs().max()),.01)
    fig=go.Figure(go.Scattergeo(lon=frame.longitude,lat=frame.latitude,text=frame.region,
        mode='markers+text',textposition='top center',
        marker=dict(size=12+25*frame.gas_change.abs()/limit,color=frame.gas_change,
                    colorscale=[[0,RED],[.5,'#34435b'],[1,GREEN]],cmin=-limit,cmax=limit,
                    colorbar=dict(title='Bcf/day'),line=dict(width=1,color='#becddd')),
        customdata=frame[['gas_change']],
        hovertemplate='%{text}<br>Contribution to national change: %{customdata[0]:+.3f} Bcf/day<extra></extra>'))
    fig.update_geos(scope='usa',projection_type='albers usa',bgcolor='rgba(0,0,0,0)',
                    landcolor='#19273a',lakecolor='#0b1019',showland=True,showsubunits=True,subunitcolor='#40506a')
    return style(fig,330)
