"""Archive tests use synthetic data solely for integrity contract checks."""
import pandas as pd
import pytest

from quant_research.research.v4_artifacts import (
    write_research_run,read_research_run,list_research_runs)


def _report():
    return {'status':'RESEARCH_ONLY_NOT_ADMITTED_TO_PAPER',
            'model_variants':{'A':['f1'],'D':['f1','market']},
            'panel_contract':{'status':'STRICT_CONTRACT_ASSEMBLED_SOURCE_AUDIT_STILL_REQUIRED'},
            'predictions':pd.DataFrame([{'date':'2025-01-02','p_up':.61}]),
            'folds':pd.DataFrame([{'horizon':3,'train_sessions':500}]),
            'metrics':pd.DataFrame([{'variant':'A','horizon':3,'brier_up':.22}]),
            'increment_vs_alpha_only':pd.DataFrame(columns=['horizon','brier_gain'])}


def test_research_manifest_is_immutable_and_readable(tmp_path):
    record=write_research_run(tmp_path,'v4-case-001',_report(),
              input_snapshot_sha256='a'*64,experiment_config_sha256='b'*64)
    assert record['status']=='VERIFIED_LOCAL_RESEARCH_ARTIFACT_ONLY'
    assert not record['historical_decision_eligible']
    assert len(list_research_runs(tmp_path))==1
    read=read_research_run(tmp_path,'v4-case-001')
    assert read['metrics'].iloc[0].brier_up==pytest.approx(.22)
    with pytest.raises(FileExistsError):
        write_research_run(tmp_path,'v4-case-001',_report(),
                  input_snapshot_sha256='a'*64,experiment_config_sha256='b'*64)


def test_tampering_with_score_file_invalidates_report(tmp_path):
    write_research_run(tmp_path,'immutable',_report(),
                       input_snapshot_sha256='a'*64,experiment_config_sha256='b'*64)
    path=tmp_path/'outputs/v4_research/runs/immutable/metrics.parquet'
    with path.open('ab') as stream:stream.write(b'tampered')
    with pytest.raises(ValueError,match='Corrupt'):
        read_research_run(tmp_path,'immutable')
    entries=list_research_runs(tmp_path)
    assert entries[0]['status']=='CORRUPT_RESEARCH_RUN'


def test_archive_rejects_misleading_execution_status_and_paths(tmp_path):
    bad=_report()
    bad['status']='BACKTEST_READY'
    with pytest.raises(ValueError,match='non-executable'):
        write_research_run(tmp_path,'not-allowed',bad,
                           input_snapshot_sha256='a'*64,experiment_config_sha256='b'*64)
    with pytest.raises(ValueError,match='Unsafe'):
        read_research_run(tmp_path,'../../invalid')
