"""Account and session storage checks for the dashboard login."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from vitals import auth


class PasswordTest(unittest.TestCase):
    def test_hash_round_trip(self):
        stored = auth.hash_password("correct-horse")
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertTrue(auth.verify_password("correct-horse", stored))
        self.assertFalse(auth.verify_password("correct-horsE", stored))
        self.assertFalse(auth.verify_password("", stored))

    def test_hash_never_contains_the_plain_password(self):
        stored = auth.hash_password("plain-text-secret")
        self.assertNotIn("plain-text-secret", stored)
        self.assertNotEqual(auth.hash_password("same-password"), auth.hash_password("same-password"))

    def test_short_and_malformed_passwords_are_rejected(self):
        with self.assertRaises(auth.AuthError):
            auth.hash_password("short")
        with self.assertRaises(auth.AuthError):
            auth.hash_password(None)
        for stored in ("", "garbage", "md5$1$2$3$4$5", "scrypt$x$8$1$00$00"):
            self.assertFalse(auth.verify_password("whatever", stored))

    def test_unknown_account_spends_verification_work(self):
        # No exception, and it must not claim success for any password.
        auth.spend_verification("anything")
        self.assertFalse(auth.verify_password("anything", auth.hash_password("something-else")))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "auth.sqlite3"
        self.store = auth.AuthStore(self.path, session_hours=12)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_user_lifecycle(self):
        self.assertEqual(self.store.count_users(), 0)
        self.assertTrue(self.store.add_user("alice", "correct-horse"))
        self.assertFalse(self.store.add_user("alice", "another-password"))
        self.assertTrue(self.store.has_user("alice"))
        self.assertTrue(self.store.authenticate("alice", "correct-horse"))
        self.assertFalse(self.store.authenticate("alice", "wrong-password"))
        self.assertFalse(self.store.authenticate("missing", "correct-horse"))
        self.assertTrue(self.store.add_user("alice", "brand-new-pass", replace=True))
        self.assertFalse(self.store.authenticate("alice", "correct-horse"))
        self.assertTrue(self.store.authenticate("alice", "brand-new-pass"))
        self.assertTrue(self.store.delete_user("alice"))
        self.assertFalse(self.store.delete_user("alice"))
        self.assertFalse(self.store.has_user("alice"))

    def test_list_users_returns_named_fields(self):
        self.store.add_user("bob", "correct-horse")
        users = self.store.list_users()
        self.assertEqual([user["username"] for user in users], ["bob"])
        self.assertGreater(users[0]["created_at"], 0)
        self.assertGreater(users[0]["updated_at"], 0)

    def test_username_and_password_rules(self):
        for name in ("", "has space", "x" * 65, "sla/sh", None, 5):
            with self.assertRaises(auth.AuthError):
                self.store.add_user(name, "correct-horse")
        with self.assertRaises(auth.AuthError):
            self.store.add_user("bob", "short")

    def test_session_is_stored_only_as_a_digest(self):
        self.store.add_user("alice", "correct-horse")
        token = self.store.create_session("alice")
        rows = self.store.connection.execute("SELECT token_hash, username FROM sessions").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, rows[0][0])
        self.assertEqual(self.store.resolve_session(token), "alice")
        self.assertIsNone(self.store.resolve_session(token + "x"))
        self.assertIsNone(self.store.resolve_session(""))
        self.assertIsNone(self.store.resolve_session(None))

    def test_logout_and_user_deletion_revoke_sessions(self):
        self.store.add_user("alice", "correct-horse")
        first = self.store.create_session("alice")
        second = self.store.create_session("alice")
        self.assertTrue(self.store.delete_session(first))
        self.assertIsNone(self.store.resolve_session(first))
        self.assertEqual(self.store.resolve_session(second), "alice")
        self.store.delete_user("alice")
        self.assertIsNone(self.store.resolve_session(second))
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_password_change_revokes_existing_sessions(self):
        self.store.add_user("alice", "correct-horse")
        token = self.store.create_session("alice")
        self.assertEqual(self.store.resolve_session(token), "alice")
        self.store.add_user("alice", "brand-new-pass", replace=True)
        self.assertIsNone(self.store.resolve_session(token))
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_expired_session_is_rejected_by_a_fresh_store(self):
        self.store.add_user("alice", "correct-horse")
        token = self.store.create_session("alice")
        with self.store.connection:
            self.store.connection.execute("UPDATE sessions SET expires_at = 1 WHERE username = 'alice'")
        # A second connection starts with an empty cache, like a restarted service.
        reopened = auth.AuthStore(self.path)
        try:
            self.assertIsNone(reopened.resolve_session(token))
            self.assertEqual(reopened.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
        finally:
            reopened.close()

    def test_prune_sessions_removes_only_expired_entries(self):
        self.store.add_user("alice", "correct-horse")
        live = self.store.create_session("alice")
        stale = self.store.create_session("alice")
        with self.store.connection:
            self.store.connection.execute("UPDATE sessions SET expires_at = 5 WHERE token_hash = ?",
                                          (auth.token_digest(stale),))
        self.assertEqual(self.store.prune_sessions(), 1)
        self.assertEqual(self.store.resolve_session(live), "alice")
        reopened = auth.AuthStore(self.path)
        try:
            self.assertIsNone(reopened.resolve_session(stale))
        finally:
            reopened.close()

    def test_session_lifetime_is_bounded(self):
        self.assertGreaterEqual(auth.AuthStore(self.path, session_hours=0.001).session_ttl, 300)
        self.assertEqual(auth.AuthStore(self.path, session_hours=12).session_ttl, 12 * 3600)


if __name__ == "__main__":
    unittest.main()
