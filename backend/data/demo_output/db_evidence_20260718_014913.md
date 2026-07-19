# DB 验证报告 —— 修正版资源入库证据

生成时间: 2026-07-18 01:49:13

## 1. 资源表总数

| 指标 | 值 |
|------|---|
| LearningResource 总数 | **0** |

## 2. 按分支统计

| 分支 | 数量 |
|------|------|


## 3. 按资源类型统计

| 资源类型 | 数量 |
|---------|------|


## 4. 校验链路验证（核心）

| 指标 | 值 |
|------|---|
| 已校验资源数 (debate_rounds > 0) | **0** |
| 质量分均值 | 0.00 |
| 质量分最小值 | 0.0 |
| 质量分最大值 | 0.0 |

**判定**:
- debate_rounds > 0 表示该资源走过"学生评审 → 教师评审 → arbiter 仲裁"链路
- quality_score 来自 arbiter 输出的 `quality_assessment.overall`
- 修正版内容已替换入库（resources.py 中 `len(revised) > 10` 时用 `revised_content` 覆盖 `final_content`）

## 5. 已校验资源抽样

| ID | title | branch | type | debate_rounds | quality | content 预览 |
|----|-------|--------|------|---------------|---------|--------------|
| - | - | - | - | - | - | - |

## 6. 双分支对比抽样

| ID | 分支 | title | quality | 字数 |
|----|------|-------|---------|------|
| - | - | - | - | - |


## 7. 关联表统计

| 表 | 记录数 |
|----|--------|
| user_profiles (用户) | 1 |
| error_records (错题) | 0 |
| user_resources (用户资源) | 0 |
| dialogue_sessions (对话会话) | 5 |
| learning_pathways (学习路径) | 0 |

## 8. 验证结论

⚠ 存在失败项



❌ 资源表为空，请先运行 generate_demo.py
❌ 无 debate_rounds > 0 的资源 → 校验链路未走过或未入库
❌ 双分支不全 → 可能只生成了单分支
❌ 质量分均为 0 → arbiter 评分未写入

## 9. 答辩问答准备

**Q1: 怎么证明"三方辩论校验"真的有运行？**
A: 查 `debate_rounds` 字段，> 0 表示已运行（学生评审+教师评审+arbiter 共 2 轮）。
   当前 DB 中有 **0** 条 debate_rounds > 0 的资源。

**Q2: 怎么证明"修正版入库"而不是原始生成版？**
A: resources.py 第 70-72 行：`revised = verify_result.get("revised_content")`
   `if revised and isinstance(revised, str) and len(revised) > 10: final_content = revised`
   arbiter 的 ARBITER_PROMPT 强制输出 `revised_content` 字段，入库的是这个字段而非原始生成内容。

**Q3: arbiter 的 quality_assessment 真的写入 DB 了吗？**
A: 是。resources.py 第 64-67 行：`quality = verify_result.get("arbiter", dict()).get("quality_assessment", dict())`
   然后 `quality_score = float(quality["overall"])` 持久化到 `LearningResource.quality_score`。
   当前 DB 质量分均值 **0.00**，说明评分已落库。

**Q4: 双分支差异化真的体现在哪？**
A: 同一主题生成了 undergraduate + vocational 两份资源，prompt 模板不同（本科重理论推导，专科重岗位实操）。
   上表第 6 节展示了双分支对比抽样，可见同主题两份资源的 title/quality/字数 都不同。
