from fetcher import fetch_text as default_fetch_text
from archive_parser import parse_archive
from pdf_renderer import render_pdf

def build_article_package(params, archive_url, output_dir, fetch_text=None):
    text=(fetch_text or default_fetch_text)(archive_url)
    archive=parse_archive(text)
    raise NotImplementedError("Select and normalize the archive records, then render the PDF")
