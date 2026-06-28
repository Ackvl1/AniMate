import re
from typing import List


separators = ["\n\n", "\n", "。", "！", "？", "；", ".", " ", ""]

def chunk_text(text:str,max_chars:int=1000,overlap:int=50)->list[str]:
    seps = separators

    cleaned = text.strip()

    # 先递归切成 返回若干"尽量小但不截断语义"的碎片
    fragments = chunk_recursive(cleaned,max_chars,seps)

    # 把碎片合并成目标大小的 chunk，并在块边界注入 overlap
    chunks = merge_with_overlap(fragments,max_chars,overlap)

    return chunks

def chunk_recursive(text:str,max_chars:int,separators:List[str])->List[str]:
    if not text:
        return []
    
    if len(text)<=max_chars:
        return [text]
    
    chosen_sep = separators[-1]
    remaining_sep=[]

    for i,sep in enumerate(separators):
        if sep=="":
            chosen_sep = sep
            remaining_sep=[]
            break

        if re.search(re.escape(sep),text):
            chosen_sep = sep
            remaining_sep=separators[i+1:]
            break

    if chosen_sep=="":
        raw_parts=list(text)
    else:
        raw_parts=re.split(re.escape(chosen_sep),text)

    # 过滤空字符串片段，并去除每片首尾空格
    parts = [p.strip() for p in raw_parts if p.strip()]

    result=[]

    for part in parts:
        if len(part)<= max_chars:
            result.append(part)
        
        elif remaining_sep:
            sub=chunk_recursive(part,max_chars,remaining_sep)
            result.extend(sub)
        
        else:
            result.append(part)
    
    return result

def merge_with_overlap(fragments:list[str],max_chars:int,overlap:int)->list[str]:
    if not fragments:
        return []
    
    docs: list[str]=[]
    window: list[str]=[]
    total:int =0

    for frag in fragments:
        frag_len = len(frag)
        if window and total+frag_len>max_chars:
            docs.append("\n".join(window))
            while window and (total>overlap or total+frag_len>max_chars):
                evicted=window.pop(0)
                total-=len(evicted)
            
        window.append(frag)
        total=total+frag_len
    
    if window:
        docs.append("\n".join(window))

    return docs

        