import unittest

from hatchet.workflows.run_metadata import device_group_trigger_options, run_trigger_options


class RunTriggerOptionsTests(unittest.TestCase):
    def test_all_values_are_strings(self) -> None:
        options = run_trigger_options(
            run_id=42, workflow_name="Backup", trigger_type="manual", parent_run_id=7
        )
        self.assertEqual(
            options.additional_metadata,
            {
                "run_id": "42",
                "trigger_type": "manual",
                "workflow_name": "Backup",
                "parent_run_id": "7",
            },
        )

    def test_optional_keys_omitted(self) -> None:
        options = run_trigger_options(run_id=1, workflow_name=None, trigger_type="scheduled")
        self.assertEqual(options.additional_metadata, {"run_id": "1", "trigger_type": "scheduled"})

    def test_device_group_children_reference_parent(self) -> None:
        options = device_group_trigger_options(parent_run_id=9, child_index=3)
        self.assertEqual(options.additional_metadata["parent_run_id"], "9")
        self.assertEqual(options.additional_metadata["child_index"], "3")


if __name__ == "__main__":
    unittest.main()
