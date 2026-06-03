import unittest

import cloud.aws_s3_service as cloud_service
from auth.permissions import can


class CloudPermissionTests(unittest.TestCase):

    def test_only_admin_can_manage_cloud_connection(self):
        self.assertTrue(
            can({"username": "admin", "role": "admin"}, "manage_cloud_connection")
        )
        self.assertFalse(
            can({"username": "dudu", "role": "operator"}, "manage_cloud_connection")
        )
        self.assertFalse(
            can({"username": "ana", "role": "viewer"}, "manage_cloud_connection")
        )

    def test_operator_can_manage_directories_and_backup_destination(self):
        operator = {"username": "dudu", "role": "operator"}

        self.assertTrue(can(operator, "manage_directories"))
        self.assertTrue(can(operator, "change_backup_destination"))
        self.assertFalse(can(operator, "manage_users"))

    def test_backend_rejects_non_admin_cloud_configuration(self):
        with self.assertRaises(cloud_service.CloudPermissionError):
            cloud_service.save_cloud_settings_for_user(
                {"username": "dudu", "role": "operator"},
                {"enabled": False}
            )


if __name__ == "__main__":
    unittest.main()
