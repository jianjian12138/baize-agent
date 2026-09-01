"""Unit tests for Ralph Pattern Autonomous PRD State Machine & Long-Horizon Delivery Loop."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from baize.ralph import (
    UserStory,
    PRDDocument,
    ProgressJournal,
    RalphLoopEngine,
)


class TestRalphEngine(unittest.TestCase):
    def test_prd_document_serialization_and_loading(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prd_file = Path(tmp_dir) / "prd.json"
            stories = [
                UserStory(
                    id="US-01",
                    title="重构核心模块接口",
                    description="提取通用契约接口并消除强耦合",
                    acceptance_criteria=["接口签名完备", "单测通过"],
                    passes=False,
                ),
                UserStory(
                    id="US-02",
                    title="补全业务实现与边界条件",
                    description="实现基类方法并处理异常",
                    acceptance_criteria=["零报错 0 告警"],
                    passes=True,
                    commit_hash="abc1234",
                ),
            ]
            prd = PRDDocument(goal="测试长程交付任务", stories=stories)
            prd.save_to_file(str(prd_file))

            self.assertTrue(prd_file.exists())
            loaded = PRDDocument.load_from_file(str(prd_file))
            self.assertEqual(loaded.goal, "测试长程交付任务")
            self.assertEqual(len(loaded.stories), 2)
            self.assertEqual(loaded.stories[0].id, "US-01")
            self.assertFalse(loaded.stories[0].passes)
            self.assertEqual(loaded.stories[1].id, "US-02")
            self.assertTrue(loaded.stories[1].passes)
            self.assertEqual(loaded.stories[1].commit_hash, "abc1234")

    def test_prd_document_next_pending_story(self):
        stories = [
            UserStory(id="US-01", title="任务1", description="", passes=True),
            UserStory(id="US-02", title="任务2", description="", passes=False),
            UserStory(id="US-03", title="任务3", description="", passes=False),
        ]
        prd = PRDDocument(goal="目标", stories=stories)
        pending = prd.next_pending_story()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.id, "US-02")

        # Mark US-02 done
        pending.passes = True
        next_p = prd.next_pending_story()
        self.assertIsNotNone(next_p)
        self.assertEqual(next_p.id, "US-03")

        # Mark US-03 done
        next_p.passes = True
        self.assertIsNone(prd.next_pending_story())

    def test_progress_journal_append_and_read(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            journal_file = Path(tmp_dir) / "progress.txt"
            journal = ProgressJournal(str(journal_file))

            journal.append_entry(
                story_id="US-01",
                title="初始化契约",
                learnings="发现底层依赖存在隐式全局状态，需使用工厂模式解耦。"
            )
            journal.append_entry(
                story_id="US-02",
                title="编写单元测试",
                learnings="测试用例覆盖率达到 100%，已通过 pytest 验证。"
            )

            summary = journal.read_summary()
            self.assertIn("US-01", summary)
            self.assertIn("工厂模式解耦", summary)
            self.assertIn("US-02", summary)
            self.assertIn("pytest 验证", summary)

    def test_ralph_loop_execution_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            prd_file = Path(tmp_dir) / "prd.json"
            progress_file = Path(tmp_dir) / "progress.txt"

            engine = RalphLoopEngine(
                prd_path=str(prd_file),
                progress_path=str(progress_file),
                workspace_dir=tmp_dir,
            )

            # Generate initial PRD
            prd = engine.generate_initial_prd("重构支付状态机")
            prd.save_to_file(str(prd_file))

            # Run loop with simulated execution (auto_commit disabled in test sandbox)
            res = engine.run_loop(max_iterations=2, auto_commit=False)

            self.assertIn("status_board", res)
            self.assertTrue(len(res["executed_stories"]) > 0)
            self.assertTrue(Path(progress_file).exists())


if __name__ == "__main__":
    unittest.main()
