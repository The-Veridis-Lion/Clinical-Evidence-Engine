import argparse
import json
from pathlib import Path
from . import runtime, evaluation, offline


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["offline","init","pilot","final","evaluate-pilot","evaluate-final","decide-pilot","decide-final","integrity"])
    parser.add_argument("--root",type=Path,default=Path("artifacts/luna-prepared-high-v1"))
    args=parser.parse_args();repo=Path.cwd();root=args.root.resolve()
    if args.command=="offline": value=offline.replay(repo,root)
    elif args.command=="init": value=runtime.initialize(repo,root)
    elif args.command=="integrity": value={"version":runtime.integrity(repo,root)["version"],"intact":True}
    elif args.command.startswith("evaluate-"): value=evaluation.evaluate(repo,root,args.command.split("-")[1])
    elif args.command.startswith("decide-"): value=evaluation.decide(root,args.command.split("-")[1])
    else: value=runtime.execute(repo,root,args.command)
    print(json.dumps(value,ensure_ascii=False))


if __name__=="__main__": main()
