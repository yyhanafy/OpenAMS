#!/usr/bin/env python3
"""Compile the standard hierarchical contract and preserve declarative training metadata."""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
import yaml

def main():
    p=argparse.ArgumentParser();p.add_argument('--intent',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--root',type=Path,default=Path('.'));a=p.parse_args();root=a.root.resolve()
    intent=a.intent if a.intent.is_absolute() else (root/a.intent).resolve();out=a.output if a.output.is_absolute() else (root/a.output).resolve()
    base=root/'tools/compile_hierarchical_component_contract.py'
    subprocess.run([sys.executable,str(base),'--intent',str(intent),'--output',str(out)],cwd=root,check=True)
    src=yaml.safe_load(intent.read_text(encoding='utf-8'));contract=json.loads(out.read_text(encoding='utf-8'))
    meta={c['id']:c.get('training') for c in src['hierarchical_feasibility']['components'] if c.get('training') is not None}
    for c in contract.get('components',[]):
        if c['id'] in meta:c['training']=meta[c['id']]
    out.write_text(json.dumps(contract,indent=2)+'\n',encoding='utf-8')
    print('training metadata preserved:',sorted(meta))
if __name__=='__main__':main()
