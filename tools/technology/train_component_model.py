#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import numpy as np
import torch
from torch import nn

class BinaryMLP(nn.Module):
    def __init__(self,nin,hidden):
        super().__init__(); layers=[]; d=nin
        for h in hidden: layers += [nn.Linear(d,h),nn.ReLU()]; d=h
        layers.append(nn.Linear(d,1)); self.net=nn.Sequential(*layers)
    def forward(self,x): return self.net(x).squeeze(-1)

class RangeEmitterMLP(nn.Module):
    def __init__(self,nin,hidden,nrange=1):
        super().__init__(); layers=[]; d=nin
        for h in hidden: layers += [nn.Linear(d,h),nn.ReLU()]; d=h
        self.backbone=nn.Sequential(*layers); self.valid_head=nn.Linear(d,1); self.range_head=nn.Linear(d,2*nrange)
    def forward(self,x):
        z=self.backbone(x); return self.valid_head(z).squeeze(-1),self.range_head(z)

def pa():
    p=argparse.ArgumentParser(); p.add_argument('--contract',required=True,type=Path); p.add_argument('--component',required=True)
    p.add_argument('--dataset',required=True,type=Path); p.add_argument('--output',required=True,type=Path)
    p.add_argument('--hidden',nargs='+',type=int,default=[64,64]); p.add_argument('--epochs',type=int,default=500)
    p.add_argument('--lr',type=float,default=1e-3); p.add_argument('--val-fraction',type=float,default=.2); p.add_argument('--seed',type=int,default=7)
    p.add_argument('--range-loss-weight',type=float,default=.5); return p.parse_args()

def rows(p):
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def conf(y,p):
    y=y.astype(int);p=p.astype(int);return int(((y==1)&(p==1)).sum()),int(((y==0)&(p==0)).sum()),int(((y==0)&(p==1)).sum()),int(((y==1)&(p==0)).sum())
def split(y,f,s):
    rng=np.random.default_rng(s);tr=[];va=[]
    for c in (0,1):
        x=np.where(y==c)[0].copy();rng.shuffle(x);n=max(1,int(round(len(x)*f)));va+=x[:n].tolist();tr+=x[n:].tolist()
    return np.array(sorted(tr)),np.array(sorted(va))
def choose(y,p):
    z=[]
    for th in np.linspace(.05,.95,181):
        tp,tn,fp,fn=conf(y,(p>=th).astype(int));r=tp/max(tp+fn,1);pr=tp/max(tp+fp,1);z.append((float(th),r,pr,tp,tn,fp,fn))
    q=[x for x in z if x[1]>=.98];return max(q,key=lambda x:(x[0],x[2])) if q else max(z,key=lambda x:(x[1],x[2],x[0]))
def tx(v,t):
    v=float(v)
    if t=='exp': return np.log(v)
    if t in (None,'identity'): return v
    raise ValueError(t)
def itx(v,t): return np.exp(v) if t=='exp' else v

def main():
    a=pa();torch.manual_seed(a.seed);np.random.seed(a.seed)
    con=json.loads(a.contract.read_text());c={x['id']:x for x in con['components']}[a.component];m=c['model'];kind=m['kind'];fs=list(m['features']);rs=rows(a.dataset)
    X=np.asarray([[float(r[f]) for f in fs] for r in rs],np.float32);y=np.asarray([int(float(r['valid'])) for r in rs],np.float32)
    if not np.any(y==1) or not np.any(y==0):raise RuntimeError('dataset must contain valid and invalid samples')
    tr,va=split(y,a.val_fraction,a.seed);mean=X[tr].mean(0);std=X[tr].std(0);std[std<1e-12]=1.;xn=(X-mean)/std
    xt=torch.tensor(xn[tr]);yt=torch.tensor(y[tr]);xv=torch.tensor(xn[va]);yv=y[va];pos=float((y[tr]==1).sum());neg=float((y[tr]==0).sum())
    losscls=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([neg/max(pos,1.)]))
    em=list(m.get('emitted_ranges',[]));rt=None
    if kind=='binary_feasibility_classifier':model=BinaryMLP(len(fs),a.hidden)
    elif kind=='feasibility_range_emitter':
        if len(em)!=1:raise RuntimeError('current generic witness engine supports exactly one emitted range')
        model=RangeEmitterMLP(len(fs),a.hidden,len(em));rt=np.full((len(rs),2),np.nan,np.float32)
        for i,r in enumerate(rs):
            if not y[i]:continue
            s=em[0];rt[i,0]=tx(r[s['name']+'_min'],s.get('transform'));rt[i,1]=tx(r[s['name']+'_max'],s.get('transform'))
    else:raise ValueError(kind)
    opt=torch.optim.Adam(model.parameters(),lr=a.lr);best=None;bl=1e99;pm=torch.tensor(y[tr]>.5)
    for ep in range(a.epochs):
        model.train();opt.zero_grad()
        if kind=='binary_feasibility_classifier':lg=model(xt);loss=losscls(lg,yt)
        else:
            lg,rp=model(xt);loss=losscls(lg,yt)
            if bool(pm.any()):
                gi=tr[y[tr]>.5];tar=torch.tensor(rt[gi]);loss=loss+a.range_loss_weight*nn.functional.smooth_l1_loss(rp[pm],tar)
        loss.backward();opt.step()
        if ep%10==0 or ep==a.epochs-1:
            model.eval()
            with torch.no_grad():lv=model(xv) if kind=='binary_feasibility_classifier' else model(xv)[0];vl=nn.functional.binary_cross_entropy_with_logits(lv,torch.tensor(yv),pos_weight=losscls.pos_weight).item()
            if vl<bl:bl=vl;best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(best);model.eval()
    with torch.no_grad():
        if kind=='binary_feasibility_classifier':lv=model(xv);rr=None
        else:lv,rr=model(xv)
        pv=torch.sigmoid(lv).numpy()
    th,rec,pre,tp,tn,fp,fn=choose(yv.astype(int),pv);ck={'schema_version':2,'kind':kind,'feature_names':fs,'mean':mean.astype(np.float32),'std':std.astype(np.float32),'hidden':list(a.hidden),'state_dict':best,'threshold':float(th)}
    metrics=[]
    if kind=='feasibility_range_emitter':
        ck['emitted_ranges']=em;vp=np.where(yv>.5)[0];gi=va[vp];pred=rr.numpy()[vp];s=em[0];tf=s.get('transform')
        tl=np.asarray([itx(rt[k,0],tf) for k in gi]);thh=np.asarray([itx(rt[k,1],tf) for k in gi]);pl=itx(pred[:,0],tf);ph=itx(pred[:,1],tf)
        metrics=[(s['name'],float(np.mean(np.abs(pl-tl)/np.maximum(np.abs(tl),1e-12))),float(np.mean(np.abs(ph-thh)/np.maximum(np.abs(thh),1e-12))))]
    a.output.parent.mkdir(parents=True,exist_ok=True);torch.save(ck,a.output)
    print('===== GENERIC COMPONENT MODEL TRAINER =====');print('component      :',a.component);print('kind           :',kind);print('features       :',fs);print('rows           :',len(rs));print('valid/invalid  :',int(y.sum()),'/',int(len(y)-y.sum()));print('threshold      :',f'{th:.3f}');print('val recall     :',f'{rec:.4f}');print('val precision  :',f'{pre:.4f}');print('TP/TN/FP/FN   :',tp,tn,fp,fn)
    for n,l,h in metrics:print(f'{n} min/max MAPE:',f'{l:.4f}/{h:.4f}')
    print('output         :',a.output)
if __name__=='__main__':main()
