"""Synthetic checks of unchanged PR implementations; no provider transport."""
import copy
from concurrent.futures import ThreadPoolExecutor
import threading
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lib import spending
from tools.base_tool import BaseTool, ToolResult, ToolRuntime
from tools.cost_tracker import ApprovalRequiredError, BudgetExceededError
from tools.video.video_compose import VideoCompose

pytestmark = pytest.mark.spending_controls

class SyntheticMusic(BaseTool):
    name = 'review_synthetic_music'
    provider = 'fake'
    runtime = ToolRuntime.API
    idempotency_key_fields = ['prompt']

    def __init__(self):
        self.calls = 0

    def estimate_cost(self, inputs):
        return 0.25

    def execute(self, inputs):
        self.calls += 1
        path = Path(inputs['output_path'])
        path.write_bytes(b'synthetic fixture, not a real audio export')
        return ToolResult(success=True, artifacts=[str(path)], cost_usd=0.25)

def setup_ledger(tmp_path, monkeypatch, total=0):
    root = tmp_path / 'authority'
    root.mkdir()
    (root / 'config.yaml').write_text(
        f'budget:\n  mode: cap\n  total_usd: {total}\n  max_action_usd: {total}\n  reserve_pct: 0\n')
    monkeypatch.setattr(spending, 'ROOT', root)
    ledger = spending.Ledger()
    ledger.initialize(opening_spend_usd=0, evidence='Synthetic account only')
    return ledger

def render_request(tmp_path, family='documentary-montage'):
    bed = tmp_path / 'bed.wav'
    bed.write_bytes(b'local synthetic fixture')
    return {
        'operation':'remotion_render', 'output_path':str(tmp_path / 'render.mp4'),
        'edit_decisions':{'renderer_family':family,
            'cuts':[{'id':'one','type':'text_card','text':'check','in_seconds':0,'out_seconds':2}],
            'audio':{'music':{'asset_id':'bed','volume':0.25,'fade_in_seconds':0,'fade_out_seconds':0}}},
        'asset_manifest':{'assets':[{'id':'bed','path':str(bed)}]},
    }

@pytest.fixture
def capture(monkeypatch):
    captured = {}
    def stub(self, command, **kwargs):
        props = Path(next(a.split('=',1)[1] for a in command if a.startswith('--props=')))
        public = Path(next(a.split('=',1)[1] for a in command if a.startswith('--public-dir=')))
        captured['props'] = json.loads(props.read_text())
        captured['bytes'] = (public / captured['props']['music']['src']).read_bytes()
        Path(command[5]).write_bytes(b'CLI stub, not rendered video')
    monkeypatch.setattr(VideoCompose,'run_command',stub)
    return captured

@pytest.mark.parametrize('family',['documentary-montage','explainer-data'])
@pytest.mark.parametrize('state',['missing','zero','corrupt','unresolved','exhausted'])
def test_local_music_works_independent_of_ledger(tmp_path, monkeypatch, capture, family, state):
    ledger = setup_ledger(tmp_path, monkeypatch, total=1 if state in {'unresolved','exhausted'} else 0)
    if state == 'missing':
        ledger.path.unlink()
    elif state == 'corrupt':
        ledger.path.write_bytes(b'invalid database')
    elif state in {'unresolved','exhausted'}:
        fake = SyntheticMusic()
        request = {'prompt':'test', 'output_path':str(tmp_path/'fake.wav')}
        q = ledger.quote(fake,request,ceiling_usd=1)
        ledger.approve(q['id'],evidence='Synthetic approval only')
        ledger.reserve(fake,request,q['id'])
        if state == 'unresolved':
            with pytest.raises(spending.SpendingError): ledger.finish(q['id'])
        else:
            ledger.finish(q['id'],ToolResult(success=True,cost_usd=1))
    before = ledger.path.read_bytes() if ledger.path.exists() else None
    inputs = render_request(tmp_path,family)
    original = copy.deepcopy(inputs)
    assert VideoCompose().execute(inputs).success
    assert inputs == original
    assert capture['props']['music']['volume'] == 0.25
    assert capture['props']['music']['fadeInSeconds'] == 0
    assert capture['bytes'] == b'local synthetic fixture'
    assert (ledger.path.read_bytes() if ledger.path.exists() else None) == before
    assert spending._ACTIVE.get() is None and spending._TOKEN.get() is None

@pytest.mark.parametrize('token',[None,'fabricated-token'])
def test_render_does_not_authorize_subsequent_real_music_provider(tmp_path,monkeypatch,capture,token):
    from tools.audio.google_music import GoogleMusic
    ledger=setup_ledger(tmp_path,monkeypatch)
    inputs=render_request(tmp_path)
    if token: inputs['_spending_approval']=token
    assert VideoCompose().execute(inputs).success
    tool=GoogleMusic()
    monkeypatch.setattr(tool,'estimate_cost',lambda _:0.25)
    transport=MagicMock(side_effect=AssertionError('Provider SDK must not be constructed'))
    monkeypatch.setattr('google.genai.Client',transport)
    with pytest.raises(ApprovalRequiredError):
        tool.execute({'prompt':'Synthetic denial test; never submit'})
    transport.assert_not_called()
    q=ledger.quote(tool,{'prompt':'Synthetic denial test; never submit'})
    with pytest.raises(BudgetExceededError): ledger.approve(q['id'],evidence='Synthetic limit test')
    assert ledger.status()['accounted_usd']==0

def test_free_render_cannot_delegate_to_unapproved_paid_provider(tmp_path,monkeypatch):
    setup_ledger(tmp_path,monkeypatch)
    fake=SyntheticMusic()
    def nested(*args,**kwargs):
        fake.execute({'prompt':'nested', 'output_path':str(tmp_path/'never.wav')})
    monkeypatch.setattr(VideoCompose,'run_command',nested)
    result=VideoCompose().execute(render_request(tmp_path))
    assert not result.success and 'Paid call blocked' in result.error
    assert fake.calls==0
    assert spending._ACTIVE.get() is None and spending._TOKEN.get() is None

def test_synthetic_approved_asset_then_render_reserves_once(tmp_path,monkeypatch,capture):
    ledger=setup_ledger(tmp_path,monkeypatch,total=1)
    fake=SyntheticMusic()
    inputs=render_request(tmp_path)
    request={'prompt':'synthetic', 'output_path':inputs['asset_manifest']['assets'][0]['path']}
    q=ledger.quote(fake,request,ceiling_usd=0.5)
    ledger.approve(q['id'],evidence='Synthetic provider only')
    approved={**request,'_spending_approval':q['id']}
    assert fake.execute(approved).success
    assert VideoCompose().execute(inputs).success
    assert ledger.status()['accounted_usd']==0.5
    with pytest.raises(ApprovalRequiredError): fake.execute(approved)
    assert fake.calls==1

def test_verified_cache_hit_is_free_but_miss_requires_new_approval(tmp_path,monkeypatch):
    ledger=setup_ledger(tmp_path,monkeypatch,total=1)
    monkeypatch.setenv('OPENMONTAGE_ASSET_CACHE','1')
    monkeypatch.setenv('OPENMONTAGE_ASSET_CACHE_DIR',str(tmp_path/'cache'))
    fake=SyntheticMusic()
    request={'prompt':'synthetic', 'output_path':str(tmp_path/'first.wav')}
    q=ledger.quote(fake,request,ceiling_usd=0.5)
    ledger.approve(q['id'],evidence='Synthetic provider only')
    assert fake.execute({**request,'_spending_approval':q['id']}).success
    cached=fake.execute({**request,'output_path':str(tmp_path/'second.wav')})
    assert cached.from_cache and fake.calls==1
    assert (tmp_path/'first.wav').read_bytes()==(tmp_path/'second.wav').read_bytes()
    with pytest.raises(ApprovalRequiredError):
        fake.execute({**request,'prompt':'changed'})
    assert fake.calls==1 and ledger.status()['accounted_usd']==0.5


@pytest.mark.parametrize('family',['documentary-montage','explainer-data'])
def test_locked_remotion_without_dependencies_blocks_before_ffmpeg(tmp_path,monkeypatch,family):
    inputs=render_request(tmp_path,family)
    inputs['operation']='render'
    inputs['edit_decisions']['render_runtime']='remotion'
    monkeypatch.setattr(VideoCompose,'_remotion_available',lambda self:False)
    fallback=MagicMock(side_effect=AssertionError('Unapproved fallback must not run'))
    monkeypatch.setattr(VideoCompose,'_compose',fallback)
    result=VideoCompose().execute(inputs)
    assert not result.success and 'unavailable' in result.error
    fallback.assert_not_called()
    assert not Path(inputs['output_path']).exists()


def test_parallel_renders_keep_music_props_separate(tmp_path,monkeypatch):
    b_written=threading.Event();a_read=threading.Event();a_finished=threading.Event()
    observed={}
    def capture(self,command,**kwargs):
        label=Path(command[5]).stem
        props=Path(next(a.split('=',1)[1] for a in command if a.startswith('--props=')))
        public=Path(next(a.split('=',1)[1] for a in command if a.startswith('--public-dir=')))
        if label=='a':
            observed['a_started']=True
            start_b.set()
            assert b_written.wait(10)
        else:
            b_written.set()
            assert a_read.wait(10)
        data=json.loads(props.read_text())
        observed[label]={'props_path':str(props),'volume':data['music']['volume'],
                         'music_exists_in_own_public_dir':(public/data['music']['src']).exists()}
        if label=='a':a_read.set()
        else:assert a_finished.wait(10)
        Path(command[5]).write_bytes(b'CLI stub, not audiovisual evidence')
    monkeypatch.setattr(VideoCompose,'run_command',capture)
    start_b=threading.Event()
    def invoke(label,volume):
        bed=tmp_path/f'{label}.wav';bed.write_bytes(label.encode())
        try:
            return VideoCompose().execute({'operation':'remotion_render','output_path':str(tmp_path/f'{label}.mp4'),
                'edit_decisions':{'renderer_family':'documentary-montage',
                    'cuts':[{'type':'text_card','text':label,'in_seconds':0,'out_seconds':2}],
                    'audio':{'music':{'src':str(bed),'volume':volume}}}})
        finally:
            if label=='a':a_finished.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(invoke,'a',0.2)
        assert start_b.wait(10)
        second=pool.submit(invoke,'b',0.7)
        a,b=first.result(timeout=15),second.result(timeout=15)
    assert a.success and b.success
    assert observed['a']['props_path']!=observed['b']['props_path']
    assert observed['a']['volume']==0.2
    assert observed['b']['volume']==0.7
    assert observed['a']['music_exists_in_own_public_dir']
    assert observed['b']['music_exists_in_own_public_dir']
    assert not list(tmp_path.glob("*.remotion_props.json"))
    assert not list(tmp_path.glob(".remotion-public-*"))
