"""Small, bounded public-data HTTP requests. Never caches error bodies."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def session():
    client = requests.Session()
    retry = Retry(total=2, connect=2, read=2, status=2, backoff_factor=0.6,
                  status_forcelist=[429,500,502,503,504], allowed_methods=['GET','HEAD'],
                  respect_retry_after_header=False)
    client.mount('https://', HTTPAdapter(max_retries=retry))
    client.headers['User-Agent'] = 'GasWeatherResearch/1.0 (public-data local dashboard)'
    return client

def get_response(url, **kwargs):
    kwargs.setdefault('timeout', (10, 35))
    with session() as client:
        response = client.get(url, **kwargs)
        response.raise_for_status()
        return response

def get_text(url, **kwargs):
    return get_response(url, **kwargs).text

def get_bytes(url, **kwargs):
    return get_response(url, **kwargs).content

def get_json(url, **kwargs):
    return get_response(url, **kwargs).json()
