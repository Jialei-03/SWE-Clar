from urllib.request import urlopen

def fetch_text(url):
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8-sig")
