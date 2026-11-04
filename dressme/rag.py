"""BM25/E5 inference extracted from BO5 notebook cell 17 (passage:/query: convention)."""
import math
from collections import Counter
import numpy as np
from .schemas import tokens, digest
from .config import CACHE as CACHE_DIR, ALLOW_DOWNLOADS, hf_auth

class E5Encoder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        from huggingface_hub import snapshot_download
        revision = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
        # The revision already present locally is pinned for repeatability.
        try:
            path = snapshot_download('intfloat/multilingual-e5-small', revision=revision, local_files_only=True)
        except Exception:
            path = snapshot_download('intfloat/multilingual-e5-small', revision=revision,
                                     token=hf_auth(), cache_dir=str(CACHE_DIR / 'models'),
                                     local_files_only=not ALLOW_DOWNLOADS,
                                     allow_patterns=['*.json', '*.safetensors', '*.model', '1_Pooling/*'])
        self.model = SentenceTransformer(path, device='cpu', local_files_only=True)
        self.model.max_seq_length = 512
        self.tokenizer = self.model.tokenizer
        self.bo5_identity = f'intfloat/multilingual-e5-small@{revision}:512:passages-v2'

    def encode(self, *args, **kwargs):
        return self.model.encode(*args, **kwargs)

class BackendUnavailable(RuntimeError):
    pass

class ProductRAG:
    """BM25 + E5 gelé. Les contraintes sont appliquées par BO5, pas inférées ici."""
    def __init__(self, catalog, mode='hybrid', encoder=None):
        if mode not in {'hybrid','lexical'}:
            raise ValueError('Mode RAG : hybrid ou lexical.')
        self.catalog, self.mode = catalog, mode
        self.ids = list(catalog.ids)
        self.encoder = encoder
        self.query_cache = {}
        self.taxonomy_vectors = None
        self.vectors = None
        self.passage_vectors = None
        self.identity = 'bm25-words-v2'
        self.docs = [Counter(tokens(text)) for text in catalog.texts]
        self.length = np.asarray([sum(doc.values()) for doc in self.docs], dtype=float)
        self.average = max(float(self.length.mean()), 1.) if len(self.length) else 1.
        df = Counter(word for doc in self.docs for word in doc)
        self.idf = {word:math.log(1+(len(self.docs)-count+.5)/(count+.5)) for word,count in df.items()}
        self.taxonomy = [{'field':field,'value':value} for field,values in catalog.vocabulary.items() for value in values]
        self.passages, self.passage_positions = [], []
        if not self.ids:
            return
        if not any(self.docs):
            raise ValueError('Index lexical vide : vérifier la tokenisation et les documents.')
        if mode == 'hybrid':
            if encoder is None:
                from sentence_transformers import SentenceTransformer
                from huggingface_hub import HfApi
                model = 'intfloat/multilingual-e5-small'
                lock = CACHE_DIR/'bo5_e5_revision.json'
                record = load_json(lock,{})
                revision = record.get('revision') if record.get('model') == model else None
                revision = revision or HfApi().model_info(model).sha
                write_json_atomic(lock,{'model':model,'revision':revision})
                encoder = SentenceTransformer(model,revision=revision,device='cpu',cache_folder=str(CACHE_DIR/'models'))
                encoder.max_seq_length = 512
                self.identity = f'{model}@{revision}:512:passages-v2'
            else:
                # Un encodeur externe doit fournir une identité versionnée pour le cache.
                self.identity = getattr(encoder,'bo5_identity',None)
                if not self.identity:
                    raise ValueError('Encodeur externe : bo5_identity versionné requis.')
            self.encoder = encoder
            for position,text in enumerate(catalog.texts):
                parts = self._pieces(text, 360, 48)
                for part in parts:
                    self.passages.append('passage: '+part)
                    self.passage_positions.append(position)
            cache = CACHE_DIR/'bo5_product_passages_v2.npz'
            identity = digest({'encoder':self.identity,'ids':self.ids,'passages':self.passages})
            if cache.is_file():
                with np.load(cache,allow_pickle=False) as stored:
                    if stored['identity'].item() == identity:
                        self.passage_vectors = stored['vectors']
            if self.passage_vectors is None:
                self.passage_vectors = self._encode(self.passages)
                temporary = cache.with_suffix('.tmp.npz')
                np.savez_compressed(temporary,identity=np.asarray(identity),vectors=self.passage_vectors)
                temporary.replace(cache)
            self._check(self.passage_vectors,len(self.passages))
            # Vecteur produit pour l'affinité de préférence, distinct du max de passages pour la recherche.
            self.vectors = np.stack([self.passage_vectors[np.asarray(self.passage_positions)==i].mean(axis=0)
                                     for i in range(len(self.ids))])
            self.vectors /= np.maximum(np.linalg.norm(self.vectors,axis=1,keepdims=True),1e-12)

    def _pieces(self,text,size,overlap=0):
        tokenizer = getattr(self.encoder,'tokenizer',None)
        if tokenizer is not None:
            ids = tokenizer.encode(str(text),add_special_tokens=False)
            return [tokenizer.decode(ids[i:i+size],skip_special_tokens=True)
                    for i in range(0,max(1,len(ids)),size-overlap)]
        words = str(text).split()
        return [' '.join(words[i:i+size]) for i in range(0,max(1,len(words)),size-overlap)]

    @staticmethod
    def _check(vectors,count):
        if vectors.ndim != 2 or len(vectors) != count or not np.isfinite(vectors).all():
            raise ValueError('Vecteurs E5 invalides ou mal alignés.')
        if count and np.any(np.linalg.norm(vectors,axis=1)<1e-8):
            raise ValueError('Vecteur E5 nul.')

    def _encode(self,texts):
        vectors = np.asarray(self.encoder.encode(texts,normalize_embeddings=True,convert_to_numpy=True,
                             batch_size=24,show_progress_bar=False),dtype=np.float32)
        self._check(vectors,len(texts))
        return vectors

    def encode_query(self,query):
        if self.encoder is None:
            raise BackendUnavailable('Affinité sémantique indisponible en mode lexical.')
        if query not in self.query_cache:
            if len(self.query_cache) >= 128:
                self.query_cache.pop(next(iter(self.query_cache)))
            vectors = self._encode(['query: '+piece for piece in self._pieces(query,400)])
            vector = vectors.mean(axis=0)
            self.query_cache[query] = vector/max(float(np.linalg.norm(vector)),1e-12)
        return self.query_cache[query]

    def hints(self,query,k=16):
        if not self.taxonomy:
            return []
        if self.mode == 'hybrid':
            if self.taxonomy_vectors is None:
                self.taxonomy_vectors = self._encode(['passage: '+x['field']+': '+x['value'] for x in self.taxonomy])
            scores = self.taxonomy_vectors@self.encode_query(query)
        else:
            words = set(tokens(query))
            scores = np.asarray([len(words&set(tokens(x['value']))) for x in self.taxonomy])
        order = sorted(range(len(scores)),key=lambda i:(-float(scores[i]),self.taxonomy[i]['value']))[:k]
        return [{**self.taxonomy[i],'similarity':float(scores[i])} for i in order]

    def score(self,query):
        if not self.ids:
            return {}
        lexical = np.zeros(len(self.ids),dtype=float)
        for word in set(tokens(query)):
            counts = np.asarray([doc.get(word,0) for doc in self.docs],dtype=float)
            lexical += self.idf.get(word,0)*counts*2.5/(counts+1.5*(.25+.75*self.length/self.average))
        lex = lexical/max(float(lexical.max()),1e-12)
        dense = None
        if self.mode == 'hybrid':
            scores = self.passage_vectors@self.encode_query(query)
            dense = np.asarray([scores[np.asarray(self.passage_positions)==i].max() for i in range(len(self.ids))])
        relevance = .85*np.clip((dense+1)/2,0,1)+.15*lex if dense is not None else lex
        return {key:{'relevance':float(relevance[i]),'dense_cosine':float(dense[i]) if dense is not None else None,
                     'bm25':float(lexical[i]),'retrieval_mode':self.mode,'encoder_identity':self.identity}
                for i,key in enumerate(self.ids)}
