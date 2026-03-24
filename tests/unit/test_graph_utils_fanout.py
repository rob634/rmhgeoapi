"""Tests for fan-out child filtering in graph utilities — COMPETE Run 53 H5."""
from core.dag_graph_utils import build_adjacency, TaskSummary
from core.models.workflow_enums import WorkflowTaskStatus


def _ts(iid, name, status=WorkflowTaskStatus.PENDING, fan_out_source=None):
    """Helper to build TaskSummary."""
    return TaskSummary(
        task_instance_id=iid,
        task_name=name,
        status=status,
        handler="test_handler",
        fan_out_source=fan_out_source,
        fan_out_index=None,
        result_data=None,
    )


class TestBuildAdjacencyFanOutFiltering:
    def test_fan_out_children_do_not_corrupt_adjacency(self):
        """Fan-out children share task_name with template.
        build_adjacency must not let children overwrite template in name-based structures."""
        template = _ts("tmpl-1", "process_tiles", WorkflowTaskStatus.EXPANDED)
        child_0 = _ts("child-0", "process_tiles", WorkflowTaskStatus.COMPLETED, fan_out_source="tmpl-1")
        child_1 = _ts("child-1", "process_tiles", WorkflowTaskStatus.COMPLETED, fan_out_source="tmpl-1")
        downstream = _ts("aggregate", "merge_results", WorkflowTaskStatus.PENDING)

        tasks = [template, child_0, child_1, downstream]
        # downstream depends on template (not children directly — fan-in handles children)
        deps = [("aggregate", "tmpl-1")]

        adjacency = build_adjacency(tasks, deps)

        # "merge_results" should depend on "process_tiles" (the template name)
        assert "process_tiles" in adjacency["merge_results"]
        # Template should appear as a key (not overwritten by children)
        assert "process_tiles" in adjacency

    def test_simple_dag_without_fanout_unchanged(self):
        """Normal DAG without fan-out should work exactly as before."""
        a = _ts("a-1", "download")
        b = _ts("b-1", "process")
        c = _ts("c-1", "upload")

        tasks = [a, b, c]
        deps = [("b-1", "a-1"), ("c-1", "b-1")]

        adjacency = build_adjacency(tasks, deps)

        assert adjacency["download"] == set()
        assert adjacency["process"] == {"download"}
        assert adjacency["upload"] == {"process"}
