from __future__ import annotations

import unittest

from aggregator.fedavg import fedavg


class FedAvgTests(unittest.TestCase):
    def test_equal_average(self) -> None:
        result = fedavg(
            [
                {"weights": [1.0, 3.0], "bias": 1.0},
                {"weights": [3.0, 5.0], "bias": 3.0},
            ]
        )

        self.assertEqual(result["weights"], [2.0, 4.0])
        self.assertEqual(result["bias"], 2.0)

    def test_weighted_average(self) -> None:
        result = fedavg(
            [
                {"weights": [0.0, 2.0], "bias": 0.0},
                {"weights": [10.0, 12.0], "bias": 10.0},
            ],
            example_counts=[1, 3],
        )

        self.assertEqual(result["weights"], [7.5, 9.5])
        self.assertEqual(result["bias"], 7.5)


if __name__ == "__main__":
    unittest.main()
