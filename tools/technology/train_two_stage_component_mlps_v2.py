#!/usr/bin/env python3
"""
Train two-stage A/B component MLPs v2 with stratified GROUP validation.
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

class BinaryMLP(nn.Module):
    def __init__(self,nin=5,hidden=(64,64)):
        super().__init__(); layers=[]; d=nin
        for h in hidden: layers += [nn.Linear(d,h),nn.ReLU()]; d=h
        layers.append(nn.Linear(d,1)); self.net=nn.Sequential(*layers)
    def forward(self,x): return self.net(x).squeeze(-1)

def rows(p):
    with open(p,newline="",encoding="utf-8") as f:return list(csv.DictReader(f))

def strat_group_split(rs,val_fraction,seed):
    groups=sorted({r["group_id"] for r in rs})
    positive={g for g in groups if any(r["group_id"]==g and int(r["valid"]) for r in rs)}
    negative=set(groups)-positive
    if len(positive)<2: raise RuntimeError(f"need >=2 positive groups; found {len(positive)}: {sorted(positive)}")
    rng=np.random.default_rng(seed)
    pos=list(positive); neg=list(negative); rng.shuffle(pos); rng.shuffle(neg)
    npv=max(1,int(round(len(pos)*val_fraction))); nnv=max(1,int(round(len(neg)*val_fraction))) if neg else 0
    vg=set(pos[:npv]+neg[:nnv])
    tr=np.array([i for i,r in enumerate(rs) if r["group_id"] not in vg])
    va=np.array([i for i,r in enumerate(rs) if r["group_id"] in vg])
    if not np.any(np.array([int(rs[i]["valid"]) for i in va])==1): raise RuntimeError("validation has zero positives")
    return tr,va,sorted(vg)

def norm(X,tr):
    m=X[tr].mean(0).astype(np.float32); s=X[tr].std(0).astype(np.float32); s[s<1e-12]=1
    return m,s,(X-m)/s

def threshold(y,p):
    best=None
    for th in np.linspace(.02,.98,193):
        z=(p>=th).astype(int); tp=((y==1)&(z==1)).sum(); tn=((y==0)&(z==0)).sum(); fp=((y==0)&(z==1)).sum(); fn=((y==1)&(z==0)).sum()
        rec=tp/max(tp+fn,1); pre=tp/max(tp+fp,1); item=(th,rec,pre,int(tp),int(tn),int(fp),int(fn))
        if rec>=.98 and (best is None or (th,pre)>(best[0],best[2])): best=item
    if best:return best
    return max((threshold_item(y,p,t) for t in np.linspace(.02,.98,193)),key=lambda x:(x[1],x[2]))
def threshold_item(y,p,th):
    z=(p>=th).astype(int); tp=((y==1)&(z==1)).sum(); tn=((y==0)&(z==0)).sum(); fp=((y==0)&(z==1)).sum(); fn=((y==1)&(z==0)).sum()
    return th,tp/max(tp+fn,1),tp/max(tp+fp,1),int(tp),int(tn),int(fp),int(fn)

def trainA(path,out,epochs,lr,vf,seed):
    rs=rows(path); feats=["w_m1_um","i_m5_a","vy_v","vbias_v"]
    X=np.array([[float(r[c]) for c in feats] for r in rs],np.float32); y=np.array([int(r["valid"]) for r in rs],np.float32)
    tr,va,vg=strat_group_split(rs,vf,seed); m,s,Xn=norm(X,tr)
    rlo=np.full(len(rs),np.nan,np.float32); rhi=rlo.copy()
    for i,r in enumerate(rs):
        if y[i]: rlo[i]=np.log(float(r["r_min"])); rhi[i]=np.log(float(r["r_max"]))
    torch.manual_seed(seed); model=AMultiHead(len(feats)); opt=torch.optim.Adam(model.parameters(),lr=lr)
    pos=y[tr].sum(); neg=len(tr)-pos; losscls=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([neg/max(pos,1)],dtype=torch.float32))
    xt=torch.tensor(Xn[tr]); yt=torch.tensor(y[tr]); pm=torch.tensor(y[tr]>0)
    best=None; bl=1e99
    for ep in range(epochs):
        model.train(); opt.zero_grad(); logit,rr=model(xt); loss=losscls(logit,yt)
        if pm.any():
            gi=tr[y[tr]>0]; target=torch.tensor(np.c_[rlo[gi],rhi[gi]],dtype=torch.float32)
            loss=loss+.5*nn.functional.smooth_l1_loss(rr[pm],target)
        loss.backward(); opt.step()
        if ep%10==0 or ep==epochs-1:
            model.eval()
            with torch.no_grad():
                lv,_=model(torch.tensor(Xn[va])); vl=nn.functional.binary_cross_entropy_with_logits(lv,torch.tensor(y[va])).item()
            if vl<bl: bl=vl; best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(best); model.eval()
    with torch.no_grad(): lv,rr=model(torch.tensor(Xn[va])); p=torch.sigmoid(lv).numpy(); rr=rr.numpy()
    th,rec,pre,tp,tn,fp,fn=threshold(y[va].astype(int),p)
    vp=np.where(y[va]>0)[0]; gi=va[vp]
    plo=np.exp(rr[vp,0]); phi=np.exp(rr[vp,1]); tlo=np.exp(rlo[gi]); thi=np.exp(rhi[gi])
    lm=float(np.mean(np.abs(plo-tlo)/tlo)); hm=float(np.mean(np.abs(phi-thi)/thi))
    out.parent.mkdir(parents=True,exist_ok=True)
    torch.save({"schema_version":2,"kind":"two_stage_A_feasibility_ratio_envelope","feature_names":feats,"mean":m,"std":s,"hidden":[64,64],"state_dict":best,"threshold":float(th),"ratio_outputs":["log_r_min","log_r_max"]},out)
    print("===== TWO-STAGE MLP-A V2 ====="); print("rows/valid/invalid:",len(y),int(y.sum()),int(len(y)-y.sum())); print("validation groups:",vg)
    print("threshold:",f"{th:.3f}"); print("val recall/precision:",f"{rec:.4f}/{pre:.4f}"); print("TP/TN/FP/FN:",tp,tn,fp,fn); print("Rmin/Rmax MAPE:",f"{lm:.4f}/{hm:.4f}"); print("output:",out)

def trainB(path,out,epochs,lr,vf,seed):
    rs=rows(path); feats=["i_m5_a","vout_v","vy_v","vbias_v","stage_ratio"]
    X=np.array([[float(r[c]) for c in feats] for r in rs],np.float32); y=np.array([int(r["valid"]) for r in rs],np.float32)
    tr,va,vg=strat_group_split(rs,vf,seed); m,s,Xn=norm(X,tr)
    torch.manual_seed(seed); model=BinaryMLP(len(feats)); opt=torch.optim.Adam(model.parameters(),lr=lr)
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
    th,rec,pre,tp,tn,fp,fn=threshold(y[va].astype(int),p)
    out.parent.mkdir(parents=True,exist_ok=True)
    torch.save({"schema_version":2,"kind":"two_stage_B_feasibility","feature_names":feats,"mean":m,"std":s,"hidden":[64,64],"state_dict":best,"threshold":float(th)},out)
    print("\n===== TWO-STAGE MLP-B V2 ====="); print("rows/valid/invalid:",len(y),int(y.sum()),int(len(y)-y.sum())); print("validation groups:",vg)
    print("threshold:",f"{th:.3f}"); print("val recall/precision:",f"{rec:.4f}/{pre:.4f}"); print("TP/TN/FP/FN:",tp,tn,fp,fn); print("output:",out)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--a-dataset",type=Path,required=True); ap.add_argument("--b-dataset",type=Path,required=True)
    ap.add_argument("--a-output",type=Path,required=True); ap.add_argument("--b-output",type=Path,required=True)
    ap.add_argument("--epochs",type=int,default=600); ap.add_argument("--lr",type=float,default=1e-3); ap.add_argument("--val-fraction",type=float,default=.2); ap.add_argument("--seed",type=int,default=7)
    a=ap.parse_args(); trainA(a.a_dataset,a.a_output,a.epochs,a.lr,a.val_fraction,a.seed); trainB(a.b_dataset,a.b_output,a.epochs,a.lr,a.val_fraction,a.seed)
if __name__=="__main__": main()
