"""Unit tests for Ralph Pattern Autonomous PRD State Machine & Long-Horizon Delivery Loop."""
from __future__ import annotations

import shutil
import subprocess
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

    # ----------------------------------------------------------------- #
    # A commit that did not happen must not be reported as one
    # ----------------------------------------------------------------- #

    def test_commit_that_cannot_happen_returns_none_with_a_reason(self):
        """``commit_git`` used to end with ``except Exception: return
        "simulated_commit"``. The loop then stored that string in
        ``story.commit_hash`` and printed "已记录状态并提交 Git" - a failed commit
        recorded and announced as a successful one, which is the fabricated
        success pattern this package claims to have removed.

        Pinned here: no hash, no fabricated sentinel, and a reason the caller can
        print. The workspace directory does not exist, so ``Popen`` cannot even
        start - deterministic, and independent of whether git is installed.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = RalphLoopEngine(
                prd_path=str(Path(tmp_dir) / "prd.json"),
                progress_path=str(Path(tmp_dir) / "progress.txt"),
                workspace_dir=str(Path(tmp_dir) / "does-not-exist"),
            )
            story = UserStory(id="US-01", title="t", description="d")

            sha = engine.commit_git(story)

            self.assertIsNone(sha, "a commit that did not happen must not return a hash")
            self.assertNotEqual(sha, "simulated_commit")
            self.assertNotEqual(sha, "committed")
            self.assertTrue(engine.last_commit_error,
                            "the caller needs a reason to report")
            self.assertEqual(story.commit_hash, "",
                             "commit_hash must stay empty when nothing was committed")

    def test_a_failing_git_commit_returns_none_not_a_sentinel(self):
        """The git-ran-but-refused branch, not just the could-not-start branch."""
        if not shutil.which("git"):
            self.skipTest("git is not on PATH")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True,
                           capture_output=True)
            # No user.email/user.name configured in a bare temp repo, and the
            # env is scrubbed of any global identity -> `git commit` exits
            # non-zero. That is the branch under test.
            engine = RalphLoopEngine(
                prd_path=str(repo / "prd.json"),
                progress_path=str(repo / "progress.txt"),
                workspace_dir=str(repo),
            )
            story = UserStory(id="US-02", title="t", description="d")

            sha = engine.commit_git(story)

            self.assertIsNone(sha)
            self.assertNotEqual(sha, "simulated_commit")
            self.assertIn("git commit", engine.last_commit_error)

    def test_a_real_commit_returns_the_real_hash(self):
        """The happy path, so the two tests above cannot pass by always returning None."""
        if not shutil.which("git"):
            self.skipTest("git is not on PATH")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir) / "repo"
            repo.mkdir()
            run = lambda *a: subprocess.run(list(a), cwd=repo, check=True,
                                            capture_output=True)
            run("git", "init", "-q")
            run("git", "config", "user.email", "probe@example.invalid")
            run("git", "config", "user.name", "probe")
            (repo / "seed.txt").write_text("seed\n", encoding="utf-8")

            engine = RalphLoopEngine(
                prd_path=str(repo / "prd.json"),
                progress_path=str(repo / "progress.txt"),
                workspace_dir=str(repo),
            )
            story = UserStory(id="US-03", title="real commit", description="d")

            sha = engine.commit_git(story)

            self.assertIsNotNone(sha, f"expected a hash, got error: {engine.last_commit_error!r}")
            self.assertEqual(len(sha), 40, "git rev-parse HEAD returns a full sha1")
            self.assertEqual(engine.last_commit_error, "")
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                  capture_output=True, text=True).stdout.strip()
            self.assertEqual(sha, head)


if __name__ == "__main__":
    unittest.main()
