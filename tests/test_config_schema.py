"""Tests for the tolerant repo config interpretation."""

import unittest

from patchback.config_schema import CONFIG_FILE_NAME, coerce_config_mapping


FIELD_TYPES = {
    'backport_branch_prefix': str,
    'backport_label_prefix': str,
    'target_branch_prefix': str,
    'delete_label_on_success': bool,
    'max_backports': int,
}


class CoerceConfigMappingTestCase(unittest.TestCase):
    def test_well_formed_config_passes_through_unchanged(self):
        raw = {
            'backport_branch_prefix': 'bp/',
            'delete_label_on_success': True,
            'max_backports': 3,
        }

        self.assertEqual(coerce_config_mapping(raw, FIELD_TYPES), (raw, ()))

    def test_empty_config_file_yields_no_overrides(self):
        self.assertEqual(coerce_config_mapping(None, FIELD_TYPES), ({}, ()))
        self.assertEqual(coerce_config_mapping({}, FIELD_TYPES), ({}, ()))

    def test_unknown_option_is_dropped_and_reported(self):
        kwargs, warnings = coerce_config_mapping(
            {'backport_branch_prefix': 'bp/', 'nonsense': 'x'}, FIELD_TYPES,
        )

        self.assertEqual(kwargs, {'backport_branch_prefix': 'bp/'})
        self.assertEqual(len(warnings), 1)
        self.assertIn('`nonsense`', warnings[0])
        self.assertIn(CONFIG_FILE_NAME, warnings[0])

    def test_mistyped_option_name_gets_a_suggestion(self):
        _kwargs, warnings = coerce_config_mapping(
            {'backport_labelprefix': 'bp-'}, FIELD_TYPES,
        )

        self.assertIn('Did you mean `backport_label_prefix`?', warnings[0])

    def test_unknown_option_unlike_any_field_gets_no_suggestion(self):
        _kwargs, warnings = coerce_config_mapping(
            {'zzzzzzzz': 1}, FIELD_TYPES,
        )

        self.assertNotIn('Did you mean', warnings[0])

    def test_mistyped_option_falls_back_to_the_default(self):
        kwargs, warnings = coerce_config_mapping(
            # `target_branch_prefix: 1.0` is valid YAML, and interpolating
            # the float would have produced a `1.0`-prefixed branch name.
            {'target_branch_prefix': 1.0}, FIELD_TYPES,
        )

        self.assertEqual(kwargs, {})
        self.assertIn('expected str, got float', warnings[0])

    def test_null_value_falls_back_to_the_default(self):
        kwargs, warnings = coerce_config_mapping(
            # A bare `backport_branch_prefix:` line parses as ``None``.
            {'backport_branch_prefix': None}, FIELD_TYPES,
        )

        self.assertEqual(kwargs, {})
        self.assertIn('expected str, got NoneType', warnings[0])

    def test_boolean_is_not_accepted_where_an_int_is_expected(self):
        kwargs, warnings = coerce_config_mapping(
            # YAML turns `yes` into ``True``, and ``bool`` subclasses
            # ``int``, so a plain isinstance() check would let it through.
            {'max_backports': True}, FIELD_TYPES,
        )

        self.assertEqual(kwargs, {})
        self.assertIn('expected int, got bool', warnings[0])

    def test_int_is_not_accepted_where_a_bool_is_expected(self):
        kwargs, _warnings = coerce_config_mapping(
            {'delete_label_on_success': 1}, FIELD_TYPES,
        )

        self.assertEqual(kwargs, {})

    def test_non_mapping_config_is_discarded_wholesale(self):
        kwargs, warnings = coerce_config_mapping(
            ['backport_branch_prefix'], FIELD_TYPES,
        )

        self.assertEqual(kwargs, {})
        self.assertIn('expected a mapping of options, got list', warnings[0])

    def test_every_bad_option_is_reported_not_just_the_first(self):
        _kwargs, warnings = coerce_config_mapping(
            {'nope': 1, 'target_branch_prefix': 2, 'also_nope': 3},
            FIELD_TYPES,
        )

        self.assertEqual(len(warnings), 3)

    def test_unannotated_field_accepts_anything(self):
        kwargs, warnings = coerce_config_mapping(
            {'whatever': object}, {'whatever': None},
        )

        self.assertEqual(kwargs, {'whatever': object})
        self.assertEqual(warnings, ())


if __name__ == '__main__':
    unittest.main()
