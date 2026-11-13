"""检查控件入库边界、过滤后的层级和模型状态上下文，不连接模型或手机。"""
import json
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock

from atestservice.contracts.observation import DeviceObservation
from atestservice.exploration.context.ui_state import render_ui_state
from atestservice.exploration.observations.store import ObservationStore
from atestservice.ui.elements import normalize_elements
from atestservice.ui.coordinate import parse_bounds, to_normalized_bounds, to_pixel_bounds
from atestservice.ui.spatial import spatial_relation


def observation(elements):
    return DeviceObservation(id="obs", index=0, screen_size={"width": 1080, "height": 2420},
                             screenshot={"filename": "obs.jpg"}, elements=normalize_elements(elements, {"width": 1080, "height": 2420}))


class ElementTests(unittest.TestCase):
    def test_observation_stores_only_standard_fields_and_survives_reload(self):
        raw = [{"text": "蓝牙", "desc": "开关", "resourceId": "settings:id/switch",
                "className": "android.widget.Switch", "bounds": "[840,317][984,461]",
                "clickable": True, "checkable": " true ", "checked": False, "node_path": [1, 0]}]
        original = deepcopy(raw)
        saved = observation(raw)
        item = saved.elements[0]
        self.assertEqual(item["resource_id"], "settings:id/switch")
        self.assertEqual(item["description"], "开关")
        for actual, expected in zip(item["bounds"], [840 * 1000 / 1080, 317 * 1000 / 2420,
                                                    984 * 1000 / 1080, 461 * 1000 / 2420]):
            self.assertAlmostEqual(actual, expected)
        self.assertIs(item["checkable"], True)
        self.assertIs(item["checked"], False)
        self.assertIsNone(item["enabled"])
        self.assertNotIn("resourceId", item)
        self.assertEqual(raw, original)
        self.assertEqual(DeviceObservation.model_validate_json(saved.model_dump_json()).elements, saved.elements)
        saved.elements = normalize_elements(raw, {'width': 1080, 'height': 2420})
        self.assertEqual(saved.elements, observation(raw).elements)

    def test_nearest_retained_ancestor_does_not_cross_branches_or_windows(self):
        raw = [{"text": "蓝牙", "node_path": [1, 0]},
               {"resourceId": "switch", "node_path": [1, 0, 3, 2]},
               {"text": "其他行", "node_path": [1, 1]},
               {"text": "状态栏", "node_path": [2, 0]}]
        rows = normalize_elements(raw, {'width': 1080, 'height': 2420})
        self.assertEqual(rows[1]["parent_id"], "e0")
        self.assertIsNone(rows[2]["parent_id"])
        self.assertIsNone(rows[3]["parent_id"])
        self.assertEqual(rows[1]["node_path"], [1, 0, 3, 2])

    def test_ambiguous_or_invalid_paths_do_not_invent_parent_links(self):
        rows = normalize_elements([
            {"text": "甲", "node_path": [1, 0]}, {"text": "乙", "node_path": [1, 0]},
            {"text": "子项", "node_path": [1, 0, 2]},
            {"text": "异常", "node_path": [True, -1]},
        ], {'width': 1080, 'height': 2420})
        self.assertIsNone(rows[2]["parent_id"])
        self.assertIsNone(rows[3]["node_path"])

    def test_invalid_values_remain_unknown_without_dropping_other_evidence(self):
        rows = normalize_elements([
            None, {"text": "目标", "bounds": "[20,20][10,30]", "checked": 0, "desc": 123},
            {"text": "其他", "bounds": "[0,0][10,10] 999", "checked": "false"},
        ], {'width': 1080, 'height': 2420})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text"], "目标")
        self.assertIsNone(rows[0]["bounds"])
        self.assertIsNone(rows[0]["checked"])
        self.assertIsNone(rows[0]["description"])
        self.assertIsNone(rows[1]["bounds"])
        self.assertIs(rows[1]["checked"], False)

    def test_ordinary_false_states_cannot_push_switch_out_of_context(self):
        saved = observation([
            *[{"resourceId": f"container{i}", "checkable": False, "checked": False, "enabled": True}
              for i in range(70)],
            {"resourceId": "switch", "checkable": True, "checked": False, "clickable": True},
        ])
        original = deepcopy(saved.elements)
        state = json.loads(render_ui_state(saved.model_dump(), limit=60))
        self.assertEqual(state["controls"][0]["resource_id"], "switch")
        self.assertIs(state["controls"][0]["checked"], False)
        self.assertEqual(state["omitted"], 11)
        self.assertEqual(saved.elements, original)

    def test_legacy_parent_ids_are_not_used_without_tree_paths(self):
        rows = normalize_elements([
            {"id": "row", "text": "区域"},
            {"text": "开关", "parent_id": "row", "parentId": "row"},
        ], {"width": 1080, "height": 2420})
        self.assertIsNone(rows[1]["parent_id"])


class CoordinateTests(unittest.TestCase):
    def test_small_bounds_keep_precision_and_round_trip_without_mutation(self):
        size = {"width": 1080, "height": 2420}
        pixels = [840, 317, 841, 318]
        normalized = to_normalized_bounds(pixels, size)
        original = normalized[:]
        self.assertGreater(normalized[2], normalized[0])
        self.assertGreater(normalized[3], normalized[1])
        self.assertNotEqual(normalized[1], round(normalized[1]))
        self.assertEqual(parse_bounds(normalized), normalized)
        self.assertEqual(parse_bounds("[1.25,2.5][3.75,4.125]"), [1.25, 2.5, 3.75, 4.125])
        for actual, expected in zip(to_pixel_bounds(normalized, size), pixels):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(pixels, [840, 317, 841, 318])
        self.assertEqual(normalized, original)

    def test_conversion_requires_dimensions_instead_of_silently_mixing_units(self):
        for size in (None, {}, {"width": 0, "height": 2420}):
            for convert in (to_normalized_bounds, to_pixel_bounds):
                with self.subTest(size=size, convert=convert.__name__):
                    with self.assertRaises(ValueError):
                        convert([0, 0, 10, 10], size)

    def test_nearby_distance_respects_screen_aspect_ratio(self):
        size = observation([]).screen_size
        target = [100, 100, 200, 200]
        horizontal = spatial_relation(target, [214, 100, 224, 110], size)
        vertical = spatial_relation(target, [100, 214, 110, 224], size)
        self.assertEqual(horizontal["relation"], "nearby")
        self.assertEqual(vertical["relation"], "weak_or_distant")
        self.assertAlmostEqual(horizontal["gap_pixels"], 15.12)
        self.assertAlmostEqual(vertical["gap_pixels"], 33.88)


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_standardizes_once_without_extra_device_calls(self):
        client = AsyncMock()
        client.status.return_value = {"width": 1080, "height": 2420}
        client.screenshot.return_value = {"image": "YQ=="}
        client.page_elements.return_value = {"elements": [{"resourceId": "switch", "checked": False}]}
        saved = await ObservationStore(client).observe(index=0)
        self.assertEqual(saved.elements[0]["resource_id"], "switch")
        self.assertIs(saved.elements[0]["checked"], False)
        self.assertEqual([call[0] for call in client.mock_calls], ["status", "screenshot", "page_elements"])
