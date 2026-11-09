"""Synthetic regression coverage for dependencies and retained client behavior."""
import io
import logging
import time
from unittest.mock import Mock

import httpx
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from paperless_client import PaperlessClient


def conflict():
    req = httpx.Request('POST', 'https://paperless.invalid/api/tags/')
    response = httpx.Response(400, request=req, text='Object violates owner / name unique constraint')
    return httpx.HTTPStatusError('synthetic race', request=req, response=response)


def test_tag_exact_match_on_later_page():
    client = PaperlessClient()
    client._make_request = Mock(side_effect=[{'results': [{'name': 'audit-other', 'id': 1}], 'next': 'page2'}, {'results': [{'name': 'audit', 'id': 2}], 'next': None}])
    assert client.get_or_create_tag('audit') == 2
    assert all(c.args[0] == 'GET' for c in client._make_request.call_args_list)
    assert client._make_request.call_args_list[1].kwargs['params']['page'] == 2


@pytest.mark.parametrize('method,key', [('get_or_create_tag', 'name'), ('get_or_create_custom_field', 'name')])
def test_concurrent_creator_eventually_visible(monkeypatch, method, key):
    sleeps=[];monkeypatch.setattr(time, 'sleep', sleeps.append)
    client=PaperlessClient()
    client._make_request=Mock(side_effect=[{'results': [], 'next': None}, conflict(), {'results': []}, {'results': [{key: 'audit', 'id': 17}]}])
    assert getattr(client, method)('audit') == 17
    assert sleeps == [0.05, 0.15]


def test_race_retry_is_bounded(monkeypatch):
    sleeps=[];monkeypatch.setattr(time, 'sleep', sleeps.append)
    client=PaperlessClient()
    client._make_request=Mock(side_effect=[{'results': []}, conflict(), {'results': []}, {'results': []}, {'results': []}])
    assert client.get_or_create_tag('audit') is None
    assert sleeps == [0.05, 0.15, 0.4]


@pytest.mark.parametrize('mode', ['RGB', 'L'])
def test_image_pipeline_runs_all_checks_without_swallowing_errors(mode, caplog):
    from image_forensics import CV_AVAILABLE, ImageForensicsAnalyzer
    assert CV_AVAILABLE
    rng=np.random.default_rng(42)
    shape=(320,320,3) if mode=='RGB' else (320,320)
    data=rng.integers(0,256,size=shape,dtype=np.uint8)
    buf=io.BytesIO();Image.fromarray(data).save(buf, format='PNG')
    with caplog.at_level(logging.ERROR):result=ImageForensicsAnalyzer().analyze_image(buf.getvalue(), 'synthetic.png')
    assert result['analyzed'] and 'error' not in result
    assert len(result['techniques_used']) == 5
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_invalid_image_is_reported():
    from image_forensics import ImageForensicsAnalyzer
    result=ImageForensicsAnalyzer().analyze_image(b'not an image', 'synthetic.invalid')
    assert 'error' in result


def test_settings_reject_empty_token():
    from config import Settings
    with pytest.raises(ValueError):Settings(paperless_api_token=' ')


def test_sqlite_api_and_scheduler_lifespan(monkeypatch):
    import main
    from database import get_db
    from models import ProcessedDocument, AnomalyLog
    start=Mock();stop=Mock()
    monkeypatch.setattr(main.scheduler, 'start', start)
    monkeypatch.setattr(main.scheduler, 'stop', stop)
    with TestClient(main.app) as client:
        assert client.get('/health').status_code == 200
        with get_db() as db:
            db.add(ProcessedDocument(paperless_doc_id=91001,title='Synthetic test',has_anomalies=True,anomaly_types=['balance_mismatch']))
            db.add(AnomalyLog(paperless_doc_id=91001,anomaly_type='balance_mismatch',severity='high',description='Synthetic fixture'))
        stats=client.get('/api/stats');assert stats.status_code==200
        assert stats.json()['total_documents']==1 and stats.json()['total_anomalies']==1
        docs=client.get('/api/documents',params={'has_anomalies':True,'limit':1});assert docs.status_code==200
        assert docs.json()['results'][0]['paperless_doc_id']==91001
        assert client.get('/api/documents',params={'limit':1001}).status_code==422
        assert client.get('/api/anomalies').status_code==200
    start.assert_called_once();stop.assert_called_once()


def test_synthetic_document_pipeline():
    from detector import AnomalyDetector
    result=AnomalyDetector().detect_all_anomalies({'id':91002,'title':'Synthetic letter'}, 'This is a plain synthetic letter.\nNo financial transactions are present.')
    assert isinstance(result['has_anomalies'],bool)
    assert 'error' not in result


def test_balance_no_claims_is_not_a_false_mismatch():
    from balance_checker import SmartBalanceChecker
    result=SmartBalanceChecker().check_balance('A synthetic informational letter without transaction counts.')
    assert result['status']=='PASS' and result['issues']==[]
