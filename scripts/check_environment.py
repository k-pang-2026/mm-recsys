from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('HF_HOME',str(Path(__file__).resolve().parents[1]/'.cache/huggingface'))


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument('--skip-clip',action='store_true')
    parser.add_argument('--skip-docker-check',action='store_true');args=parser.parse_args()
    from src.common.config import load_config
    from src.common.artifacts import write_json
    cfg=load_config();versions={}
    for name in ['torch','torchvision','faiss','transformers','fastapi','streamlit','redis','yaml','pandas','pyarrow','sklearn','fakeredis','httpx']:
        module=importlib.import_module(name);versions[name]=getattr(module,'__version__','unknown')
    import faiss,numpy as np,torch
    vectors=np.eye(4,dtype=np.float32);index=faiss.IndexFlatIP(4);index.add(vectors)
    assert index.search(vectors[:1],1)[1][0,0]==0
    result={'python':platform.python_version(),'platform':platform.platform(),'versions':versions,
            'scale':cfg['scale'],'seed':cfg['seed'],'cuda_available':torch.cuda.is_available(),
            'clip_inference':'UNMEASURED','docker':'UNMEASURED'}
    if not args.skip_clip:
        from PIL import Image
        from transformers import CLIPModel,CLIPProcessor
        name=cfg['search']['clip_model'];revision=cfg['search']['clip_revision']
        model=CLIPModel.from_pretrained(name,revision=revision).eval()
        processor=CLIPProcessor.from_pretrained(name,revision=revision)
        with torch.inference_mode():
            text=model.get_text_features(**processor(text=['a black shirt'],return_tensors='pt',truncation=True))
            image=model.get_image_features(**processor(images=Image.new('RGB',(224,224),'black'),return_tensors='pt'))
        assert text.shape==image.shape==(1,model.config.projection_dim)
        assert torch.isfinite(text).all() and torch.isfinite(image).all()
        result.update(clip_inference='PASS',clip_model=name,clip_revision=model.config._commit_hash,clip_projection_dim=model.config.projection_dim)
    failure=False
    if not args.skip_docker_check:
        checks=[]
        for command in [['docker','compose','version'],['docker','info','--format','{{.ServerVersion}}'],['docker','compose','config','--quiet']]:
            try:
                completed=subprocess.run(command,text=True,capture_output=True,timeout=30)
                checks.append({'command':command,'exit_code':completed.returncode,'output':(completed.stdout+completed.stderr)[-1500:]})
                failure|=completed.returncode!=0
            except (OSError,subprocess.TimeoutExpired) as error:
                checks.append({'command':command,'exit_code':None,'output':str(error)});failure=True
        result['docker']='BLOCKED' if failure else 'PASS';result['docker_checks']=checks
    write_json(Path('.team/environment.json'),result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if failure else 0


if __name__=='__main__':raise SystemExit(main())
