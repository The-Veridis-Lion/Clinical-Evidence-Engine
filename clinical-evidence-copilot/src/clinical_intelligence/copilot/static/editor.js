'use strict';
// Form controls adapt the existing review contracts; they do not infer values.
const CopilotEditor = (() => {
  const main = [
    ['concept', 'Clinical concept'], ['original_term', 'Original term'],
    ['category', 'Category', ['symptom','condition','diagnosis','medication','treatment','procedure','laboratory_result','observation','other']],
    ['polarity', 'Assertion polarity', ['present','absent','uncertain']],
    ['temporality', 'Time scope', ['current','historical','planned','unknown']],
    ['experiencer', 'Subject', ['patient','family','other','unknown']],
    ['assertion_basis', 'Reporting basis', ['patient_report','clinician_assessment','clinician_observation','documented_history','discussion','unknown']],
    ['attribution_confidence', 'Subject attribution', ['context_supported','uncertain']],
    ['clinical_status', 'Documented status / qualifier'],
    ['attributes.severity', 'Severity'], ['attributes.duration', 'Duration'],
    ['attributes.value', 'Value'], ['attributes.unit', 'Unit']
  ];
  const timing = [
    ['frequency', 'Frequency'], ['event_time', 'Event time'], ['duration', 'Duration'],
    ['action_state', 'Action state', ['planned','completed','not_completed','ongoing','discussed','unknown']],
    ['completion_scope', 'Completion scope', ['','single_event','course','full_course','unknown']],
    ['assertion_basis', 'Reporting basis', ['patient_report','patient_reported','clinician_assessment','clinician_observation','documented_history','discussion','unknown']],
    ['action_type', 'Action type']
  ];
  const get = (object, key) => key.split('.').reduce((value, part) => value?.[part], object);
  const copy = object => JSON.parse(JSON.stringify(object));
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(container, proposal, semantics=false) {
    const fields = semantics ? timing : main;
    container.innerHTML = '<div class="correction-grid">' + fields.map(([key,label,choices]) => {
      const value = get(proposal,key) ?? '';
      const options = choices && [...new Set([...choices, value])];
      const input = options ? `<select data-field="${key}" aria-label="${label}">${options.map(option=>`<option value="${escape(option)}" ${option===value?'selected':''}>${escape(option || 'Not asserted')}</option>`).join('')}</select>` :
        `<input data-field="${key}" aria-label="${label}" value="${escape(value)}" ${key==='original_term'?'required':''}>`;
      return `<label>${label}${input}</label>`;
    }).join('') + '</div>';
    if (!semantics) {
      const spans = [proposal.evidence, ...(proposal.supporting_evidence || [])];
      container.innerHTML += `<label>Primary source passage<select data-primary-evidence aria-label="Primary source passage">${spans.map((span,i)=>`<option value="${i}">${escape(`[${span.start}:${span.end}] ${span.quote}`)}</option>`).join('')}</select></label><p class="field-help">All cited passages are retained. A question alone does not establish a symptom; a short answer may need the question as context. Select a passage only after reading the full source.</p>`;
    }
  }
  function collect(container, proposal, semantics=false) {
    const result = copy(proposal);
    const attributes = {...(proposal.attributes || {})};
    let attributeChanged = false;
    for (const input of container.querySelectorAll('[data-field]')) {
      const key = input.dataset.field;
      const value = input.value === '' ? null : input.value;
      if (key.startsWith('attributes.')) {
        attributes[key.split('.')[1]] = value;
        attributeChanged ||= value !== (get(proposal,key) ?? null);
      } else if (value !== (get(proposal,key) ?? null)) result[key] = value;
    }
    if (!semantics && attributeChanged) result.attributes = attributes;
    if (!semantics) {
      const index = Number(container.querySelector('[data-primary-evidence]').value);
      if (index) {
        const spans = [proposal.evidence, ...(proposal.supporting_evidence || [])];
        result.evidence = copy(spans[index]);
        result.supporting_evidence = spans.filter((_,i)=>i!==index).map(copy);
        // The server rebuilds and checks provenance against unchanged source text.
        result.provenance = [];
      }
    }
    return result;
  }
  return {render, collect};
})();
