# Luna 抽取优化：最终交付摘要

结论：`clinical_partition` 是在本轮数据、请求模型与已测试设计范围内，按临床事实覆盖和关系正确优先选出的方案。它不在所有指标上领先，也不是临床验证。请求模型为 `gpt-6-luna`、reasoning `high`，CLI 0.159.3；实际后端模型快照不可获取。

## 实现与程序修复

默认抽取采用 Pydantic 派生的 typed object schema、完整文档示例、可逆行段 ID、身份对象、标识清单和临床语义规则。第一次抽全部事实，第二次仍读取完整原文、只抽 observation，并替换第一轮的 observation；实际运行校验失败最多修复一次。代码负责 offset、时间换算、区间、跨文档合并和查询。不会依据 gold 重试或挑选答案。

公共程序修复包括显式 patient/document/encounter 标识校验、服务漏抽检查、合法 offset 的重复引用上下文验证、拒绝被忽略的参数，以及将 provider/schema/adapter/CLI 等版本纳入缓存身份。缺失日期、分数和未决更正保留不确定性。这些收益不能归因于 prompt；公平对照使用相同校验、计算与 `critical-fields-9` 评分逻辑。原始任务 oracle 外置到忽略目录，不随软件分发。

## 主要实验与最终比较

共探索 42 个配置：字符串与 typed 契约、片段与文档示例、引用与行段 ID、身份结构、语义规则、拆分、校验修复、复核、等预算重采样及不同 reasoning。typed schema 单独没有稳定提升；匹配的完整示例、身份和语义规则组合更有效。全量复核、增强 reasoning、不同 partition 和额外字段说明未带来稳定增益，按收敛要求停止继续迭代。

| 三次真实重复 | baseline | 最终方案 | 等预算重采样对照 |
|---|---:|---:|---:|
| 原始任务 31 文档完整正确 | 63/93 | 90/93 | 92/93 |
| 新合成 24 文档完整正确 | 58/72 | 71/72 | 71/72 |
| 公开 8 文档完整正确 | 17/24 | 24/24 | 24/24 |
| 独立临床覆盖断言 | 63/81 | 76/81 | 74/81 |
| 中位延迟（秒） | 12.40 | 20.16 | 27.54 |

等预算对照始终采用第二次抽取、最多一次校验修复，不是人工择优。最终方案的选择侧重临床覆盖与延迟；这些相关样本不支持显著性或全面优越性的结论。原始任务、公开小样例和新合成材料分别统计。

19 个困难案例各做十次独立真实重复：原始 8 文档完整正确从 53/80 提升到 72/80；新合成 10 文档从 93/100 到 100/100；公开活动文档从 2/10 到 10/10。重复不能代替不同案例的泛化证据。

## 独立封存测试与限制

冻结后才调用的 10 个新模板/患者，三次重复中完整正确 baseline 19/30、最终 21/30；查询正确 25/30、27/30。最终 9 个 strict 失败集中于取消电话、未定稿和签署信件三个模板。前两者将 appointment 标签标为 encounter 的 gold 与原文不一致；第三者将签署日期视为服务日期，原文未独立建立这一关系。一轮取消电话输出另漏记录日期。保留冻结分数，不修改 gold、不删失败、不在封存后调参。因此这些分数不能证明未见临床材料的可靠性，也不能将九次失败都算作模型语义错误。公开后的 sealed fixture 只能再作回归材料。

生产默认 CLI 的真实抽取验证：公开文档 8/8、16 次调用；原始文档 27/31、64 次调用（含两次定向修复）。随后数据库缓存复用没有模型调用，不算独立重复。离线回归原版本 206 passed，包括固定响应测试；这些也不是模型质量测量。

仍未稳定消除复制/签署记录、患者在场、时间角色、关联和临床覆盖错误。精确引用及 provenance complete 不等于临床正确。系统假设单患者文档、同日 local 时间及现有类别；未验证跨午夜/时区、大规模病历或未见量表，也未实现模型生成 functional-action taxonomy。

## 具体前后对照

以下为公开合成案例的固定运行投影，未人工择优。分钟表示由代码转换。

| 原文与固定样本 | 旧输出 | 最终输出 | 错误类型与下游影响 |
|---|---|---|---|
| DEMO-ACTIVITY：`Facilitator signed LAB-G7 activity record dated 2026-04-06... equipment pause from 09:41 to 09:49.`；final-confirmation-v13 repeat-01 | encounter_ref=null，break=[581,589] | encounter_ref=LAB-G7，同一 break | 无标签 ID 遗漏；休息不能归入正确 encounter。最终关联 break，整组保留更正后的 71 分钟及真实冲突 |
| robust-1：签署个人治疗 20 分钟，有 DOB，未给治疗日期；missing-date-before / 最终 repeat-01 | non-nullable 候选猜 2026-03-01；诚实 null baseline 被 Pydantic 拒绝 | service_date=null，保留 20 分钟事实 | 表示限制/时间角色；本轮期间贡献 0..20，不冒称已知日期。此收益属于公共表示修复，非单独 prompt 收益 |
| robust-7：原始 PHQ-9，完成 2026-08-08，total score 留白 | baseline null score 被拒绝；旧 typed 候选漏整项量表 | 日期保留，score=null；query score_options=[] | 遗漏/表示限制；不制造零分或虚假分数变化 |
| robust-8：`No patient contact...` 的地址格式行政记录；final-confirmation-v13 repeat-01 | 旧 validator 误触发 service 必需，repair 候选可制造行政 service | 此次仍多抽一条 administrative service；后续 stability-v13 固定十次全部正确为空 claims | 程序否定 cue 已修复，模型无目标误抽仍偶发；不能只展示空输出成功样本 |
| sealed negation：`Parent says ... has no suicidal thoughts ... still losing sleep.`；固定 repeat-02 | baseline 内部 observation 缺必需字段，校验失败 | safety/absent/current 与 symptom/present/current 两条，reporter=parent、experiencer=patient | 解析后契约/主体/否定；typed 契约和专项临床抽取保留两种不同 assertion |
| sealed letter：信件签署日期和已完成治疗时钟，但未单列治疗日期 | service_date=null | service_date=null | 未改善的日期歧义与 gold 问题；最终输出仍是 0..32，保留失败而非选一个日期 |

## 调用记录与数据边界

29 个本地运行目录保留 4250 个 runner 任务；5826 次 CLI 尝试，5825 次生成可见 usage，另一次 sandbox 失败无 usage。累计 input 118,739,782 tokens（其中 cached input 37,597,952），output 6,092,364（reasoning 2,775,914 是其子集）。累计各调用耗时 68,728.11 秒，是并行调用求和，不是墙钟时间。费用不可获取。不是单文档 45k 限制。

机器可读聚合见 [luna-results-summary.json](luna-results-summary.json)。完整候选与失败登记、原始输入、完整 gold、请求响应和数据库保留本地忽略目录。发布不包含这些材料。模型子进程只读取原文、通用说明及配置示例；gold 和评分仅在父进程使用。

发布整理后的离线回归为 **206 passed**；移除一个仅针对淘汰字符串候选的参数化测试，并新增私有 oracle 必须匹配完整文档组的行为测试。公开八文档、两个 pass 共 16 对 prompt/schema 与真实测量版本逐一哈希相等。

## 复现

按 README 安装锁定依赖，认证本地 Codex；以下从仓库根目录运行。独立运行使用新 run 名和数据库，旧 run 名只断点恢复。每请求超时 180 秒，传输错误最多三次，退避 5/15 秒；所有请求均记账。

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m clinical_intelligence --db artifacts/best.sqlite process --input examples/synthetic/documents
.\.venv\Scripts\python.exe tools/validate_live.py artifacts/best.sqlite
.\.venv\Scripts\python.exe tools/luna_experiment.py --run public-repeat-01 --candidates baseline clinical_partition semantic_resample --splits public dev validation original --private tests/fixtures/luna/robustness.json --repeat 3 --workers 6
.\.venv\Scripts\python.exe tools/analyze_luna.py public-repeat-01 --private tests/fixtures/luna/robustness.json --revalidate
# sealed 已公开；这是回归重跑，不再是新的独立封存测试
.\.venv\Scripts\python.exe tools/luna_freeze.py --candidates baseline clinical_partition --output artifacts/sealed-freeze.json
.\.venv\Scripts\python.exe tools/luna_experiment.py --run sealed-regression-01 --candidates baseline clinical_partition --splits sealed --repeat 3 --workers 6 --freeze artifacts/sealed-freeze.json --allow-sealed
```

`--extractor baseline` 使用历史 prompt/schema 和相同公共程序修复，可回退抽取设计。dev/validation/sealed 按患者及模板家族隔离；先建事实和 gold 再生成合成文本。公开 fixtures、独立查询 oracle、runner 和 scorer 可直接复现公开评测；原始任务复现需要另行有权取得的原文与 reviewed annotations，不包含在软件里。

私有数值 oracle 可置于 `artifacts/luna-private/query_oracles.json`：按 group 键记录 `sample_ids` 与 `utilization`；只有样本集合完整相等才评分。临床查询可提供 `instrument` 与 `assessments`（各含 `date`、`scores`）。额外临床事实放在 `artifacts/luna-private/clinical_supplement.json`。这些只进入离线评分。manifest 记录代码、数据与配置 hash、模型/CLI、重复及缓存策略；请求目录保存 prompt/schema、CLI events、响应、usage、延迟和失败信息。切勿将 artifacts 提交到 GitHub。
