from workspace import load_workspace


def run_inventory_sync(workspace, cin7_client, post_processor=None):
    root,config=load_workspace(workspace)
    return {'processed':[], 'skipped':[], 'outputs':[], 'warnings':[], 'errors':[], 'actions':[]}
