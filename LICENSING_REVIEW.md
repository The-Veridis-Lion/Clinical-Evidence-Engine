# Licensing and medical-boundary review

Reviewed on October 18, 2026 against public `main` commit
`b1af6797130a6673cd6c26aac9fd8750873bdab3`. This is an engineering review with
explicit unresolved legal questions, not a legal opinion or a compliance certificate.

## License decision

Recommend the unmodified **Apache License 2.0** for original material once the
rights holder confirms authority to relicense it. It is
[OSI approved](https://opensource.org/license/apache-2.0), permits commercial use,
and includes an express contributor patent grant, patent-litigation termination,
warranty disclaimer and liability limitation. Its attribution and redistribution
requirements are familiar to enterprise evaluators. Its protections have legal
limits; it does not promise immunity or grant clinical authorization.

MIT is another familiar permissive option but has no comparable express patent
grant. A custom medical restriction attached to Apache would complicate the grant
and should not be described as standard Apache. Medical safety belongs in the
intended-use guidance and relevant deployment controls.

**No relicensing was performed.** The existing root, product and verifier licenses
and package license identifiers remain PolyForm Noncommercial 1.0.0. PolyForm is
source-available with a noncommercial-purpose restriction, rather than OSI-approved
open source. Its scope may complicate enterprise evaluation; do not promise that
every internal evaluation is licensed, or that every enterprise use is prohibited.
The actual purpose and any separately granted permission matter.

The history contains two author email identities under The-Veridis-Lion, which
supports attribution but does not prove employment, assignment or contribution
rights. The imported Gemini-designed frontend already has Apache-2.0 SPDX headers;
those were preserved. Its upstream provenance/permission record is not supplied
in the published frontend README. A blanket replacement could misstate these
mixed scopes. The existing copyright notice is preserved, without inventing a
new owner or agreement.

Before migration, the maintainer should confirm rights in original code and
documentation (including employer/client rights and any external contributions),
record the frontend origin and permissions, and resolve third-party exceptions.
Then replace only the authorized project license copies with the standard Apache
text, update all three Python package identifiers and README/NOTICE scope, preserve
upstream notices and data exceptions, and identify the first Apache release.
Existing recipients' grants under earlier releases are not erased by a new release.

## LangExtract: code, documentation and model terms

Both product locks pin LangExtract 1.7.0. Its
[tagged LICENSE](https://github.com/google/langextract/blob/v1.7.0/LICENSE)
contains Apache 2.0. A local installed 1.7.0 distribution was also inspected:
`License-Expression: Apache-2.0`, with an Apache license file. However, its packaged
README metadata and [tagged README](https://github.com/google/langextract/blob/v1.7.0/README.md#disclaimer)
also refer health-related applications to Google's HAI-DEF terms. The previous
notices incorrectly attributed that statement to the LICENSE itself.

The [HAI-DEF terms](https://developers.google.com/health-ai-developer-foundations/terms)
define covered models/services and derivatives, separately address source code,
and impose conditions on covered use and distribution, including hosting. Their
[prohibited-use policy](https://developers.google.com/health-ai-developer-foundations/prohibited-use-policy)
includes automated decisions affecting healthcare and insurance rights or wellbeing.
Where these agreements apply, the operator must satisfy their actual restrictions;
a warning or nominal review button does not establish compliance.

The launcher selects Codex CLI or the OpenAI API, not HAI-DEF weights. No such
weights were identified in the published tree. Importing LangExtract does not by
itself establish that all original project code, all outputs or unrelated models
inherit HAI-DEF restrictions. Conversely, the README reference must not be ignored:
its contractual applicability to this health-related library use remains a legal
confirmation item, especially before external hosting or clinical deployment.
Neither universal applicability nor a definitive exemption is asserted here.

## Third-party distribution findings

- The repository ships a compiled React interface. The previous claim that no
  dependency code was distributed was inaccurate for this frontend. Runtime React,
  React DOM, Scheduler and Lucide/Feather license texts are now retained with the
  frontend, together with Tailwind's license. The production UI links to that file;
  Python package data includes it. Build tools have separate licenses and are not
  all shipped merely because they appear in the npm lock.
- Existing Python inventories remain historical declared/component-license
  summaries, not an exhaustive legal clearance. MPL components, optional Unidecode
  GPL obligations, and platform wheel runtime exceptions need distribution-specific
  review if dependencies are bundled. Merely installing them does not automatically
  relicense every original project file. No dependency versions or runtime choices
  were changed for this review.
- ACI-BENCH attribution, HPO ontology notices and license, and Synthea source
  provenance remain applicable where their material is present. Attribution alone
  does not prove a redistribution grant. Verify the exact Synthea data archive and
  any other dataset/excerpt grants before republishing them; software, terminology,
  datasets and model weights have separate rights. No new grant is invented.
- Provider service terms and data-processing arrangements depend on the actual
  configured account, service and deployment; neither PolyForm nor a future Apache
  release replaces those agreements.

## Safety implementation scope

[MEDICAL_USE.md](MEDICAL_USE.md) separates intended-use responsibilities from legal
license conditions and implemented controls. Clinical drafts and CareFlow reports
now explain professional review and the documentation-only meaning of readiness.
An unconditional statement that human review was optional in a Copilot export
was narrowed to evidence preparation and demonstration.

Existing source checks, immutable packet history and review-versus-readiness
separation were retained. No new approval workflow was added: the reviewed product
does not execute prescriptions, treatment or final payer authorization. Human
credential checks, authenticated clinical sign-off and prevention of downstream
misuse are not implemented. Enterprise or clinical deployment still requires
rights clearance, data/provider review and an intended-use regulatory assessment.

## Verification evidence

Both Python requirement locks contain 65 pinned packages; all 65 names/versions
matched the existing local evaluation environment during this review. This is a
version/inventory check, not a full transitive source or vulnerability audit.
The inspected LangExtract 1.7.0 files have these SHA-256 digests:

- Packaged `licenses/LICENSE`: `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.
- Packaged `METADATA` (including the health-use reference): `f00c8eb4300ecdd8655925864f9293ecb10e0ccbc9a756053275cbb05ae85776`.

The frontend license texts were taken from installed packages at the same versions
as the npm lock, including Scheduler 0.28.0. These file checks do not prove the
origin of all project contributions or settle the legal applicability questions.

Validation for this change: 119 Copilot tests (118 in the sandbox, plus the local
HTTP test with socket access), 3 CareFlow tests and 7 verifier tests passed.
Frontend `npm run typecheck` and `npm run build` passed. A built Copilot wheel was
inspected to confirm it contains the complete frontend notice and retains the
PolyForm license identifier. Both Copilot Markdown renderers and a synthetic
CareFlow report were checked for the medical boundary; packet integrity was
preserved. The HTTP check covers notice content/type and rejects an out-of-scope
static path. No live model requests or clinical evaluation were performed.
