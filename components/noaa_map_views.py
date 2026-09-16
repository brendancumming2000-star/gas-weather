"""A compact, dated gallery of saved NOAA temperature outlook images."""
import base64
import binascii
import streamlit as st

from storage.database import parse_time
from data_sources.noaa_dates import previous_noaa_date


def _date(value):
    try:
        return parse_time(value).strftime('%b %d, %Y')
    except (TypeError, ValueError):
        return 'date unavailable'


def _map_card(title, product, missing_text):
    st.markdown('### ' + title)
    if not product:
        st.info(missing_text)
        return
    st.caption(f"Issued {_date(product.get('observed_at'))} · {product.get('valid_period') or 'See valid dates on map'}")
    if product.get('retained_from_cache'):
        st.caption('Saved issue shown; the latest publication could not be checked.')
    if product.get('selection_warning'):
        st.caption(product['selection_warning'])
    if product.get('image_base64'):
        try:
            st.image(base64.b64decode(product['image_base64'], validate=True), width='stretch')
        except (binascii.Error, ValueError, TypeError, OSError):
            st.info('The saved image could not be displayed. Open the official source below.')
    else:
        st.info('The map image is unavailable for this issue.')
    if product.get('source_url'):
        if product.get('is_dated_archive') and product.get('image_url'):
            st.markdown(f"[Full-size map]({product['image_url']}) · [NOAA discussion]({product['source_url']})")
        else:
            st.markdown(f"[NOAA seasonal outlook]({product['source_url']})")


def render_home_outlooks(payload):
    payload = payload or {}
    requested = payload.get('requested_previous_date')
    target = previous_noaa_date()
    st.markdown('## NOAA temperature outlooks')
    st.caption(f"Daily maps issued {_date(target)} · Weeks 3–4 uses the latest weekly issue available by that date · Seasonal map uses the latest published November–January outlook.")
    # Never relabel a retained historical bundle as yesterday's forecast.
    if requested and requested != target:
        st.warning(f"These saved maps were selected for {_date(requested)}, not yesterday. Update the data to load the requested date.")
    products = {p.get('name'): p for p in payload.get('previous_outlooks', []) if isinstance(p, dict)}
    a, b = st.columns(2, gap='large')
    with a:
        _map_card('6–10 days', products.get('6–10 day'), 'The previous-day 6–10 day map is unavailable.')
    with b:
        _map_card('8–14 days', products.get('8–14 day'), 'The previous-day 8–14 day map is unavailable.')
    a, b = st.columns(2, gap='large')
    with a:
        _map_card('Weeks 3–4', products.get('Weeks 3–4'), 'A weekly map available by the previous day could not be retrieved.')
        st.caption('Updated weekly, so its issue date will often be earlier than yesterday.')
    with b:
        _map_card('November–December–January', payload.get('seasonal'), 'The latest November–January seasonal map is unavailable.')
        st.caption('One outlook for the three months together, not three separate monthly forecasts.')
    st.markdown('**Read the colors:** orange/red favors warmer than usual; blue favors cooler. **N** favors near-normal temperatures; **EC** means no category is favored. Percentages are the chance of a temperature category—not the size of the temperature change.')
    st.caption('These maps describe the average across each labeled period. A warm season can still contain a very cold week. Open a map fullscreen to read its detailed legend.')
    if payload.get('warnings'):
        with st.expander('Map availability and source details'):
            for warning in dict.fromkeys(payload['warnings']):
                st.warning(str(warning))
    if requested:
        st.caption(f"Previous day uses NOAA’s Eastern Time calendar. Saved archive selection: {_date(requested)}.")
