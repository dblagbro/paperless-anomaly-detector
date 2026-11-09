"""Run archived tests against exact image code, offline with synthetic state."""
import argparse,json,os,re,secrets,subprocess,tarfile,time,uuid
from pathlib import Path
import xml.etree.ElementTree as ET

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image',required=True)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args()
    repo=Path(__file__).resolve().parents[1]
    image=json.loads(subprocess.check_output(['docker','image','inspect',args.image],text=True))[0]
    revision=image['Config']['Labels']['org.opencontainers.image.revision']
    assert re.fullmatch('[0-9a-f]{40}',revision)
    out=args.output.resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    archive=out/'tests.tar'
    subprocess.run(['git','-C',str(repo),'archive','--format=tar','-o',str(archive),revision,'tests'],check=True)
    with tarfile.open(archive) as tf:
        for item in tf.getmembers():
            assert out in (out/item.name).resolve().parents and not item.issym() and not item.islnk()
        tf.extractall(out)
    name='anomaly-offline-'+uuid.uuid4().hex[:12]
    state={'phase':'running','started':time.time(),'image':image['Id'],'source_revision':revision,'container':name,'network':'none','production_data_or_credentials_mounted':False,'application_code_from_image':True}
    status=out/'status.json';status.write_text(json.dumps(state,indent=2)+'\n')
    code="import subprocess,sys; a=subprocess.run([sys.executable,'-m','pytest','/tests','-q','--tb=short','--junitxml=/results/results.xml','-p','no:cacheprovider']); b=subprocess.run([sys.executable,'-m','pip','check']); sys.exit(a.returncode or b.returncode)"
    command=['docker','run','--name',name,'--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','2','--memory','2g','--user',str(os.getuid())+':'+str(os.getgid()),'-v',str(out/'tests')+':/tests:ro','-v',str(out)+':/results','--tmpfs','/tmp:rw,size=256m','-e','DATABASE_URL=sqlite:////tmp/anomaly-tests.db','-e','PAPERLESS_API_TOKEN='+secrets.token_urlsafe(24),'-e','PAPERLESS_API_BASE_URL=http://paperless.invalid','-e','PYTHONPATH=/app','-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','python',image['Id'],'-c',code]
    try:
        with (out/'checks.log').open('w') as f:r=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=600)
        state.update(phase='passed' if r.returncode==0 else 'failed',exit_code=r.returncode)
        if (out/'results.xml').exists():state['suites']=[s.attrib for s in ET.parse(out/'results.xml').getroot() if s.tag=='testsuite']
    except BaseException as exc:
        subprocess.run(['docker','stop','--time','10',name],capture_output=True)
        state.update(phase='failed',error_class=type(exc).__name__)
        raise
    finally:
        state['finished']=time.time();status.write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state))
    return 0 if state['phase']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
