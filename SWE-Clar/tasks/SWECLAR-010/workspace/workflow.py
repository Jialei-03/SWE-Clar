"""Unfinished monitoring, archive and subscription workflows.

The working server and competitor directory call this module. Clarify business
policies, then implement the actual HTTP/database workflows using the prepared
page and receipt service. Public schemas and commands are in README.md.
"""
from common import Problem


def authorize_creation(db, owner):
    # Existing directory behavior; integrate clarified subscription permissions.
    pass


def dispatch(db, owner, provider, method, path, query, body):
    raise Problem(501, 'workflow_not_implemented')
