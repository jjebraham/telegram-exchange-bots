import unittest
from runpod_systemd_guard import SupervisionError, duration_seconds, validate_properties


class SystemdGuardTests(unittest.TestCase):
    def test_accepts_equivalent_bounded_time_formats(self):
        for text in ('7min', '7min 0s', '420s', '420000000'):
            with self.subTest(text=text):
                self.assertEqual(duration_seconds(text), 420)
                self.assertTrue(validate_properties('MainPID=42\nActiveState=active\nRuntimeMaxUSec=' + text, 42))
    def test_rejects_unbounded_or_wrong_process(self):
        for text in ('infinity', '0', '8min', '-2s', '7min junk'):
            with self.subTest(text=text), self.assertRaises(SupervisionError):
                validate_properties('MainPID=42\nActiveState=active\nRuntimeMaxUSec=' + text, 42)
        with self.assertRaises(SupervisionError):
            validate_properties('MainPID=41\nActiveState=active\nRuntimeMaxUSec=7min', 42)
        with self.assertRaises(SupervisionError):
            validate_properties('MainPID=42\nMainPID=42\nActiveState=active\nRuntimeMaxUSec=7min', 42)


if __name__ == '__main__': unittest.main()
