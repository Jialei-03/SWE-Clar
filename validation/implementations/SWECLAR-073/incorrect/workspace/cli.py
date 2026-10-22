"""Migrate synthetic local assets to a local content repository."""
import argparse,json,sys

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--destination',required=True);a=p.parse_args();request=json.load(sys.stdin)
 from solution import migrate_asset_batch
 print(json.dumps(migrate_asset_batch(request['assets'],request['taxonomy'],a.source,a.destination),allow_nan=False))
if __name__=='__main__':main()
