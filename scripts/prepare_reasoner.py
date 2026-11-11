"""Download openly licensed weights; never connects to inference/billing services."""
import os
os.environ['ORT_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'
from huggingface_hub import hf_hub_download
path=hf_hub_download('Qwen/Qwen2.5-1.5B-Instruct-GGUF','qwen2.5-1.5b-instruct-q4_k_m.gguf',local_dir='state/reasoner')
import hashlib
h=hashlib.sha256()
with open(path,'rb') as f:
    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
expected='6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e'
if h.hexdigest()!=expected:raise SystemExit('Unexpected model hash; do not load without reviewing the upstream change')
print('Verified model. Set ARES_REASONER_MODEL='+path)
