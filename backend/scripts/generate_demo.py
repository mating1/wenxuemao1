"""
演示数据生成脚本 —— 一键生成双分支对比示例（答辩演示用）

工作流程:
1. 对每个主题，分别用本科 / 专科分支生成多类资源
2. 可选开启 verify（三方辩论校验），保存修正版入库
3. 持久化到 DB，同时输出 JSON + Markdown 对比报告

用法:
    python scripts/generate_demo.py                       # 默认 2 主题、开启校验
    python scripts/generate_demo.py --no-verify           # 关闭校验（更快）
    python scripts/generate_demo.py --topic 递归 --types handout mindmap
    python scripts/generate_demo.py --foundation 70       # 调整学生基础分

输出:
    data/demo_output/demo_<时间戳>.md     双分支对比 Markdown 报告
    data/demo_output/demo_<时间戳>.json   完整 JSON（含 quality_score / debate_rounds）
    data/demo_output/latest.md            最新报告副本
"""
import asyncio
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 让脚本可从 backend/ 目录直接运行
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from app.db.base import init_db, async_session_factory
from app.agents.generation_agent import GenerationAgent
from app.agents.verification_agent import VerificationAgent
from app.models.resource import (
    LearningResource, ResourceType, EducationBranch, ResourceDifficulty,
)

# 默认演示计划：2 个主题，覆盖讲义 + 思维导图 + 实训案例
DEFAULT_DEMO = [
    {"topic": "递归", "foundation": 45, "types": ["handout", "mindmap"]},
    {"topic": "二叉树遍历", "foundation": 60, "types": ["handout", "practical_case"]},
]


async def gen_one(
    generation: GenerationAgent,
    verification: VerificationAgent,
    branch_level: str,
    topic: str,
    foundation: float,
    rtype: str,
    verify: bool,
) -> dict:
    """生成单分支资源 + 可选三方辩论校验"""
    content = await generation.generate(
        resource_type=rtype, topic=topic,
        education_level=branch_level, foundation=foundation,
    )
    result = {
        "content": content,
        "verify": None,
        "quality_score": 7.0,   # 生成成功即给基准分
        "debate_rounds": 0,
    }
    if verify:
        v = await verification.verify(
            resource_content=content, resource_type=rtype, topic=topic,
            education_level=branch_level, foundation=foundation,
        )
        result["verify"] = v
        q = v.get("arbiter", {}).get("quality_assessment", {})
        if q.get("overall"):
            result["quality_score"] = float(q["overall"])
            result["debate_rounds"] = 2
        # 与 /api/resources/generate 保持一致：用修正版入库
        revised = v.get("revised_content")
        if revised and isinstance(revised, str) and len(revised) > 10:
            result["content"] = revised
    return result


def persist(topic: str, foundation: float, rtype: str,
            branch_level: str, result: dict) -> int:
    """同步持久化到 DB（在 async session 内调用）"""
    branch = (EducationBranch.UNDERGRADUATE if branch_level == "undergraduate"
              else EducationBranch.VOCATIONAL)
    diff = (ResourceDifficulty.BASIC if foundation < 40
            else ResourceDifficulty.INTERMEDIATE if foundation < 70
            else ResourceDifficulty.ADVANCED)
    return LearningResource(
        title=f"[演示-{branch_level}] {topic} - {rtype}",
        resource_type=ResourceType(rtype),
        difficulty=diff,
        branch=branch,
        content=result["content"],
        summary=result["content"][:300],
        knowledge_points=[topic],
        generated_by_agent="资源生成Agent",
        debate_rounds=result["debate_rounds"],
        quality_score=result["quality_score"],
        target_foundation_min=max(0, foundation - 15),
        target_foundation_max=min(100, foundation + 15),
        cached_for_offline=True,
    )


async def main():
    parser = argparse.ArgumentParser(description="生成双分支对比演示数据")
    parser.add_argument("--topic", help="单主题模式（默认跑 2 个主题）")
    parser.add_argument("--types", nargs="+",
                        default=["handout", "mindmap"],
                        choices=["handout", "mindmap", "question_bank",
                                 "practical_case", "micro_lecture"],
                        help="资源类型（单主题模式生效）")
    parser.add_argument("--foundation", type=float, default=50.0,
                        help="学生基础分 0-100")
    parser.add_argument("--no-verify", action="store_true",
                        help="关闭三方辩论校验（更快，但无修正版）")
    parser.add_argument("--output-dir", default="data/demo_output")
    args = parser.parse_args()

    if args.topic:
        demo_plan = [{"topic": args.topic, "foundation": args.foundation,
                      "types": args.types}]
    else:
        demo_plan = DEFAULT_DEMO

    verify = not args.no_verify
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"初始化数据库...")
    await init_db()
    generation = GenerationAgent()
    verification = VerificationAgent()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_results = []
    saved_count = 0

    for plan in demo_plan:
        topic, foundation, rtypes = plan["topic"], plan["foundation"], plan["types"]
        logger.info(f"=== 主题: {topic} | 基础分: {foundation} | "
                    f"资源类型: {rtypes} | verify: {verify} ===")
        for rtype in rtypes:
            try:
                ug = await gen_one(generation, verification, "undergraduate",
                                   topic, foundation, rtype, verify)
                voc = await gen_one(generation, verification, "vocational",
                                    topic, foundation, rtype, verify)
            except Exception as e:
                logger.error(f"生成失败 {topic}/{rtype}: {e}")
                continue

            # 持久化到 DB
            async with async_session_factory() as session:
                session.add(persist(topic, foundation, rtype, "undergraduate", ug))
                session.add(persist(topic, foundation, rtype, "vocational", voc))
                await session.commit()
                saved_count += 2

            all_results.append({
                "topic": topic, "foundation": foundation, "rtype": rtype,
                "undergraduate": {
                    "content": ug["content"],
                    "quality_score": ug["quality_score"],
                    "debate_rounds": ug["debate_rounds"],
                },
                "vocational": {
                    "content": voc["content"],
                    "quality_score": voc["quality_score"],
                    "debate_rounds": voc["debate_rounds"],
                },
            })
            logger.info(f"✓ {topic}/{rtype}: 本科质量={ug['quality_score']}, "
                        f"专科质量={voc['quality_score']}")

    if not all_results:
        logger.warning("未生成任何资源，退出")
        return

    # 写 JSON
    json_path = output_dir / f"demo_{timestamp}.json"
    json_data = {
        "generated_at": timestamp,
        "verify_enabled": verify,
        "results": [
            {
                "topic": r["topic"], "foundation": r["foundation"],
                "rtype": r["rtype"],
                "undergraduate": {
                    "quality_score": r["undergraduate"]["quality_score"],
                    "debate_rounds": r["undergraduate"]["debate_rounds"],
                    "content_length": len(r["undergraduate"]["content"]),
                    "content_preview": r["undergraduate"]["content"][:500],
                },
                "vocational": {
                    "quality_score": r["vocational"]["quality_score"],
                    "debate_rounds": r["vocational"]["debate_rounds"],
                    "content_length": len(r["vocational"]["content"]),
                    "content_preview": r["vocational"]["content"][:500],
                },
            }
            for r in all_results
        ],
    }
    json_path.write_text(
        json.dumps(json_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 写 Markdown 对比报告
    md_path = output_dir / f"demo_{timestamp}.md"
    lines = [
        "# 双分支对比演示报告",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 校验开关: {'✅ 开启（三方辩论+修正版入库）' if verify else '❌ 关闭'}",
        f"- 主题数: {len(demo_plan)}",
        f"- 资源对数: {len(all_results)}（每对本科+专科各 1 份）",
        "",
        "## 概览",
        "",
        "| 主题 | 资源类型 | 本科质量 | 专科质量 | 本科字数 | 专科字数 |",
        "|------|---------|---------|---------|---------|---------|",
    ]
    for r in all_results:
        ug_len = len(r["undergraduate"]["content"])
        voc_len = len(r["vocational"]["content"])
        lines.append(
            f"| {r['topic']} | {r['rtype']} | "
            f"{r['undergraduate']['quality_score']} | "
            f"{r['vocational']['quality_score']} | {ug_len} | {voc_len} |"
        )
    lines.append("")

    for r in all_results:
        lines.append("---")
        lines.append("")
        lines.append(f"## {r['topic']} - {r['rtype']}")
        lines.append("")
        lines.append(
            f"### 🎓 本科版  "
            f"(quality={r['undergraduate']['quality_score']}, "
            f"debate_rounds={r['undergraduate']['debate_rounds']})"
        )
        lines.append("")
        lines.append(r["undergraduate"]["content"])
        lines.append("")
        lines.append(
            f"### 🔧 专科版  "
            f"(quality={r['vocational']['quality_score']}, "
            f"debate_rounds={r['vocational']['debate_rounds']})"
        )
        lines.append("")
        lines.append(r["vocational"]["content"])
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    # latest.md 副本（Windows 无软链，用复制）
    latest_md = output_dir / "latest.md"
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"✅ 演示数据生成完成！")
    print(f"{'=' * 60}")
    print(f"  📄 Markdown 对比报告: {md_path}")
    print(f"  📊 JSON 数据:          {json_path}")
    print(f"  💾 持久化资源数:       {saved_count} 条（已写入 learning_resources 表）")
    print(f"  📁 最新报告副本:       {latest_md}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
