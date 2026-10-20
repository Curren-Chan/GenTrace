from __future__ import annotations

import unittest

import os

from gentrace.gpu import GpuSampler, NvmlSampler, _nvml_candidates, aggregate_engine_values, combine_utilization


class GpuTests(unittest.TestCase):
    def test_processes_on_same_engine_are_summed(self) -> None:
        values = [
            ("pid_1_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D", 35.0),
            ("pid_2_luid_0x00000000_0x00000001_phys_0_eng_0_engtype_3D", 25.0),
            ("pid_2_luid_0x00000000_0x00000001_phys_0_eng_1_engtype_Copy", 12.0),
        ]
        self.assertEqual(aggregate_engine_values(values), 60.0)

    def test_wrong_adapter_is_ignored_and_value_is_capped(self) -> None:
        values = [
            ("pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 80.0),
            ("pid_2_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 50.0),
            ("pid_3_luid_0x0_0x2_phys_1_eng_0_engtype_3D", 99.0),
        ]
        self.assertEqual(aggregate_engine_values(values, 0), 100.0)
        self.assertEqual(aggregate_engine_values(values, 1), 99.0)

    def test_busiest_source_wins_and_missing_sources_are_ignored(self) -> None:
        # eGPU: GPU Engine counters see only the iGPU while NVML sees CUDA load.
        self.assertEqual(combine_utilization(3.6, 82.0), 82.0)
        self.assertEqual(combine_utilization(None, 40.0), 40.0)
        self.assertEqual(combine_utilization(55.0, None), 55.0)
        self.assertIsNone(combine_utilization(None, None))

    @unittest.skipUnless(
        any(os.path.isfile(path) for path in _nvml_candidates()), "NVIDIA driver not installed"
    )
    def test_live_nvml_reads_utilization(self) -> None:
        sampler = NvmlSampler()
        try:
            self.assertTrue(sampler.available, sampler.error)
            value = sampler.sample()
            self.assertIsNotNone(value)
            self.assertTrue(0.0 <= value <= 100.0)
        finally:
            sampler.close()

    def test_live_counter_initializes_on_windows(self) -> None:
        sampler = GpuSampler(0)
        try:
            self.assertTrue(sampler.available, sampler.error)
        finally:
            sampler.close()


if __name__ == "__main__":
    unittest.main()
