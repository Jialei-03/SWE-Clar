"""Provided JSON file/stdin adapter for the level analyzer."""
import argparse,json,sys
from pathlib import Path
from levels import analyze_levels

def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',nargs='?');args=parser.parse_args()
    value=json.loads(Path(args.input).read_text()) if args.input else json.load(sys.stdin)
    print(json.dumps(analyze_levels(value['bars'],value['lookback'],**value.get('options',{})),allow_nan=False))
if __name__=='__main__':main()
