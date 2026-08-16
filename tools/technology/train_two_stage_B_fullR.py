#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import torch
from torch import nn


class BMLP(nn.Module):
    def __init__(self, nin=4, hidden=(64,64)):
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


def read_rows(path):
    with open(path,newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group_split(rows, val_fraction, seed):
    groups=sorted({r["group_id"] for r in rows})
    rng=np.random.default_rng(seed)
    rng.shuffle(groups)
    nval=max(1,int(round(len(groups)*val_fraction)))
    val_groups=set(groups[:nval])
    tr=np.array([i for i,r in enumerate(rows) if r["group_id"] not in val_groups])
    va=np.array([i for i,r in enumerate(rows) if r["group_id"] in val_groups])
    return tr,va,sorted(val_groups)


def choose_threshold(y,p,target_recall=0.98):
    candidates=[]
    for th in np.linspace(0.01,0.99,197):
        pred=(p>=th).astype(int)
        tp=int(((y==1)&(pred==1)).sum())
        tn=int(((y==0)&(pred==0)).sum())
        fp=int(((y==0)&(pred==1)).sum())
        fn=int(((y==1)&(pred==0)).sum())
        recall=tp/max(tp+fn,1)
        precision=tp/max(tp+fp,1)
        candidates.append((th,recall,precision,tp,tn,fp,fn))
    good=[x for x in candidates if x[1]>=target_recall]
    if good:
        return max(good,key=lambda x:(x[0],x[2]))
    return max(candidates,key=lambda x:(x[1],x[2],x[0]))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--epochs",type=int,default=700)
    ap.add_argument("--lr",type=float,default=1e-3)
    ap.add_argument("--val-fraction",type=float,default=0.25)
    ap.add_argument("--seed",type=int,default=7)
    args=ap.parse_args()

    rows=read_rows(args.dataset)
    feats=["vout_v","vy_v","vbias_v","stage_ratio"]

    X=np.asarray([[float(r[c]) for c in feats] for r in rows],dtype=np.float32)
    y=np.asarray([int(r["valid"]) for r in rows],dtype=np.float32)

    tr,va,val_groups=group_split(rows,args.val_fraction,args.seed)

    mean=X[tr].mean(axis=0).astype(np.float32)
    std=X[tr].std(axis=0).astype(np.float32)
    std[std<1e-12]=1.0
    Xn=(X-mean)/std

    torch.manual_seed(args.seed)
    model=BMLP(len(feats),(64,64))

    pos=float((y[tr]==1).sum())
    neg=float((y[tr]==0).sum())
    loss_fn=nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([neg/max(pos,1.0)],dtype=torch.float32)
    )
    opt=torch.optim.Adam(model.parameters(),lr=args.lr)

    xt=torch.tensor(Xn[tr],dtype=torch.float32)
    yt=torch.tensor(y[tr],dtype=torch.float32)

    best_state=None
    best_val=float("inf")

    for ep in range(args.epochs):
        model.train()
        opt.zero_grad()
        loss=loss_fn(model(xt),yt)
        loss.backward()
        opt.step()

        if ep % 10 == 0 or ep == args.epochs-1:
            model.eval()
            with torch.no_grad():
                lv=model(torch.tensor(Xn[va],dtype=torch.float32))
                vloss=nn.functional.binary_cross_entropy_with_logits(
                    lv,torch.tensor(y[va],dtype=torch.float32)
                ).item()
            if vloss < best_val:
                best_val=vloss
                best_state={k:v.detach().cpu().clone()
                            for k,v in model.state_dict().items()}

    model.load_state_dict(best_state)
    model.eval()

    with torch.no_grad():
        p=torch.sigmoid(
            model(torch.tensor(Xn[va],dtype=torch.float32))
        ).numpy()

    th,rec,prec,tp,tn,fp,fn=choose_threshold(y[va].astype(int),p)

    args.output.parent.mkdir(parents=True,exist_ok=True)
    torch.save({
        "schema_version":4,
        "kind":"two_stage_B_feasibility_full_R",
        "feature_names":feats,
        "mean":mean,
        "std":std,
        "hidden":[64,64],
        "state_dict":best_state,
        "threshold":float(th),
        "training_R_min":float(X[:,3].min()),
        "training_R_max":float(X[:,3].max()),
    },args.output)

    print("===== TWO-STAGE MLP-B FULL-R =====")
    print("rows / valid / invalid :",len(y),int(y.sum()),int(len(y)-y.sum()))
    print("validation groups      :",val_groups)
    print("threshold              :",f"{th:.3f}")
    print("val recall             :",f"{rec:.4f}")
    print("val precision          :",f"{prec:.4f}")
    print("val TP/TN/FP/FN        :",tp,tn,fp,fn)
    print("R training range       :",f"{X[:,3].min():.6g} to {X[:,3].max():.6g}")
    print("output                  :",args.output)


if __name__=="__main__":
    raise SystemExit(main())
