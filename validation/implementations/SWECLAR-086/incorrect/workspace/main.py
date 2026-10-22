"""Incremental stdin to SSE adapter with a local place lookup fixture."""
import argparse,json,sys
from itinerary_generator import stream_itinerary

def get_itinerary(chunks,location,find_place,find_replacement):return stream_itinerary(chunks,location,find_place,find_replacement)

def main():
 p=argparse.ArgumentParser();p.add_argument('--places',required=True);p.add_argument('--location',required=True);a=p.parse_args()
 with open(a.places) as f:places=json.load(f)
 chunks=iter(lambda:sys.stdin.read(1),'')
 for event in get_itinerary(chunks,a.location,lambda name,location:places.get('primary',{}).get(name),lambda description,location:places.get('replacement',{}).get(description)):
  sys.stdout.write(event);sys.stdout.flush()
if __name__=='__main__':main()
