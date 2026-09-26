"""Private experimental CLI. No production routes or rendering changes."""
import argparse
import json
import sys

from experiment_data import ROOT, candidate_pool, load_library, save
from model_reader import Reader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('index')
    discover = commands.add_parser('discover')
    discover.add_argument('--limit',type=int,default=80)
    discover.add_argument('--workers',type=int,default=2)
    find = commands.add_parser('find')
    request = find.add_mutually_exclusive_group(required=True)
    request.add_argument('--brief')
    request.add_argument('--brief-file',type=__import__('pathlib').Path)
    find.add_argument('--samples',type=int,default=48)
    commands.add_parser('report')
    serve = commands.add_parser('serve')
    serve.add_argument('--port',type=int,default=8770)
    args = parser.parse_args()
    reader = Reader()  # Full-tier and configured-model guard precedes corpus access.
    if args.command == 'serve':
        from review_server import serve
        serve(reader,args.port)
        return
    library = load_library()
    if args.command == 'index':
        candidates = candidate_pool(library)
        print(json.dumps({'captions':len(library.rows),'candidates':len(candidates)}))
    elif args.command == 'discover':
        from nominate import nominate
        from workflow import run_refinement
        candidates = candidate_pool(library)
        path = ROOT/'data/nominations.json'
        nominations = json.loads(path.read_text()) if path.exists() else []
        if {d['key'] for d in nominations}!={c['key'] for c in candidates}:
            nominations = nominate(reader,library,candidates,args.workers)
        run_refinement(reader,library,candidates,nominations,args.limit,args.workers)
        from report import write_report
        write_report(reader,library)
    elif args.command == 'find':
        from query import find
        brief = (sys.stdin.read() if str(args.brief_file)=='-' else args.brief_file.read_text()) if args.brief_file else args.brief
        result = find(reader,library,brief,args.samples)
        print(json.dumps({'key':result['key'],'status':result['status'],
                          'title':result.get('judgment',{}).get('title'),
                          'accepted':result.get('accepted'),
                          'file':str(ROOT/'requests'/f"{result['key'][8:]}.json")},ensure_ascii=False))
        save(ROOT/'data/model-stats.json',reader.statistics())
    elif args.command == 'report':
        from report import write_report
        write_report(reader,library)


if __name__ == '__main__':
    main()
