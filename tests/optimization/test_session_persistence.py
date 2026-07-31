from __future__ import annotations
import csv, json
from pathlib import Path
import pytest
from openams.optimization.evaluation import CandidateState,ObjectiveComponent,ObjectiveDirection,OptimizerFeedback
from openams.optimization.session import CandidateProposal,OptimizationIteration,OptimizationRoute,OptimizationSessionState,ProposalRecord,ProposalStatus
from openams.optimization.session_persistence import OptimizationSessionPersistence,SCHEMA_VERSION,SessionPersistenceError,feedback_rows,proposal_history_rows
def make_state():
    c=ObjectiveComponent(name='gain',measurement='gain_db',analysis='ac',direction=ObjectiveDirection.MAXIMIZE,status='available',raw_value=72.0,normalized_value=1.2,weighted_value=1.2,weight=1.0,unit='dB')
    f=OptimizerFeedback(candidate_id='candidate_0000',feasible=True,objective_value=1.2,state=CandidateState.VALID,components=(c,))
    a=CandidateProposal(candidate_id='candidate_0000',parameters={'vbias':0.7,'w1':3.0},route=OptimizationRoute.CONTRACT_SEARCH,iteration=0,proposal_index=0,source='deterministic')
    b=CandidateProposal(candidate_id='candidate_0001',parameters={'vbias':0.8,'w1':4.0},route=OptimizationRoute.CONTRACT_SEARCH,iteration=0,proposal_index=1,source='deterministic')
    it=OptimizationIteration(index=0,records=(ProposalRecord(a,ProposalStatus.EVALUATED,f),ProposalRecord(b,ProposalStatus.PROPOSED)))
    return OptimizationSessionState(session_id='session_001',route=OptimizationRoute.CONTRACT_SEARCH,iterations=(it,),metadata={'seed':7})
def test_persist_writes_artifacts(tmp_path):
    a=OptimizationSessionPersistence().persist(make_state(),tmp_path,evaluation_artifact_path=tmp_path/'candidate_evaluation.json')
    assert a.session_json.is_file() and a.proposal_history_csv.is_file() and a.feedback_csv.is_file()
def test_json_schema_and_relative_link(tmp_path):
    a=OptimizationSessionPersistence().persist(make_state(),tmp_path,evaluation_artifact_path=tmp_path/'candidate_evaluation.json')
    p=json.loads(a.session_json.read_text()); assert p['schema_version']==SCHEMA_VERSION; assert p['evaluation_artifact']=='candidate_evaluation.json'; assert p['session']['candidate_count']==2
def test_proposal_rows_deterministic():
    rows=proposal_history_rows(make_state()); assert [(r['candidate_id'],r['parameter_name']) for r in rows]==[('candidate_0000','vbias'),('candidate_0000','w1'),('candidate_0001','vbias'),('candidate_0001','w1')]
def test_feedback_rows_preserve_components():
    rows=feedback_rows(make_state()); assert len(rows)==1; assert rows[0]['objective_name']=='gain'; assert rows[0]['feasible']=='true'
def test_load_state_round_trip(tmp_path):
    p=OptimizationSessionPersistence(); a=p.persist(make_state(),tmp_path); restored=p.load_state(a.session_json); assert restored==make_state(); assert restored.next_iteration_index==1
def test_unknown_schema_rejected(tmp_path):
    f=tmp_path/'optimization_session.json'; f.write_text(json.dumps({'schema_version':'future.v99','session':{}}))
    with pytest.raises(SessionPersistenceError,match='unsupported'): OptimizationSessionPersistence().load_payload(f)
def test_missing_session_rejected(tmp_path):
    f=tmp_path/'optimization_session.json'; f.write_text(json.dumps({'schema_version':SCHEMA_VERSION}))
    with pytest.raises(SessionPersistenceError,match="missing 'session'"): OptimizationSessionPersistence().load_payload(f)
