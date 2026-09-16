import plotly.graph_objects as go
import plotly.express as px

GREEN='#56dbc0'
RED='#fa7c83'
BLUE='#75a9ff'
AMBER='#f1bf73'
MUTED='#8898ae'

def style(fig,height=330):
    fig.update_layout(template='plotly_dark',height=height,paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',font=dict(family='Inter, sans-serif',size=12,color='#b8c6d9'),
        margin=dict(l=10,r=15,t=25,b=10),legend=dict(orientation='h',y=1.15,x=0),
        hovermode='x unified',xaxis_title=None)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor='#233044',zerolinecolor='#53657c')
    return fig

def hdd_chart(daily):
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=daily.date,y=daily.hdd,name='GFS forecast',line=dict(color=GREEN,width=3),fill='tozeroy',fillcolor='rgba(86,219,192,0.07)'))
    if daily.normal_hdd.notna().any():
        fig.add_trace(go.Scatter(x=daily.date,y=daily.normal_hdd,name='1991–2020 normal',line=dict(color=MUTED,width=2,dash='dot')))
    fig.update_yaxes(title='Population-weighted HDD / day')
    return style(fig,350)

def delta_chart(frame,value='change',title='Δ weighted HDD'):
    fig=go.Figure(go.Bar(x=frame.date,y=frame[value],marker_color=[GREEN if x>=0 else RED for x in frame[value]],name=title))
    fig.update_yaxes(title=title)
    return style(fig,290)

def line_chart(frame,x,y,title,color=BLUE,height=280):
    fig=px.line(frame,x=x,y=y,color_discrete_sequence=[color])
    fig.update_yaxes(title=title)
    return style(fig,height)

def regional_map(frame):
    fig=go.Figure(go.Scattergeo(lon=frame.longitude,lat=frame.latitude,
        text=frame.region,mode='markers+text',textposition='top center',
        marker=dict(size=frame['magnitude'],color=frame.weighted_change,colorscale=[[0,RED],[0.5,'#31435d'],[1,GREEN]],
                    cmin=-max(frame.weighted_change.abs().max(),0.1),cmax=max(frame.weighted_change.abs().max(),0.1),
                    colorbar=dict(title='Δ HDD'),line=dict(width=1,color='#dce8f8')),
        customdata=frame[['weighted_change','change']],
        hovertemplate='%{text}<br>National contribution: %{customdata[0]:+.2f} HDD<br>Regional change: %{customdata[1]:+.2f} HDD<extra></extra>'))
    fig.update_geos(scope='usa',projection_type='albers usa',bgcolor='rgba(0,0,0,0)',landcolor='#19273a',
                    lakecolor='#0b1019',showland=True,showsubunits=True,subunitcolor='#40506a')
    return style(fig,340)
