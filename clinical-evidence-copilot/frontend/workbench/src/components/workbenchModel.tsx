import React from 'react';
import { rows, sourceRefs, sourceSlice } from '../services/dataAdapter.ts';

export type RecordData = Record<string, any>;
export type SourceChoice = { key: string; label: string; ref: RecordData; embedded?: RecordData };
export const sectionNames = { S: 'Subjective', O: 'Objective', A: 'Assessment', P: 'Plan' };
export const queryLabels: Record<string,string> = {
  visit_count: 'Registered encounter count', documented_duration_sum: 'Explicitly documented duration',
  visit_frequency: 'Registered encounter frequency', symptom_timeline: 'Symptom timeline', observation_history: 'Observation history',
};
export function message(error: unknown) { return error instanceof Error ? error.message : String(error); }
export function statusLabel(value:string) {
  const labels:Record<string,string>={SUPPORTED:'Supported',NOT_SUPPORTED:'Not supported',INSUFFICIENT_EVIDENCE:'More evidence needed',CONFLICTED:'Conflicting evidence',NOT_APPLICABLE:'Not applicable',DOCUMENTATION_READY:'Documentation ready',NEEDS_EVIDENCE:'More evidence needed'};
  return labels[value] || String(value || 'Unknown').replaceAll('_',' ');
}
export function readable(value: any): string {
  if(value == null) return 'Not documented';
  if(typeof value !== 'object') return String(value);
  if(Array.isArray(value)) return value.map(readable).join('; ');
  for(const key of ['display_text','text','statement','description','reason','label','value']) if(value[key]!=null) return readable(value[key])+(value.unit ? ` ${value.unit}` : '');
  return 'See saved evidence details';
}
export function sentences(text: string) {
  return typeof Intl.Segmenter === 'function' ? [...new Intl.Segmenter('en',{granularity:'sentence'}).segment(text)].map(part=>part.segment.trim()).filter(Boolean) : [text];
}
export function soapStatements(soap: RecordData | null) {
  return Object.keys(sectionNames).flatMap(section => {
    let index=0;
    return rows(soap?.sections?.[section]).flatMap((row: RecordData) => {
      const linked=rows(soap?.sentence_evidence_links).filter((link: RecordData)=>link.fact_id===row.fact_id || rows(link.fact_ids).includes(row.fact_id)).flatMap(sourceRefs);
      const refs=rows(row.source_refs).length ? row.source_refs : linked.length ? linked : [{case_id:row.case_id,packet_version:row.packet_version,document_id:row.document_id,fact_id:row.fact_id}];
      const textRows=row.compact_text?[row.compact_text]:sentences(row.display_text || row.concept || 'Saved statement');
      return textRows.map(text=>({...row,id:`soap-sentence-${section}-${++index}`,section,text,refs:refs.map((ref:RecordData)=>({...ref,fact_id:row.fact_id}))}));
    });
  });
}
export function soapGroups(statements:RecordData[],section:string) {
  const order=['HPI','History','Medications','ROS','Findings','Assessment','Plan'];
  const groups=new Map<string,RecordData[]>();
  for(const row of statements.filter(row=>row.section===section)){
    const name=row.summary_group || 'Key points';
    groups.set(name,[...(groups.get(name)||[]),row]);
  }
  return [...groups].sort(([a],[b])=>order.indexOf(a)-order.indexOf(b)).map(([name,items])=>({name,items}));
}
export function keyPoints(items:RecordData[]) {
  // This controls reading density, not fact acceptance. Every saved assertion
  // remains in All facts, and specific risks are never hidden by the row limit.
  const selected=new Set([...items].sort((a,b)=>(b.summary_priority||0)-(a.summary_priority||0)).slice(0,3).map(row=>row.id));
  return items.filter(row=>selected.has(row.id)||row.specific_risk);
}
export function keyPointStatementIds(statements:RecordData[]) {
  return [...new Set(Object.keys(sectionNames).flatMap(section=>soapGroups(statements,section).flatMap(group=>keyPoints(group.items).map(row=>row.statement_id))).filter(Boolean))];
}
export function choicesFor(refs: RecordData[], documents: RecordData[] = []): SourceChoice[] {
  const grouped=new Map<string,SourceChoice>();
  for(const original of refs.filter(Boolean)) for(const ref of [original,...rows(original.all_refs)]) {
    if(!ref.case_id) continue;
    const key=`${ref.case_id}:${ref.packet_version ?? ''}`;
    if(!grouped.has(key)) {
      const doc=documents.find(d=>d.case_id===ref.case_id);
      grouped.set(key,{key,label:doc?.filename || ref.document_id || doc?.document_id || ref.case_id,ref:{...ref,all_refs:[]}});
    }
    if(Number.isInteger(ref.start)) grouped.get(key)!.ref.all_refs.push(ref);
  }
  return [...grouped.values()];
}
export function documentChoices(documents: RecordData[]) {
  return choicesFor(documents.filter(d=>d.packet_version).map(d=>({case_id:d.case_id,document_id:d.document_id,packet_version:d.packet_version})),documents);
}
export function evidenceSpans(data: RecordData): RecordData[] {
  const {packet,ref}=data;
  if(!packet) return [];
  const fact=rows(packet.facts).find((f:RecordData)=>f.fact_id===ref?.fact_id);
  const explicit=rows(ref?.all_refs).filter((r:RecordData)=>r.case_id===packet.case_id && Number.isInteger(r.start));
  let spans=explicit.length ? explicit : Number.isInteger(ref?.start) ? [ref] : rows(packet.evidence).filter((e:RecordData)=>rows(fact?.evidence_ids).includes(e.evidence_id));
  if(!spans.length && fact?.assertion?.evidence) spans=[fact.assertion.evidence,...rows(fact.assertion.supporting_evidence)];
  return [...new Map(spans.map((span:RecordData)=>[`${span.start}:${span.end}`,span])).values()].sort((a,b)=>a.start-b.start || a.end-b.end);
}
export function validSpans(text: string,spans: RecordData[]) {
  const length=Array.from(text).length;
  return spans.filter(span=>Number.isInteger(span.start)&&Number.isInteger(span.end)&&span.start>=0&&span.end>span.start&&span.end<=length&&sourceSlice(text,span.start,span.end)===span.quote).sort((a,b)=>a.start-b.start||a.end-b.end);
}
export function HighlightedText({text,spans,start=0,end=Array.from(text).length}:{text:string;spans:RecordData[];start?:number;end?:number}) {
  const nodes:React.ReactNode[]=[];let cursor=start;
  validSpans(text,spans).forEach((span,index)=>{
    if(span.end<=cursor||span.start>=end)return;
    const from=Math.max(cursor,span.start),through=Math.min(end,span.end);
    nodes.push(sourceSlice(text,cursor,from));
    nodes.push(<mark key={`${span.start}-${span.end}-${index}`} data-source-start={span.start} data-source-end={span.end} className="bg-amber-200/80 text-stone-900 rounded-sm">{sourceSlice(text,from,through)}</mark>);
    cursor=through;
  });
  nodes.push(sourceSlice(text,cursor,end));return <>{nodes}</>;
}
export function contextRanges(text: string,spans: RecordData[],segments: RecordData[]) {
  const length=Array.from(text).length,groups:RecordData[]=[];
  for(const span of validSpans(text,spans)) {
    let start=Math.max(0,span.start-300),end=Math.min(length,span.end+400);
    const matches=segments.map((segment,index)=>({segment,index})).filter(({segment})=>segment.start<span.end&&segment.end>span.start);
    if(matches.length) {
      let first=Math.max(0,matches[0].index-1),last=Math.min(segments.length-1,matches.at(-1)!.index+1);
      if(first>0 && /patient/i.test(segments[first].raw_speaker_label || ''))first--;
      if(last<segments.length-1 && /[?？]\s*$/.test(sourceSlice(text,segments[last].start,segments[last].end).trim()))last++;
      start=segments[first].start;end=segments[last].end;
    }
    const previous=groups.at(-1);if(previous&&start<=previous.end)previous.end=Math.max(previous.end,end);else groups.push({start,end});
  }
  return groups;
}
export function careflowSources(packet:RecordData,check:RecordData):SourceChoice[] {
  const facts=[...rows(packet.facts).filter((f:RecordData)=>rows(check.fact_ids).includes(f.fact_id)),...rows(packet.excluded_facts).filter((f:RecordData)=>f.requirement===check.requirement)];
  const mapped=new Set(rows(packet.clinical_mapping?.decisions).filter((d:RecordData)=>rows(d.derived_fact_ids).some(id=>rows(check.fact_ids).includes(id))).flatMap((d:RecordData)=>rows(d.binding?.clinical_fact_ids)));
  const clinical=rows(packet.clinical_context).flatMap((context:RecordData)=>rows(context.facts).filter((f:RecordData)=>mapped.has(f.context_fact_id)).flatMap((f:RecordData)=>[f.evidence,...rows(f.supporting_evidence)].filter(Boolean).map(ref=>({...ref,source_id:context.source_id}))));
  const refs=[...clinical,...facts.flatMap((f:RecordData)=>[...rows(f.citations),...rows(f.requirement_support?.source_refs),...rows(f.requirement_support?.semantic_evidence_bundle?.context_spans)])];
  const sourceIds=new Set([...refs.map(ref=>ref.source_id),...facts.flatMap((f:RecordData)=>rows(f.evidence).map((r:RecordData)=>r.source_id))]);
  for(const source of rows(packet.sources).filter((s:RecordData)=>sourceIds.has(s.source_id))) {
    const original=source.content?.original_document?.source_id;
    if(original){sourceIds.add(original);for(const fields of Object.values(source.content.original_field_evidence || {})) for(const span of Array.isArray(fields)?fields:[fields])if(span&&typeof span==='object')refs.push({...span,source_id:original});}
  }
  return rows(packet.sources).filter((source:RecordData)=>sourceIds.has(source.source_id)&&typeof source.content==='string').map((source:RecordData)=>{
    const locator=source.original_locator || {},selected=refs.filter(ref=>ref.source_id===source.source_id);
    const ref={case_id:locator.case_id,packet_version:locator.version,document_id:locator.document_id || source.source_id,all_refs:selected.map(span=>({...span,case_id:locator.case_id}))};
    return {key:source.source_id,label:locator.document_id || source.source_id,ref,embedded:{packet:{case_id:locator.case_id,version:locator.version,source:{document_id:ref.document_id,text:source.content}},ref,spans:selected}};
  });
}
export function querySummary(result:RecordData) {
  if(result.status&&result.status!=='ready')return result.clarification_question || result.explanation || 'This question needs clarification.';
  const answer=result.answer || {},family=result.query_spec?.family;
  if(typeof answer==='string')return answer;
  if(family==='visit_count')return `${answer.visit_count ?? 'Unknown'} registered encounter${answer.visit_count===1?'':'s'}.`;
  if(family==='documented_duration_sum')return answer.documented_minutes==null?'No complete documented duration total is available.':`${answer.documented_minutes} explicitly documented minutes${answer.complete===false?' (incomplete subtotal)':''}.`;
  if(family==='visit_frequency')return `${rows(answer.weeks || answer.buckets).length} registered encounter frequency intervals.`;
  return `${rows(answer.events).length} dated records.`;
}
export function recordText(item:RecordData) {
  if(item.reason)return `${String(item.reason).replaceAll('_',' ')}${item.document_id?` · ${item.document_id}`:''}${item.record?.concept?` · ${item.record.concept}`:''}`;
  // Query records retain ClinicalFact attributes as a nested object. Show the
  // saved measurement, not just its concept label; do not infer a new value.
  const value=item.value ?? item.attributes?.value;
  const severity=item.attributes?.severity;
  const unit=item.unit ?? item.attributes?.unit;
  const measurementParts=[value,severity].filter((part,index,all)=>part!=null&&all.indexOf(part)===index).map(readable);
  const measurement=item.duration_unknown?'Unknown':typeof item.minutes==='number'?`${item.minutes} minutes`:measurementParts.length?`${measurementParts.join(' · ')}${unit?` ${unit}`:''}`:item.attributes?.duration;
  if(item.concept)return `${item.display_date || item.event_date || item.record_date || 'Date unknown'} · ${item.concept}${item.clinical_status?` · ${item.clinical_status}`:item.polarity?` · ${item.polarity}`:''}${measurement?`: ${measurement}`:''}`;
  if(item.encounter_id)return `${item.encounter_date || 'Date unknown'} · ${item.encounter_id}`;
  if(item.week_start)return `${item.week_start} to ${item.week_end}: ${item.visit_count} registered encounters`;
  if(item.operation)return `${queryLabels[item.operation] || item.operation}: ${item.inputs?.record_count ?? 0} included records`;
  if(item.document_id)return `${item.document_id} · saved version ${item.packet_version ?? 'unknown'}`;
  return readable(item);
}

export function durationEquation(result:RecordData) {
  if(result.query_spec?.family!=='documented_duration_sum')return null;
  const events=rows(result.answer?.events),total=result.answer?.documented_minutes;
  if(!events.length||typeof total!=='number'||events.some(event=>typeof event.minutes!=='number'))return null;
  // Explain the existing calculation only when all displayed terms reconcile.
  // Missing and excluded records stay in the server's separate audit sections.
  if(Math.abs(events.reduce((sum,event)=>sum+event.minutes,0)-total)>0.000001)return null;
  return `${events.map(event=>event.minutes).join(' + ')} = ${total} minutes`;
}

export function durationRecordPreview(result:RecordData) {
  const events=rows(result.answer?.events);
  if(result.query_spec?.family!=='documented_duration_sum')return events;
  // This is a source-document preview, not event deduplication or a new total.
  // Keep every unresolved assertion in the existing calculation details below.
  const represented=new Set(events.map(event=>event.document_id));
  const extra=new Map<string,RecordData>();
  const service=result.query_spec?.filters?.service_type?.trim().toLowerCase();
  for(const missing of rows(result.missing_data)){
    const record=missing.record;
    if(!record?.document_id||record.action_state!=='completed'||represented.has(record.document_id))continue;
    if(service&&record.action_type?.trim().toLowerCase()!==service)continue;
    if(record.attributes?.duration||record.minutes!=null)continue;
    if(!extra.has(record.document_id))extra.set(record.document_id,{...record,duration_unknown:true});
  }
  return [...events,...extra.values()];
}
