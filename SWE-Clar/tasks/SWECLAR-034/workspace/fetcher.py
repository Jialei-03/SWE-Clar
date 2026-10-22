from urllib.request import urlopen


def fetch_html(url):
    with urlopen(url, timeout=5) as response:
        return response.read().decode(response.headers.get_content_charset() or 'utf-8')
