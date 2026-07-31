"""Persistence and typed reconstruction for optimization sessions."""
from __future__ import annotations
from dataclasses import dataclass
import csv, json
from pathlib import Path
from typing import Any, Iterable, Mapping
from .evaluation import CandidateState, ObjectiveComponent, ObjectiveDirection, OptimizerFeedback
from .session import CandidateProposal, OptimizationIteration, OptimizationRoute, OptimizationSessionState, ProposalRecord, ProposalStatus
SCHEMA_VERSION = "openams.optimization_session.v1"
class SessionPersistenceError(RuntimeError): pass
@dataclass(frozen=True)
class PersistedSessionArtifacts:
    directory: Path
    session_json: Path
    proposal_history_csv: Path
    feedback_csv: Path
    def to_dict(self) -> dict[str, str]:
        return {"directory": str(self.directory), "session_json": str(self.session_json), "proposal_history_csv": str(self.proposal_history_csv), "feedback_csv": str(self.feedback_csv)}
def _relativize_path(value: Any, base_directory: Path) -> Any:
    if isinstance(value, Mapping): return {str(k): _relativize_path(v, base_directory) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_relativize_path(v, base_directory) for v in value]
    if isinstance(value, str):
        p = Path(value)
        if p.is_absolute():
            try: return str(p.relative_to(base_directory))
            except ValueError: return value
    return value
def canonical_session_payload(state: OptimizationSessionState, *, output_directory: Path, evaluation_artifact_path: str | Path | None = None) -> dict[str, Any]:
    payload = {"schema_version": SCHEMA_VERSION, "artifact_root": ".", "evaluation_artifact": None if evaluation_artifact_path is None else str(evaluation_artifact_path), "session": state.to_dict()}
    return _relativize_path(payload, output_directory.resolve())
def write_canonical_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
PROPOSAL_FIELDS = ("session_id","route","iteration","proposal_index","candidate_id","status","source","parameter_name","parameter_value","diagnostic")
def proposal_history_rows(state: OptimizationSessionState) -> tuple[dict[str, Any], ...]:
    rows=[]
    for iteration in state.iterations:
        for record in sorted(iteration.records, key=lambda x: x.proposal.proposal_index):
            p=record.proposal
            for name, value in sorted(p.parameters.items()):
                rows.append({"session_id":state.session_id,"route":state.route.value,"iteration":iteration.index,"proposal_index":p.proposal_index,"candidate_id":p.candidate_id,"status":record.status.value,"source":p.source or "","parameter_name":name,"parameter_value":repr(float(value)),"diagnostic":record.diagnostic or ""})
    return tuple(rows)
FEEDBACK_FIELDS=("session_id","iteration","candidate_id","state","feasible","objective_value","failure_reasons","unknown_reasons","objective_name","analysis","measurement","direction","component_status","raw_value","normalized_value","weighted_value","weight","unit","diagnostic")
def feedback_rows(state: OptimizationSessionState) -> tuple[dict[str, Any], ...]:
    rows=[]
    for iteration in state.iterations:
        for record in sorted(iteration.records, key=lambda x: x.proposal.proposal_index):
            f=record.feedback
            if f is None: continue
            base={"session_id":state.session_id,"iteration":iteration.index,"candidate_id":f.candidate_id,"state":f.state.value,"feasible":"" if f.feasible is None else str(f.feasible).lower(),"objective_value":"" if f.objective_value is None else repr(f.objective_value),"failure_reasons":"|".join(f.failure_reasons),"unknown_reasons":"|".join(f.unknown_reasons)}
            components=sorted(f.components,key=lambda x:x.name)
            if not components:
                rows.append({**base,**{k:"" for k in FEEDBACK_FIELDS if k not in base}}); continue
            for c in components:
                rows.append({**base,"objective_name":c.name,"analysis":c.analysis,"measurement":c.measurement,"direction":c.direction.value,"component_status":c.status,"raw_value":"" if c.raw_value is None else repr(c.raw_value),"normalized_value":"" if c.normalized_value is None else repr(c.normalized_value),"weighted_value":"" if c.weighted_value is None else repr(c.weighted_value),"weight":repr(c.weight),"unit":c.unit or "","diagnostic":c.diagnostic or ""})
    return tuple(rows)
def write_csv(path: Path, *, fieldnames: tuple[str,...], rows: Iterable[Mapping[str,Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as h:
        w=csv.DictWriter(h,fieldnames=fieldnames,extrasaction='ignore',lineterminator='\n'); w.writeheader()
        for row in rows: w.writerow({f:row.get(f,'') for f in fieldnames})
def _component(payload: Mapping[str,Any]) -> ObjectiveComponent:
    return ObjectiveComponent(name=str(payload['name']),measurement=str(payload['measurement']),analysis=str(payload['analysis']),direction=ObjectiveDirection(str(payload['direction'])),status=str(payload['status']),raw_value=payload.get('raw_value'),normalized_value=payload.get('normalized_value'),weighted_value=payload.get('weighted_value'),weight=float(payload['weight']),unit=payload.get('unit'),diagnostic=payload.get('diagnostic'),provenance=dict(payload.get('provenance',{})))
def _feedback(payload: Mapping[str,Any]) -> OptimizerFeedback:
    return OptimizerFeedback(candidate_id=str(payload['candidate_id']),feasible=payload.get('feasible'),objective_value=payload.get('objective_value'),state=CandidateState(str(payload['state'])),failure_reasons=tuple(payload.get('failure_reasons',())),unknown_reasons=tuple(payload.get('unknown_reasons',())),components=tuple(_component(x) for x in payload.get('components',())))
def reconstruct_session_state(payload: Mapping[str,Any]) -> OptimizationSessionState:
    s=payload.get('session')
    if not isinstance(s,Mapping): raise SessionPersistenceError("optimization-session JSON is missing 'session'")
    iterations=[]
    for it in s.get('iterations',()):
        records=[]
        for r in it.get('records',()):
            p=r['proposal']
            proposal=CandidateProposal(candidate_id=str(p['candidate_id']),parameters={str(k):float(v) for k,v in p['parameters'].items()},route=OptimizationRoute(str(p['route'])),iteration=int(p['iteration']),proposal_index=int(p['proposal_index']),source=p.get('source'),metadata=dict(p.get('metadata',{})))
            fp=r.get('feedback')
            records.append(ProposalRecord(proposal=proposal,status=ProposalStatus(str(r['status'])),feedback=None if fp is None else _feedback(fp),diagnostic=r.get('diagnostic')))
        iterations.append(OptimizationIteration(index=int(it['index']),records=tuple(records),metadata=dict(it.get('metadata',{}))))
    return OptimizationSessionState(session_id=str(s['session_id']),route=OptimizationRoute(str(s['route'])),iterations=tuple(iterations),metadata=dict(s.get('metadata',{})))
class OptimizationSessionPersistence:
    def persist(self,state:OptimizationSessionState,output_directory:str|Path,*,evaluation_artifact_path:str|Path|None=None)->PersistedSessionArtifacts:
        d=Path(output_directory); d.mkdir(parents=True,exist_ok=True)
        sj=d/'optimization_session.json'; pc=d/'proposal_history.csv'; fc=d/'feedback_history.csv'
        write_canonical_json(sj,canonical_session_payload(state,output_directory=d,evaluation_artifact_path=evaluation_artifact_path))
        write_csv(pc,fieldnames=PROPOSAL_FIELDS,rows=proposal_history_rows(state)); write_csv(fc,fieldnames=FEEDBACK_FIELDS,rows=feedback_rows(state))
        return PersistedSessionArtifacts(d,sj,pc,fc)
    def load_payload(self,session_json:str|Path)->dict[str,Any]:
        p=Path(session_json)
        try: payload=json.loads(p.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError) as exc: raise SessionPersistenceError(f"could not load optimization-session JSON {p}: {exc}") from exc
        if payload.get('schema_version')!=SCHEMA_VERSION: raise SessionPersistenceError(f"unsupported optimization-session schema version: {payload.get('schema_version')!r}")
        if 'session' not in payload: raise SessionPersistenceError("optimization-session JSON is missing 'session'")
        return payload
    def load_state(self,session_json:str|Path)->OptimizationSessionState:
        return reconstruct_session_state(self.load_payload(session_json))
