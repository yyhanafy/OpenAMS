#!/usr/bin/env python3
"""
Train the two-stage component MLPs.

MLP-A:
  inputs: W1, I5, VY, VBIAS
  heads:
    - feasibility logit
    - log(Rmin)
    - log(Rmax)

MLP-B:
  inputs: I5, VOUT, VY, VBIAS, R
  output:
    - feasibility logit

Validation split is GROUPED by independent design point so validation
does not leak neighboring interface cells from the same (W1,I5) case.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import torch
from torch import nn


class AMultiHead(nn.Module):
    def __init__(self, nin=4, hidden=(64,64)):
        super().__init__()
        layers = []
        d = nin
        for h in hidden:
            layers += [nn.Linear(d,h), nn.ReLU()]
            d = h
        self.backbone = nn.Sequential(*layers)
        self.valid_head = nn.Linear(d,1)
        self.range_head = nn.Linear(d,2)

    def forward(self, x):
        z = self.backbone(x)
        return self.valid_head(z).squeeze(-1), self.range_head(z)


class BinaryMLP(nn.Module):
    def __init__(self, nin=5, hidden=(64,64)):
        super().__init__()
        layers=[]
        d=nin
        for h in hidden:
            layers += [nn.Linear(d,h), nn.ReLU()]
            d=h
        layers.append(nn.Linear(d,1))
        self.net=nn.Sequential(*layers)

    def forward(self,x):
        return self.net(x).squeeze(-1)


def rows(path):
    with open(path,newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))


def grouped_split(rs, val_fraction, seed):
    groups = sorted({r["group_id"] for r in rs})
    rng = np.random.default_rng(seed)
    rng.shuffle(groups)
    nval = max(1, int(round(len(groups)*val_fraction)))
    val_groups = set(groups[:nval])
    tr = np.array([i for i,r in enumerate(rs) if r["group_id"] not in val_groups])
    va = np.array([i for i,r in enumerate(rs) if r["group_id"] in val_groups])
    return tr, va, sorted(val_groups)


def choose_threshold(y, p, target_recall=0.98):
    best = None
    for th in np.linspace(0.02,0.98,193):
        pred=(p>=th).astype(int)
        tp=int(np.sum((y==1)&(pred==1)))
        tn=int(np.sum((y==0)&(pred==0)))
        fp=int(np.sum((y==0)&(pred==1)))
        fn=int(np.sum((y==1)&(pred==0)))
        recall=tp/max(tp+fn,1)
        precision=tp/max(tp+fp,1)
        item=(th,recall,precision,tp,tn,fp,fn)
        if recall >= target_recall:
            if best is None or (th,precision) > (best[0],best[2]):
                best=item
    if best is None:
        scored=[]
        for th in np.linspace(0.02,0.98,193):
            pred=(p>=th).astype(int)
            tp=int(np.sum((y==1)&(pred==1)))
            tn=int(np.sum((y==0)&(pred==0)))
            fp=int(np.sum((y==0)&(pred==1)))
            fn=int(np.sum((y==1)&(pred==0)))
            recall=tp/max(tp+fn,1)
            precision=tp/max(tp+fp,1)
            scored.append((th,recall,precision,tp,tn,fp,fn))
        best=max(scored,key=lambda x:(x[1],x[2],x[0]))
    return best


def normalize(X,tr):
    mean=X[tr].mean(axis=0).astype(np.float32)
    std=X[tr].std(axis=0).astype(np.float32)
    std[std<1e-12]=1.0
    return mean,std,(X-mean)/std


def train_A(path,out,epochs,lr,val_fraction,seed):
    rs=rows(path)
    feats=["w_m1_um","i_m5_a","vy_v","vbias_v"]
    X=np.asarray([[float(r[c]) for c in feats] for r in rs],dtype=np.float32)
    y=np.asarray([int(r["valid"]) for r in rs],dtype=np.float32)
    tr,va,val_groups=grouped_split(rs,val_fraction,seed)
    mean,std,Xn=normalize(X,tr)

    valid_idx=np.where(y>0.5)[0]
    rmin=np.full(len(rs),np.nan,dtype=np.float32)
    rmax=np.full(len(rs),np.nan,dtype=np.float32)
    for i in valid_idx:
        rmin[i]=np.log(float(rs[i]["r_min"]))
        rmax[i]=np.log(float(rs[i]["r_max"]))

    model=AMultiHead(len(feats),(64,64))
    torch.manual_seed(seed)
    pos=float(np.sum(y[tr]==1)); neg=float(np.sum(y[tr]==0))
    cls_loss=nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([neg/max(pos,1.0)],dtype=torch.float32)
    )
    opt=torch.optim.Adam(model.parameters(),lr=lr)

    xt=torch.tensor(Xn[tr],dtype=torch.float32)
    yt=torch.tensor(y[tr],dtype=torch.float32)
    train_global=tr
    pos_mask=torch.tensor(y[tr]>0.5)

    best=None; best_loss=float("inf")
    for ep in range(epochs):
        model.train(); opt.zero_grad()
        logit,rr=model(xt)
        loss=cls_loss(logit,yt)
        if bool(pos_mask.any()):
            idx=train_global[y[tr]>0.5]
            target=torch.tensor(
                np.column_stack([rmin[idx],rmax[idx]]),dtype=torch.float32
            )
            range_loss=nn.functional.smooth_l1_loss(rr[pos_mask],target)
            loss=loss+0.5*range_loss
        loss.backward(); opt.step()

        if ep%10==0 or ep==epochs-1:
            model.eval()
            with torch.no_grad():
                lv,rv=model(torch.tensor(Xn[va],dtype=torch.float32))
                vloss=nn.functional.binary_cross_entropy_with_logits(
                    lv,torch.tensor(y[va],dtype=torch.float32)
                ).item()
            if vloss<best_loss:
                best_loss=vloss
                best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}

    model.load_state_dict(best); model.eval()
    with torch.no_grad():
        lv,rv=model(torch.tensor(Xn[va],dtype=torch.float32))
        p=torch.sigmoid(lv).numpy()
        rr=rv.numpy()

    th,rec,prec,tp,tn,fp,fn=choose_threshold(y[va].astype(int),p)

    val_pos=np.where(y[va]>0.5)[0]
    if len(val_pos):
        gi=va[val_pos]
        true_lo=np.exp(rmin[gi]); true_hi=np.exp(rmax[gi])
        pred_lo=np.exp(rr[val_pos,0]); pred_hi=np.exp(rr[val_pos,1])
        lo_mape=float(np.mean(np.abs(pred_lo-true_lo)/true_lo))
        hi_mape=float(np.mean(np.abs(pred_hi-true_hi)/true_hi))
    else:
        lo_mape=hi_mape=float("nan")

    out.parent.mkdir(parents=True,exist_ok=True)
    torch.save({
        "schema_version":1,
        "kind":"two_stage_component_A_feasibility_ratio_envelope",
        "feature_names":feats,
        "mean":mean,"std":std,
        "hidden":[64,64],
        "state_dict":best,
        "threshold":float(th),
        "ratio_outputs":["log_r_min","log_r_max"],
    },out)

    print("===== TWO-STAGE MLP-A =====")
    print("rows / valid / invalid :",len(y),int(y.sum()),int(len(y)-y.sum()))
    print("validation groups      :",val_groups)
    print("threshold              :",f"{th:.3f}")
    print("val recall / precision :",f"{rec:.4f} / {prec:.4f}")
    print("val TP/TN/FP/FN        :",tp,tn,fp,fn)
    print("Rmin/Rmax val MAPE     :",f"{lo_mape:.4f} / {hi_mape:.4f}")
    print("output                 :",out)


def train_B(path,out,epochs,lr,val_fraction,seed):
    rs=rows(path)
    feats=["i_m5_a","vout_v","vy_v","vbias_v","stage_ratio"]
    X=np.asarray([[float(r[c]) for c in feats] for r in rs],dtype=np.float32)
    y=np.asarray([int(r["valid"]) for r in rs],dtype=np.float32)
    tr,va,val_groups=grouped_split(rs,val_fraction,seed)
    mean,std,Xn=normalize(X,tr)

    model=BinaryMLP(len(feats),(64,64))
    torch.manual_seed(seed)
    pos=float(np.sum(y[tr]==1)); neg=float(np.sum(y[tr]==0))
    loss_fn=nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([neg/max(pos,1.0)],dtype=torch.float32)
    )
    opt=torch.optim.Adam(model.parameters(),lr=lr)
    xt=torch.tensor(Xn[tr],dtype=torch.float32)
    yt=torch.tensor(y[tr],dtype=torch.float32)

    best=None; best_loss=float("inf")
    for ep in range(epochs):
        model.train(); opt.zero_grad()
        loss=loss_fn(model(xt),yt); loss.backward(); opt.step()
        if ep%10==0 or ep==epochs-1:
            model.eval()
            with torch.no_grad():
                vloss=nn.functional.binary_cross_entropy_with_logits(
                    model(torch.tensor(Xn[va],dtype=torch.float32)),
                    torch.tensor(y[va],dtype=torch.float32)
                ).item()
            if vloss<best_loss:
                best_loss=vloss
                best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}

    model.load_state_dict(best); model.eval()
    with torch.no_grad():
        p=torch.sigmoid(model(torch.tensor(Xn[va],dtype=torch.float32))).numpy()
    th,rec,prec,tp,tn,fp,fn=choose_threshold(y[va].astype(int),p)

    out.parent.mkdir(parents=True,exist_ok=True)
    torch.save({
        "schema_version":1,
        "kind":"two_stage_component_B_feasibility",
        "feature_names":feats,
        "mean":mean,"std":std,
        "hidden":[64,64],
        "state_dict":best,
        "threshold":float(th),
    },out)

    print("\n===== TWO-STAGE MLP-B =====")
    print("rows / valid / invalid :",len(y),int(y.sum()),int(len(y)-y.sum()))
    print("validation groups      :",val_groups)
    print("threshold              :",f"{th:.3f}")
    print("val recall / precision :",f"{rec:.4f} / {prec:.4f}")
    print("val TP/TN/FP/FN        :",tp,tn,fp,fn)
    print("output                 :",out)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--a-dataset",type=Path,required=True)
    ap.add_argument("--b-dataset",type=Path,required=True)
    ap.add_argument("--a-output",type=Path,required=True)
    ap.add_argument("--b-output",type=Path,required=True)
    ap.add_argument("--epochs",type=int,default=600)
    ap.add_argument("--lr",type=float,default=1e-3)
    ap.add_argument("--val-fraction",type=float,default=0.2)
    ap.add_argument("--seed",type=int,default=7)
    args=ap.parse_args()

    train_A(args.a_dataset,args.a_output,args.epochs,args.lr,args.val_fraction,args.seed)
    train_B(args.b_dataset,args.b_output,args.epochs,args.lr,args.val_fraction,args.seed)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
