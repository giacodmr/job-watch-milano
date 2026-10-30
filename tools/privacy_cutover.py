#!/usr/bin/env python3
"""CLI: stdout is redacted; detailed evidence and encrypted backups stay outside Git."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from privacy_safety.common import SafetyError, canonical, digest, read_private_json, source_remote, write_private
from privacy_safety.continuity import capture, compare
from privacy_safety.git_backup import create_backup, restore_backup
from privacy_safety.publish_guard import check_publish
from privacy_safety.preflight import GitHubReadClient, preflight, compare_preflight

class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default includes invalid arguments, potentially tokens or PII.
        raise SafetyError('INVALID_ARGUMENTS')

def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--age',default=os.environ.get('JOB_WATCH_AGE_BIN','age'))
    commands = parser.add_subparsers(dest='command',required=True,parser_class=Parser)
    pf = commands.add_parser('preflight');pf.add_argument('--phase',choices=['before','after'],default='before')
    pf.add_argument('--online',action='store_true');pf.add_argument('--out')
    pf.add_argument('--baseline')
    cont = commands.add_parser('continuity');cont.add_argument('--commit',required=True)
    cont.add_argument('--at');cont.add_argument('--out',required=True);cont.add_argument('--baseline')
    backup = commands.add_parser('backup');backup.add_argument('--recipient',required=True);backup.add_argument('--out',required=True)
    for name in ('verify','restore'):
        sub = commands.add_parser(name);sub.add_argument('--capsule',required=True);sub.add_argument('--identity',required=True);sub.add_argument('--sha256',required=True)
        if name=='restore': sub.add_argument('--target',required=True)
    publish = commands.add_parser('publish-check');publish.add_argument('--base',required=True)
    args = parser.parse_args(argv)
    if args.command == 'publish-check':
        print(json.dumps(check_publish(args.root,args.base),sort_keys=True));return 0
    if args.command == 'preflight':
        source_remote(args.root)
        client = GitHubReadClient(os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')) if args.online else None
        result = preflight(args.root,phase=args.phase,age=args.age,client=client)
        if args.baseline:
            result['comparison'] = compare_preflight(read_private_json(args.baseline),result)
        if args.out: write_private(args.out,canonical(result))
        print(json.dumps(result,sort_keys=True))
        return 0 if result['ready'] else 2
    if args.command == 'continuity':
        result = capture(args.root,args.commit,at=args.at)
        summary = compare(read_private_json(args.baseline),result) if args.baseline else {'status':'CONTINUITY_CAPTURED','commit_sha':args.commit,'evidence_sha256':digest(canonical(result))}
        write_private(args.out,canonical(result));print(json.dumps(summary,sort_keys=True));return 0
    if args.command == 'backup':
        result = create_backup(source_remote(args.root),args.out,args.recipient,age=args.age)
    else:
        result = restore_backup(args.capsule,args.identity,args.sha256,getattr(args,'target',None),age=args.age)
    print(json.dumps(result,sort_keys=True));return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except SafetyError as error:
        print(json.dumps({'error':error.code,'production_mutation':False}),file=sys.stderr);sys.exit(1)
    except Exception:
        print('{"error":"SAFETY_OPERATION_FAILED","production_mutation":false}',file=sys.stderr);sys.exit(1)
