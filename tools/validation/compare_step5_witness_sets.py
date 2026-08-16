#!/usr/bin/env python3
"""
Compare two generic Step-5 witness CSVs at the canonical witness level.
"""
from __future__ import annotations
import argparse,csv
from pathlib import Path

def rows(path):
    with path.open(newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reference",type=Path,required=True)
    ap.add_argument("--candidate",type=Path,required=True)
    ap.add_argument("--keys",nargs="+",required=True)
    a=ap.parse_args()

    rr=rows(a.reference)
    cc=rows(a.candidate)

    def sig(r):
        return tuple(round(float(r[k]),9) for k in a.keys)

    R={sig(r) for r in rr}
    C={sig(r) for r in cc}

    tp=len(R&C)
    fp=len(C-R)
    fn=len(R-C)

    print("===== STEP-5 REGRESSION =====")
    print("reference rows :",len(rr))
    print("candidate rows :",len(cc))
    print("unique ref     :",len(R))
    print("unique cand    :",len(C))
    print("TP / FP / FN  :",tp,fp,fn)
    print("exact match    :",R==C)

if __name__=="__main__":
    main()
