# CareFlow Readiness Engine — 项目方向与验收合同

本文件持续维护目标、约束、研究结论、开发计划、验证结果及未完成事项。
每轮自主开发开始前必须重读本文件，核对该轮工作是否符合方向。
更新日期：2026-10-13。所有进展以实际实现和执行结果为准。

可审核成果：[草稿 PR #4](https://github.com/The-Veridis-Lion/Clinical-Evidence-Engine/pull/4)，
base为未合并PR #3分支；独立feature分支最新实现提交`c7a8936`。尚未合并/部署，
新合同的公开文本P/R与最终保留验收仍待完成。

## 长期自主开发合同（最新用户规则，优先级高于此前过程约定）

2026-10-13本次明确授权全部四项完成工作：
1. 原始临床事实经显式请求关联、主体、时间与状态校验进入材料规则，不能仅展示context。
2. 完成既有ACI47/ACN200开发组评价；参考外额外断言也需源核查，保留原标签/分母。
3. 任务1/2和共享代码稳定后冻结代码SHA、prompt/schema/model、规则、数据/参考、
   评分脚本，再分别执行一次构造材料与公开文本保留验收，绝不迭代窥探holdout。
4. 在独立共享提交修复PR #3两条P2、推送和集成PR #4；不碰并行Copilot工作目录。
不逐步询问是否继续，完成四项才作最终验收总结。新测量基线755 passed（8.76秒），
远端#3=f91768e/#4=c4aa749；历史开发集100%仍是历史结果，不冒充本次最终验收。

不设置人为开发时长或五轮停止上限。每五轮总结只是检查点，不是停止条件。
持续完成可运行产品与冻结可靠性验收；不以研究取代交付，不要求人工审核
作为研发、测试或产品运行前置条件。这覆盖此前任何“五轮后停止”、强制人工
审核或研究优先约定。每次决策前重读本文件、[实时进度](CAREFLOW_PROGRESS.md)、
本文件决策表及相关历史实验日志。阻塞时保留成果、错误与恢复入口，不重复
无收益实验。所有修改须具备跨患者、文档、Referral/PA 与规则条件的泛化价值。

### 数据与冻结隔离

复用 [ACI-BENCH](https://github.com/wyim/aci-bench) 和
[Augmented Clinical Notes](https://huggingface.co/datasets/AGBonnet/augmented-clinical-notes)
的已有数据与抽取缓存。评估 source-supported 诊断、既往治疗、症状、功能影响、
检查结果和其他相关事实槽位。按病例组冻结 development/holdout；Augmented
Clinical Notes 至少各 200 组。相同病例、变体文档和相同内容不能跨分区。
已被研究使用的病例不能谎称“从未见过”的独立保留集；缓存是否暴露须入清单。

两个公开数据集不提供可靠的 PA 批准或完整性金标，绝不构造假保险审批参考答案。
公开文本用于证据抽取评价，明确版本材料合同、既有 Synthea 原始记录和机械
可核查事实用于 Readiness 评价，分别报告。候选运行前冻结预期状态、引用、
触发条件、病例分区和分母。保留集只在候选冻结后用于最终验收。

### Reference-first 与模型分工

Luna/high 输出先与冻结结构化参考比对；一致部分直接通过，不调用 Sol 重审。
只有差异交 Sol/high，提供原始 source、相关事实、参考标签和具体规则。
分类为 MODEL_ERROR、REFERENCE_ERROR、EQUIVALENT、BOTH_WRONG、UNRESOLVED。
自动输出差异和可泛化错误机制。原始标签、原始分数/分母、Sol 结论和修正后
辅助指标分开保存，不覆盖原金标。Sol 核查的 silver 指标不称独立医学正确率。

GPT-6.1 Sol/high 负责研发决策、争议源核查、代码策略和结果解释；GPT-6 Luna/high
负责临床抽取与批量处理。Sol 也可按风险做产品审核，但不重复检查所有已匹配项。
人类/高级 AI 均能独立读证据包，意见单独保留；没有新证据不能覆写规则状态。
不能把离线脚本输出冒充实际 Sol/Luna 调用或实际审核结论。

### 冻结的可靠性门槛

验收合同 `careflow-acceptance/2`：

| 独立指标 | 门槛 | 当前是否已测量达成 |
| --- | --- | --- |
| 冻结确定性材料集五态 macro-F1 | ≥98% | 开发312场景/2028检查为100%；最终保留未运行 |
| 缺失/冲突证据误判 Ready | 0 次 | 冻结开发集0；最终保留未运行 |
| fact/source 原文引用机械通过率 | 100% | 开发2076/2076；最终保留未运行 |
| rule ID/version/content 引用机械通过率 | 100% | 开发2340/2340；最终保留未运行 |
| API、持久审计、修改重算、回归 | 全部通过 | 最新完整837 tests passed；后续原参考可用性验证12项通过；公开临床指标仍待测 |
| source-checked 抽取辅助 Precision | ≥95% | 未测量 |
| source-checked 抽取辅助 Recall | ≥90% | 未测量 |
| Augmented Clinical Notes 分组规模 | dev≥200，holdout≥200 | 已冻结各200组；未运行保留集 |

全部分母包含失败、解析/机械验证失败、未解决项；不能用重试挑最佳语义分数。
不足时不虚报完成，继续其他有效产品功能。任何修改前冻结基线，修改后跨病例、
跨规则对照；无可验证收益回滚，同一方法连续两次无效换方向。

### 调度、重试、进度与禁止项

两个项目 Luna 全局并发≤50，使用共享 scheduler/call ledger；共享调度未建立前
每项目≤25。每文档最多 2 次额外重试，仅上游输出失败、解析失败或机械验证
失败可触发；语义不一致不能重采样。所有失败/attempt append-only，禁止覆盖。
早期研究默认零、额外研究 attempt 最多100的约束仍保留，除非用户明确覆盖；
普通产品抽取/审核分别记账，不得为规避限制重新分类。

实际运行期间每约30分钟更新 docs/CAREFLOW_PROGRESS.md，记录已实现功能、
当前规则分数与严重误判、源核查问题、Luna调用/失败/重试、Sol决策和下一项。
支持时向当前聊天发中文进度。没有持续执行或定时发送能力时明确说明并保存
恢复点，不虚构后台工作。不得自动合并、部署、购买资源或重启无收益 Prompt 优化。

上述新门槛尚未全部达成。此前“已交付”指可运行 v1 基线，不是新验收完成。

## 产品目标

基于现有 Clinical Evidence Engine 实现 Referral / Prior Authorization 的
**文档准备度**产品：独立请求 → 相关事实与材料 → 可追溯来源 → 版本化规则
→ 完整性、缺失及冲突报告 → 人类或高级 AI 审核 → 带新证据的修正与重算
→ API 与持久化审计。不得宣称自动医疗审批、保险赔付资格或完整法规合规。
至少交付一条完整 Referral 工作流，并以独立 PA 请求和规则集验证扩展性。

必须保留现有五种证据状态的语义：

| 状态 | 判定要求 |
| --- | --- |
| SUPPORTED | 可追溯、在请求范围内的支持证据 |
| NOT_SUPPORTED | 明确相反证据；缺失不等于否定 |
| INSUFFICIENT_EVIDENCE | 缺失、未知、不可用或支持不足 |
| CONFLICTED | 未解决矛盾或修正权威不明；不能选择最新记录静默解决 |
| NOT_APPLICABLE | 来源支持的明确 false 触发条件；未知不能豁免 |

新增 documentation readiness 不替换 claims-review 的历史人类审核状态，
也不把原始医疗账单 claim 视为 Referral/PA 请求。现有 NOT_EVALUATED
语义保持不变；未知规则版本必须明确失败，不能静默回退到 Ready。

## 已检查的基线与历史研究

- 主仓库：<https://github.com/The-Veridis-Lion/Clinical-Evidence-Engine>。
  main 基线 `8fcb6655411d86034b6fa53374fa14794c062e39`。
- PR #3：<https://github.com/The-Veridis-Lion/Clinical-Evidence-Engine/pull/3>，
  检查时 open/unmerged，head `f91768e303564715cf2ab962e22a51be8fe267b4`。
  本分支从该 head 建立，明确依赖其 claims_engine；没有将其合并到 main。
  复用 ArchiveIndex、同患者/encounter 索引与 SourceRow 原始 CSV provenance。
  PR 已记录 9,421 claims、26,854 charge items、465 offline tests；这些是
  **历史结果**，不是本项目的新测试结果，也不是临床准确率。
- 已检查 Claims Review 的 Contract、SourceInput、Citation、CriterionResult、
  digest、source_key、pointer、line_anchors 和 field-scoped reconcile。
  复用这些能力；新建的是请求文档 checklist，不复写 HbA1c/CMS 判断。
- PR #3 尚有两条未解决 P2 review threads：
  `claims_engine/verification.py` 全量验证遗漏 unassigned claims；
  `claims_engine/archive.py` 解压前缺少成员与总量限制。
  CareFlow 不调用 split/batch verification；归档入口必须在调用既有索引
  前增加独立边界适配，不能声称已修复 PR #3 的共享代码。
- 研究归档：<https://github.com/The-Veridis-Lion/clinical-evidence-engine-research-archive-20261013-t054502z>。
  已读 README 与 `DELIVERY_FINAL_REPORT.zh-CN.md`。历史研究未证明可靠
  泛化提升，未达到独立基准 F1≥95%；最后 100 个开发 SimSUM 文件 99 成功、
  1 次 502，全部保留在分母；原银标签 F1 83.149606%，旧缓存 83.619345%。
  这是症状提及评分，不能当作文档准备度、完整临床正确率或验收依据。
  小型合成覆盖 100% 不代表 F1=100%；缓存局部微小开发增益不是独立泛化提升。
  Phase 0 不重启，不修改已冻结研究结果。

## 技术约束与并行边界

- 独立 checkout：`careflow-readiness`；分支 `feature/careflow-readiness`。
  另一个会话在 `clinical-evidence-copilot`，不读写其未提交成果。
- 新代码限定 `src/clinical_intelligence/careflow/`，专属 tests、examples、docs。
  不修改共享抽取提示、规则、claims indexing、provenance 或冲突算法。
- Python 3.12+，复用项目锁定的 Pydantic。API 优先使用标准库，避免为了
  demo 引入网络依赖；持久化 SQLite。默认本机服务，合成数据开发环境。
- 明确 patient/request/service/encounter 关联，保留原始文本、字段、行号、
  Unicode offsets、原始 source/fact IDs 和 hashes；不能通过同日期或同代码
  自动把上下文当作请求支持。机械 grounding 不保证临床语义正确。
- 规则集/规则 ID、版本与内容哈希进入每次 packet。条件触发需正向已知事实。
- 审核意见保留 reviewer type、model/version、basis revision/packet hash、
  fact IDs、judgment、reason、server UTC time。审核意见与规则结果分开。
- AI 审核可选、按风险触发；无模型也能完成 demo。AI 不得覆盖规则，不得
  在没有新来源证据时把缺失改成已满足。所有修正必须记录原因、来源与审核者。
- 事实和来源 append-only，修正保留旧版本，重算规则；避免丢失更新。
  审计与 revision/packet 保存必须在同一事务中完成，验证完整性。
- 研究模型调用：默认 0；有明确评估价值才能最多追加 100 次，失败重试均计数。
  可选产品 AI 调用另记；未知 usage 不能当作零。
- 不自动合并、不部署；可创建可审核的独立提交/草稿 PR。

## 泛化改进纪律

每轮：重读本文件 → 确认实际问题 → 固定测试 → 最小实现 → 前后对照
→ 跨患者/文档/请求类型/条件的验证 → 既有回归 → 保留或回滚。
同一路线连续两次失败应转向；每五轮改进决策作简洁总结。

绝对禁止针对特定失败 case 添加例外、硬编码患者/文档标识、匹配测试文本
或过拟合 fixture。产品逻辑使用稳定的数据合同、引用与通用范围检查。
若改进只在一个 case 或一类 fixture 通过，标记“未经泛化验证”，不能宣称有效。
软件泛化测试不等于真实临床验证；不调整参考答案、分母或评分方式。

## 实施计划与当前状态

1. 请求/事实/规则合同与固定风险测试：已实现并验证；初次 collection error
   作为开发过程保留，未伪装为业务 oracle 分数。
2. 确定性准备度、来源检查与既有冲突适配：初版已实现，119 项合同测试通过。
3. SQLite revision、审核、修正、事务和审计：已实现，32 项生命周期测试通过。
4. API、CLI、JSON/Markdown Review Packet、可选风险审核：已实现；5 项真实 HTTP/CLI 测试通过。
5. 可复现 Referral 与 PA demo、既有 Synthea 开发数据接入：已实现；3 个既有 development 患者 × 两请求类型的 6 个流程实际完成。
6. 跨患者、文档、Referral/PA、条件矩阵、HTTP/CLI、既有全回归：637 tests 全部通过。
7. 独立 [README](careflow/README.md)、[测试报告](careflow/TEST_REPORT.md)、
   [机器验收结果](careflow/validation-summary.json)、[共享代码完整性](careflow/shared-integrity.json)
   和 examples/careflow 已交付到本 worktree；正在提交可审核的独立变更。

## 验收标准

必须实际验证以下行为，并记录运行命令、结果、样本范围和限制：

- 缺失不变 SUPPORTED；正反断言、unknown、未解决冲突与已知 false 触发区分。
- 不同患者、请求、service/code system、encounter 的材料不能错误关联。
- 不可用来源、未来实际事件、错误引文不能填补缺口；未来计划订单可用于 PA。
- 修正无新证据被拒绝；无权威的修正保留冲突；有依据修正重算相关规则。
- AI/human 审核同合同；审核建议不能改变确定性结果，引用必须来自所审 packet。
- 规则版本/哈希可追溯；不支持的版本不回退；旧 packet、来源与事实不被覆盖。
- 所有更新留痕，事务失败不产生半写入；并发旧 revision 更新被拒绝。
- 人类报告与 JSON 使用相同确定性 packet，完整包含 IDs、原文、触发、缺失
  原因、冲突与可执行问题；重启后 case、review、revision 与审计仍可读取。
- 本机 API 完成创建→查询→审核→新增证据/修正→重算→历史→审计流程。
- 演示不依赖人工逐条签字或网络/模型；同时保留 human 和 optional AI 审核。
- 泛化测试使用不同患者、来源形式、Referral/PA、真假/未知/矛盾规则条件。
  既有离线回归通过；共享模块未修改；模型研究调用实际为 0。

## 决策与验证日志

14:45续开发检查点：共享修复90adea7已远端确认、本地d54fa9f集成。临床映射
56项通过，真实两请求HTTP更新/packet/报告/审计完成；完整回归837通过。
原材料开发集重新运行312场景/2028检查，macro-F1=100%、严重误判0、
来源2076/2076、规则2340/2340。最终Holdout未启用。

研究转录路线连续无收益已停止，45/100研究attempt保留（含39本地入口失败、
4上游失败、2不确定派发），未知usage45；没有将其重新分类规避授权上限。
Luna通道2新开发病例实际有效，共7产品attempt/4成功/3机械失败/3额外重试，
当前447开发文档批处理实际运行。原10ACI和2ACN有效缓存复用，不为分数重采样。

原生参考可用性是新增透明诊断，不能替换旧gold或宣称提升：无候选输入、
不修复原JSON，只保留原字段值/笔记原文span。447文档有12430已知单位，112份
文档的原标签严格格式失败、完整断言分母未知。全字段ClinicalFact语义没有
原完整结构化标注，原始完整临床P/R/F1必须写不可计算；源审核辅助Precision和
已知原生单位coverage独立报告。未知分母不按0计，完整cohort Recall/F1不可
计算时不得宣称抽取验收达标。None/null占位保留为非断言，不能猜否定。此视图
不是AI修正金标、保险审批金标，也不用于替换任何历史评分。相关12项测试通过。

本次续开发检查点（13:28 UTC）：共享P2独立提交`90adea7`已推送PR #3，并在
本地PR #4分支无冲突集成。483项共享测试、773项集成全仓回归通过；此前六个
unassigned覆盖失败修复；八个跨入口边界测试在机制加入后通过，含非CSV。
原分区未改变，校验按原始source-row核对全覆盖，空/缺失/歧义患者明确保留。
临床映射新增52项固定测试通过，连同生命周期84项：患者/时间/执行状态/
请求关联/原始binding来源/缺失目标/有权威修正均覆盖Referral和PA。发现并
修复“一个完成目标掩盖另一个unknown目标”以及JSON重启时tuple/list不一致。
正在补充原文→抽取→映射→API实际运行和冻结开发集评估。真实调用仍Luna2、
失败0、重试0；新Sol外部调用0。最终保留集未启用，不宣称全部验收完成。

| 轮次 | 实际问题与决策 | 固定测试/前后结果 | 泛化验证与结论 |
| --- | --- | --- | --- |
| 1 | 缺少独立请求合同与准备度产品；复用现有来源、状态、冲突合同，新增 checklist | 固定五项风险 oracle；首次收集失败（模块缺失），初版类型错误已修正；pytest 参数名和临时目录问题单独修正，未改业务预期 | 119 tests 通过：3 患者、Unicode 文档、text/structured、Referral/PA、五态、2 条件规则及 scope/availability；仅软件合同验证 |
| 2 | 修正和审核可能绕过缺失/冲突或丢失旧版；用新来源、显式 authority、分离 review、事务保存和既有 reconcile | 32 项固定生命周期测试通过；包含 rollback 注入、两并发写入、伪造审核/引用、hash 重算后的篡改检测 | 跨 Referral/PA、2 患者、人类/AI、true/false/unknown authority 与 future order/actual 对照通过；AI 为离线 callback 测试，无真实模型调用 |
| 3 | 尚无外部可运行入口和同源的人类报告；实现本机 HTTP/CLI 和 packet renderer | 首次 HTTP 运行 3 个测试因沙箱 WinError10013 失败、2 个非 HTTP 测试通过；同一固定测试在获准回环权限后 5/5 通过 | 不改 oracle/分母；两个患者的 Referral/PA HTTP 创建→审核→新增→重算→历史→audit 通过；Unicode 与原文围栏验证通过 |
| 4 | 原始索引未设解压边界，CSV 容易被误当完整请求证据；新增 bounded snapshot 适配，复用 ArchiveIndex 与独立 verify_archive | 模块新增前收集失败；8 项原始字段/隔离/坏链接/解压上限/篡改测试通过 | 3 个已有 development 患者、6 个 Referral/PA 工作流，4/60/3 个原始上下文来源；现有 verifier 重验字节、字段、患者和日期，通过；上下文不生成文档满足事实；holdout 未使用 |
| 5 | 换 source ID 的旧内容可能伪装新证据，NOT_APPLICABLE 可掩盖原始矛盾；按内容阻止旧文档充当新增材料，保存全局未解决冲突 | 独立手写场景 6 failed / 2 passed → 8 passed；相关回归 167 passed | 独立于 demo generator 的两患者、Referral/PA、CRLF 引文、多规则条件、排序变化；无 case-ID/文本特例；已知 false 保留 NOT_APPLICABLE，但存在请求内冲突时整体不 Ready |
| 6 | 全仓暴露 Windows 超限请求不能可靠返回拒绝响应；有界排空拒绝体，保留旧 report 兼容渲染 | 全仓 636 passed / 1 failed → 637 passed / 0 failed；固定 HTTP/CLI 5/5 通过；前后 JUnit 都保存 | 两患者、两请求类型的真实 HTTP 工作流回归；101 个已有 src/test 文件未修改；最终两类 demo、6 个 development 请求和新证据 amendment 示例实际重放完成 |

| 7 | 新合同需要无泄漏病例分区与reference-first；实现原始身份/重复内容connected components、冻结清单和五类差异审核 | 10项独立冻结/篡改/匹配不复审/固定分母/引文核查测试通过 | ACN1204组中dev200/holdout200；ACI67组中dev47/holdout20；均未运行保留抽取/评分 |
| 8 | 缺少统一macro-F1/严重误判/引用评分；新增候选seal、失败保留与一次holdout预约 | 5项固定评分测试通过；整体CONFLICTED但单项NA时严重误判遗漏：1 failed→pass | 各状态、执行失败、坏引用、版本错误及候选/最终评估锁测试；仅评估代码，未替代产品验收 |
| 9 | 排除的amendment可影响范围内事实；reference归一化会误等价单位大小写/布尔数字 | 6 scope失败→通过，相关180项回归；2 reference-type失败→通过，评估17项通过 | Referral/PA、不同患者/日期/定位与数值类型；删去范围外影响逻辑、保持严格类型，未添加病例特例/降低门槛 |
| 10 | 现有临床抽取缓存无法进入独立请求证据包；逐字复用ClinicalFact/dialogue合同，增加原始source-index核查和context-only视图 | 45项原有dialogue测试、19项context测试通过；20个真实缓存重放case/469原事实均保留且不产生Ready | 两请求类型、多种事实类别、跨患者排除/坏quote/错文档/AI引用；共享兼容部分独立提交441f66f |
| 11 | 缺少真实调用可追溯调度及结构修复保护；新增共享SQLite账本和原有Luna/high抽取适配 | scheduler8项、extraction3项通过；结构修复改变已有事实的固定失败经原有inspect_repair解决；最新全仓735 passed | 两份真实dev源文一次VALID；0失败/重试，保留原始输出与usage，未作语义重采样或临床准确率宣称 |
| 12 | 缓存可被篡改后直接读取，统一packet verifier漏掉临床上下文；从原响应/账本重构首个有效输出，复用源文validator验证context bundle | 固定10项风险：10 failed/22 passed → 37 passed；中间严格日期反序列化错误6 failed/31 passed也保留 | 多种篡改类型、Referral/PA、坏quote/ID/hash，错误缓存不新增调用；不修改原始响应、引用或参考答案 |
| 13 | 缺少公开源文抽取的可复现产品入口；增加extract-development与仅缓存replay-extraction，按原病例绑定全文/对话 | 3项跨患者CLI重放/篡改/规模测试、2项临床context HTTP测试通过；全仓750 passed | ACN原首组88 facts重放为2个请求，均NEEDS_EVIDENCE、源bundle/规则/audit通过，新增调用0；首次适配漏必填metadata已修正并验证 |
| 14 | 原始summary解析失败可能丢失参考原字符串；新增独立原标签inventory，冻结raw/hash/strict错误和仅诊断permissive视图 | 3项原文/标签篡改、错误病例保留、旧清单不变测试通过；1500病例全部保留，1128 strict有效、372失败、354仅诊断可读、18未解析 | 解析不猜测内容、不回填严格gold、不改变旧reference/分母；补充packet调用统计范围，上游未知不写0 |
| 15 | 差异可按列表顺序错误关联，旧审核意见可被错误用于新比较快照；限制唯一槽位配对、按comparison hash绑定辅助信用 | 2 failed/12 passed → 20项相关评估通过；全仓755 passed | 多事实/排序变化、快照状态变化、跨病例冻结与两请求重放；原始TP/FP/FN定义和分母未改，没有真实silver分数被提高 |

第十五轮检查点：临床缓存/真实Luna输出可进入两种请求证据包；API能引用context
fact进行独立AI意见记录，规则不被改写。原标签格式问题全部保留，缓存篡改不
触发重采样，歧义配对和过期意见不再给辅助信用。755项完整回归通过，材料
开发集评分保持100%/严重误判0；抽取P/R和最终保留验收未完成，继续有效工作。

第十轮检查点：从可运行v1扩展至病例隔离、冻结材料评分、reference-first与
临床缓存来源核查。没有五轮停止。冻结材料开发集312场景/2028检查的五态
macro-F1=100%、严重误判0、source/rule引用100%；限于构造场景，最终保留
验收尚未运行。完整735项回归通过。

五轮总结：已有确定性准备度、来源定位、版本化 checklist、持久化审核/修正、
本机 HTTP/CLI、同源 JSON/Markdown、bounded 原始数据接入。真实 Synthea
development 的 6 个构造请求已完成，未使用 holdout。所有结论限于软件合同，
最终已通过全仓回归和交付检查；研究和真实产品模型调用均为 0。

第六轮全仓初检：636 passed / 1 failed。失败为 oversized HTTP body
在 Windows 上未消费请求体即关闭连接，导致客户端收到 reset 而非 413。
保留原测试与全部分母，修复通用拒绝响应的有界请求体排空后，最终
637 passed / 0 failed / 0 skipped。失败前后报告均在 docs/careflow 保留。

## 已完成范围与剩余边界

最新合同进展：ACI train67组冻结dev47/holdout20，旧10已暴露缓存病例仅dev。
ACN固定revision `c1cb55e3fb2a08bef749c0de59500ef97ca582b6` 的前1,500完整行，
原始prefix SHA256 `5f007e3dce70ca5220bec983bafe5268afe72e1fb2c715f0623d180a61530de3`。
全文重复合并后1,204病例组，dev200/holdout200/reserve804；两源清单在
`docs/careflow/evaluation-v2/`，原文和未运行参考保存在ignored artifacts。
数据前缀不是全30K随机代表样本；不得扩大泛化结论。ACN summary为生成silver，
ACI reference note不是结构化源核查gold。抽取模型只接收原文与来源索引，
参考/规则不进入抽取；Sol差异核查才可读取参考与规则。最终保留评估尚未执行。

Referral 与 PA 文档准备度、严格合同、两个 1.0.0 checklist、原文 Citation、
来源筛选、全局冲突、缺失清单、审核问题、human/advanced_ai 意见、
新证据 amendment、全规则重算、SQLite revision/transaction/hash-chain、
HTTP API、CLI、JSON/Markdown、可选风险 callback、原始数据 context 适配、
可复现例子和自动测试已完成。没有改动共享旧代码或既有评分；没有合并或部署。

这仍是合成数据可运行原型：真实 payer 文档规则、临床语义验证、来源签名
真实性、生产身份/访问控制、外部签名审计锚及真实患者性能未完成。
新增抽取适配复用既有Luna/high源文prompt/schema/validator，不重开发抽取语义。
首个固定ACN dev组2源文首次有效输出56/32 facts，真实产品调用2，研究调用0。
临床上下文经原文校验进入packet，不自动充当材料满足断言。来源定位不保证
临床语义；source-checked P/R仍未测量。补充资料和demo审核意见明确构造，
不能当作真实医疗审核。仅对已跨患者、文档、请求和条件验证的软件行为宣称有效。

本表在每轮结束后更新。不得把待办、代码存在或历史测试写成验收通过。

公开参考接入的实际问题：固定ACN前缀1500条summary中1128条严格JSON有效，
372条无效（356条未转义control character，16条分隔符错误）。当前冻结清单
保留这些病例与reference_error，不跳过或把失败当正确。原始summary仍在固定
JSONL源文件，已建立独立保留原字符串/hash的版本化inventory，不修改旧清单，
也不能根据候选输出修补某病例参考。ACI现有源核查inventory不提供简单可直接
计算的独立Recall分母；旧469 facts源审核不能当新候选独立医学准确率。
