# Third-party notices

## ACI-BENCH dialogue-first input

The dialogue-first pilot uses the original ACI-BENCH training split from
https://github.com/wyim/aci-bench at revision
`b909b2bb9cf1d19de08df15cddde7bd0179665e4`. The upstream data is published
under Creative Commons Attribution 4.0 International (CC BY 4.0).
Original dataset files, clinical text and inference logs remain ignored local
artifacts. Selected attributed excerpts appear only in the delivery report.

Citation: Wen-wai Yim, Yujuan Fu, Asma Ben Abacha, Neal Snider, Thomas Lin,
Meliha Yetisgen. ACI-BENCH: a Novel Ambient Clinical Intelligence Dataset for
Benchmarking Automatic Visit Note Generation. Nature Scientific Data (2023).
https://doi.org/10.1038/s41597-023-02487-3 .

Original project code and documentation use Apache-2.0. Third-party libraries,
datasets, terminology and model resources retain their own licenses and terms.
The compiled workbench includes third-party frontend code. Python dependencies
are installed separately; their source, wheels and model weights are not bundled.

The package inventory summarizes declared and component licenses for the pinned
dependencies. When redistributing dependencies, include their complete upstream
licenses, copyright notices and any required NOTICE files. The summaries here do
not replace those texts.

Direct dependencies: Pydantic (MIT), LangExtract (Apache-2.0; separate health-use reference below),
intervaltree (Apache-2.0). pytest and setuptools are MIT. Python uses PSF and component
licenses; SQLite core is public domain. Codex CLI is independently installed under
Apache-2.0; hosted inference has separate service terms and operator authentication.

## Claims review example sources

The claims-review development cases are constructed synthetic engineering fixtures,
not original patient records or clinically validated benchmarks.
The small unmodified CSV slice comes from the official Synthea/SyntheticMass sample at
https://synthetichealth.github.io/downloads.html. Archive and original-row provenance
are preserved in examples/claims_review/synthea/source_manifest.json. The wrapper request
is separately labeled constructed_synthetic and does not alter original clinical values.
This attribution does not invent a data-license grant or relicense upstream material.

Suggested source citation: Jason Walonoski et al., "Synthea: An approach, method, and
software mechanism for generating synthetic patients and the synthetic electronic health
care record," Journal of the American Medical Informatics Association 25(3), 2018,
230–238, https://doi.org/10.1093/jamia/ocx079.

CMS full documents, code tables and CPT descriptions are not bundled;
the draft registry retains links and limited paraphrases.

## LangExtract code license and health-use reference

LangExtract 1.7.0's LICENSE is Apache-2.0. Its README (also included in installed
package metadata) separately refers health-related applications to HAI-DEF terms.
The health-use reference is not text in the Apache LICENSE:
https://github.com/google/langextract/blob/v1.7.0/LICENSE
https://github.com/google/langextract/blob/v1.7.0/README.md#disclaimer

The HAI-DEF agreement defines covered models/services and derivatives and has
use/distribution requirements, including hosting, where applicable:
https://developers.google.com/health-ai-developer-foundations/terms
https://developers.google.com/health-ai-developer-foundations/prohibited-use-policy

The launcher uses Codex CLI or OpenAI API inference; no HAI-DEF weights are bundled.
The library's Apache license and its README's health-use reference have distinct
scopes. Use of the library does not by itself relicense original project code
under model-use terms. Operators should assess how the referenced agreements
apply to their chosen integration before clinical use or external hosting, and
retain applicable upstream agreements and notices. Project medical-use guidance
is separate from these third-party obligations.

## Component obligations

certifi includes MPL-2.0 material; tqdm includes MPL-2.0 and MIT; regex includes
Apache-2.0 and CNRI-Python. The installed NumPy Windows wheel includes component
licenses and a GCC runtime under GPL-3.0-or-later WITH GCC-exception-3.1.
Preserve complete wheel license directories for redistribution. The environment is
not exclusively permissive. Google packages are LangExtract transitive dependencies;
the current launcher selects Codex CLI or the OpenAI API, not Google inference.

## Exact locked package inventory

License expressions below come from the pinned installed metadata, with generic classifiers clarified from packaged licenses where needed. Each package link identifies the exact upstream release. `AND` preserves cumulative component terms; `OR` preserves upstream license choice.

| Package | Version | Declared/component license |
|---|---|---|
| [absl-py](https://pypi.org/project/absl-py/2.5.0/) | 2.5.0 | Apache-2.0 |
| [aiohappyeyeballs](https://pypi.org/project/aiohappyeyeballs/2.7.1/) | 2.7.1 | PSF-2.0 |
| [aiohttp](https://pypi.org/project/aiohttp/3.14.4/) | 3.14.4 | Apache-2.0 AND MIT |
| [aiosignal](https://pypi.org/project/aiosignal/1.4.0/) | 1.4.0 | Apache-2.0 |
| [annotated-types](https://pypi.org/project/annotated-types/0.8.0/) | 0.8.0 | MIT |
| [anyio](https://pypi.org/project/anyio/4.15.1/) | 4.15.1 | MIT |
| [async-timeout](https://pypi.org/project/async-timeout/5.0.1/) | 5.0.1 | Apache-2.0 |
| [attrs](https://pypi.org/project/attrs/26.1.0/) | 26.1.0 | MIT |
| [certifi](https://pypi.org/project/certifi/2026.7.22/) | 2026.7.22 | MPL-2.0 |
| [cffi](https://pypi.org/project/cffi/2.1.1/) | 2.1.1 | MIT-0 |
| [charset-normalizer](https://pypi.org/project/charset-normalizer/3.5.2/) | 3.5.2 | MIT |
| [colorama](https://pypi.org/project/colorama/0.4.6/) | 0.4.6 | BSD-3-Clause |
| [cryptography](https://pypi.org/project/cryptography/50.0.2/) | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| [distro](https://pypi.org/project/distro/1.9.0/) | 1.9.0 | Apache-2.0 |
| [exceptiongroup](https://pypi.org/project/exceptiongroup/1.3.1/) | 1.3.1 | MIT |
| [frozenlist](https://pypi.org/project/frozenlist/1.8.0/) | 1.8.0 | Apache-2.0 |
| [google-api-core](https://pypi.org/project/google-api-core/2.41.0/) | 2.41.0 | Apache-2.0 |
| [google-auth](https://pypi.org/project/google-auth/2.60.0/) | 2.60.0 | Apache-2.0 |
| [google-cloud-core](https://pypi.org/project/google-cloud-core/2.8.0/) | 2.8.0 | Apache-2.0 |
| [google-cloud-storage](https://pypi.org/project/google-cloud-storage/3.16.0/) | 3.16.0 | Apache-2.0 |
| [google-crc32c](https://pypi.org/project/google-crc32c/1.9.0/) | 1.9.0 | Apache-2.0 |
| [google-genai](https://pypi.org/project/google-genai/2.28.0/) | 2.28.0 | Apache-2.0 |
| [google-resumable-media](https://pypi.org/project/google-resumable-media/2.11.0/) | 2.11.0 | Apache-2.0 |
| [googleapis-common-protos](https://pypi.org/project/googleapis-common-protos/1.75.5/) | 1.75.5 | Apache-2.0 |
| [h11](https://pypi.org/project/h11/0.16.0/) | 0.16.0 | MIT |
| [httpcore](https://pypi.org/project/httpcore/1.0.9/) | 1.0.9 | BSD-3-Clause |
| [httpx](https://pypi.org/project/httpx/0.28.1/) | 0.28.1 | BSD-3-Clause |
| [idna](https://pypi.org/project/idna/3.20/) | 3.20 | BSD-3-Clause |
| [iniconfig](https://pypi.org/project/iniconfig/2.3.0/) | 2.3.0 | MIT |
| [intervaltree](https://pypi.org/project/intervaltree/3.2.1/) | 3.2.1 | Apache-2.0 |
| [langextract](https://pypi.org/project/langextract/1.7.0/) | 1.7.0 | Apache-2.0; separate health-use reference above |
| [ml_collections](https://pypi.org/project/ml-collections/1.1.0/) | 1.1.0 | Apache-2.0 |
| [more-itertools](https://pypi.org/project/more-itertools/11.1.0/) | 11.1.0 | MIT |
| [multidict](https://pypi.org/project/multidict/6.9.1/) | 6.9.1 | Apache-2.0 |
| [numpy](https://pypi.org/project/numpy/2.5.3/) | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; wheel runtime notice above |
| [opentelemetry-api](https://pypi.org/project/opentelemetry-api/1.45.1/) | 1.45.1 | Apache-2.0 |
| [packaging](https://pypi.org/project/packaging/26.3/) | 26.3 | Apache-2.0 OR BSD-2-Clause |
| [pandas](https://pypi.org/project/pandas/3.0.6/) | 3.0.6 | BSD-3-Clause |
| [pluggy](https://pypi.org/project/pluggy/1.6.0/) | 1.6.0 | MIT |
| [propcache](https://pypi.org/project/propcache/0.5.4/) | 0.5.4 | Apache-2.0 |
| [proto-plus](https://pypi.org/project/proto-plus/1.29.0/) | 1.29.0 | Apache-2.0 |
| [protobuf](https://pypi.org/project/protobuf/7.36.2/) | 7.36.2 | BSD-3-Clause |
| [pyasn1](https://pypi.org/project/pyasn1/0.6.4/) | 0.6.4 | BSD-2-Clause |
| [pyasn1_modules](https://pypi.org/project/pyasn1-modules/0.4.2/) | 0.4.2 | BSD-2-Clause |
| [pycparser](https://pypi.org/project/pycparser/3.0/) | 3.0 | BSD-3-Clause |
| [pydantic](https://pypi.org/project/pydantic/2.13.5/) | 2.13.5 | MIT |
| [pydantic_core](https://pypi.org/project/pydantic-core/2.46.5/) | 2.46.5 | MIT |
| [Pygments](https://pypi.org/project/Pygments/2.21.0/) | 2.21.0 | BSD-2-Clause |
| [pytest](https://pypi.org/project/pytest/9.1.1/) | 9.1.1 | MIT |
| [python-dateutil](https://pypi.org/project/python-dateutil/2.9.0.post0/) | 2.9.0.post0 | Apache-2.0 and BSD-3-Clause components |
| [python-dotenv](https://pypi.org/project/python-dotenv/1.2.4/) | 1.2.4 | BSD-3-Clause |
| [PyYAML](https://pypi.org/project/PyYAML/6.0.3/) | 6.0.3 | MIT |
| [regex](https://pypi.org/project/regex/2026.9.29/) | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| [requests](https://pypi.org/project/requests/2.34.2/) | 2.34.2 | Apache-2.0 |
| [six](https://pypi.org/project/six/1.17.0/) | 1.17.0 | MIT |
| [sniffio](https://pypi.org/project/sniffio/1.3.1/) | 1.3.1 | MIT OR Apache-2.0 |
| [sortedcontainers](https://pypi.org/project/sortedcontainers/2.4.0/) | 2.4.0 | Apache-2.0 |
| [tenacity](https://pypi.org/project/tenacity/9.1.4/) | 9.1.4 | Apache-2.0 |
| [tqdm](https://pypi.org/project/tqdm/4.70.1/) | 4.70.1 | MPL-2.0 AND MIT |
| [typing-inspection](https://pypi.org/project/typing-inspection/0.4.4/) | 0.4.4 | MIT |
| [typing_extensions](https://pypi.org/project/typing-extensions/4.16.0/) | 4.16.0 | PSF-2.0 |
| [tzdata](https://pypi.org/project/tzdata/2026.5/) | 2026.5 | Apache-2.0 |
| [urllib3](https://pypi.org/project/urllib3/2.8.0/) | 2.8.0 | MIT |
| [websockets](https://pypi.org/project/websockets/16.1.1/) | 16.1.1 | BSD-3-Clause |
| [yarl](https://pypi.org/project/yarl/1.25.1/) | 1.25.1 | Apache-2.0 |

`setuptools==80.10.2` is deliberately outside the runtime/test freeze: it is the pinned build-system requirement. Its official release exists, supports Python >=3.9, and declares MIT. It need not be installed in an existing environment when pip runs the build in isolation. [Exact build dependency metadata](https://pypi.org/project/setuptools/80.10.2/)

## Optional clinical rule-first experiment (2026-10-11)

The `rule-first` optional extra selects medSpaCy 1.3.1 (MIT) and spaCy 3.8.16
(MIT). Their English rules, PyRuSH sentence splitting, matchers and ConText are
used without pretrained model weights. Dependencies were installed separately
in `.work/rule-first-venv`; historical environments and locks were not changed.
Source, wheels and dependency model resources are not redistributed here.
Complete upstream licenses remain with installed distributions; the local
research archive retains the exact inventory and license-file locations.

medSpaCy requires medspacy_quickumls 3.2 even when the QuickUMLS pipeline is
disabled. Its code is MIT; the transitive Unidecode 1.4.0 component is
GPL-2.0-or-later. The environment is therefore not entirely MIT/Apache.
QuickUMLS was not instantiated, and no UMLS or SNOMED CT vocabulary database
was downloaded, selected, copied into application resources or redistributed.
Those terminology rights are independent of the Python code license.

Seven unmodified HPO term JSON responses and ontology version metadata,
retrieved through EMBL-EBI OLS4 on 2026-10-11, are included in
`clinical_intelligence/rule_first/resources`. HPO version: **2026-09-01**.
The original payloads and their source URLs are preserved. The HPO Consortium
is acknowledged; application aliases and family mappings are original
configuration stored separately and do not modify HPO vocabulary content or
logical relationships. The custom HPO ontology license requires acknowledgement
and citation, visible version/date, and preserving content/relationships.
Its full source-license HTML is retained as `resources/HPO-LICENSE.html`.
The website application's software license is a different license and is not
the ontology license applied to these records.

This service/product uses the Human Phenotype Ontology (version 2026-09-01).
Find out more at http://www.human-phenotype-ontology.org.
Citation: Gargano MA et al. The Human Phenotype Ontology in 2024: phenotypes
around the world. Nucleic Acids Research 52(D1), D1333-D1346 (2024).
https://doi.org/10.1093/nar/gkad1005.
Ontology license source: https://github.com/TheJacksonLaboratory/hpo-web/blob/main/src/app/static/resources/license/license.component.html.

No pretrained clinical weights are included. scispaCy code is Apache-2.0;
the separately inspected advertised `en_core_sci_sm` 0.5.4 weights declare
CC BY-SA 3.0 in their archive metadata and require spaCy <3.8. They were not
installed or retained. Its listed training sources (OntoNotes 5, Common Crawl,
GENIA) have independent terms; this repository does not redistribute them.
MedCAT v2 code is Apache-2.0, but no particular model pack's weights and
terminology were selected or licensed for redistribution. negspacy code is
MIT and was not installed. Libraries' code licenses do not license their
weights, training datasets or terminology resources. SimSUM remains an
existing pinned local research input; raw notes and annotations are ignored
artifacts, not bundled in this optional package. No new dataset redistribution
or licensing grant is inferred.

The table below records the exact added/resolved optional-environment packages,
including overlaps with previously documented dependencies. Existing runtime
dependency notices above continue to apply. Summary labels do not replace full
license files or component obligations. NumPy wheel runtime exceptions, certifi
MPL, regex CNRI/Apache and tqdm dual component notices must be retained with
any independently redistributed dependency distribution.

| Package | Experiment version | Code/component license summary |
|---|---|---|
| Cython | 3.1.8 | Apache-2.0 |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| PyFastNER | 1.0.10 | Apache-2.0 |
| PyRuSH | 1.0.13 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| Unidecode | 1.4.0 | GPL-2.0-or-later |
| annotated-doc | 0.0.5 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| blis | 1.3.3 | BSD-3-Clause |
| catalogue | 2.0.10 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| cloudpathlib | 0.26.0 | MIT |
| cloudpickle | 3.1.2 | BSD-3-Clause |
| colorama | 0.4.6 | BSD-3-Clause |
| confection | 1.3.3 | MIT |
| cymem | 2.0.13 | MIT |
| defusedxml | 0.7.1 | PSF-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| intervaltree | 3.2.1 | Apache-2.0 |
| joblib | 1.6.0 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| langextract | 1.7.0 | Apache-2.0 |
| loguru | 0.7.3 | MIT |
| markdown-it-py | 4.2.0 | MIT |
| mdurl | 0.1.2 | MIT |
| medspacy | 1.3.1 | MIT |
| medspacy_quickumls | 3.2 | MIT |
| medspacy_unqlite | 0.9.8 | MIT |
| murmurhash | 1.0.15 | MIT |
| nltk | 3.10.3 | Apache License, Version 2.0 |
| numpy | 2.3.5 | BSD-3-Clause; component/runtime licenses retained |
| pluggy | 1.6.0 | MIT |
| preshed | 3.0.13 | MIT |
| pydantic | 2.13.5 | MIT |
| pysbd | 0.3.4 | MIT |
| pysimstring | 1.3.0 | BSD-3-Clause |
| pytest | 9.1.1 | MIT |
| quicksectx | 0.4.1 | MIT |
| referencing | 0.37.0 | MIT |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache-2.0 |
| rich | 15.0.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| shellingham | 1.5.4 | ISC |
| smart_open | 8.0.2 | MIT |
| spacy | 3.8.16 | MIT |
| spacy-legacy | 3.0.12 | MIT |
| spacy-loggers | 1.0.5 | MIT |
| srsly | 2.5.4 | MIT |
| thinc | 8.3.13 | MIT |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typer | 0.27.3 | MIT |
| urllib3 | 2.8.0 | MIT |
| wasabi | 1.1.3 | MIT |
| weasel | 1.0.0 | MIT |
| win32_setctime | 1.2.0 | MIT |
| wrapt | 2.5.0 | BSD-2-Clause |

## Frontend licenses

The checked-in workbench JavaScript/CSS includes third-party runtime code.
React 19.3.1, React DOM 19.3.1 and Scheduler 0.28.0 use MIT; Lucide React
0.546.0 uses ISC with MIT-licensed Feather portions. Tailwind CSS 4.3.3 uses MIT.
Complete installed upstream license texts are preserved in the Copilot frontend's
`public/THIRD_PARTY_LICENSES.txt` and copied into the shipped
`static/gemini/THIRD_PARTY_LICENSES.txt`. The workbench exposes that notice.
Original frontend code uses Apache-2.0. The Apache license text is also included
in the frontend notice.

These summaries do not relicense data, models, dependencies or upstream resources.
