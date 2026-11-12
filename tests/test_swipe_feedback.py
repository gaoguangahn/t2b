"""Recorded page feedback helps parameter decisions without claiming task success."""
import unittest
from copy import deepcopy

from atestservice.contracts.case import CaseSpec
from atestservice.contracts.observation import DeviceObservation
from atestservice.exploration.context.swipe_feedback import last_swipe_feedback
from test_exploration_controls import make_node


def label(text, y, **extra):
    return {"text": text, "resourceId": "app:id/row", "bounds": [100, y, 300, y + 100], **extra}


def snapshot(identifier, elements):
    return {"id": identifier, "package": "app", "activity": "List",
            "screen_size": {"width": 1000, "height": 2000}, "elements": elements}


def trace(before, after, *, args=None):
    return {"observations": [snapshot("o0", before), snapshot("o1", after)], "operations": [{
        "id": "op0", "semantic_ref": {"step_id": "s1", "instruction_id": "i1"},
        "action": {"type": "swipe", "args": args or {"direction": "down", "times": 1}},
        "execution": {"status": "succeeded"},
        "observation_transition": {"before_observation_id": "o0", "after_observation_id": "o1"}}]}


def feedback(trajectory, **extra):
    return last_swipe_feedback(trajectory, step_id="s1", instruction_id="i1",
                               current_observation_id=extra.pop("current_observation_id", "o1"), **extra)


class SwipeFeedbackTests(unittest.TestCase):
    def test_real_label_positions_and_changes_do_not_claim_a_correct_direction(self):
        trajectory = trace([label("标题", 0), label("条目甲", 800), label("条目乙", 1700)],
                           [label("标题", 0), label("条目甲", 400), label("条目丙", 1500)])
        original = deepcopy(trajectory)
        result = feedback(trajectory)
        self.assertEqual(result["requested_args"]["direction"], "down")
        self.assertEqual(result["moved_labels"], [{"label": "条目甲", "before_center": [200, 425], "after_center": [200, 225]}])
        self.assertEqual(result["newly_visible_labels"], ["条目丙"])
        self.assertEqual(result["no_longer_visible_labels"], ["条目乙"])
        self.assertFalse(result["readable_markers_unchanged"])
        self.assertNotIn("direction_correct", result)
        self.assertNotIn("goal_completed", result)
        self.assertEqual(trajectory, original)

    def test_no_labels_and_unchanged_labels_do_not_prove_a_scroll_boundary(self):
        result = feedback(trace([], []))
        self.assertEqual(result["comparison"], "insufficient_labels")
        self.assertNotIn("readable_markers_unchanged", result)
        result = feedback(trace([label("标题", 0)], [label("标题", 0)]))
        self.assertTrue(result["readable_markers_unchanged"])
        self.assertNotIn("at_boundary", result)

    def test_duplicate_identities_cannot_prove_which_control_moved(self):
        result = feedback(trace([label("标题", 0), label("同名条目", 500), label("同名条目", 1000)],
                                [label("标题", 0), label("同名条目", 200), label("同名条目", 700)]))
        self.assertEqual(result["moved_labels"], [])
        self.assertNotIn("同名条目", str(result))

    def test_observe_refresh_keeps_the_recorded_pair_explicitly_noncurrent(self):
        trajectory = trace([label("条目甲", 800)], [label("条目甲", 400)])
        trajectory["observations"].append(snapshot("refresh", [label("其他", 300)]))
        result = feedback(trajectory, current_observation_id="refresh")
        self.assertFalse(result["is_current_frame"])
        self.assertEqual(result["after_observation_id"], "o1")
        self.assertEqual(result["moved_labels"][0]["label"], "条目甲")

    def test_do_not_compare_different_foregrounds_or_viewports_as_scrolling(self):
        for key, value, expected in (("activity", "Other", "foreground_changed"),
                                     ("screen_size", {"width": 2000, "height": 1000}, "viewport_changed")):
            trajectory = trace([label("条目甲", 800)], [label("条目甲", 400)])
            trajectory["observations"][1][key] = value
            result = feedback(trajectory)
            self.assertEqual(result["comparison"], expected)
            self.assertNotIn("moved_labels", result)

    def test_feedback_stops_at_an_intervening_action_or_instruction(self):
        trajectory = trace([label("甲", 800)], [label("甲", 400)])
        for reference in ({"step_id": "s2", "instruction_id": "i1"}, {"step_id": "s1", "instruction_id": "i2"}):
            trajectory["operations"][-1]["semantic_ref"] = reference
            self.assertIsNone(feedback(trajectory))
        trajectory["operations"][-1]["semantic_ref"] = {"step_id": "s1", "instruction_id": "i1"}
        trajectory["operations"][-1]["action"] = {"type": "click", "args": {}}
        self.assertIsNone(feedback(trajectory))

    def test_missing_observation_and_offscreen_controls_remain_unknown(self):
        trajectory = trace([label("不可见", 2500)], [label("不可见", 2200)])
        self.assertEqual(feedback(trajectory)["comparison"], "insufficient_labels")
        trajectory["observations"].pop()
        self.assertEqual(feedback(trajectory)["comparison"], "missing_observation")


class SwipeLoopFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_reaches_next_decision_without_extra_calls_images_or_parameter_rewrites(self):
        node, llm = make_node([
            ("DirectionSwipe", {"direction": "down", "times": 1}),
            ("DirectionSwipe", {"direction": "up", "times": 1}),
            ("CompleteStep", {"summary": "目标可见"}),
        ])
        async def observe(*, index):
            return DeviceObservation(id=f"o{index}", index=index, screen_size={"width": 1000, "height": 2000},
                screenshot={"filename": f"{index}.jpg", "base64": "YQ=="},
                elements=[label("参照条目", [800, 1200, 600][index])])
        node.step_loop.observation_store.observe = observe
        case = CaseSpec(case_name="查找条目", steps=[{"id": "s1", "goal": "滑动查找指定条目"}])
        state = await node({"case_spec": case.model_dump(mode="json")})
        self.assertEqual(len(llm.requests), 3)
        self.assertNotIn("最近滑动前后UI参考", llm.requests[0][1]["content"])
        text = llm.requests[1][1]["content"]
        self.assertIn("最近滑动前后UI参考", text)
        self.assertIn('"direction": "down"', text)
        self.assertIn('"before_center": [200.0, 425.0]', text)
        self.assertIn('"after_center": [200.0, 625.0]', text)
        self.assertEqual([item["action"]["args"]["direction"] for item in state["trajectory"]["operations"]], ["down", "up"])
        self.assertEqual(node.step_loop.executor.execute.await_count, 2)
        for messages in llm.requests:
            images = [block for message in messages if isinstance(message.get("content"), list)
                      for block in message["content"] if block.get("type") == "image_url"]
            self.assertEqual(len(images), 1)
