"""Mention matching and assertion interpretation are separate, observable stages.

Only unchanged source text enters this module. No benchmark/model-output imports.
ConText is a heuristic assertion engine, not a guarantee of clinical correctness.
The experiment audits errors among apparently resolved cases explicitly.
"""
from collections import defaultdict
from importlib.resources import files
import json

import medspacy
from medspacy.context import ConTextRule
from medspacy.ner import TargetRule
from medspacy.section_detection import SectionRule
from spacy.matcher import PhraseMatcher


def evidence(span):
    return {"quote": span.text, "start": span.start_char, "end": span.end_char}


class RuleFirstExtractor:
    def __init__(self):
        resources = files(__package__).joinpath("resources")
        self.concepts = json.loads(resources.joinpath("concepts.json").read_text())
        self.nlp = medspacy.load(medspacy_enable=["medspacy_pyrush", "medspacy_target_matcher",
                                                  "medspacy_context", "medspacy_sectionizer"])
        # Preserve upstream section recognition, with generic History separated from PMH.
        section_rules = self.nlp.get_pipe("medspacy_sectionizer").rules
        self.nlp.remove_pipe("medspacy_sectionizer")
        sectionizer = self.nlp.add_pipe("medspacy_sectionizer", config={"rules": None, "span_attrs": None})
        sectionizer.add([r for r in section_rules if r.literal.casefold() not in {"history:", "history"}])
        sectionizer.add([SectionRule("History:", "history"), SectionRule("HPI:", "history_present_illness")])
        sectionizer.add([
            SectionRule("History heading", "history", pattern=r"(?im)^[ \t]*(?:\*\*)?History(?:\*\*)?[ \t]*:?[ \t]*$"),
            SectionRule("Physical Examination heading", "physical_exam",
                        pattern=r"(?im)^[ \t]*(?:\*\*)?Physical Examination(?:\*\*)?[ \t]*:?[ \t]*$")
        ])
        # The upstream bare 'history' cue also matches current History headings.
        context_rules = self.nlp.get_pipe("medspacy_context").rules
        self.nlp.remove_pipe("medspacy_context")
        context = self.nlp.add_pipe("medspacy_context", config={"rules": None})
        context.add([r for r in context_rules if r.literal != "history"])
        context.add([ConTextRule("history of", "HISTORICAL", direction="FORWARD"),
                     ConTextRule("hx of", "HISTORICAL", direction="FORWARD"),
                     ConTextRule("absent", "NEGATED_EXISTENCE", direction="BACKWARD"),
                     ConTextRule("resolved", "HISTORICAL", direction="BACKWARD")])
        targets = []
        for key, spec in self.concepts.items():
            terms = list(spec["aliases"])
            if spec["hpo"]:
                data = json.loads(resources.joinpath(spec["hpo"].replace(":", "_") + ".json").read_text())
                term = data["_embedded"]["terms"][0]
                terms += [term["label"], *term["synonyms"]]
            for phrase in sorted(set(terms) - set(spec.get("exclude", []))):
                # Uppercase abbreviations avoid treating ordinary English 'sob' as dyspnea.
                pattern = [{"TEXT": phrase}] if phrase in {"SOB", "DOE"} else None
                targets.append(TargetRule(phrase, key, pattern=pattern))
        self.nlp.get_pipe("medspacy_target_matcher").add(targets)
        self.scope_guard = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        for reason, phrases in {
            "negated_change_scope": ["no change", "no increase", "no decrease", "no worsening", "no improvement",
                                      "without change", "denies change", "denies worsening", "not improved"],
            "uncertain_time_or_subject": ["previously", "yesterday", "last week", "used to", "resolved", "mother", "father",
                                          "wife", "husband", "sister", "brother", "child", "son", "daughter"],
            "unresolved_assertion": ["not only", "not necessarily", "cannot exclude", "not excluded", "feverish"]
        }.items():
            self.scope_guard.add(reason, [self.nlp.make_doc(p) for p in phrases])
        self.coverage_guard = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        self.coverage_guard.add("unmapped_possible_symptom", [self.nlp.make_doc(p) for p in [
            "respiratory symptoms", "respiratory distress", "breathing patterns", "breathing", "breath",
            "congestion", "coryza", "nasal", "chest", "hyperthermia", "panting", "feverish", "temperature"]])

    def detect(self, text):
        """Return library spans before any final-fact decision."""
        return self.nlp(text)

    def interpret(self, doc):
        candidates, issues = [], []
        for i, ent in enumerate(doc.ents):
            spec = self.concepts[ent.label_]
            sent = ent.sent
            reasons = {doc.vocab.strings[m] for m, _, _ in self.scope_guard(sent)}
            if ent._.is_uncertain or ent._.is_hypothetical:
                reasons.add("uncertain_or_hypothetical")
            if ent._.is_family:
                reasons.add("experiencer_scope")
            negated = ent._.is_negated
            if ent.text.casefold() in spec.get("negative_terms", []):
                if negated:
                    reasons.add("double_negation")
                negated = not negated
            modifiers = [{"category": m.category, "evidence": evidence(doc[slice(*m.modifier_span)])}
                         for m in ent._.modifiers]
            item = {"candidate_id": f"m{i:04d}", "concept_group": spec["group"], "hpo_id": spec["hpo"],
                    "mention": evidence(ent), "context": evidence(sent),
                    "section": {"category": ent._.section_category, "title": str(ent._.section_title or "")},
                    "modifiers": modifiers, "reasons": sorted(reasons),
                    "fact": {"category": "symptom", "concept": spec["concept"], "original_term": ent.text,
                             "polarity": "uncertain" if ent._.is_uncertain else "absent" if negated else "present",
                             "temporality": "historical" if ent._.is_historical or ent._.section_category == "past_medical_history" else "current",
                             "experiencer": "family" if ent._.is_family else "patient", "attributes": None,
                             "evidence": evidence(ent)}}
            if ent._.section_category == "family_history":
                item["fact"]["experiencer"] = "family"
                item["reasons"] = sorted(set(item["reasons"]) | {"experiencer_scope"})
            if ent._.section_category in {"assessment_and_plan", "plan", "instructions"}:
                item["reasons"] = sorted(set(item["reasons"]) | {"treatment_or_future_scope"})
            candidates.append(item)
        # Opposing reports and findings in distinct sections remain independent.
        by_scope = defaultdict(list)
        for c in candidates:
            f = c["fact"]
            by_scope[(c["concept_group"], c["section"]["category"], f["temporality"], f["experiencer"])].append(c)
        for group in by_scope.values():
            if {c["fact"]["polarity"] for c in group} >= {"present", "absent"}:
                for c in group:
                    c["reasons"] = sorted(set(c["reasons"]) | {"opposing_assertions_same_scope"})
        # Broad lexical signals cover some normalization misses, not arbitrary unseen wording.
        for sent in doc.sents:
            covered = [c for c in candidates if c["mention"]["start"] < sent.end_char and c["mention"]["end"] > sent.start_char]
            for _, start, end in self.coverage_guard(sent):
                # spaCy matchers return document-relative indices even for a Span input.
                span = doc[start:end]
                if any(c["mention"]["start"] <= span.start_char and c["mention"]["end"] >= span.end_char for c in covered):
                    continue
                issues.append({"reason": "unmapped_possible_symptom", "signal": evidence(span), "context": evidence(sent)})
        return candidates, issues

    def extract(self, document_id, text):
        doc = self.detect(text)
        candidates, issues = self.interpret(doc)
        sections = [{"category": s.category, "title": evidence(doc[slice(*s.title_span)]) if s.title_span and s.title_span[0] != s.title_span[1] else None,
                     "body": evidence(doc[slice(*s.body_span)]) if s.body_span[0] != s.body_span[1] else None}
                    for s in doc._.sections]
        return {"document_id": document_id, "sections": sections, "candidates": candidates,
                "coverage_issues": issues, "requires_adjudication": bool(issues or any(c["reasons"] for c in candidates)),
                "result": {"document_id": document_id, "facts": [c["fact"] for c in candidates if not c["reasons"]]}}
