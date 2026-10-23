import json

from validation.configuration import ProfileConfiguration
from validation.evaluator import ValidationCase, ValidationDataset, ValidationEvaluator, build_regression_dataset


def test_dataset_round_trip_and_no_key_evaluation(tmp_path):
    dataset = ValidationDataset("sample", [ValidationCase("one", "req.txt", b"The system shall log events.", {"document_type": "requirement"})])
    path = tmp_path / "dataset.json"
    dataset.save(path)
    loaded = ValidationDataset.load(path)
    report = ValidationEvaluator().evaluate(loaded)
    assert report["case_count"] == 1
    assert "extraction_recall" in report["metrics"]


def test_regression_dataset_and_profile_configuration(tmp_path):
    dataset = build_regression_dataset()
    assert {"txt", "xml", "c", "markdown", "json"} <= {case.name for case in dataset.cases}
    config = ProfileConfiguration(tmp_path / "profiles.json")
    config.update("gt44", {"rules": [{"id": "GT44-SAMPLE-001", "severity": "low", "applicability": "requirement"}]})
    assert config.get("gt44")["sample_rules"] is True


def test_metrics_are_bounded_and_exports_work():
    report = ValidationEvaluator().evaluate(build_regression_dataset())
    assert all(0 <= value <= 1 for value in report["metrics"].values() if isinstance(value, (int, float)))
    assert json.loads(ValidationEvaluator.report_json(report))["case_count"] == len(build_regression_dataset().cases)
    assert ValidationEvaluator.report_excel(report)
