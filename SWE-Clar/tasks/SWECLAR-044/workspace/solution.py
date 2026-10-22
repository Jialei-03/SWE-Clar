from fetcher import fetch_text as default_fetch_text
from measurements import parse_measurements
from copy import deepcopy

def process_trend_action(state,action,fetch_text=None):
    return deepcopy(state)
