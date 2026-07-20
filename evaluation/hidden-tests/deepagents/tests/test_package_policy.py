import unittest

from package_policy import package_for_feature


class PackagePolicyHiddenTests(unittest.TestCase):
    def test_context_command_uses_code_package(self):
        self.assertEqual(package_for_feature("context_command"), "code")

    def test_startup_tip_uses_code_package(self):
        self.assertEqual(package_for_feature("startup_tip"), "code")

    def test_deployment_command_stays_in_cli_package(self):
        self.assertEqual(package_for_feature("deployment_command"), "cli")
