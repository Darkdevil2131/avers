import re
from collections import Counter
from .text_spans import sentence_spans
WORDS=re.compile(r'[A-Za-z][A-Za-z-]{2,}')
STOP=set('the and with from that this were was are for not but study studies results effect effects'.split())
DIRECTION=re.compile(r'\b(increas\w*|decreas\w*|reduc\w*|improv\w*|associated|correlat\w*|no significant|not associated|did not)\b',re.I)
NUMBER=re.compile(r'(?<!\w)(?:n\s*=\s*)?[-+]?\d+(?:\.\d+)?\s*(?:%|mg|kg|mm|cm|°C|K|days?|hours?|months?|years?)?',re.I)
def terms(value):return set(w.lower() for w in WORDS.findall(value))-STOP
def plan(question):
    words=terms(question)
    kind='comparison' if re.search(r'\b(vs|versus|compare|better|outperform)\b',question,re.I) else 'mechanism' if re.search(r'\b(why|mechanism|cause|how)\b',question,re.I) else 'evidence_review'
    return {'objective':question,'task_type':kind,'search_terms':sorted(words)[:20],
            'decisions':[{'action':'retrieve_project_evidence','reason':'Inspect existing project evidence before requesting new documents'},
                         {'action':'check_context_and_counterevidence','reason':'Matching text alone cannot establish a scientific conclusion'}],
            'budgets':{'search_requests':2,'fulltext_documents':4,'citation_depth':1,'passages':8,'deadline_seconds':180},
            'planner':'explicit-policy-v1','general_reasoning_model':False}
def extract(citations,question):
    """Extract candidates verbatim; no generated claims or guessed study attributes."""
    findings=[];q=terms(question)
    seen=set()
    for citation in citations:
        if citation.get('origin','').endswith('_metadata'):continue
        text=citation['quote']
        if len(findings)>=80:break
        for left,right in sentence_spans(text):
            value=text[left:right]
            if len(value)<30 or not (terms(value)&q):continue
            identity=(citation['source_id'],value)
            if identity in seen:continue
            seen.add(identity)
            start=citation['start_offset']+left
            numbers=[m.group().strip() for m in NUMBER.finditer(value)]
            design=next((d for d in ['randomized','observational','retrospective','in vitro','simulation','cohort','systematic review'] if d in value.lower()),None)
            findings.append({'source_id':citation['source_id'],'citation':citation['label'],'statement':value,
                             'start_offset':start,'end_offset':start+len(value),'measurements':numbers,
                             'study_design':design,'context_verified':False,'method':'extractive-pattern-v1',
                             'passage_relevance_score':citation.get('rerank_score'),'status':'candidate','limitations':['Sentence-level extraction; study context and scientific interpretation require review']})
            if len(findings)>=80:break
    if not findings:return []
    try:
        from .retrieval import DENSE
        scores=DENSE.rerank(question,[f['statement'] for f in findings])
        for finding,score in zip(findings,scores):
            finding['sentence_relevance_score']=float(score)
            finding['selection_score']=float(score) if finding['passage_relevance_score'] is None else .75*float(score)+.25*float(finding['passage_relevance_score'])
            finding['method']='context-weighted-sentence-reranker-v2'
        findings.sort(key=lambda f:-f['selection_score'])
    except (ImportError,OSError,ValueError,RuntimeError):
        findings=[f for f in findings if DIRECTION.search(f['statement'])]
    # Keep a small review queue; scores measure relevance, never entailment/truth.
    return findings[:3]

def critique(findings,citations):
    pairs=[]
    for index,left in enumerate(findings):
        for right in findings[index+1:]:
            if left['source_id']==right['source_id']:continue
            a,b=terms(left['statement']),terms(right['statement'])
            overlap=len(a&b)/max(1,len(a|b))
            negative=lambda s:bool(re.search(r'\b(no significant|not associated|did not|no effect)\b',s,re.I))
            if overlap>=.35 and negative(left['statement'])!=negative(right['statement']):
                pairs.append({'left':left['citation'],'right':right['citation'],'state':'potential_disagreement',
                              'reason':'Related wording with different negation; context is not verified',
                              'automatic_verdict':False})
    groups={}
    for c in citations:groups.setdefault(c.get('study_id') or c['url'],[]).append(c['label'])
    return {'potential_disagreements':pairs[:12],'study_identifier_groups':list(groups.values()),
            'independence_verified':False,'missing_checks':['Full study context','Risk of bias','Independent study identity','Expert scientific appraisal'],
            'decision':'abstain_from_scientific_verdict','reason':'Extractive candidates and retrieval scores do not validate scientific support'}
def propose(findings,question):
    if not findings:return []
    anchor=findings[0]
    return [{'kind':'replication_candidate','statement':'Test whether the relationship in the cited observation replicates under independently controlled conditions.',
             'basis_quote':anchor['statement'],'source_id':anchor['source_id'],'citation':anchor['citation'],
             'mechanism':'Not established by the extracted sentence; requires a domain-specific mechanism before experimental approval.',
             'falsification':'A preregistered independent replication fails to reproduce the stated relationship within a justified uncertainty bound.',
             'experiment_plan':{'design':'Independent replication proposal','required_inputs':['Operational definitions','Population or material','Comparator or control','Measurement protocol','Effect estimate and variance','Domain-specific safety review'],
                                'sample_size':None,'reason':'Sample size cannot be chosen without an effect target, variance, design, and error criteria'},
             'novelty':'not assessed','status':'proposal_needs_review','experiment_executed':False}]
def proposal_critic(proposal):
    """Reject simple observable inconsistencies; passing is not scientific validation."""
    hypothesis=proposal.get('statement','').lower()
    quote=proposal.get('basis_quote','').lower()
    mechanism=proposal.get('mechanism','').lower()
    reasons=[]
    def direction(value):
        # "Did not increase" may mean stable or decreased. Never invert it into
        # a positive/negative effect, or interpret absence of significance as one.
        if re.search(r"\b(not|no|never|without|neither|failed to)\b|n['’]t\b",value):
            return 0, 'negation_requires_context_review'
        # Comparative adjectives can describe exposure/dose, not the outcome:
        # "adhesion increased at lower humidity" is not mixed direction.
        up=bool(re.search(r'\b(increase[sd]?|increasing|improve[sd]?|improving)\b',value))
        down=bool(re.search(r'\b(decrease[sd]?|decreasing|reduce[sd]?|reducing)\b',value))
        if up and down:return 0, 'mixed_directions_require_context_review'
        if up or down:return (1 if up else -1), 'explicit_direction_word'
        # Bare "higher/lower" remains ambiguous; require a predicative phrase.
        up=bool(re.search(r'\b(?:is|are|was|were|became|becomes)\s+higher\b',value))
        down=bool(re.search(r'\b(?:is|are|was|were|became|becomes)\s+lower\b',value))
        if up != down:return (1 if up else -1), 'predicative_comparison'
        return 0, 'direction_not_established'
    (a,a_reason),(b,b_reason)=direction(hypothesis),direction(quote)
    shared=len(terms(hypothesis)&terms(quote))/max(1,len(terms(hypothesis)))
    opposition=a*b==-1 and shared>=.3
    if opposition:
        reasons.append('Proposed direction opposes its cited observation without a validated reconciliation')
    if any(x in mechanism for x in ('not supported by the evidence','contradicts the evidence')):
        reasons.append('The generated mechanism explicitly disclaims its own evidential support')
    return {'accepted_as_candidate':not reasons,'reasons':reasons,'scientific_validation':False,
            'direction_check':{'status':'potential_opposition' if opposition else 'requires_review' if not a or not b or shared<.3 else 'no_opposition_detected',
                               'hypothesis_basis':a_reason,'evidence_basis':b_reason,
                               'context_verified':False},
            'limitations':['Direction words do not verify matching outcomes, populations, exposures or causal support.',
                           'A proposal not rejected by these rules still requires scientific review.']}
