# CareFlow 实际运行进度

更新：2026-10-13 14:34 UTC（纽约10:34）。此文件记录实际工作，不是后台运行承诺。
方向合同：AGENTS.md、docs/CAREFLOW_READINESS_ENGINE.md。全部四项继续授权。

## 当前实现和验证

PR #3 共享修复独立提交90adea7已推送，远端确认该SHA；PR #4本地d54fa9f无冲突集成。
共享483项、集成773项测试通过。原始claim按source-row核对完整覆盖，缺失/空白/
歧义患者明确保留。共享ZIP入口在读取任何成员前检查成员、总量、数量和压缩
档案界限，包括非CSV。未编辑Copilot工作目录。

临床映射要求显式原始来源patient/request/service/code-system binding；保留
ClinicalFact ID、原文、主体和时间。诊断不生成PA表单/意图，计划不算完成，诊断性
procedure不算既往治疗，未知目标不会被其他完成目标掩盖。映射规则独立版本/哈希，
审核意见不覆盖确定性结果，有依据的修正可重算。56项映射测试通过。

真实HTTP映射工作流两种请求均已运行：原文→首次真实Luna输出→绑定→规则
→JSON/Markdown→API→SQLite历史/审计。复用2份有效输出，额外模型调用0；
请求intake为明确构造fixture，不是保险审批或医生签字。

最新完整回归833 passed / 0 failed / 0 skipped（11.159秒），报告current-regression.xml。
随后新增批处理保护相关11项通过，完整新回归待运行。保留2项中间失败报告。
冻结材料dev重新执行：312场景/2028检查，五态macro-F1=100%，缺失/冲突误判
Ready=0，整体错误0，来源2076/2076，规则2340/2340。不是临床抽取准确率。

## 数据、调用和实际阻塞

ACI dev47/hold20，ACN dev200/hold200分组保持原冻结。开发抽取固定范围ACI47
文档+ACN400全文/对话代表文档，共447；已原样复用ACI10缓存/469 facts，ACN2份
有效输出仍可复用。原summary格式问题、分母与历史结果保留。

14:30账本检查点：47 attempts；Luna产品2成功、0失败/重试；Sol研究45，其中39次
本地schema路径失败、4次后续上游失败、2次停止后的不确定派发；研究重试29。
45次usage未知，不能写0；有效Sol转录0。原事件/错误保留，研究45/100全部计数，
没有重新分类规避额度。参考转录连续无收益已停止，检查点无悬挂reservation。
当前另有两份未抽取ACI开发文档的Luna通道检查实际运行中，结束后更新账本；
以上为检查点数字，不能当最新最终统计。

公开文本source-checked Precision/Recall/F1未测量。参考转录没有可靠产出，不能
把空参考集算为满分或完整医学准确率。ACI笔记/ACN生成summary不是独立医生金标。
最终材料及公开文本Holdout均未预约/运行，候选尚未最终封存。

## Sol 决策与下一项

保留已通过跨患者/文档/请求/条件测试的共享修复和临床映射。批处理连续两份
上游文档失败停止新派发，未运行文档保留分母；wrapper按首个有效原响应重构
校验，失败usage回收，每次运行报告追加保存。相关11项通过。
停止无产出的20文档Sol转录路线，核对原Luna通道可用性后执行447文档批处理，
再完成评分范围清楚的reference-first差异和源审核。Task1/2及共享实现稳定前
不启用最终holdout，不更改原参考或评分追求数字。

## 可恢复检查点

独立feature/careflow-readiness worktree；共享修复目录claims-shared-fixes。
真实API入口：python -m clinical_intelligence.careflow --db NEW.sqlite http-workflow
--case CASE.json --update UPDATE.json --output NEW_DIRECTORY。
实际输入/报告：artifacts/careflow-completion-v3/actual-mapped-e2e/；CLI重放：
artifacts/careflow-completion-v3/reproducible-mapped-api/。
账本：../artifacts/model-scheduling/careflow-copilot-calls.sqlite；研究原始日志：
artifacts/careflow-completion-v3/references-development/calls/。
30分钟heartbeat只报告实际工作，不发起模型实验。未合并main、部署或购买。
尚未达到完整产品验收；继续任务2/3，环境无法执行时保留明确恢复点。
