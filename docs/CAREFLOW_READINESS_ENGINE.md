# CareFlow Readiness Engine — 项目方向与验收合同

本文件持续维护目标、约束、研究结论、开发计划、验证结果及未完成事项。
每轮自主开发开始前必须重读本文件，核对该轮工作是否符合方向。
更新日期：2026-10-13。所有进展以实际实现和执行结果为准。

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

| 轮次 | 实际问题与决策 | 固定测试/前后结果 | 泛化验证与结论 |
| --- | --- | --- | --- |
| 1 | 缺少独立请求合同与准备度产品；复用现有来源、状态、冲突合同，新增 checklist | 固定五项风险 oracle；首次收集失败（模块缺失），初版类型错误已修正；pytest 参数名和临时目录问题单独修正，未改业务预期 | 119 tests 通过：3 患者、Unicode 文档、text/structured、Referral/PA、五态、2 条件规则及 scope/availability；仅软件合同验证 |
| 2 | 修正和审核可能绕过缺失/冲突或丢失旧版；用新来源、显式 authority、分离 review、事务保存和既有 reconcile | 32 项固定生命周期测试通过；包含 rollback 注入、两并发写入、伪造审核/引用、hash 重算后的篡改检测 | 跨 Referral/PA、2 患者、人类/AI、true/false/unknown authority 与 future order/actual 对照通过；AI 为离线 callback 测试，无真实模型调用 |
| 3 | 尚无外部可运行入口和同源的人类报告；实现本机 HTTP/CLI 和 packet renderer | 首次 HTTP 运行 3 个测试因沙箱 WinError10013 失败、2 个非 HTTP 测试通过；同一固定测试在获准回环权限后 5/5 通过 | 不改 oracle/分母；两个患者的 Referral/PA HTTP 创建→审核→新增→重算→历史→audit 通过；Unicode 与原文围栏验证通过 |
| 4 | 原始索引未设解压边界，CSV 容易被误当完整请求证据；新增 bounded snapshot 适配，复用 ArchiveIndex 与独立 verify_archive | 模块新增前收集失败；8 项原始字段/隔离/坏链接/解压上限/篡改测试通过 | 3 个已有 development 患者、6 个 Referral/PA 工作流，4/60/3 个原始上下文来源；现有 verifier 重验字节、字段、患者和日期，通过；上下文不生成文档满足事实；holdout 未使用 |
| 5 | 换 source ID 的旧内容可能伪装新证据，NOT_APPLICABLE 可掩盖原始矛盾；按内容阻止旧文档充当新增材料，保存全局未解决冲突 | 独立手写场景 6 failed / 2 passed → 8 passed；相关回归 167 passed | 独立于 demo generator 的两患者、Referral/PA、CRLF 引文、多规则条件、排序变化；无 case-ID/文本特例；已知 false 保留 NOT_APPLICABLE，但存在请求内冲突时整体不 Ready |
| 6 | 全仓暴露 Windows 超限请求不能可靠返回拒绝响应；有界排空拒绝体，保留旧 report 兼容渲染 | 全仓 636 passed / 1 failed → 637 passed / 0 failed；固定 HTTP/CLI 5/5 通过；前后 JUnit 都保存 | 两患者、两请求类型的真实 HTTP 工作流回归；101 个已有 src/test 文件未修改；最终两类 demo、6 个 development 请求和新证据 amendment 示例实际重放完成 |

五轮总结：已有确定性准备度、来源定位、版本化 checklist、持久化审核/修正、
本机 HTTP/CLI、同源 JSON/Markdown、bounded 原始数据接入。真实 Synthea
development 的 6 个构造请求已完成，未使用 holdout。所有结论限于软件合同，
最终已通过全仓回归和交付检查；研究和真实产品模型调用均为 0。

第六轮全仓初检：636 passed / 1 failed。失败为 oversized HTTP body
在 Windows 上未消费请求体即关闭连接，导致客户端收到 reset 而非 413。
保留原测试与全部分母，修复通用拒绝响应的有界请求体排空后，最终
637 passed / 0 failed / 0 skipped。失败前后报告均在 docs/careflow 保留。

## 已完成范围与剩余边界

Referral 与 PA 文档准备度、严格合同、两个 1.0.0 checklist、原文 Citation、
来源筛选、全局冲突、缺失清单、审核问题、human/advanced_ai 意见、
新证据 amendment、全规则重算、SQLite revision/transaction/hash-chain、
HTTP API、CLI、JSON/Markdown、可选风险 callback、原始数据 context 适配、
可复现例子和自动测试已完成。没有改动共享旧代码或既有评分；没有合并或部署。

这仍是合成数据可运行原型：真实 payer 文档规则、临床语义验证、来源签名
真实性、生产身份/访问控制、外部签名审计锚及真实患者性能未完成。
自动笔记语义抽取不在本轮重开发；调用者提供既有抽取/收件/审核流程产生的
可定位断言。来源定位不保证临床语义；补充资料和 demo 审核意见明确构造，
不能当作真实医疗审核。仅对已跨患者、文档、请求和条件验证的软件行为宣称有效。

本表在每轮结束后更新。不得把待办、代码存在或历史测试写成验收通过。
