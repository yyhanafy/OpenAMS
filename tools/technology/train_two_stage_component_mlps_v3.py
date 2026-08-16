#!/usr/bin/env python3
"""
Train two-stage A and corrected B component MLPs.

A:
  inputs  W1,I5,VY,VBIAS
  outputs feasibility + log(Rmin),log(Rmax)

B:
  inputs  VOUT,VY,VBIAS,R
  output  feasibility
"""
from __future__ import annotations
import argparse,csv
from pathlib import Path
import numpy as np
import torch
from torch import nn

class AMultiHead(nn.Module):
    def __init__(self,nin=4,hidden=(64,64)):
        super().__init__(); layers=[]; d=nin
        for h in hidden: layers += [nn.Linear(d,h),nn.ReLU()]; d=h
        self.backbone=nn.Sequential(*layers); self.valid_head=nn.Linear(d,1); self.range_head=nn.Linear(d,2)
    def forward(self,x):
        z=self.backbone(x); return self.valid_head(z).squeeze(-1),self.range_head(z)

class BMLP(nn.Module):
    def __init__(self,nin=4,hidden=(64,64)):
        super().__init__(); layers=[]; d=nin
        for h in hidden: layers += [nn.Linear(d,h),nn.ReLU()]; d=h
        layers.append(nn.Linear(d,1)); self.net=nn.Sequential(*layers)
    def forward(self,x): return self.net(x).squeeze(-1)

def rows(p):
    with open(p,newline="",encoding="utf-8") as f:return list(csv.DictReader(f))

def strat_group_split(rs,vf,seed):
    groups=sorted({r["group_id"] for r in rs})
    pos={g for g in groups if any(r["group_id"]==g and int(r["valid"]) for r in rs)}
    neg=set(groups)-pos
    if len(pos)<2: raise RuntimeError(f"need >=2 positive groups, found {sorted(pos)}")
    rng=np.random.default_rng(seed); pos=list(pos); neg=list(neg); rng.shuffle(pos); rng.shuffle(neg)
    vp=max(1,int(round(len(pos)*vf))); vn=max(1,int(round(len(neg)*vf))) if neg else 0
    vg=set(pos[:vp]+neg[:vn])
    tr=np.array([i for i,r in enumerate(rs) if r["group_id"] not in vg])
    va=np.array([i for i,r in enumerate(rs) if r["group_id"] in vg])
    return tr,va,sorted(vg)

def norm(X,tr):
    m=X[tr].mean(0).astype(np.float32); s=X[tr].std(0).astype(np.float32); s[s<1e-12]=1
    return m,s,(X-m)/s

def metrics(y,p):
    best=None
    for th in np.linspace(.02,.98,193):
        z=(p>=th).astype(int); tp=int(((y==1)&(z==1)).sum()); tn=int(((y==0)&(z==0)).sum()); fp=int(((y==0)&(z==1)).sum()); fn=int(((y==1)&(z==0)).sum())
        rec=tp/max(tp+fn,1); pre=tp/max(tp+fp,1)
        item=(th,rec,pre,tp,tn,fp,fn)
        if rec>=.98 and (best is None or (th,pre)>(best[0],best[2])): best=item
    if best:return best
    allm=[]
    for th in np.linspace(.02,.98,193):
        z=(p>=th).astype(int); tp=int(((y==1)&(z==1)).sum()); tn=int(((y==0)&(z==0)).sum()); fp=int(((y==0)&(z==1)).sum()); fn=int(((y==1)&(z==0)).sum())
        rec=tp/max(tp+fn,1); pre=tp/max(tp+fp,1); allm.append((th,rec,pre,tp,tn,fp,fn))
    return max(allm,key=lambda x:(x[1],x[2]))

def trainA(path,out,epochs,lr,vf,seed):
    rs=rows(path); feats=["w_m1_um","i_m5_a","vy_v","vbias_v"]
    X=np.array([[float(r[c]) for c in feats] for r in rs],np.float32); y=np.array([int(r["valid"]) for r in rs],np.float32)
    tr,va,vg=strat_group_split(rs,vf,seed); m,s,Xn=norm(X,tr)
    lo=np.full(len(rs),np.nan,np.float32); hi=np.full(len(rs),np.nan,np.float32)
    for i,r in enumerate(rs):
        if y[i]: lo[i]=np.log(float(r["r_min"])); hi[i]=np.log(float(r["r_max"]))
    torch.manual_seed(seed); model=AMultiHead(); opt=torch.optim.Adam(model.parameters(),lr=lr)
    pos=y[tr].sum(); neg=len(tr)-pos; lcls=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([neg/max(pos,1)],dtype=torch.float32))
    xt=torch.tensor(Xn[tr]); yt=torch.tensor(y[tr]); pm=torch.tensor(y[tr]>0)
    best=None; bl=1e99
    for ep in range(epochs):
        model.train(); opt.zero_grad(); lg,rr=model(xt); loss=lcls(lg,yt)
        if pm.any():
            gi=tr[y[tr]>0]; target=torch.tensor(np.c_[lo[gi],hi[gi]],dtype=torch.float32)
            loss=loss+.5*nn.functional.smooth_l1_loss(rr[pm],target)
        loss.backward(); opt.step()
        if ep%10==0 or ep==epochs-1:
            model.eval()
            with torch.no_grad():
                lv,_=model(torch.tensor(Xn[va])); vl=nn.functional.binary_cross_entropy_with_logits(lv,torch.tensor(y[va])).item()
            if vl<bl: bl=vl; best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(best); model.eval()
    with torch.no_grad(): lv,rr=model(torch.tensor(Xn[va])); p=torch.sigmoid(lv).numpy(); rr=rr.numpy()
    th,rec,pre,tp,tn,fp,fn=metrics(y[va].astype(int),p)
    vp=np.where(y[va]>0)[0]; gi=va[vp]
    lm=float(np.mean(np.abs(np.exp(rr[vp,0])-np.exp(lo[gi]))/np.exp(lo[gi])))
    hm=float(np.mean(np.abs(np.exp(rr[vp,1])-np.exp(hi[gi]))/np.exp(hi[gi])))
    out.parent.mkdir(parents=True,exist_ok=True)
    torch.save({"schema_version":3,"kind":"two_stage_A_feasibility_ratio_envelope","feature_names":feats,"mean":m,"std":s,"hidden":[64,64],"state_dict":best,"threshold":float(th),"ratio_outputs":["log_r_min","log_r_max"]},out)
    print("===== MLP-A ====="); print("validation groups:",vg); print("recall/precision:",f"{rec:.4f}/{pre:.4f}"); print("TP/TN/FP/FN:",tp,tn,fp,fn); print("Rmin/Rmax MAPE:",f"{lm:.4f}/{hm:.4f}"); print("output:",out)

def trainB(path,out,epochs,lr,vf,seed):
    rs=rows(path); feats=["vout_v","vy_v","vbias_v","stage_ratio"]
    X=np.array([[float(r[c]) for c in feats] for r in rs],np.float32); y=np.array([int(r["valid"]) for r in rs],np.float32)
    # For B every VOUT group should contain positives and negatives; grouped split tests unseen VOUT slices.
    tr,va,vg=strat_group_split(rs,vf,seed); m,s,Xn=norm(X,tr)
    torch.manual_seed(seed); model=BMLP(); opt=torch.optim.Adam(model.parameters(),lr=lr)
    pos=y[tr].sum(); neg=len(tr)-pos; lossfn=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([neg/max(pos,1)],dtype=torch.float32))
    xt=torch.tensor(Xn[tr]); yt=torch.tensor(y[tr]); best=None; bl=1e99
    for ep in range(epochs):
        model.train(); opt.zero_grad(); loss=lossfn(model(xt),yt); loss.backward(); opt.step()
        if ep%10==0 or ep==epochs-1:
            model.eval()
            with torch.no_grad():
                lv=model(torch.tensor(Xn[va])); vl=nn.functional.binary_cross_entropy_with_logits(lv,torch.tensor(y[va])).item()
            if vl<bl: bl=vl; best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(best); model.eval()
    with torch.no_grad(): p=torch.sigmoid(model(torch.tensor(Xn[va]))).numpy()
    th,rec,pre,tp,tn,fp,fn=metrics(y[va].astype(int),p)
    out.parent.mkdir(parents=True,exist_ok=True)
    torch.save({"schema_version":3,"kind":"two_stage_B_feasibility","feature_names":feats,"mean":m,"std":s,"hidden":[64,64],"state_dict":best,"threshold":float(th)},out)
    print("\n===== MLP-B ====="); print("validation groups:",vg); print("recall/precision:",f"{rec:.4f}/{pre:.4f}"); print("TP/TN/FP/FN:",tp,tn,fp,fn); print("output:",out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--a-dataset",type=Path,required=True); ap.add_argument("--b-dataset",type=Path,required=True)
    ap.add_argument("--a-output",type=Path,required=True); ap.add_argument("--b-output",type=Path,required=True)
    ap.add_argument("--epochs",type=int,default=600); ap.add_argument("--lr",type=float,default=1e-3); ap.add_argument("--val-fraction",type=float,default=.25); ap.add_argument("--seed",type=int,default=7)
    a=ap.parse_args(); trainA(a.a_dataset,a.a_output,a.epochs,a.lr,a.val_fraction,a.seed); trainB(a.b_dataset,a.b_output,a.epochs,a.lr,a.val_fraction,a.seed)

if __name__=="__main__": main()
