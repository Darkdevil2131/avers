"""Conservative sentence boundaries with exact offsets; no scientific interpretation."""
import re

ABBREVIATIONS={'e.g.','i.e.','et al.','fig.','figs.','dr.','mr.','mrs.','vs.','approx.'}

def sentence_spans(text):
    start=0
    for match in re.finditer(r'[.!?](?=\s+\S|$)|\n+',text):
        end=match.end()
        prefix=text[max(start,match.start()-8):end].lower()
        if match.group()=='.' and any(prefix.endswith(a) for a in ABBREVIATIONS):continue
        left=start
        while left<end and text[left].isspace():left+=1
        right=end
        while right>left and text[right-1].isspace():right-=1
        if right>left:yield left,right
        start=end
    while start<len(text) and text[start].isspace():start+=1
    if start<len(text):yield start,len(text)

def complete_passage(text,start,end,max_expansion=1200):
    """Expand only within a bounded window. Reject incomplete edge sentences later."""
    spans=list(sentence_spans(text))
    for left,right in spans:
        if left<=start<right and start-left<=max_expansion:start=left;break
    for left,right in spans:
        if left<end<=right and right-end<=max_expansion:end=right;break
    return start,end
