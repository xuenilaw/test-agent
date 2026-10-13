# Use the corrected Excel directly
Status: IN REVIEW
Workflow step(s): 1 Read test case, 1b Translate

## Handoff (Codex)
### Goal
Remove the temporary amendment layer now that the user has updated the project workbook.
The user suggested a future case-review agent; it is not part of this change.

### What changed
- `cases/osm/WBS_testcase1_osm.xlsx`: user's updated input already contains all three confirmed corrections.
  It was inspected, not edited by Codex. Downloads still contains the older copy.
- `cases/osm/amendments.json`: removed.
- `src/test_agent/readers/excel.py`: removed amendment loading and patching.
- `src/test_agent/cli.py`: removed `--amendments`; translation and validation use the workbook directly.
  New `source.json` stores `case`, `contract`, and `application_url`, without duplicated original/effective data.
- `src/test_agent/translation/translator.py`: expectations now explicitly come from the workbook.
- `tests/`: confirm workbook/reference consistency, direct source evidence, and rejection of the removed option.
- `README.md`: updated command and explanation of the current input format.

### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent translate --help
uv run python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx
```
The first two commands are offline; the last requires the configured GLM provider.

### Test output
Required command run with a writable UV_CACHE_DIR in the sandbox:
```text
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_removed_amendment_option_is_rejected (test_cli.PackageCliTests.test_removed_amendment_option_is_rejected) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
test_arbitrary_code_action_is_rejected (test_translation.TranslationValidationTests.test_arbitrary_code_action_is_rejected) ... ok
test_comparator_cannot_replace_expected_driving_mode (test_translation.TranslationValidationTests.test_comparator_cannot_replace_expected_driving_mode) ... ok
test_duration_limit_cannot_be_relaxed_or_tightened (test_translation.TranslationValidationTests.test_duration_limit_cannot_be_relaxed_or_tightened) ... ok
test_inclusive_duration_is_rejected (test_translation.TranslationValidationTests.test_inclusive_duration_is_rejected) ... ok
test_missing_cleanup_field_is_rejected (test_translation.TranslationValidationTests.test_missing_cleanup_field_is_rejected) ... ok
test_missing_field_check_is_rejected (test_translation.TranslationValidationTests.test_missing_field_check_is_rejected) ... ok
test_missing_step_is_rejected (test_translation.TranslationValidationTests.test_missing_step_is_rejected) ... ok
test_model_cannot_claim_test_pass (test_translation.TranslationValidationTests.test_model_cannot_claim_test_pass) ... ok
test_rewritten_source_is_rejected (test_translation.TranslationValidationTests.test_rewritten_source_is_rejected) ... ok
test_submit_before_fill_is_rejected (test_translation.TranslationValidationTests.test_submit_before_fill_is_rejected) ... ok
test_swapped_origin_destination_is_rejected (test_translation.TranslationValidationTests.test_swapped_origin_destination_is_rejected) ... ok
test_unnumbered_and_duplicate_steps_rejected (test_translation.TranslationValidationTests.test_unnumbered_and_duplicate_steps_rejected) ... ok
test_unresolved_issue_blocks_plan (test_translation.TranslationValidationTests.test_unresolved_issue_blocks_plan) ... ok
test_valid_translation_and_nonblocking_notes (test_translation.TranslationValidationTests.test_valid_translation_and_nonblocking_notes) ... ok
test_workbook_requirements_match_reviewed_reference (test_translation.TranslationValidationTests.test_workbook_requirements_match_reviewed_reference) ... ok
test_wrong_city_is_rejected (test_translation.TranslationValidationTests.test_wrong_city_is_rejected) ... ok

----------------------------------------------------------------------
Ran 22 tests in 0.753s

OK
```
Also verified CLI help and `git diff --check`. No live LLM or browser was needed for the tests.

### Known limitations / open questions
- Contract validation remains in place; when requirements change, align the contract and regenerate the plan.
- Older translation artifacts retain their historical original/effective/amendments format; they were not migrated.
- The Plan Loader, OSM locator mappings, and case-review agent have not been implemented in this change.
- The user explicitly authorized committing and pushing this change together with the folder
  restructuring. Claude review remains pending; status is not APPROVED.
