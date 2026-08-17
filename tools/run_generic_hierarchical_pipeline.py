#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,shutil,subprocess,sys
from pathlib import Path

def pa():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--intent',type=Path,default=None);p.add_argument('--contract',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=12);p.add_argument('--component-model-dir',type=Path,default=Path('technology/component_models'));p.add_argument('--epochs',type=int);p.add_argument('--lr',type=float);p.add_argument('--val-fraction',type=float);p.add_argument('--seed',type=int);p.add_argument('--hidden',nargs='+',type=int);p.add_argument('--skip-contract-compile',action='store_true');p.add_argument('--skip-datasets',action='store_true');p.add_argument('--skip-training',action='store_true');p.add_argument('--skip-final-witnesses',action='store_true');p.add_argument('--clean',action='store_true');return p.parse_args()
def re(root,p):return p if p.is_absolute() else (root/p).resolve()
def run(c,cwd):
    print('\nRUN:');print('  '+' \\\n    '.join(map(str,c)));subprocess.run(list(map(str,c)),cwd=cwd,check=True)
def main():
    a=pa();root=a.root.resolve();contract=re(root,a.contract);work=re(root,a.work_dir);output=re(root,a.output);md=re(root,a.component_model_dir);ds=work/'datasets';oracle=work/'dataset_oracle';models=work/'models';hw=work/'hierarchical_witness'
    ct=root/'tools/compile_hierarchical_component_contract_training.py';dt=root/'tools/validation/generate_component_feasibility_datasets.py';tt=root/'tools/technology/train_component_model.py';wt=root/'tools/validation/hierarchical_witness_engine.py'
    for p in [dt,tt,wt]:
        if not p.is_file():raise SystemExit(f'missing required tool: {p}')
    if a.clean and work.exists():shutil.rmtree(work)
    for d in [work,ds,models,md,output.parent]:d.mkdir(parents=True,exist_ok=True)
    if a.intent is not None and not a.skip_contract_compile:run([sys.executable,ct,'--intent',re(root,a.intent),'--output',contract],root)
    obj=json.loads(contract.read_text());cs=list(obj['components']);print('\n===== PIPELINE COMPONENTS =====')
    for c in cs:print(f"{c['id']}: kind={c['model']['kind']} features={c['model'].get('features',[])} checkpoint={c['model'].get('checkpoint')}")
    if not a.skip_datasets:run([sys.executable,dt,'--contract',contract,'--output-dir',ds,'--work-dir',oracle,'--workers',a.workers],root)
    if not a.skip_training:
        for c in cs:
            cid=c['id'];fn=Path(c['model'].get('checkpoint',cid+'.pt')).name;tr=models/fn;ins=md/fn;cmd=[sys.executable,tt,'--contract',contract,'--component',cid,'--dataset',ds/f'{cid}_dataset.csv','--output',tr]
            if a.hidden is not None:cmd+=['--hidden',*a.hidden]
            if a.epochs is not None:cmd+=['--epochs',a.epochs]
            if a.lr is not None:cmd+=['--lr',a.lr]
            if a.val_fraction is not None:cmd+=['--val-fraction',a.val_fraction]
            if a.seed is not None:cmd+=['--seed',a.seed]
            run(cmd,root);shutil.copy2(tr,ins);print('INSTALLED:',ins)
            try:rel=ins.relative_to(root)
            except ValueError:rel=ins
            c['model']['checkpoint']=str(rel)
        contract.write_text(json.dumps(obj,indent=2)+'\n');print('\nUPDATED CONTRACT CHECKPOINTS:',contract)
    if not a.skip_final_witnesses:
        if hw.exists():shutil.rmtree(hw)
        run([sys.executable,wt,'--contract',contract,'--output',output,'--work-dir',hw,'--workers',a.workers],root)
    print('\n===== OPENAMS HIERARCHICAL PIPELINE COMPLETE =====');print('contract:',contract);print('datasets:',ds);print('trained models:',models);print('final witnesses:',output if not a.skip_final_witnesses else 'skipped')
if __name__=='__main__':main()
