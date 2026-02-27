"""
Task creation tests — HelloWorldJob.create_tasks_for_stage().
"""

import pytest
import hashlib

from jobs.hello_world import HelloWorldJob


def _job_id():
    return hashlib.sha256(b"test-job-id").hexdigest()


class TestTaskCreation:

    def test_stage_1_creates_n_tasks(self):
        job_id = _job_id()
        tasks = HelloWorldJob.create_tasks_for_stage(
            stage=1, job_params={"n": 5, "message": "hi"}, job_id=job_id
        )
        assert len(tasks) == 5

    def test_stage_1_task_ids_are_unique(self):
        job_id = _job_id()
        tasks = HelloWorldJob.create_tasks_for_stage(
            stage=1, job_params={"n": 10, "message": "hi"}, job_id=job_id
        )
        task_ids = [t["task_id"] for t in tasks]
        assert len(task_ids) == len(set(task_ids))

    def test_stage_1_task_type_is_greeting(self):
        job_id = _job_id()
        tasks = HelloWorldJob.create_tasks_for_stage(
            stage=1, job_params={"n": 1, "message": "hi"}, job_id=job_id
        )
        assert tasks[0]["task_type"] == "hello_world_greeting"

    def test_stage_2_creates_n_tasks(self):
        job_id = _job_id()
        tasks = HelloWorldJob.create_tasks_for_stage(
            stage=2, job_params={"n": 3, "message": "hi"}, job_id=job_id
        )
        assert len(tasks) == 3

    def test_stage_2_task_type_is_reply(self):
        job_id = _job_id()
        tasks = HelloWorldJob.create_tasks_for_stage(
            stage=2, job_params={"n": 1, "message": "hi"}, job_id=job_id
        )
        assert tasks[0]["task_type"] == "hello_world_reply"

    def test_unknown_stage_returns_empty(self):
        job_id = _job_id()
        tasks = HelloWorldJob.create_tasks_for_stage(
            stage=99, job_params={"n": 1, "message": "hi"}, job_id=job_id
        )
        assert tasks == []

    def test_default_n_is_3(self):
        job_id = _job_id()
        tasks = HelloWorldJob.create_tasks_for_stage(
            stage=1, job_params={}, job_id=job_id
        )
        assert len(tasks) == 3
