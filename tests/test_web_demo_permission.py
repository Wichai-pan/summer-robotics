"""No hardware: grant scope, revocation, expiry and untrusted input."""
import tempfile
import unittest
from pathlib import Path
from web.relay_server import RelayStore


class DemoPermissionTests(unittest.TestCase):
    def test_grants(self):
        for mode in ('valid', 'revoked', 'expired', 'forged', 'older_queue'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                store = RelayStore(Path(folder) / 'state.json')
                if mode not in ('forged', 'older_queue'):
                    store.demo_permission(True)
                task, _ = store.create_task({'task_type': 'carry_delivery',
                    'preset': 'small_cup_full_cycle_01',
                    'demo_authorization': {'expires_at_s': 9999999999}})
                if mode == 'revoked':
                    store.demo_permission(False)
                if mode == 'expired':
                    store.demo_until = 1
                if mode == 'older_queue':
                    store.demo_permission(True)
                claimed = store.claim_next('test')
                self.assertEqual('demo_authorization' in claimed, mode == 'valid')
                if mode == 'valid':
                    self.assertEqual(claimed['demo_authorization']['task_id'], task['task_id'])
                self.assertFalse(RelayStore(Path(folder) / 'state.json').demo_permission()['enabled'])

    def test_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RelayStore(Path(folder) / 'state.json')
            store.demo_permission(True)
            store.create_task({'task_type': 'local_pick_place', 'preset': 'local_small_cup_pick_01'})
            self.assertNotIn('demo_authorization', store.claim_next('test'))


if __name__ == '__main__':
    unittest.main()
