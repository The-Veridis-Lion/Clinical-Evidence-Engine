# Third-party notices

This repository distributes original application code, not dependency source, wheels,
model weights, the Python interpreter, or the external Codex executable. PolyForm
applies only to original material owned by The-Veridis-Lion; it does not relicense dependencies.
The inventory below was retained from the installed locked-distribution audit and
rechecked against the local installed metadata during preparation. Package license
files remain with independently installed distributions. Retain full upstream licenses,
copyright and NOTICE files when distributing dependencies; summaries are not replacements.

Direct dependencies: Pydantic (MIT), LangExtract (Apache-2.0 and health-use terms),
intervaltree (Apache-2.0). pytest and setuptools are MIT. Python uses PSF and component
licenses; SQLite core is public domain. Codex CLI is independently installed under
Apache-2.0; hosted inference has separate service terms and operator authentication.

## LangExtract health-use notice

HAI-DEF is provided under and subject to the Health AI Developer Foundations Terms of Use found at https://developers.google.com/health-ai-developer-foundations/terms

LangExtract's upstream LICENSE subjects health-related applications to those terms
and their incorporated prohibited-use policy, in addition to Apache-2.0.
See https://github.com/google/langextract/blob/v1.7.0/LICENSE and
https://developers.google.com/health-ai-developer-foundations/prohibited-use-policy.
Future dependency redistribution or hosting requires reviewing the actual distributions
and applicable agreement, preserving notices and any required modification notices.
No HAI-DEF model weights or LangExtract source are bundled or modified here.

## Component obligations

certifi includes MPL-2.0 material; tqdm includes MPL-2.0 and MIT; regex includes
Apache-2.0 and CNRI-Python. The installed NumPy Windows wheel includes component
licenses and a GCC runtime under GPL-3.0-or-later WITH GCC-exception-3.1.
Preserve complete wheel license directories for redistribution. The environment is
not exclusively permissive. Google packages are LangExtract transitive dependencies;
the retained provider uses Codex, not Google inference.

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
