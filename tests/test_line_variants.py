import importlib
import unittest

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

api = importlib.import_module("custom_components.vigobus.api")
gtfs = importlib.import_module("custom_components.vigobus.gtfs")


class SplitLineVariantTests(unittest.TestCase):
    def test_line_a_with_numeric_route_prefix_becomes_a1(self):
        self.assertEqual(
            api.split_line_variant("A", "1 P.E.FADRIQUE por TORRECED"),
            ("A1", "P.E.FADRIQUE por TORRECED"),
        )

    def test_quoted_variant_is_split_for_any_line(self):
        self.assertEqual(
            api.split_line_variant("A", '"1" P.E.FADRIQUE por TORRECED'),
            ("A1", "P.E.FADRIQUE por TORRECED"),
        )
        self.assertEqual(
            api.split_line_variant("A", "“1” P.E.FADRIQUE"),
            ("A1", "P.E.FADRIQUE"),
        )
        self.assertEqual(api.split_line_variant("15", '"B" CENTRO'), ("15B", "CENTRO"))

    def test_quoted_variant_already_in_line_is_not_duplicated(self):
        self.assertEqual(api.split_line_variant("15", '"15B" X'), ("15B", "X"))
        self.assertEqual(api.split_line_variant("PSA1", '"1" X'), ("PSA1", "X"))

    def test_plain_line_a_route_is_untouched(self):
        self.assertEqual(
            api.split_line_variant("A", "PEINADOR - AEROPORTO"),
            ("A", "PEINADOR - AEROPORTO"),
        )

    def test_multi_letter_lines_are_never_split(self):
        self.assertEqual(
            api.split_line_variant("PSA1", "1 STELLANTIS"), ("PSA1", "1 STELLANTIS")
        )

    def test_numeric_lines_are_never_split(self):
        self.assertEqual(api.split_line_variant("15", "2 ALGO"), ("15", "2 ALGO"))


class GtfsLineNameTests(unittest.TestCase):
    def test_trailing_punctuation_variants_collapse_to_the_same_line(self):
        for raw in ("15A.", "4A-", "15A"):
            self.assertEqual(gtfs._normalize_line(raw), raw.rstrip(".-"))


if __name__ == "__main__":
    unittest.main()
