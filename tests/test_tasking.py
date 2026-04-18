"""
多任务系统自动化测试
覆盖: 任务创建、配置快照、状态流转、并发安全、取消、重试、SQLite 持久化
"""
import os
import tempfile
import unittest
from pathlib import Path

from src.tasking.models import TaskStatus, TaskRecord
from src.tasking.store import TaskStore
from src.tasking.manager import TaskManager


class TestTaskStatus(unittest.TestCase):
    """状态机流转测试"""

    def test_pending_to_running(self):
        self.assertTrue(TaskStatus.PENDING.can_transition_to(TaskStatus.RUNNING))

    def test_pending_to_cancelled(self):
        self.assertTrue(TaskStatus.PENDING.can_transition_to(TaskStatus.CANCELLED))

    def test_pending_cannot_fail_directly(self):
        self.assertFalse(TaskStatus.PENDING.can_transition_to(TaskStatus.FAILED))

    def test_running_to_succeeded(self):
        self.assertTrue(TaskStatus.RUNNING.can_transition_to(TaskStatus.SUCCEEDED))

    def test_running_to_failed(self):
        self.assertTrue(TaskStatus.RUNNING.can_transition_to(TaskStatus.FAILED))

    def test_running_to_cancelled(self):
        self.assertTrue(TaskStatus.RUNNING.can_transition_to(TaskStatus.CANCELLED))

    def test_terminal_states_no_transition(self):
        for s in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.assertFalse(s.can_transition_to(TaskStatus.RUNNING))
            self.assertFalse(s.can_transition_to(TaskStatus.PENDING))


class TestTaskRecord(unittest.TestCase):
    """数据类序列化测试"""

    def test_to_dict_and_from_dict(self):
        rec = TaskRecord(
            task_id="t001", created_at="2026-03-31T10:00:00",
            status=TaskStatus.RUNNING, model_name="xgboost", top_k=50,
        )
        d = rec.to_dict()
        self.assertEqual(d["status"], "running")
        self.assertEqual(d["top_k"], 50)

        rec2 = TaskRecord.from_dict(d)
        self.assertEqual(rec2.status, TaskStatus.RUNNING)
        self.assertEqual(rec2.task_id, "t001")

    def test_from_dict_ignores_extra_keys(self):
        d = {"task_id": "t002", "created_at": "2026-03-31", "unknown_col": 999}
        rec = TaskRecord.from_dict(d)
        self.assertEqual(rec.task_id, "t002")


class TestTaskStore(unittest.TestCase):
    """SQLite 持久化测试"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test_tasks.db")
        self.store = TaskStore(self.db_path)

    def test_insert_and_get(self):
        rec = TaskRecord(
            task_id="test_001", created_at="2026-03-31T10:00:00",
            model_name="xgboost", top_k=100,
        )
        self.store.insert(rec)
        got = self.store.get("test_001")
        self.assertIsNotNone(got)
        self.assertEqual(got.task_id, "test_001")
        self.assertEqual(got.status, TaskStatus.PENDING)
        self.assertEqual(got.top_k, 100)

    def test_get_nonexistent(self):
        self.assertIsNone(self.store.get("does_not_exist"))

    def test_update_status(self):
        self.store.insert(TaskRecord(task_id="t_upd", created_at="2026-03-31T10:00:00"))
        self.store.update_status("t_upd", TaskStatus.RUNNING, started_at="2026-03-31T10:01:00")
        got = self.store.get("t_upd")
        self.assertEqual(got.status, TaskStatus.RUNNING)
        self.assertEqual(got.started_at, "2026-03-31T10:01:00")

    def test_update_status_with_error(self):
        self.store.insert(TaskRecord(task_id="t_err", created_at="2026-03-31T10:00:00"))
        self.store.update_status(
            "t_err", TaskStatus.FAILED,
            finished_at="2026-03-31T10:05:00",
            error_message="OOM",
        )
        got = self.store.get("t_err")
        self.assertEqual(got.status, TaskStatus.FAILED)
        self.assertEqual(got.error_message, "OOM")

    def test_list_tasks(self):
        for i in range(5):
            self.store.insert(TaskRecord(
                task_id=f"t_list_{i:03d}",
                created_at=f"2026-03-31T{10 + i}:00:00",
            ))
        all_tasks = self.store.list_tasks()
        self.assertEqual(len(all_tasks), 5)

    def test_list_tasks_by_status(self):
        self.store.insert(TaskRecord(task_id="t_a", created_at="2026-03-31T10:00:00"))
        self.store.insert(TaskRecord(task_id="t_b", created_at="2026-03-31T10:01:00"))
        self.store.update_status("t_b", TaskStatus.RUNNING)
        pending = self.store.list_tasks(status=TaskStatus.PENDING)
        running = self.store.list_tasks(status=TaskStatus.RUNNING)
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(running), 1)

    def test_claim_pending(self):
        self.store.insert(TaskRecord(task_id="t_claim", created_at="2026-03-31T10:00:00"))
        claimed = self.store.claim_pending()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, TaskStatus.RUNNING)
        self.assertEqual(claimed.progress_pct, 0)
        self.assertIn("启动", claimed.progress_message)
        # 再次 claim 应返回 None
        self.assertIsNone(self.store.claim_pending())

    def test_update_progress(self):
        self.store.insert(TaskRecord(task_id="t_prog", created_at="2026-03-31T10:00:00"))
        self.store.update_progress("t_prog", 42, "因子计算 3/6")
        got = self.store.get("t_prog")
        self.assertEqual(got.progress_pct, 42)
        self.assertEqual(got.progress_message, "因子计算 3/6")

    def test_recover_orphaned(self):
        self.store.insert(TaskRecord(task_id="t_orphan", created_at="2026-03-31T10:00:00"))
        self.store.update_status("t_orphan", TaskStatus.RUNNING)
        count = self.store.recover_orphaned()
        self.assertEqual(count, 1)
        got = self.store.get("t_orphan")
        self.assertEqual(got.status, TaskStatus.FAILED)
        self.assertIn("orphaned", got.error_message)

    def test_count_by_status(self):
        self.store.insert(TaskRecord(task_id="cnt_1", created_at="2026-03-31T10:00:00"))
        self.store.insert(TaskRecord(task_id="cnt_2", created_at="2026-03-31T10:01:00"))
        self.assertEqual(self.store.count_by_status(TaskStatus.PENDING), 2)
        self.assertEqual(self.store.count_by_status(TaskStatus.RUNNING), 0)


class TestTaskManager(unittest.TestCase):
    """任务管理器测试"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test_mgr.db")
        self.store = TaskStore(self.db_path)
        self.mgr = TaskManager(self.store)

    def test_submit_creates_snapshot(self):
        task = self.mgr.submit(
            ui_overrides={"backtest": {"top_k": 100}},
            submit_source="cli",
        )
        self.assertIsNotNone(task.task_id)
        self.assertTrue(task.task_id.startswith("task_"))
        self.assertTrue(os.path.exists(task.config_snapshot_path))
        self.assertTrue(os.path.isdir(task.output_dir))
        self.assertEqual(task.top_k, 100)
        self.assertEqual(task.status, TaskStatus.PENDING)

    def test_submit_does_not_modify_base_config(self):
        from src.config_loader import _find_config_path
        config_path = _find_config_path()
        with open(config_path, "r", encoding="utf-8") as f:
            before = f.read()

        self.mgr.submit(
            ui_overrides={"backtest": {"top_k": 999}},
            submit_source="cli",
        )

        with open(config_path, "r", encoding="utf-8") as f:
            after = f.read()

        self.assertEqual(before, after, "base_config.yaml 被修改了！")

    def test_submit_two_tasks_isolated_dirs(self):
        t1 = self.mgr.submit(ui_overrides={"backtest": {"top_k": 10}}, submit_source="cli")
        t2 = self.mgr.submit(ui_overrides={"backtest": {"top_k": 20}}, submit_source="cli")
        self.assertNotEqual(t1.task_id, t2.task_id)
        self.assertNotEqual(t1.output_dir, t2.output_dir)
        self.assertNotEqual(t1.config_snapshot_path, t2.config_snapshot_path)

    def test_cancel_pending(self):
        task = self.mgr.submit(submit_source="cli")
        result = self.mgr.cancel(task.task_id)
        self.assertTrue(result)
        got = self.store.get(task.task_id)
        self.assertEqual(got.status, TaskStatus.CANCELLED)

    def test_cancel_succeeded_raises(self):
        task = self.mgr.submit(submit_source="cli")
        self.store.update_status(task.task_id, TaskStatus.RUNNING)
        self.store.update_status(task.task_id, TaskStatus.SUCCEEDED)
        with self.assertRaises(ValueError):
            self.mgr.cancel(task.task_id)

    def test_cancel_nonexistent_raises(self):
        with self.assertRaises(ValueError):
            self.mgr.cancel("does_not_exist")

    def test_retry_creates_new_task(self):
        task = self.mgr.submit(submit_source="cli")
        self.store.update_status(task.task_id, TaskStatus.RUNNING)
        self.store.update_status(task.task_id, TaskStatus.FAILED, error_message="test error")
        new_task = self.mgr.retry(task.task_id)
        self.assertNotEqual(new_task.task_id, task.task_id)
        self.assertEqual(new_task.status, TaskStatus.PENDING)

    def test_retry_non_failed_raises(self):
        task = self.mgr.submit(submit_source="cli")
        with self.assertRaises(ValueError):
            self.mgr.retry(task.task_id)

    def test_list_and_get(self):
        t1 = self.mgr.submit(submit_source="cli")
        t2 = self.mgr.submit(submit_source="ui")
        tasks = self.mgr.list_tasks()
        self.assertEqual(len(tasks), 2)
        got = self.mgr.get(t1.task_id)
        self.assertIsNotNone(got)


if __name__ == "__main__":
    unittest.main()
