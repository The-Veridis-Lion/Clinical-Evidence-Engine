# CareFlow 实际运行进度

更新：2026-10-13 11:55 UTC（纽约07:55）。当前 turn 中实际开发；没有虚构后台计算。
长期方向与冻结验收：docs/CAREFLOW_READINESS_ENGINE.md、AGENTS.md。

## 已实现的 Referral / PA 功能

独立 feature/careflow-readiness worktree。v1 产品提交287feb3；原有临床事实/对话
模块的逐字复用作为独立兼容提交441f66f。请求、五态材料检查、1.0.0规则、原文
引用、JSON/Markdown、HTTP/CLI、human/advanced_ai审核、新证据修正重算、
SQLite revisions和审计均可运行。已有ACI10病例/469条事实在20个Referral/PA
case中实际重放；事实只作clinical context，不填补缺失材料，全部NEEDS_EVIDENCE，
审计全部通过。最新完整回归755 passed / 0 failed / 0 skipped，含实际本机HTTP。

## 评分与冻结数据

材料规格在候选运行前冻结：6个已有Synthea development患者，26种机制×两请求
类型×两来源形式，共624构造场景；3患者/312场景为材料dev，另3患者/312场景
保留。它们不是624个独立真实临床病例。开发集2,028个criterion，五态macro-F1
100%，严重false Ready 0，整体错误0；来源2,076/2,076、规则2,340/2,340机械通过。
最终候选未封存，保留集未执行，不能声明新合同验收完成。

ACN固定revision前1,500完整行合并为1,204病例组；dev200组/768文档，holdout200组/
708文档，reserve804组。ACI67组中dev47、holdout20；旧10缓存病例只进dev。
公开文本保留集未运行。源核查抽取Precision/Recall尚未测量。ACN生成summary
不能作为独立医学正确答案；两个数据集都不提供可靠PA批准/材料完整性金标。

## 真实模型调用与来源问题

Luna/high：2次product_extraction，成功2、失败0、额外重试0；研究调用0。
Sol实际外部审核调用0。固定dev首组全文56 facts、对话32 facts，首次输出机械
有效；88条机械有效事实不能说成88条临床正确事实。共享SQLite调度/账本已实现
并记录真实调用；参与者global≤50、项目≤25。另一项目尚未接入，不能声称强制
覆盖其全部调用。有效首次输出不可因语义分数不佳重采样，失败/响应/usage均保留。
PR #3两项共享P2仍未解决；CareFlow归档适配有解压边界，未改共享实现。

## Sol 决策与下一项

保留原始抽取合同/提示，逐字复用。临床事实绑定原始source index，保留assertion/
temporality/experiencer和quotes；材料状态由独立确定性规则产生。修复范围外
amendment影响原事实、单位大小写/布尔数字误等价、结构修复改变有效事实三个
通用机制；跨患者/Referral/PA/条件验证，保留失败前后记录。下一项：可复现抽取
入口、缓存完整性、reference-first差异流程和产品重放；不改参考或分母。

## 可恢复运行

应用30分钟heartbeat careflow只报告实际新增工作，不自动进行模型实验。依赖
Codex应用运行，不保证持续后台计算。若执行结束，以此文件、提交、冻结manifest、
原始attempt及共享账本恢复；没有运行的时段不能冒充进展。

最新检查点（第15轮）：缓存原响应/账本重构、clinical context bundle机械核查、
抽取/重放CLI和API已通过，ACN88 facts真实缓存重放两请求，均NEEDS_EVIDENCE、
来源/规则/audit有效，额外调用0。差异审核不再按列表顺序强配多事实，也不能
给新快照复用旧意见；2失败固定测试修复，全仓755通过。原标签inventory保存
全部1500 raw summary/hash：1128严格有效、372失败；354仅诊断可读、18未解析，
诊断结果未用于评分。测试报告：docs/careflow/evaluation-v2/TEST_REPORT.md。
下一项实际工作：冻结跨类别的结构化源参考映射、接入仅差异的Sol源核查，分别
报告原始与silver辅助指标；最终保留集继续封存。没有完成全部目标，不虚报完成。
