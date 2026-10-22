"""Compatibility facade: candidates execute only in the unprivileged worker."""
from types import SimpleNamespace
from candidate_proxy import call
def load_solution():return SimpleNamespace(process_review_action=call)
