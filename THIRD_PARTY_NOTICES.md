# Third-party dependencies and notices

Reviewed 2026-10-06 against `pyproject.toml`, all **65** entries in `requirements.lock`, and the corresponding installed distribution metadata/license files. This is a source-only submission: third-party library source, wheels, the Python interpreter, and the Codex executable are not bundled or modified. Installations retain each dependency's own packaged license files. The summaries below do not replace those licenses.

## Direct dependencies and external tools

| Component | Version | License | Use in this prototype |
|---|---|---|---|
| [Pydantic](https://pypi.org/project/pydantic/2.13.5/) | 2.13.5 | MIT | Our domain schemas, validation, and JSON persistence boundaries. |
| [LangExtract](https://pypi.org/project/langextract/1.7.0/) | 1.7.0 | Apache-2.0; additional HAI-DEF terms for health applications | Extraction prompting, structured-output parsing, and source alignment, isolated behind our extractor. |
| [intervaltree](https://pypi.org/project/intervaltree/3.2.1/) | 3.2.1 | Apache-2.0 | Interval union/overlap behind our temporal utility. |
| [pytest](https://pypi.org/project/pytest/9.1.1/) | 9.1.1 | MIT | Development/evaluation tests. |
| [setuptools](https://pypi.org/project/setuptools/80.10.2/) | 80.10.2 | MIT | Build backend pinned separately in `pyproject.toml`; resolved by isolated builds. |
| [SQLite core](https://www.sqlite.org/copyright.html) | Python-bundled; reported by benchmark | Public domain | Persistent registry, claims, and clinical abstraction through `sqlite3`. |
| [Python](https://docs.python.org/3/license.html) | Tested with 3.12.14; project requires >=3.12 | PSF license and included component notices | Standard-library ingestion, hashing, CLI, subprocess, timing, and storage support. |
| [OpenAI Codex CLI](https://github.com/openai/codex/blob/rust-v0.159.3/LICENSE) | Actual extraction 0.159.3; PATH preflight 0.160.0 | Apache-2.0 for CLI code; hosted-service terms are separate | External model provider invoked as a local process; not a Python dependency. |

Pydantic and pytest are established validation/testing dependencies; intervaltree supplies tested interval operations. LangExtract 1.7.0 is a recent pinned release, its contribution guidance requires tests, and it is not an officially supported Google product. Our adapter contains its types and provider interface so it can be replaced without changing clinical logic. These choices favor tested infrastructure while retaining custom reconciliation and arithmetic in this repository. [LangExtract release and disclaimer](https://pypi.org/project/langextract/1.7.0/), [contribution/testing guidance](https://github.com/google/langextract/blob/v1.7.0/CONTRIBUTING.md)

## Choice and replacement cost

These are engineering judgments and estimates, not measured implementation times.

| Selected component | Alternative | Replacement burden and reason to retain it |
|---|---|---|
| Pydantic | Standard-library dataclasses plus validators/serialization | Several hours initially, with ongoing schema validation work; boundary validation is central here. |
| LangExtract | An isolated structured-output provider plus exact span checking | Moderate for short notes; larger for alignment diagnostics/chunking. Health terms and install footprint require production review. |
| intervaltree | A sorted interval sweep | Low for union alone; retaining tested merge/chop operations limits temporal mistakes. Its sortedcontainers dependency has an older release, so used operations were tested on the target interpreter. |
| pytest | Standard-library unittest | Low porting effort, with more verbose parameterization and fixtures. |
| SQLite | Retain Python's bundled sqlite3 | No dependency removal needed; production changes should follow measured query/concurrency needs. |
| Codex CLI provider | Another isolated model transport | Transport replacement is local to the adapter; authentication, usage measurement and semantic extraction require revalidation. No alternative service is used by this prototype. |

The current environment passed `pip check`, actual extraction and the regression suite.
This establishes prototype compatibility, not a complete production dependency or
clinical validation review.

## LangExtract health-use terms

The upstream project explicitly subjects health-related applications to the [Health AI Developer Foundations Terms of Use](https://developers.google.com/health-ai-developer-foundations/terms), in addition to Apache-2.0. The incorporated [Prohibited Use Policy](https://developers.google.com/health-ai-developer-foundations/prohibited-use-policy) also applies.

Required upstream notice:

> HAI-DEF is provided under and subject to the Health AI Developer Foundations Terms of Use found at https://developers.google.com/health-ai-developer-foundations/terms

The terms address downstream use restrictions, provision of the agreement, modification notices, regulatory authorization where applicable, and indemnification. Their distribution definition includes hosted functionality. This prototype supplies original application source that imports an unmodified dependency; it does not vendor LangExtract code or wheels. The links and notice document the dependency's terms without bundling a duplicate library or presenting a rewritten license. A future binary/container distribution or hosted product must preserve full upstream licenses/notices and review the HAI-DEF distribution obligations. [HAI-DEF agreement](https://developers.google.com/health-ai-developer-foundations/terms)

## Provider and service terms

The provider uses the **local Codex CLI with `gpt-6-luna`**. The CLI process is local; model inference is supplied by OpenAI's hosted service using the operator's own existing sign-in. Credentials and user configuration are not distributed in this submission.

The CLI's Apache-2.0 license covers its code, not model weights, hosted inference rights, or a subscription. Its pinned upstream [LICENSE](https://github.com/openai/codex/blob/rust-v0.159.3/LICENSE) and [NOTICE](https://github.com/openai/codex/blob/rust-v0.159.3/NOTICE) remain with an independently installed CLI. Hosted use is governed by the applicable [OpenAI Terms of Use](https://openai.com/policies/terms-of-use/) or [OpenAI Services Agreement](https://openai.com/policies/services-agreement/), together with applicable service policies and the operator's plan.

Recorded CLI usage is reported as tokens/calls when the CLI supplies it. Actual billed USD cost is unavailable. Subscription usage and API token pricing are separate, so API prices are not used to claim the cost of these subscription-authenticated extractions. [Official OpenAI pricing guidance](https://learn.chatgpt.com/docs/pricing)

**Google GenAI and Google Cloud packages are transitive dependencies of LangExtract's base install. They do not serve this prototype's extraction calls.** LangExtract also installs NumPy/pandas and HTTP/utility packages that our clinical calculation code does not require directly. This increases installation footprint; it is recorded rather than hidden by an incomplete lock. No Gemini credentials or Google extraction integration are supplied.

## Transitive license details

- **certifi 2026.7.22:** MPL-2.0, including its certificate bundle. Retain the unmodified package and its notices. [Maintainer license metadata](https://github.com/certifi/python-certifi/blob/master/setup.py)
- **tqdm 4.70.1:** MPL-2.0 AND MIT, with contributor/file-specific notices in its packaged `LICENCE`. [Pinned package](https://pypi.org/project/tqdm/4.70.1/)
- **regex 2026.9.29:** Apache-2.0 AND CNRI-Python; its packaged license explains the inherited CPython code and separately licensed additions. [Pinned package](https://pypi.org/project/regex/2026.9.29/)
- **NumPy 2.5.3:** its package metadata lists BSD-3-Clause, 0BSD, MIT, Zlib, and CC0-1.0 components. The inspected Windows wheel's `numpy-2.5.3.dist-info/licenses/LICENSE.txt` additionally lists OpenBLAS/LAPACK and a GCC runtime library under **GPL-3.0-or-later WITH GCC-exception-3.1**. That runtime exception matters; this is not a GPL application library deliberately added to clinical code. Any future redistribution of numerical wheels must preserve the complete wheel license directory, not just NumPy's top-level BSD summary. [Pinned NumPy distribution](https://pypi.org/project/numpy/2.5.3/)

The installed environment is therefore not described as exclusively permissive. These are identified transitive terms; the current artifact does not redistribute the installed wheels. Production review should operate on the actual target-platform distributions and service arrangement.

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
| [langextract](https://pypi.org/project/langextract/1.7.0/) | 1.7.0 | Apache-2.0; health-use terms above |
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
