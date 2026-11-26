import json, os, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen
binary = Path(sys.argv[1]).resolve(strict=True)
with tempfile.TemporaryDirectory() as tmp:
    work=Path(tmp)
    env=dict(os.environ,XDG_CONFIG_HOME=str(work/'config'),XDG_CACHE_HOME=str(work/'cache'),OPS_INDEX_DIR=str(work/'indexes'),OPENAEC_BEHEERD='1')
    gui=subprocess.Popen([binary,'--api-port','0'],env=env)
    try:
        discovery=work/'config/open-pointcloud-studio-native/instances'/f'instance-{gui.pid}.json'
        deadline=time.monotonic()+35
        while not discovery.exists():
            assert gui.poll() is None and time.monotonic()<deadline
            time.sleep(.1)
        instance=json.loads(discovery.read_text())
        def api(command,**kwargs):
            req=Request(f"http://127.0.0.1:{instance['port']}/exec",json.dumps(dict(command=command,**kwargs)).encode(),{'Content-Type':'application/json','X-OPS-Token':instance['token']})
            with urlopen(req,timeout=20) as r: value=json.load(r)
            assert value['ok'],value
            return value
        api('mesh_to_plans_view',open=True,step='mesh')
        elapsed=[]
        for attempt in range(11):
            args={'folder':str(work/'project')} if attempt==0 else {}
            reply=api('mesh_to_plans_action',action='run',**args)
            jobid=reply['job_id']
            def job():return api('job',id=jobid)['job']
            deadline=time.monotonic()+10
            state=job()
            while state.get('completed',0)<2:
                assert state['state']=='running' and time.monotonic()<deadline,state
                time.sleep(.005)
                state=job()
            start=time.monotonic()
            if attempt<10: api('mesh_to_plans_action',action='cancel')
            while state['state']=='running':
                assert time.monotonic()<deadline,state
                time.sleep(.005)
                state=job()
            assert state['state']==('cancelled' if attempt<10 else 'complete'),state
            if attempt<10:elapsed.append(round(1000*(time.monotonic()-start),1))
        print('10 cancellations after at least two ticks, observed client latency (ms):',elapsed,flush=True)
        print('Next job:',state,flush=True)
    finally:
        gui.terminate()
        try: gui.wait(timeout=15)
        except subprocess.TimeoutExpired: gui.kill();gui.wait()
