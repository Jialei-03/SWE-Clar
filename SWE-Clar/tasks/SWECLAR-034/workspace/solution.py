import json
import sys
from fetcher import fetch_html
from listing_parser import parse_listing


def transform(rows):
    if rows == []:
        return []
    raise NotImplementedError('Implement listing normalization')


def scrape(urls):
    return transform([parse_listing(fetch_html(url), url) for url in urls])


if __name__ == '__main__':
    print(json.dumps(scrape(json.load(sys.stdin)), ensure_ascii=False))
