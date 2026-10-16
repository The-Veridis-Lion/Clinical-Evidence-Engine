/** @license SPDX-License-Identifier: Apache-2.0 */
import React,{useEffect,useState} from 'react';
import {ExternalLink,Layers,FileText} from 'lucide-react';
import {rows} from '../services/dataAdapter.ts';
import {RecordData,SourceChoice,evidenceSpans,validSpans,HighlightedText} from './workbenchModel.tsx';

export function InlineEvidenceSnippet({data,choices,choiceKey,onChoice,onViewFullSource,onClose,loading,error,children}:{data:RecordData|null;choices:SourceChoice[];choiceKey:string;onChoice:(key:string)=>void;onViewFullSource:(choice:SourceChoice)=>void;onClose:()=>void;loading:boolean;error:string;children?:React.ReactNode}) {
  const [passage,setPassage]=useState('all');
  useEffect(()=>setPassage('all'),[choiceKey,data]);
  const text=data?.packet?.source?.text || '',all=data?data.spans || evidenceSpans(data):[],exact=validSpans(text,all),selected=passage==='all'?all:[exact[Number(passage)]].filter(Boolean);
  // Inline evidence contains only the saved citations. Surrounding text belongs
  // to the full-source viewer below the workbench.
  const passages=validSpans(text,selected),segments=rows(data?.presentation?.source_navigation?.segments);
  const current=choices.find(choice=>choice.key===choiceKey);
  return <div id="inline-evidence" className="my-2.5 p-3.5 bg-stone-50/90 border border-stone-200/80 rounded-md text-stone-800 font-sans" role="region" aria-label="Original passage" onClick={e=>e.stopPropagation()}>
    <div className="flex items-center justify-between gap-3 pb-2 mb-2 border-b border-stone-200 text-xs"><div className="flex items-center gap-1.5"><Layers className="w-3.5 h-3.5 text-teal-700"/><strong>Source provenance</strong></div><button id="close-inline-evidence" onClick={onClose} className="text-link">Hide passage</button></div>
    {choices.length>1&&<label className="field-label">Supporting source<select id="inline-source-choice" value={choiceKey} onChange={e=>onChoice(e.target.value)}>{choices.map(choice=><option key={choice.key} value={choice.key}>{choice.label}</option>)}</select></label>}
    {loading?<p className="text-xs text-stone-500 py-3" role="status">Loading original passage…</p>:error?<p className="error-text" role="alert">{error}</p>:data?<>
      <div className="flex items-center gap-1.5 text-[11px] text-stone-600 my-2"><FileText className="w-3.5 h-3.5 text-teal-700"/><span>{current?.label || data.packet.source.document_id} · {exact.length} exact saved span{exact.length===1?'':'s'}</span></div>
      {exact.length>1&&<label className="field-label">Supporting passage<select id="inline-passage-choice" value={passage} onChange={e=>setPassage(e.target.value)}><option value="all">All supporting passages</option>{exact.map((span,index)=><option key={index} value={index}>Passage {index+1} · characters {span.start}–{span.end}</option>)}</select></label>}
      <p className="text-[11px] text-stone-500 my-2">Questions and answers retain their original order.</p>
      {passages.map((span,index)=>{
        const speaker=segments.find(segment=>segment.start<=span.start&&segment.end>=span.end)?.raw_speaker_label;
        return <blockquote key={index} className="text-[12.5px] leading-relaxed font-serif whitespace-pre-wrap select-text py-2">{speaker&&<span className="font-sans text-xs text-stone-500 mr-1">{speaker}:</span>}<HighlightedText text={text} spans={[span]} start={span.start} end={span.end}/></blockquote>;
      })}
      {!exact.length&&<p className="text-xs text-stone-500 py-2">No verified individual source span is available. Read the full original source.</p>}
      {exact.length<all.length&&<p className="warning-text">Some saved coordinates could not be verified against this version. No approximate highlight was substituted.</p>}
      <div className="flex justify-end pt-2"><button id="view-full-source" disabled={!current} onClick={()=>current&&onViewFullSource({...current,ref:{...current.ref,all_refs:selected.map((span:RecordData)=>({...span,case_id:data.packet.case_id}))},embedded:{...data,spans:selected}})} className="source-button">View full source<ExternalLink className="w-3 h-3"/></button></div>
      {children}
    </>:<p className="text-xs text-stone-500 py-2">No original source is linked to this statement.</p>}
  </div>;
}
