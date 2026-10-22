"""Read one request from a file or stdin and emit one JSON result."""
import json
import sys
from request_io import read_request
from solution import optimize_lineups


def main():
    request = read_request(sys.argv[1] if len(sys.argv) > 1 else None)
    result = optimize_lineups(request['players'], request['limit'], request['mode'])
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
