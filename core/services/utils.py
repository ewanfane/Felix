import re

def parse_chunking_output(raw_text):
    """
    Extracts XML tags for Content and Tags.
    """
    data = {
        "content": "",     # FACTUAL SUMMARY
        "metadata": {},
        "skip": False
    }
    
    # 0. Check for Trivial Skip
    if "<skip>TRUE</skip>" in raw_text:
        data["skip"] = True
        return data

    # 1. Extract Content (The What)
    content_match = re.search(r'<content>(.*?)</content>', raw_text, re.DOTALL)
    if content_match:
        data["content"] = content_match.group(1).strip()
    
    # 2. Extract Tags (The Metadata)
    tags_match = re.search(r'<topic_tags>(.*?)</topic_tags>', raw_text, re.DOTALL)
    if tags_match:
        tag_list = [t.strip() for t in tags_match.group(1).split(',') if t.strip()]
        data["metadata"]["topics"] = tag_list

    return data