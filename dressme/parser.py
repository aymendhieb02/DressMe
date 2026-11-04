"""Pinned Qwen + the user's exact adapter, loaded once; no alternate parser."""
import hashlib
import json
import os
import re
import threading

from .config import ADAPTER, ALLOW_DOWNLOADS, CACHE, hf_auth, safe_error
from .grounding import normalize_contract, reconcile_turn
from .schemas import ROLES, Turn, norm


class ParserUnavailable(RuntimeError):
    pass


class PlanRejected(ValueError):
    def __init__(self, message, turn):
        super().__init__(message)
        self.plan = turn.model_dump()


# Generic bilingual garment vocabulary used only to reject lost information.
# It never supplies a replacement plan or a recommendation.
GARMENT_TERMS = set('jacket coat blazer shirt tshirt dress pant trouser jean skirt shoe sneaker boot sandal bag sweater hoodie short scarf veste manteau chemise robe pantalon jupe chaussure basket botte sandale sac pull sweat echarpe haut bas'.split())

# Translation evidence for rejecting invented color values, never for making a plan.
COLOR_EVIDENCE = {
    'black': r'black|noir(?:e)?s?', 'white': r'white|blanc(?:he)?s?',
    'blue': r'blue|bleu(?:e)?s?', 'red': r'red|rouges?',
    'green': r'green|vert(?:e)?s?', 'pink': r'pink|roses?',
    'grey': r'grey|gray|gris(?:e)?s?', 'gray': r'grey|gray|gris(?:e)?s?',
    'beige': r'beiges?', 'brown': r'brown|brun(?:e)?s?|marrons?',
    'navy': r'navy|marine', 'yellow': r'yellow|jaunes?',
    'orange': r'oranges?', 'purple': r'purple|violet(?:te)?s?|mauves?',
    'gold': r'gold(?:en)?|or|dore(?:e)?s?', 'silver': r'silver|argent(?:e)?s?',
    'cream': r'cream|cremes?', 'burgundy': r'burgundy|bordeaux',
    'multicolor': r'multicolor(?:ed|s|e|es)?|multicolour(?:ed|s)?',
}
FOLLOWUP_EVIDENCE = re.compile(
    r'\b(et|aussi|encore|plutot|davantage|meme|memes|precedent\w*|cette|ces|cela|celle\w*|'
    r'ceux|maintenant|ajoute\w*|retire\w*|enleve\w*|garde\w*|conserve\w*|'
    r'and|also|again|instead|same|previous|this|these|those|that|now|add|remove|keep|what if)\b')


class LocalParser:
    def __init__(self):
        self.lock = threading.RLock()
        self.request_trace = threading.local()
        self.model = self.tokenizer = None
        self.error = None
        self.metadata = {}
        self.attempted = False
        try:
            receipt = json.loads((ADAPTER / 'training_receipt.json').read_text(encoding='utf-8'))
            config = json.loads((ADAPTER / 'adapter_config.json').read_text(encoding='utf-8'))
            actual = hashlib.sha256((ADAPTER / 'adapter_model.safetensors').read_bytes()).hexdigest()
            if receipt['base_model'] != 'Qwen/Qwen3-1.7B' or config['base_model_name_or_path'] != receipt['base_model']:
                raise ValueError('Adapter/base architecture mismatch')
            if actual != receipt['adapter_file_sha256'] or not receipt.get('base_revision'):
                raise ValueError('Adapter hash mismatch or missing base revision')
            self.receipt = receipt
            self.metadata = dict(model=receipt['base_model'], revision=receipt['base_revision'],
                                 adapter_sha256=actual, run_identity=receipt['run_identity'],
                                 selected_checkpoint='checkpoint-400', adapter_path=str(ADAPTER),
                                 precision=os.getenv('DRESSME_PARSER_PRECISION', 'nf4'),
                                 reviewer=None, writer='deterministic evidence templates', fallback=None,
                                 postprocessing='grounded-request-v2 (typed replacements, explicit words, audited edits)',
                                 prompt_sha256=hashlib.sha256(receipt['training_config']['prompt'].encode()).hexdigest(),
                                 semantic_validation='Exact citations and conservative guards; no independent LLM oracle.')
        except Exception as exc:
            self.error = safe_error(exc)

    def health(self):
        return dict(loaded=self.model is not None, configured=bool(self.metadata),
                    attempted=self.attempted, error=self.error, **self.metadata)

    def load(self):
        with self.lock:
            if self.model is not None:
                return
            if self.error:
                raise ParserUnavailable(self.error)
            self.attempted = True
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
                from peft import PeftModel
                base = self.receipt['base_model']
                revision = self.receipt['base_revision']
                source = CACHE / 'models' / ('models--' + base.replace('/', '--')) / 'snapshots' / revision
                index_path = source / 'model.safetensors.index.json'
                required = ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'model.safetensors.index.json']
                if index_path.is_file():
                    required += sorted(set(json.loads(index_path.read_text(encoding='utf-8'))['weight_map'].values()))
                if not all((source / name).is_file() for name in required):
                    if not ALLOW_DOWNLOADS:
                        raise FileNotFoundError('Pinned local base files missing: ' + ', '.join(name for name in required if not (source/name).is_file()))
                    from huggingface_hub import snapshot_download
                    source = type(source)(snapshot_download(base, revision=revision, token=hf_auth(),
                                          cache_dir=str(CACHE / 'models'),
                                          allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt', '*.jinja']))
                # A physical path avoids Transformers querying remote chat-template
                # metadata even when local_files_only is supplied with a repo ID.
                common = dict(local_files_only=True)
                local_tokenizer = AutoTokenizer.from_pretrained(str(ADAPTER), local_files_only=True)
                base_tokenizer = AutoTokenizer.from_pretrained(str(source), **common)
                if local_tokenizer.get_vocab() != base_tokenizer.get_vocab():
                    raise ValueError('Adapter tokenizer vocabulary differs from the pinned base tokenizer')
                if local_tokenizer.eos_token_id != base_tokenizer.eos_token_id:
                    raise ValueError('Tokenizer EOS mismatch')
                device = os.getenv('DRESSME_PARSER_DEVICE', 'cuda:0' if torch.cuda.is_available() else 'cpu')
                precision = self.metadata['precision']
                args = dict(**common, attn_implementation='sdpa', use_safetensors=True,
                            device_map={'': device}, dtype=torch.float16 if device.startswith('cuda') else torch.float32)
                if precision == 'nf4':
                    if not device.startswith('cuda') or not torch.cuda.is_available():
                        raise RuntimeError('NF4 requires CUDA. Explicitly configure fp32 on CPU if desired; no automatic fallback.')
                    free, total = torch.cuda.mem_get_info()
                    self.metadata['gpu_free_mib_at_load'] = free // 2**20
                    if free < 2400 * 2**20:
                        raise RuntimeError('Less than 2400 MiB of GPU memory available for NF4 inference')
                    args['quantization_config'] = BitsAndBytesConfig(
                        load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True,
                        bnb_4bit_compute_dtype=torch.float16)
                elif precision not in {'fp16', 'fp32'}:
                    raise ValueError('DRESSME_PARSER_PRECISION must be nf4, fp16 or fp32')
                else:
                    args['dtype'] = torch.float16 if precision == 'fp16' else torch.float32
                model = AutoModelForCausalLM.from_pretrained(str(source), **args)
                model = PeftModel.from_pretrained(model, str(ADAPTER), is_trainable=False)
                model.eval()
                model.config.use_cache = True
                if local_tokenizer.pad_token_id is None:
                    local_tokenizer.pad_token = local_tokenizer.eos_token
                self.model, self.tokenizer = model, local_tokenizer
                self.metadata.update(device=device, tokenizer_verified=True)
            except Exception as exc:
                self.error = safe_error(exc)
                raise ParserUnavailable(self.error) from exc

    def parse(self, message, previous_roles=(), pending_facets=(), pending_question=''):
        with self.lock:
            self.request_trace.value = {}
            self.load()
            import torch
            selections = list(previous_roles)
            if selections and all(isinstance(role, str) for role in selections):
                selections = [dict(number=1, roles=selections)]
            numbers = set()
            for selection in selections:
                if not isinstance(selection, dict) or set(selection) != {'number', 'roles'}:
                    raise ValueError('Previous selections require numbered role lists')
                if type(selection['number']) is not int or not 1 <= selection['number'] <= 5 or selection['number'] in numbers:
                    raise ValueError('Previous selection numbers must be distinct integers in 1..5')
                if not isinstance(selection['roles'], list) or any(role not in ROLES for role in selection['roles']):
                    raise ValueError('Unknown previous selection roles')
                numbers.add(selection['number'])
            payload = dict(message=message, previous_selection_roles=selections,
                           pending_clarification=pending_question, pending_facets=list(pending_facets),
                           observed_genders=['men', 'women'],
                           observed_colors=['black', 'blue', 'beige', 'red', 'white', 'green', 'pink', 'grey'])
            messages = [dict(role='system', content=self.receipt['training_config']['prompt']),
                        dict(role='user', content=json.dumps(payload, ensure_ascii=False))]
            prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            inputs = self.tokenizer(prompt, add_special_tokens=False, return_tensors='pt').to(self.model.get_input_embeddings().weight.device)
            if inputs['input_ids'].shape[1] + 1200 > 4096:
                raise ValueError('Message too long; no silent truncation')
            with torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=1200, do_sample=False,
                                             temperature=None, top_p=None, top_k=None,
                                             pad_token_id=self.tokenizer.pad_token_id)
            raw = self.tokenizer.decode(output[0, inputs['input_ids'].shape[1]:], skip_special_tokens=True)
            self.request_trace.value = dict(previous_selection_roles=selections, raw_output=raw)
            model_json = json.loads(raw)
            contract, contract_changes = normalize_contract(model_json, message)
            original = Turn.model_validate(contract, strict=True)
            turn, changes = reconcile_turn(original, message, COLOR_EVIDENCE, pending_question)
            self.request_trace.value.update(model_plan=model_json, normalized_contract_plan=original.model_dump(),
                                            corrections=contract_changes + changes,
                                            reconciled_plan=turn.model_dump())
            try:
                validate_turn(turn, message, pending_question=pending_question)
            except ValueError as exc:
                raise PlanRejected(str(exc), turn) from exc
            return turn

    def last_trace(self):
        # Per request thread: never expose another browser's last message in health.
        return getattr(self.request_trace, 'value', {})


def validate_turn(turn, message, pending_question=''):
    """Reject unsupported assertions; these checks are not a semantic accuracy metric."""
    for f in turn.facets + turn.before_facets:
        if f.quote not in message or len(f.quote.split()) > 24:
            raise ValueError('Une citation du plan ne correspond pas exactement au message.')
        if not f.values and f.mode != 'clear':
            raise ValueError('Facette sans valeur.')
        q = norm(f.quote)
        if f.field == 'color':
            for value in f.values:
                evidence = COLOR_EVIDENCE.get(norm(value), re.escape(norm(value)))
                if not re.search(r'\b(?:' + evidence + r')\b', q):
                    raise ValueError('Une couleur du plan ne figure pas dans sa citation. Reformule la demande.')
        if f.field == 'count' and f.mode != 'clear':
            if len(f.values) != 1 or not re.fullmatch(r'[1-5]', f.values[0]):
                raise ValueError('Une demande peut retourner entre une et cinq tenues.')
        if re.search(r'\b(prefer\w*|preferabl\w*|ideally|si possible|de preference)\b', q) and f.strength != 'prefer':
            raise ValueError('Une préférence a été transformée en obligation. Reformule ou précise la demande.')
        if f.field not in {'budget', 'currency', 'count'} and re.search(r'\b(sans|without|avoid|no|pas de|ni)\b', q) and f.mode not in {'exclude', 'clear'}:
            raise ValueError('La négation de la demande n’a pas été préservée.')
    if turn.reuse_previous and (not turn.reference_quote or turn.reference_quote not in message):
        raise ValueError('Référence au contexte précédent non vérifiable.')
    currency_answer = bool(pending_question) and bool(turn.facets) and all(f.field == 'currency' for f in turn.facets)
    if turn.reuse_previous and turn.action in {'compose', 'products', 'compare'} and not currency_answer and not FOLLOWUP_EVIDENCE.search(norm(turn.reference_quote)):
        raise ValueError('Le plan réutilise le contexte sans référence explicite à la demande précédente.')
    if turn.action == 'replace' and (not turn.target_quote or turn.target_quote not in message):
        raise ValueError('Cible du remplacement non vérifiable.')
    if turn.action in {'general', 'explain', 'clarify'} and (turn.facets or turn.before_facets):
        raise ValueError('Une explication ne doit pas ajouter de filtres.')
    # Explicit gender mentions must not disappear. No gender is guessed from an occasion.
    genders = set(re.findall(r'\b(men|women|homme|femme|male|female)\b', norm(message)))
    if genders and turn.action in {'compose', 'products', 'replace', 'compare'} and not any(f.field == 'gender' for f in turn.facets + turn.before_facets):
        raise ValueError('Le genre explicite a été perdu par le parseur.')
    def garment_words(text):
        words = re.findall(r'\w+', norm(text))
        return {w if w in GARMENT_TERMS else w[:-1] for w in words
                if w in GARMENT_TERMS or (w.endswith('s') and w[:-1] in GARMENT_TERMS)}
    if turn.action in {'compose', 'products'}:
        mentioned = garment_words(message)
        represented = set().union(*(garment_words(f.quote) for f in turn.facets if f.field in {'type', 'role'}))
        if mentioned - represented:
            raise ValueError('Un type de vêtement explicite a été perdu par le parseur. Précise la pièce recherchée.')
    if turn.action == 'compose':
        numbers = {'zero':0,'un':1,'une':1,'one':1,'deux':2,'two':2,'trois':3,'three':3,
                   'quatre':4,'four':4,'cinq':5,'five':5,'six':6,'sept':7,'seven':7,
                   'huit':8,'eight':8,'neuf':9,'nine':9,'dix':10,'ten':10}
        pattern = r'\b(\d+|' + '|'.join(numbers) + r')\s+(?:tenues?|outfits?|looks?|propositions?)\b'
        requested = {int(m) if m.isdigit() else numbers[m] for m in re.findall(pattern,norm(message))}
        if len(requested) == 1:
            count = next(iter(requested))
            declared = [int(f.values[0]) for f in turn.facets if f.field=='count' and f.strength=='must' and f.mode!='clear']
            if not 1 <= count <= 5:
                raise ValueError('Une demande peut retourner entre une et cinq tenues.')
            if (declared or [1]) != [count]:
                raise ValueError('Le nombre de tenues demandé a été perdu ou modifié par le parseur.')
