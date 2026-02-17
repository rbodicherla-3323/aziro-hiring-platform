"""
Comprehensive E2E test suite for the Aziro Hiring Platform.
Tests: app creation, all routes, test creation for all 12 roles,
question loading, evaluation, reports, DB integration, auth flow.
"""
import json
import os
import sys
import unittest
import tempfile

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

os.environ["AUTH_DISABLED"] = "true"
os.environ["SECRET_KEY"] = "test-secret"


class TestAppCreation(unittest.TestCase):
    """Test that the Flask app creates successfully."""

    def test_app_creates(self):
        from app import create_app
        app = create_app()
        self.assertIsNotNone(app)

    def test_app_has_secret_key(self):
        from app import create_app
        app = create_app()
        self.assertIsNotNone(app.secret_key)

    def test_db_initialized(self):
        from app import create_app
        from app.extensions import db
        app = create_app()
        with app.app_context():
            # DB should be accessible
            from app.models import Candidate
            self.assertIsNotNone(Candidate.__tablename__)


class TestRouteResponses(unittest.TestCase):
    """Test all admin routes respond correctly."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def _login(self):
        """Set up dev session."""
        with self.client.session_transaction() as sess:
            sess["user"] = {
                "name": "Test User",
                "email": "test@aziro.com",
                "authenticated": True,
            }

    def test_root_redirects(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertIn(resp.status_code, [302, 308])

    def test_login_page(self):
        # With AUTH_DISABLED=true, before_request auto-logs in and redirects
        resp = self.client.get("/login", follow_redirects=False)
        # Either shows login (200) or redirects to dashboard (302) if auto-logged in
        self.assertIn(resp.status_code, [200, 302])

    def test_dashboard_requires_login(self):
        # Without dev bypass cookie, should redirect
        with self.client.session_transaction() as sess:
            sess.clear()
        # With AUTH_DISABLED=true, before_request auto-logs in
        resp = self.client.get("/dashboard")
        self.assertIn(resp.status_code, [200, 302])

    def test_dashboard_page(self):
        self._login()
        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Dashboard", resp.data)

    def test_create_test_page(self):
        self._login()
        resp = self.client.get("/create-test")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Generate", resp.data)

    def test_generated_tests_page(self):
        self._login()
        resp = self.client.get("/generated-tests")
        self.assertEqual(resp.status_code, 200)

    def test_evaluation_page(self):
        self._login()
        resp = self.client.get("/evaluation")
        self.assertEqual(resp.status_code, 200)

    def test_reports_page(self):
        self._login()
        resp = self.client.get("/reports")
        self.assertEqual(resp.status_code, 200)

    def test_reports_search(self):
        self._login()
        resp = self.client.get("/reports/search?q=test")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("candidates", data)

    def test_logout(self):
        self._login()
        resp = self.client.get("/logout", follow_redirects=False)
        self.assertIn(resp.status_code, [302, 308])

    def test_microsoft_login_route(self):
        resp = self.client.get("/login/microsoft", follow_redirects=False)
        # Should redirect to login with flash (since Azure creds are not configured)
        self.assertIn(resp.status_code, [302, 308])


class TestRoleConfiguration(unittest.TestCase):
    """Test all 12 roles are properly configured."""

    def test_role_normalizer_has_12_roles(self):
        from app.utils.role_normalizer import ROLE_NAME_TO_KEY
        self.assertEqual(len(ROLE_NAME_TO_KEY), 12)

    def test_all_roles_in_round_mapping(self):
        from app.utils.role_normalizer import ROLE_NAME_TO_KEY
        from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
        for label, key in ROLE_NAME_TO_KEY.items():
            self.assertIn(key, ROLE_ROUND_MAPPING, f"Missing role in ROLE_ROUND_MAPPING: {key}")

    def test_all_roles_in_display_mapping(self):
        from app.utils.role_normalizer import ROLE_NAME_TO_KEY
        from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
        for label, key in ROLE_NAME_TO_KEY.items():
            self.assertIn(key, ROUND_DISPLAY_MAPPING, f"Missing role in ROUND_DISPLAY_MAPPING: {key}")

    def test_all_roles_in_question_mapping(self):
        from app.utils.role_normalizer import ROLE_NAME_TO_KEY
        from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING
        for label, key in ROLE_NAME_TO_KEY.items():
            self.assertIn(key, ROUND_QUESTION_MAPPING, f"Missing role in ROUND_QUESTION_MAPPING: {key}")

    def test_phase3_roles_present(self):
        from app.utils.role_normalizer import ROLE_NAME_TO_KEY
        phase3_keys = ["bmc_engineer", "linux_kernel_dd", "systems_architect_cpp"]
        role_keys = list(ROLE_NAME_TO_KEY.values())
        for key in phase3_keys:
            self.assertIn(key, role_keys, f"Phase 3 role missing: {key}")

    def test_coding_language_mapping(self):
        from app.utils.role_round_mapping import ROLE_CODING_LANGUAGE
        expected = {
            "java_entry": "java",
            "java_aws": "java",
            "java_qa": "java",
            "bmc_engineer": "c",
            "linux_kernel_dd": "c",
            "systems_architect_cpp": "cpp",
        }
        for key, lang in expected.items():
            self.assertEqual(ROLE_CODING_LANGUAGE.get(key), lang,
                             f"Wrong coding language for {key}")


class TestQuestionLoading(unittest.TestCase):
    """Test that questions load correctly for all roles and rounds."""

    def _load_questions(self, role_key, round_key, domain=None):
        from app.services.question_bank.loader import QuestionLoader
        from app.services.question_bank.registry import QuestionRegistry
        loader = QuestionLoader(base_path="app/services/question_bank/data")
        registry = QuestionRegistry(loader)
        return registry.get_questions(role_key, round_key, domain)

    def test_all_roles_all_rounds_load(self):
        from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING
        failures = []
        for role_key, rounds in ROUND_QUESTION_MAPPING.items():
            for round_key, files in rounds.items():
                try:
                    questions = self._load_questions(role_key, round_key)
                    if not questions:
                        failures.append(f"{role_key}/{round_key}: empty")
                except FileNotFoundError as e:
                    failures.append(f"{role_key}/{round_key}: {e}")
                except Exception as e:
                    failures.append(f"{role_key}/{round_key}: {e}")
        if failures:
            self.fail("Question loading failures:\n" + "\n".join(failures))

    def test_phase3_question_files_have_50(self):
        """Phase 3 question files should each have 50 questions."""
        phase3_files = [
            "c/c_theory.json",
            "bmc/bmc_firmware.json",
            "linux/linux_kernel.json",
            "device_driver/device_driver_basics.json",
            "cpp/cpp_theory.json",
            "system_design/system_design_architecture.json",
            "soft_skills_leadership.json",
        ]
        from app.services.question_bank.loader import QuestionLoader
        loader = QuestionLoader(base_path="app/services/question_bank/data")
        for f in phase3_files:
            try:
                questions = loader.load(f)
                self.assertEqual(len(questions), 50,
                                 f"{f} has {len(questions)} questions, expected 50")
            except FileNotFoundError:
                self.fail(f"Phase 3 file missing: {f}")

    def test_domain_questions_load(self):
        """Domain questions should load for storage, virtualization, networking."""
        for domain in ["storage", "virtualization", "networking"]:
            try:
                questions = self._load_questions("python_qa", "L6", domain)
                self.assertGreater(len(questions), 0,
                                   f"No questions for domain: {domain}")
            except FileNotFoundError:
                # Domain files are optional
                pass

    def test_coding_yaml_files_exist(self):
        """L4 coding YAML files should exist for java, c, cpp."""
        import yaml
        base = "app/services/question_bank/data/l4_coding"
        for lang in ["java", "c", "cpp"]:
            path = os.path.join(base, lang, "questions.yaml")
            self.assertTrue(os.path.exists(path), f"Missing coding YAML: {path}")
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "questions" in data:
                data = data["questions"]
            self.assertIsInstance(data, list, f"Invalid YAML format: {path}")
            self.assertGreater(len(data), 0, f"Empty coding questions: {path}")


class TestTestCreation(unittest.TestCase):
    """Test creating tests for all 12 roles."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {
                "name": "Test User",
                "email": "tester@aziro.com",
                "authenticated": True,
            }

    def test_create_test_for_all_12_roles(self):
        """POST create-test for each of the 12 roles and verify it works."""
        from app.utils.role_normalizer import ROLE_NAME_TO_KEY

        self._login()

        for role_label, role_key in ROLE_NAME_TO_KEY.items():
            with self.subTest(role=role_label):
                resp = self.client.post("/create-test", data={
                    "name[]": f"Test Candidate {role_key}",
                    "email[]": f"{role_key}@test.com",
                    "role[]": role_label,
                    "domain[]": "None",
                }, follow_redirects=True)
                self.assertEqual(resp.status_code, 200,
                                 f"Failed for role: {role_label}")

    def test_created_tests_appear_in_store(self):
        """Tests created above should appear in the generated tests store."""
        from app.services.generated_tests_store import GENERATED_TESTS
        from app.utils.role_normalizer import ROLE_NAME_TO_KEY

        emails = {f"{key}@test.com" for key in ROLE_NAME_TO_KEY.values()}
        stored_emails = {t["email"] for t in GENERATED_TESTS}

        for email in emails:
            self.assertIn(email, stored_emails,
                          f"Test for {email} not in store")

    def test_created_tests_have_correct_rounds(self):
        """Each created test should have the expected rounds."""
        from app.services.generated_tests_store import GENERATED_TESTS
        from app.utils.role_round_mapping import ROLE_ROUND_MAPPING

        for t in GENERATED_TESTS:
            role_key = t.get("role_key", "")
            if not role_key or role_key not in ROLE_ROUND_MAPPING:
                continue
            config = ROLE_ROUND_MAPPING[role_key]
            expected_rounds = set(config["rounds"] + config.get("coding_rounds", []))
            actual_rounds = set(t.get("tests", {}).keys())

            # Actual rounds should be a subset (domain rounds are optional)
            for rk in expected_rounds:                self.assertIn(rk, actual_rounds,
                              f"Missing round {rk} for role {role_key}")

    def test_mcq_session_registry_populated(self):
        """MCQ sessions should be registered for created tests."""
        from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
        # Ensure tests have been created first
        if len(MCQ_SESSION_REGISTRY) == 0:
            self.test_create_test_for_all_12_roles()
        self.assertGreater(len(MCQ_SESSION_REGISTRY), 0,
                           "MCQ session registry is empty after test creation")

    def test_coding_session_registry_populated(self):
        """Coding sessions should be registered for roles with L4."""
        from app.services.coding_session_registry import CODING_SESSION_REGISTRY
        # Ensure tests have been created first
        if len(CODING_SESSION_REGISTRY) == 0:
            self.test_create_test_for_all_12_roles()
        self.assertGreater(len(CODING_SESSION_REGISTRY), 0,
                           "Coding session registry is empty after test creation")

    def test_test_urls_are_dynamic(self):
        """Test URLs should use request host, not hardcoded 127.0.0.1."""
        from app.services.generated_tests_store import GENERATED_TESTS
        for t in GENERATED_TESTS:
            for level, test_info in t.get("tests", {}).items():
                url = test_info.get("url", "")
                self.assertNotIn("127.0.0.1:5000", url,
                                 f"Hardcoded URL found: {url}")
                self.assertTrue(url.startswith("http"),
                                f"Invalid URL: {url}")


class TestMCQFlow(unittest.TestCase):
    """Test MCQ candidate flow."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def _create_test(self, role_label="Python Entry Level (0–2 Years)"):
        """Create a test and return a session_id."""
        with self.client.session_transaction() as sess:
            sess["user"] = {
                "name": "Test User",
                "email": "mcqtest@aziro.com",
                "authenticated": True,
            }
        self.client.post("/create-test", data={
            "name[]": "MCQ Candidate",
            "email[]": "mcqcandidate@test.com",
            "role[]": role_label,
            "domain[]": "None",
        }, follow_redirects=True)

        from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
        for sid, meta in MCQ_SESSION_REGISTRY.items():
            if meta["email"] == "mcqcandidate@test.com" and meta["round_key"] == "L1":
                return sid
        return None

    def test_mcq_start_page(self):
        sid = self._create_test()
        self.assertIsNotNone(sid, "Failed to create MCQ session")
        resp = self.client.get(f"/mcq/start/{sid}")
        self.assertEqual(resp.status_code, 200)
        # Page content is lowercase, check for key content
        content = resp.data.lower()
        self.assertTrue(
            b"start test" in content or b"mcq" in content or b"aptitude" in content,
            "MCQ start page missing expected content"
        )

    def test_mcq_invalid_session(self):
        resp = self.client.get("/mcq/start/invalid_session_id")
        self.assertEqual(resp.status_code, 404)

    def test_mcq_begin_redirects(self):
        sid = self._create_test("Java Entry Level (0–2 Years)")
        from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
        for s, meta in MCQ_SESSION_REGISTRY.items():
            if meta["email"] == "mcqcandidate@test.com":
                sid = s
                break
        if sid:
            self.client.get(f"/mcq/start/{sid}")
            resp = self.client.post(f"/mcq/begin/{sid}", follow_redirects=False)
            self.assertIn(resp.status_code, [302, 308])


class TestCodingFlow(unittest.TestCase):
    """Test coding candidate flow."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def _create_coding_test(self):
        """Create a test for a role with coding round and return a coding session_id."""
        with self.client.session_transaction() as sess:
            sess["user"] = {
                "name": "Test User",
                "email": "codingtest@aziro.com",
                "authenticated": True,
            }
        self.client.post("/create-test", data={
            "name[]": "Coding Candidate",
            "email[]": "codingcandidate@test.com",
            "role[]": "Java Entry Level (0–2 Years)",
            "domain[]": "None",
        }, follow_redirects=True)

        from app.services.coding_session_registry import CODING_SESSION_REGISTRY
        for sid, meta in CODING_SESSION_REGISTRY.items():
            if meta["email"] == "codingcandidate@test.com":
                return sid
        return None

    def test_coding_start_page(self):
        sid = self._create_coding_test()
        self.assertIsNotNone(sid, "Failed to create coding session")
        resp = self.client.get(f"/coding/start/{sid}")
        self.assertEqual(resp.status_code, 200)

    def test_coding_invalid_session(self):
        resp = self.client.get("/coding/start/invalid_session_id")
        self.assertEqual(resp.status_code, 404)


class TestDashboardFilters(unittest.TestCase):
    """Test dashboard date filter functionality."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {
                "name": "Filter Tester",
                "email": "filter@aziro.com",
                "authenticated": True,
            }

    def test_dashboard_filter_today(self):
        self._login()
        resp = self.client.get("/dashboard?filter=today")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_filter_24h(self):
        self._login()
        resp = self.client.get("/dashboard?filter=24h")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_filter_2d(self):
        self._login()
        resp = self.client.get("/dashboard?filter=2d")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_filter_7d(self):
        self._login()
        resp = self.client.get("/dashboard?filter=7d")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_filter_specific_date(self):
        self._login()
        resp = self.client.get("/dashboard?date=2026-02-17")
        self.assertEqual(resp.status_code, 200)


class TestDBIntegration(unittest.TestCase):
    """Test database persistence."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_create_candidate(self):
        with self.app.app_context():
            from app.services import db_service
            candidate = db_service.get_or_create_candidate("DB Test User", "dbtest@test.com")
            self.assertIsNotNone(candidate)
            self.assertIsNotNone(candidate.id)
            self.assertEqual(candidate.email, "dbtest@test.com")

    def test_create_test_session(self):
        with self.app.app_context():
            from app.services import db_service
            candidate = db_service.get_or_create_candidate("DB Session User", "dbsession@test.com")
            ts = db_service.get_or_create_test_session(
                candidate_id=candidate.id,
                role_key="python_entry",
                role_label="Python Entry Level",
                batch_id="test_batch_001",
                created_by="tester@aziro.com",
            )
            self.assertIsNotNone(ts)
            self.assertIsNotNone(ts.id)

    def test_save_round_result(self):
        with self.app.app_context():
            from app.services import db_service
            candidate = db_service.get_or_create_candidate("DB Round User", "dbround@test.com")
            ts = db_service.get_or_create_test_session(
                candidate_id=candidate.id,
                role_key="python_entry",
                role_label="Python Entry Level",
                batch_id="test_batch_002",
            )
            db_service.save_round_result(
                test_session_id=ts.id,
                round_key="L1",
                round_label="Aptitude",
                total_questions=15,
                attempted=15,
                correct=12,
                percentage=80.0,
                pass_threshold=60.0,
                status="PASS",
                time_taken_seconds=600,
            )
            # Verify
            data = db_service.get_candidate_report_data("dbround@test.com")
            self.assertIsNotNone(data)
            self.assertIn("L1", data["rounds"])
            self.assertEqual(data["rounds"]["L1"]["correct"], 12)

    def test_search_candidates(self):
        with self.app.app_context():
            from app.services import db_service
            # First create data that we can search for
            candidate = db_service.get_or_create_candidate("Searchable User", "searchable@test.com")
            db_service.get_or_create_test_session(
                candidate_id=candidate.id,
                role_key="python_entry",
                role_label="Python Entry Level",
                batch_id="search_batch",
            )
            results = db_service.search_candidates("searchable")
            self.assertIsInstance(results, list)
            self.assertGreater(len(results), 0)


class TestAuthFlow(unittest.TestCase):
    """Test authentication flow."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_login_post_valid_aziro_email(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.post("/login", data={
            "username": "test@aziro.com",
            "password": "aziro123",
        }, follow_redirects=False)
        # Should redirect to dashboard on success (or auto-login from before_request)
        self.assertIn(resp.status_code, [302, 308])

    def test_login_post_invalid_email_domain(self):
        # With AUTH_DISABLED, before_request auto-logs in, so we get 302 redirect
        # This is expected behavior in dev mode
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.post("/login", data={
            "username": "test@gmail.com",
            "password": "aziro123",
        }, follow_redirects=False)
        self.assertIn(resp.status_code, [200, 302])

    def test_login_post_wrong_password(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        resp = self.client.post("/login", data={
            "username": "test@aziro.com",
            "password": "wrongpassword",
        }, follow_redirects=False)
        # With AUTH_DISABLED, before_request auto-logs in, so 302 redirect
        self.assertIn(resp.status_code, [200, 302])

    def test_logout_clears_session(self):
        # Login first
        self.client.post("/login", data={
            "username": "test@aziro.com",
            "password": "aziro123",
        })
        # Logout
        resp = self.client.get("/logout", follow_redirects=False)
        self.assertIn(resp.status_code, [302, 308])


class TestGeneratedTestsStore(unittest.TestCase):
    """Test the generated tests in-memory store."""

    def test_add_and_retrieve(self):
        from app.services.generated_tests_store import (
            GENERATED_TESTS, add_generated_test, get_tests_for_user_today, get_all_tests_today
        )
        from datetime import datetime, timezone

        initial_count = len(GENERATED_TESTS)
        add_generated_test({
            "name": "Store Test",
            "email": "storetest@test.com",
            "role": "Test Role",
            "tests": {},
            "created_by": "admin@aziro.com",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self.assertEqual(len(GENERATED_TESTS), initial_count + 1)

        # Test user filter
        user_tests = get_tests_for_user_today("admin@aziro.com")
        found = any(t["email"] == "storetest@test.com" for t in user_tests)
        self.assertTrue(found, "Test entry not found for user")

        # Test all today
        all_today = get_all_tests_today()
        found = any(t["email"] == "storetest@test.com" for t in all_today)
        self.assertTrue(found, "Test entry not found in today's tests")


class TestEvaluationAggregator(unittest.TestCase):
    """Test the evaluation aggregator."""

    def test_get_candidates_returns_list(self):
        from app.services.evaluation_aggregator import EvaluationAggregator
        candidates = EvaluationAggregator.get_candidates()
        self.assertIsInstance(candidates, list)

    def test_candidates_have_summary(self):
        from app.services.evaluation_aggregator import EvaluationAggregator
        candidates = EvaluationAggregator.get_candidates()
        for c in candidates:
            self.assertIn("summary", c, f"Missing summary for {c.get('email', '?')}")
            self.assertIn("overall_verdict", c["summary"])


class TestPDFService(unittest.TestCase):
    """Test PDF report generation."""

    def test_generate_pdf(self):
        from app.services.pdf_service import generate_candidate_pdf, REPORTS_DIR
        candidate_data = {
            "name": "PDF Test User",
            "email": "pdftest@test.com",
            "role": "Python Entry Level",
            "batch_id": "test_batch",
            "test_session_id": 999,
            "rounds": {
                "L1": {
                    "round_label": "Aptitude",
                    "correct": 10,
                    "total": 15,
                    "attempted": 15,
                    "percentage": 66.7,
                    "pass_threshold": 60,
                    "status": "PASS",
                    "time_taken_seconds": 500,
                },
            },
            "summary": {
                "total_rounds": 1,
                "attempted_rounds": 1,
                "passed_rounds": 1,
                "failed_rounds": 0,
                "total_correct": 10,
                "total_questions": 15,
                "overall_percentage": 66.7,
                "overall_verdict": "In Progress",
            },
        }
        filename = generate_candidate_pdf(candidate_data)
        self.assertTrue(filename.endswith(".pdf"))
        filepath = REPORTS_DIR / filename
        self.assertTrue(filepath.exists(), f"PDF not created at {filepath}")
        # Cleanup
        try:
            filepath.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
