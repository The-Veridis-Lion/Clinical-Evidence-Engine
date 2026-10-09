"""Author independent synthetic facts first, then render and verify source text.

Examples and all evaluation partitions have distinct patients, documents and
template families. Existing public/original failures belong only to development.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "luna"


def service(encounter, date, **changes):
    data = dict(kind="service", encounter_ref=encounter, appointment_ref=None, service_date=date,
        service_type="individual", evidence_kind="clinical", signed=True, patient_present=True, delivered=True,
        actual_intervals=[], scheduled_intervals=[], unspecified_intervals=[], breaks=[], reported_minutes=None)
    data.update(changes)
    return data


def interval(a, b):
    return dict(start=a, end=b)


def observation(date, category, reporter, experiencer, polarity="present", temporality="current", **extra):
    return dict(kind="observation", observation_date=date, category=category, reporter=reporter,
                experiencer=experiencer, polarity=polarity, temporality=temporality, **extra)


def case(identifier, split, family, facts, body, **extra):
    # Fact objects are passed before rendering, independent of inference.
    patient = {"patient_id": "SYN-" + identifier.upper(), "name": identifier.title() + " Example", "dob": "1984-03-17"}
    declared = "DOC-" + identifier.upper()
    text = f"MRN: {patient['patient_id']} | Patient: {patient['name']} | DOB: {patient['dob']}\nDocument ID: {declared}\n" + body
    return dict(id=identifier, split=split, group=identifier, family=family, source="new_synthetic",
                text=text, patient=patient, declared_id=declared, facts=facts, exhaustive=True, **extra)


def build():
    rows = []
    f = service("DEV-E1", "2026-05-04", actual_intervals=[interval("09:03", "09:34")], reported_minutes=31)
    rows.append(case("header", "dev", "header_clinical", [f], "Encounter DEV-E1 | Service date 2026-05-04\nSigned individual psychotherapy. Patient contact 09:03 to 09:34; explicitly completed 31 minutes.\n"))
    f = [service("DEV-E2", "2026-05-05", service_type="group", actual_intervals=[interval("10:00", "10:50")], breaks=[interval("10:20", "10:25")]),
         service("DEV-E3", "2026-05-06", service_type="group", actual_intervals=[interval("10:00", "10:50")], breaks=[interval("10:20", "10:25")])]
    rows.append(case("repeated", "dev", "blank_sections", f, "Encounter DEV-E2, 2026-05-05\nSigned group care. Patient contact 10:00 to 10:50; no therapy during break 10:20 to 10:25.\n\nEncounter DEV-E3, 2026-05-06\nSigned group care. Patient contact 10:00 to 10:50; no therapy during break 10:20 to 10:25.\n"))
    f = service("DEV-E4", "2026-05-07", appointment_ref="DEV-A4", actual_intervals=[interval("13:00", "13:13"), interval("13:23", "13:48")], breaks=[interval("13:13", "13:23")], reported_minutes=38)
    rows.append(case("reconnect", "dev", "platform_segments", [f], "Encounter DEV-E4 | Appointment DEV-A4 | 2026-05-07\nSigned individual psychotherapy. Patient contact 13:00 to 13:13 and 13:23 to 13:48. Network outage 13:13 to 13:23: no therapeutic contact. The second connection continued the same appointment. Total patient therapy: 38 minutes.\n"))
    f = service("DEV-E5", "2026-05-08", service_type="family", actual_intervals=[interval("14:19", "14:55")], reported_minutes=36)
    rows.append(case("family", "dev", "partner_only", [f], "Encounter DEV-E5 | 2026-05-08\nSigned family psychotherapy. Therapist worked 14:00 to 14:55. Partner only 14:00 to 14:19; patient joined at 14:19 and received therapy through 14:55, 36 patient-present minutes.\n"))
    f = service("DEV-E6", "2026-05-11", evidence_kind="schedule", signed=False, patient_present=False, delivered=False, scheduled_intervals=[interval("11:00", "11:45")])
    rows.append(case("noshow", "dev", "desk_absence", [f], "Encounter DEV-E6 | 2026-05-11\nIndividual psychotherapy booked 11:00 to 11:45. Desk status: No show. Patient did not arrive; no treatment contact. Unsigned scheduling export.\n"))
    rows.append(case("unknown", "dev", "unknown_duration", [service("DEV-E7", "2026-05-12")], "Encounter DEV-E7 | 2026-05-12\nSigned individual psychotherapy. Patient attended and treatment was delivered. Neither clock times nor a completed duration were recorded.\n"))
    p = "SYN-MIXED"; name = "Mixed Example"
    f = [observation("2026-05-13", "symptom", name, name, keywords=["sleep"]),
         observation("2026-05-13", "safety", name, name, "absent", keywords=["suicid"]),
         observation("2026-05-13", "symptom", "partner", "partner", keywords=["anx"])]
    rows.append(case("mixed", "dev", "mixed_assertions", f, "2026-05-13: Mixed Example reports disrupted sleep and denies current suicidal thoughts. The partner reports that the partner feels anxious about giving reminders. No visit occurred.\n"))
    rows.append(case("administrative", "dev", "authorization_only", [], "Authorization correspondence dated 2026-05-14: 6 group slots approved for the next month. This is an authorization only, no clinical visit, no weekly therapy requirement and no symptom or function report.\n"))

    f = service("VAL-E1", "2026-06-01", actual_intervals=[interval("08:20", "08:47")], reported_minutes=27)
    rows.append(case("bodyid", "validation", "identifier_prose", [f], "Signed note dated June 1, 2026\nThe individual psychotherapy contact is filed as VAL-E1. The patient was present from 08:20 until 08:47; treatment duration was reported as 27 minutes.\n"))
    f = [service("VAL-E2", "2026-06-02", service_type="group", actual_intervals=[interval("09:10", "10:00")]), service("VAL-E3", "2026-06-03", service_type="group", actual_intervals=[interval("09:10", "10:00")])]
    rows.append(case("adjacent", "validation", "adjacent_sections", f, "Encounter VAL-E2 | June 2, 2026\nSigned group psychotherapy; actual patient contact 09:10 to 10:00.\nEncounter VAL-E3 | June 3, 2026\nSigned group psychotherapy; actual patient contact 09:10 to 10:00.\n"))
    f = service("VAL-E4", "2026-06-04", evidence_kind="clinical", actual_intervals=[interval("10:00", "10:30")], reported_minutes=35)
    rows.append(case("clockconflict", "validation", "within_document_conflict", [f], "Encounter VAL-E4 | June 4, 2026\nFinal signed individual psychotherapy: actual patient contact 10:00 to 10:30. Separately reported completed patient therapy duration: 35 minutes. Both statements remain in the signed note; no correction is indicated.\n"))
    f = service("VAL-E5", "2026-06-05", actual_intervals=[], unspecified_intervals=[interval("14:00", "14:50")], reported_minutes=40)
    rows.append(case("headerclock", "validation", "unqualified_header_clock", [f], "Encounter VAL-E5 | June 5, 2026 | 14:00 to 14:50\nFinal signed individual psychotherapy. Patient participated; completed patient therapy duration was 40 minutes. The header interval is unqualified and is not an actual contact attestation.\n"))
    f = dict(kind="assessment", instrument="PHQ-9", assessment_date="2026-06-02", form_ref="VAL-Q6", score=11, reporter="Measure Example", experiencer="Measure Example", copied=True)
    rows.append(case("measure", "validation", "receipt_completion", [f], "Import receipt June 6, 2026\nCopied PHQ-9 form VAL-Q6: completed by Measure Example on June 2, 2026, total 11. June 6 is the filing date. No new questionnaire or visit.\n"))
    f = service("VAL-E7", "2026-06-08", service_type="collateral", patient_present=False, delivered=False)
    rows.append(case("collateral", "validation", "professional_contact", [f], "Encounter VAL-E7 | June 8, 2026\nSigned collateral consultation with the partner only; patient absent throughout. This entry records service classification only, with no symptom or function report. No patient psychotherapy or patient-contact minutes were provided.\n"))
    f = dict(kind="plan", plan_ref="VAL-P8", effective_start="2026-06-08", effective_end="2026-06-26", required_days=2, required_minutes=95, service_types=["individual","group"], week_basis="monday_sunday", signed=True)
    rows.append(case("numericplan", "validation", "quantitative_weekly", [f], "Signed treatment plan VAL-P8, effective June 8 through June 26, 2026: at least two therapy days and 95 patient-present minutes per Monday-Sunday week. Only individual and group psychotherapy count. No other clinical statements.\n"))
    f = [observation("2026-06-09", "function", "Tense Example", "Tense Example", temporality="historical", keywords=["avoid"]), observation("2026-06-09", "function", "Tense Example", "Tense Example", temporality="planned", keywords=["call"])]
    rows.append(case("tense", "validation", "history_vs_intention", f, "June 9, 2026: Tense Example reports having avoided telephone calls last winter. Tense Example plans to make one telephone call tomorrow; it has not been attempted. No service took place.\n"))

    # Sealed template families use independently authored facts and distinct
    # organization, layout and clinical structures. Do not inspect results before
    # the candidate freeze recorded by the runner.
    f = service("TEST-E1", "2026-07-02", service_type="family", actual_intervals=[interval("16:07", "16:39")], reported_minutes=32)
    rows.append(case("letter", "sealed", "narrative_letter", [f], "Final signed correspondence, July 2, 2026\nI certify the family therapy encounter TEST-E1. Although the partner arrived earlier, the patient's therapeutic participation began at 16:07 and ended at 16:39. I recorded 32 minutes of patient therapy.\n"))
    f = [service("TEST-E2", "2026-07-03", actual_intervals=[interval("09:05", "09:25")], reported_minutes=20), service("TEST-E3", "2026-07-03", actual_intervals=[interval("11:10", "11:35")], reported_minutes=25)]
    rows.append(case("twovisits", "sealed", "two_same_day_visits", f, "July 3, 2026 / Final signed individual psychotherapy logs\nTEST-E2 -- patient contact 09:05 to 09:25, 20 minutes.\nTEST-E3 -- a separate appointment, patient contact 11:10 to 11:35, 25 minutes.\n"))
    f = service("TEST-E4", "2026-07-06", service_type="group", evidence_kind="attendance", actual_intervals=[interval("10:06", "11:02")])
    rows.append(case("vertical", "sealed", "vertical_roster", [f], "Final signed attendance\nDate = July 6, 2026\nEncounter = TEST-E4\nService = group psychotherapy\nPatient arrived = 10:06\nPatient departed = 11:02\nStatus = attended, treatment delivered\n"))
    f = service("TEST-E5", "2026-07-07", evidence_kind="schedule", signed=False, patient_present=False, delivered=False, scheduled_intervals=[interval("15:00", "15:45")])
    rows.append(case("cancelphone", "sealed", "previsit_cancel", [f], "Desk log, unsigned, July 7, 2026\nIndividual appointment TEST-E5 reserved 15:00 to 15:45. Cancelled by patient before the start. Administrative phone message only; patient never attended and no therapeutic service occurred.\n"))
    f = dict(kind="relationship", relation="corrects", signed=True, target_encounter="TEST-E6", target_document_ref="ORIGINAL-D6", target_plan_ref=None, field="minutes", replacement_time=None, replacement_minutes=28, replacement_presence=None, original_time=None, service_date="2026-07-08")
    rows.append(case("erratum", "sealed", "duration_erratum", [f], "Final signed erratum dated July 9, 2026\nFor the July 8 encounter TEST-E6 recorded in ORIGINAL-D6, replace the stated completed patient therapy duration with 28 minutes. This corrects only minutes and records no new service.\n"))
    f = dict(kind="assessment", instrument="GAD-7", assessment_date="2026-07-10", form_ref=None, score=9, reporter="Envelope Example", experiencer="Envelope Example", copied=False)
    rows.append(case("envelope", "sealed", "measurement_envelope", [f], "Scanned envelope received July 14, 2026\nEnclosed original questionnaire: GAD-7, self-completed by Envelope Example July 10, 2026, score nine. The original has no form identifier. Filing occurred July 14 and is not a new completion or treatment encounter.\n"))
    f = [observation("2026-07-15", "safety", "Parent", "Negation Example", "absent", keywords=["suicid"]), observation("2026-07-15", "symptom", "Parent", "Negation Example", keywords=["sleep"])]
    rows.append(case("negation", "sealed", "quoted_parent_report", f, 'July 15, 2026 / Parent statement\nParent says: "Negation Example has no suicidal thoughts, but Negation Example is still losing sleep." No visit or therapy is documented.\n'))
    f = service("TEST-E8", "2026-07-16", patient_present=None, delivered=None, evidence_kind="draft", signed=False, scheduled_intervals=[interval("12:00", "12:45")])
    rows.append(case("unfinalized", "sealed", "unsigned_ambiguous_template", [f], "Unsigned draft for individual appointment TEST-E8 on July 16, 2026, booked 12:00 to 12:45. Attendance field and clinical content are blank. There is no evidence establishing whether patient contact occurred.\n"))
    rows.append(case("mailing", "sealed", "mailing_metadata", [], "Clerical update July 17, 2026: mailing preference changed to electronic delivery. No service, symptoms, assessment, treatment plan or clinical action is described.\n"))
    f = service("TEST-E10", "2026-07-20", service_type="group", actual_intervals=[interval("09:00", "09:40")], breaks=[interval("09:12", "09:16")])
    rows.append(case("equipment", "sealed", "mechanical_pause", [f], "Final signed group log, July 20, 2026\nTEST-E10: patient treatment/presence 09:00 to 09:40. Equipment repair paused all treatment 09:12 to 09:16. No intervention, discussion or therapeutic activity was conducted in that pause.\n"))
    for row in rows:
        # Independently verify that literals in gold survived rendering. Dates
        # spelled in prose are manually reviewed above, clocks must be exact.
        for fact in row["facts"]:
            for field in ("encounter_ref", "appointment_ref", "target_encounter", "target_document_ref", "form_ref", "plan_ref"):
                if fact.get(field):
                    assert fact[field] in row["text"], (row["id"], field)
            for field in ("actual_intervals", "scheduled_intervals", "unspecified_intervals", "breaks"):
                for segment in fact.get(field, []):
                    assert segment["start"] in row["text"] and segment["end"] in row["text"]
    return rows


def examples():
    header = "Patient: Dana Example | MRN: EX-P1 | DOB: 1980-04-03 | Document ID: EX-D1"
    a = "Encounter EX-E1 | 2026-02-04 | Final signed individual psychotherapy. Patient contact 10:00 to 10:25; 25 completed patient-treatment minutes."
    b = "On 2026-02-04 Dana Example reports interrupted sleep and denies current suicidal thoughts."
    f = service("EX-E1", "2026-02-04", actual_intervals=[interval("10:00", "10:25")], reported_minutes=25)
    f.update(statement="Signed individual psychotherapy", recorded_at=None); f.pop("kind")
    claims = [{"kind": "patient", "quote": header, "data": dict(patient_id="EX-P1", name="Dana Example", dob="1980-04-03", declared_id="EX-D1")}, {"kind":"service","quote":a,"data":f}]
    for category, polarity, statement in [("symptom","present","Patient reports interrupted sleep"),("safety","absent","Patient denies current suicidal thoughts")]:
        f = observation("2026-02-04", category,"Dana Example","Dana Example",polarity); f.pop("kind"); f.update(statement=statement,recorded_at=None)
        claims.append(dict(kind="observation",quote=b,data=f))
    first = dict(text=header+"\n"+a+"\n"+b,extractions=claims)
    header = "Patient: Ellis Example | MRN: EX-P2 | Document ID: EX-D2"
    a = "Encounter EX-E2 | 2026-02-05 | Signed group activity. Patient participated in group therapy. No treatment during equipment pause 09:20 to 09:28; actual attendance is documented separately."
    f = service("EX-E2", "2026-02-05",service_type="group",breaks=[interval("09:20","09:28")]); f.pop("kind"); f.update(statement="Group participation with no-treatment pause",recorded_at=None)
    second = dict(text=header+"\n"+a,extractions=[dict(kind="patient",quote=header,data=dict(patient_id="EX-P2",name="Ellis Example",dob=None,declared_id="EX-D2")),dict(kind="service",quote=a,data=f)])
    header = "Patient: Jules Example | MRN: EX-P3 | Document ID: EX-D3"
    a = "Signed amendment for encounter EX-E3 on 2026-02-06: departure corrected to 11:10, replacing 11:20. No additional service occurred."
    f = dict(statement="Departure-only correction",recorded_at=None,relation="corrects",signed=True,target_encounter="EX-E3",target_document_ref=None,target_plan_ref=None,field="departure",replacement_time="11:10",original_time="11:20",replacement_minutes=None,replacement_presence=None,service_date="2026-02-06")
    third = dict(text=header+"\n"+a,extractions=[dict(kind="patient",quote=header,data=dict(patient_id="EX-P3",name="Jules Example",dob=None,declared_id="EX-D3")),dict(kind="relationship",quote=a,data=f)])
    return [first,second,third]


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    rows = build()
    for split in ("dev", "validation", "sealed"):
        (OUT / f"{split}.json").write_text(json.dumps([r for r in rows if r["split"]==split], indent=2), encoding="utf-8")
    target = ROOT / "src/clinical_intelligence/contracts/luna_documents.json"
    target.write_text(json.dumps(examples(),indent=2),encoding="utf-8")
    print({split:sum(r['split']==split for r in rows) for split in ('dev','validation','sealed')})
