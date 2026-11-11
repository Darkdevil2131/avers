import os
os.environ['ORT_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'
from fastembed import TextEmbedding
model=TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2',cache_dir=os.environ.get('ARES_MODEL_CACHE','state/models'),threads=2)
print({'model':'sentence-transformers/all-MiniLM-L6-v2','dimensions':len(next(model.embed(['Model verification']))),'telemetry':'disabled before runtime initialization'})
from fastembed.rerank.cross_encoder import TextCrossEncoder
reranker=TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2',cache_dir=os.environ.get('ARES_MODEL_CACHE','state/models'),threads=2)
print({'reranker':'Xenova/ms-marco-MiniLM-L-6-v2','scores':list(reranker.rerank('What powers a car?',['Gasoline powers an automobile.']))})
