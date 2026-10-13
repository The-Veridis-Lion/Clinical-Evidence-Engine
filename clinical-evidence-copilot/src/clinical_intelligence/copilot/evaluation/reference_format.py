"""Lossless syntax adaptation for generated reference containers, not clinical edits."""
import json

from ..models import digest

VERSION='copilot-reference-format/v1'


def escape_interior_quotes(raw):
    """Only insert escapes at quotes followed by non-JSON boundary characters.

    No character is deleted or substituted; missing delimiters/ambiguous quote
    boundaries remain parse errors. This is a recorded syntactic interpretation,
    never a correction of clinical label content.
    """
    output=[]; edits=[]; inside=False; escaped=False
    for i,char in enumerate(raw):
        if not inside:
            output.append(char)
            if char=='"': inside=True
            continue
        if escaped:
            output.append(char); escaped=False; continue
        if char=='\\':
            output.append(char); escaped=True; continue
        if char=='"':
            after=raw[i+1:].lstrip()
            if not after or after[0] in ':,}]':
                inside=False
            else:
                output.append('\\'); edits.append(i)
        output.append(char)
    return ''.join(output),edits


def decode_reference(raw):
    """Accept literal control chars inside JSON strings without rewriting content.

    Python's strict=False changes only JSON string control-character acceptance.
    Invalid delimiters, malformed keys, duplicate keys and other syntax errors are
    never guessed. Keep strict status/hash for a separate original-format report.
    """
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('Duplicate reference key; ambiguous labels')
            result[key]=value
        return result
    strict_error=None; edits=[]; derived=raw
    if isinstance(raw,str):
        try:
            value=json.loads(raw,object_pairs_hook=unique)
        except json.JSONDecodeError as exc:
            strict_error=str(exc)
            try:
                value=json.loads(raw,strict=False,object_pairs_hook=unique)
                edits=[]
            except json.JSONDecodeError:
                derived,edits=escape_interior_quotes(raw)
                if not edits: raise
                value=json.loads(derived,strict=False,object_pairs_hook=unique)
    elif isinstance(raw,dict):
        value=raw
    else:
        raise ValueError('Reference root must be a JSON object')
    if not isinstance(value,dict): raise ValueError('Reference root must be a JSON object')
    adaptation='none'
    if strict_error:
        adaptation='JSON string control characters accepted without changing values'
        if edits: adaptation+='; interior quote escapes inserted without deleting/substituting original characters'
    return value,dict(version=VERSION,original_hash=digest(raw),original_strict_parse_passed=strict_error is None,
        original_strict_error=strict_error,adaptation=adaptation,quote_escape_positions=edits,
        derived_json_hash=digest(derived))


def container_items(value):
    """Preserve nonobject template values as explicit scalar labels, never discard."""
    if isinstance(value,dict): return list(value.items())
    if isinstance(value,list): return [(str(i),v) for i,v in enumerate(value)]
    return [('scalar',value)]
