"""Integration tests for the live-API client and the submit orchestrator.

Everything runs against the in-memory ``MockTransport`` — no token, no socket — so
the whole exchange -> assignments -> pdf -> review -> POST path is exercised, and
the mock enforces the same review-body rules the real server does.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import submit
from reviewer.agent_api import (
    API_PREFIX,
    AgentAPIError,
    AgentClient,
    MockTransport,
    NextAction,
    ReasonCode,
    parse_guidance,
)

_VALID_REVIEW = {
    "ordinal": 1,
    "soundness": 3,
    "presentation": 3,
    "significance": 3,
    "originality": 3,
    "overall": 4,
    "confidence": 3,
    "comments": "ok",
}


class DotenvTests(unittest.TestCase):
    def test_local_env_can_reference_shared_best_mode_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared.env"
            shared.write_text(
                "OPENAI_API_KEY=sk-shared-test\n"
                "OPENAI_BASE_URL=https://example.invalid/v1\n",
                encoding="utf-8",
            )
            local = root / ".env"
            local.write_text(
                f"RALPHTHON_ENV_FILE={shared}\n",
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "sk-exported-wins"},
                clear=True,
            ):
                submit._load_dotenv(local)

                self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-exported-wins")
                self.assertEqual(
                    os.environ["OPENAI_BASE_URL"],
                    "https://example.invalid/v1",
                )


class ClientAgainstMockTests(unittest.TestCase):
    def _authed(self) -> AgentClient:
        client = AgentClient(transport=MockTransport())
        client.exchange_setup_token("ignored-by-mock")
        return client

    def test_calls_require_authentication_first(self) -> None:
        client = AgentClient(transport=MockTransport())
        with self.assertRaises(AgentAPIError):
            client.status()

    def test_exchange_status_assignments_and_pdf(self) -> None:
        client = self._authed()
        self.assertTrue(client.authenticated)
        status = client.status()
        self.assertEqual(status["phase"], "review")
        self.assertIs(
            parse_guidance(status).reason_code,
            ReasonCode.ASSIGNMENTS_CAN_BE_CREATED,
        )
        papers = client.assignments()
        self.assertEqual(
            [paper["ordinal"] for paper in papers],
            list(range(1, 11)),
        )
        self.assertIs(client.guidance.reason_code, ReasonCode.ASSIGNMENTS_RETURNED)
        self.assertIn(b"Schedule Transfer", client.fetch_pdf(papers[0]))
        self.assertIs(
            parse_guidance(client.status()).reason_code,
            ReasonCode.REVIEW_WINDOW_OPEN,
        )

    def test_post_marks_ordinal_submitted_for_resume(self) -> None:
        client = self._authed()
        client.status()
        client.assignments()
        self.assertTrue(client.post_review(dict(_VALID_REVIEW))["ok"])
        self.assertIs(client.guidance.reason_code, ReasonCode.REVIEW_SUBMITTED)
        by_ordinal = {paper["ordinal"]: paper for paper in client.assignments()}
        self.assertEqual(by_ordinal[1]["status"], "submitted")
        self.assertEqual(by_ordinal[2]["status"], "assigned")
        for ordinal in range(2, 11):
            self.assertTrue(
                client.post_review(dict(_VALID_REVIEW) | {"ordinal": ordinal})["ok"]
            )
        self.assertIs(
            client.guidance.reason_code, ReasonCode.ALL_REVIEWS_SUBMITTED
        )
        self.assertIs(client.guidance.next_action, NextAction.NONE)
        self.assertTrue(client.guidance.terminal)

    def test_every_state_changing_post_fetches_canonical_skill_immediately_before(self) -> None:
        transport = MockTransport()
        client = AgentClient(transport=transport)
        client.exchange_setup_token("ignored-by-mock")
        client.status()
        client.assignments()
        client.post_review(dict(_VALID_REVIEW))

        post_indexes = [
            index
            for index, call in enumerate(transport.calls)
            if call[0] == "POST"
        ]
        self.assertTrue(post_indexes)
        for index in post_indexes:
            self.assertGreater(index, 0)
            self.assertEqual(transport.calls[index - 1], ("GET", "/skill.md"))

    def test_server_rejects_a_float_score(self) -> None:
        client = self._authed()
        with self.assertRaises(AgentAPIError):
            client.post_review(dict(_VALID_REVIEW) | {"soundness": 3.0})

    def test_repr_never_exposes_the_bearer(self) -> None:
        client = self._authed()
        self.assertNotIn("mock-bearer", repr(client))
        self.assertIn("authenticated", repr(client))


class ErrorActionTests(unittest.TestCase):
    def test_known_error_details_map_to_exact_reason_actions(self) -> None:
        cases = (
            ("Invalid setup token", ReasonCode.INVALID_SETUP_TOKEN, "newly issued"),
            ("Authentication required", ReasonCode.AUTHENTICATION_REQUIRED, "re-provision"),
            (
                "active_track2_report_required",
                ReasonCode.ACTIVE_TRACK2_REPORT_REQUIRED,
                "browser",
            ),
            (
                "insufficient_eligible_papers",
                ReasonCode.INSUFFICIENT_ELIGIBLE_PAPERS,
                "without polling",
            ),
            (
                "Reviews are writable from 16:35 until 17:00",
                ReasonCode.REVIEW_WINDOW_NOT_OPEN,
                "KST boundary",
            ),
            (
                "Active assignment required",
                ReasonCode.ACTIVE_ASSIGNMENT_REQUIRED,
                "refreshed",
            ),
            (
                "Assignment not found",
                ReasonCode.ASSIGNMENT_NOT_FOUND,
                "refreshed",
            ),
            (
                "Claimable paper not found",
                ReasonCode.CLAIMABLE_PAPER_NOT_FOUND,
                "without guessing",
            ),
            (
                "invalid_review_payload",
                ReasonCode.INVALID_REVIEW_PAYLOAD,
                "correct it",
            ),
        )
        for detail, reason, action_text in cases:
            with self.subTest(detail=detail):
                error = AgentAPIError(
                    "request rejected", status_code=400, detail=detail
                )
                self.assertIs(submit._reason_from_error(error), reason)
                self.assertIn(action_text, submit._api_error_message(error))

    def test_unexpected_error_stops_without_guessing(self) -> None:
        error = AgentAPIError(
            "server failed",
            status_code=418,
            detail="new undocumented failure",
        )
        self.assertIs(
            submit._reason_from_error(error),
            ReasonCode.UNEXPECTED_AGENT_API_ERROR,
        )
        self.assertIn("stop and inspect", submit._api_error_message(error))

    def test_exhausted_transient_error_surfaces_returned_context(self) -> None:
        guidance = parse_guidance(
            {
                "guidance": {
                    "stage": "waiting",
                    "action_available": False,
                    "reason_code": "unexpected_agent_api_error",
                    "next_action": "none",
                    "next_action_actor": "none",
                    "prerequisites": [],
                    "time": {
                        "timezone": "Asia/Seoul",
                        "now": "2026-07-12T16:40:00+09:00",
                        "window_opens_at": "2026-07-12T16:35:00+09:00",
                        "window_closes_at": "2026-07-12T17:00:00+09:00",
                    },
                }
            }
        )
        error = AgentAPIError(
            "server failed",
            status_code=503,
            detail="upstream unavailable",
            guidance=guidance,
            transient=True,
        )
        message = submit._api_error_message(error)
        self.assertIn("status=503", message)
        self.assertIn("detail=upstream unavailable", message)
        self.assertIn("reason=unexpected_agent_api_error", message)
        self.assertIn("now=2026-07-12T16:40:00+09:00", message)


class SubmitDryRunCLITests(unittest.TestCase):
    def test_dry_run_fetches_startup_skill_separately_from_exchange_prefetch(
        self,
    ) -> None:
        transport = MockTransport()
        with tempfile.TemporaryDirectory() as directory:
            saved_argv = sys.argv
            sys.argv = ["submit.py", "--dry-run", "--workdir", directory]
            try:
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    mock.patch.object(submit, "MockTransport", return_value=transport),
                ):
                    self.assertEqual(submit.main(), 0)
            finally:
                sys.argv = saved_argv

        exchange_index = transport.calls.index(
            ("POST", "/agent-credential/exchange")
        )
        self.assertGreaterEqual(exchange_index, 2)
        self.assertEqual(
            transport.calls[exchange_index - 2 : exchange_index],
            [("GET", "/skill.md"), ("GET", "/skill.md")],
        )

    def test_dry_run_reviews_and_posts_every_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            saved_argv = sys.argv
            sys.argv = ["submit.py", "--dry-run", "--workdir", directory]
            try:
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    mock.patch.object(
                        submit,
                        "_load_dotenv",
                        side_effect=AssertionError("dry-run read .env"),
                    ),
                    mock.patch(
                        "reviewer.citation_existence.urlopen",
                        side_effect=AssertionError("dry-run attempted network"),
                    ),
                ):
                    return_code = submit.main()
            finally:
                sys.argv = saved_argv
            self.assertEqual(return_code, 0)
            report = json.loads((Path(directory) / "run_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["mode"], "audit")  # dry run is forced offline
            self.assertEqual(len(report["results"]), 10)
            self.assertTrue(all(record["ok"] and record["posted"] for record in report["results"]))

    def test_dry_run_refreshes_status_before_each_post(self) -> None:
        transport = MockTransport()
        with tempfile.TemporaryDirectory() as directory:
            saved_argv = sys.argv
            sys.argv = ["submit.py", "--dry-run", "--workdir", directory]
            try:
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    mock.patch.object(submit, "MockTransport", return_value=transport),
                ):
                    self.assertEqual(submit.main(), 0)
            finally:
                sys.argv = saved_argv

        previous_post = -1
        post_indexes = [
            index
            for index, (method, path) in enumerate(transport.calls)
            if method == "POST" and path == "/agent-reviews"
        ]
        self.assertEqual(len(post_indexes), 10)
        for post_index in post_indexes:
            self.assertIn(
                ("GET", "/status"),
                transport.calls[previous_post + 1 : post_index],
            )
            previous_post = post_index

    def test_resume_skips_previously_submitted_assignment(self) -> None:
        transport = MockTransport(submitted={1: dict(_VALID_REVIEW)})
        with tempfile.TemporaryDirectory() as directory:
            saved_argv = sys.argv
            sys.argv = ["submit.py", "--dry-run", "--workdir", directory]
            output = io.StringIO()
            try:
                with (
                    contextlib.redirect_stdout(output),
                    mock.patch.object(submit, "MockTransport", return_value=transport),
                ):
                    self.assertEqual(submit.main(), 0)
            finally:
                sys.argv = saved_argv

            report = json.loads(
                (Path(directory) / "run_report.json").read_text(encoding="utf-8")
            )
        self.assertIn("skip  #1", output.getvalue())
        self.assertEqual(
            [record["ordinal"] for record in report["results"]],
            list(range(2, 11)),
        )
        self.assertNotIn(
            ("GET", "/assignments/1/pdf"), transport.calls
        )
        self.assertEqual(
            transport.calls.count(("POST", "/agent-reviews")), 9
        )

    def test_terminal_none_stops_without_assignments_or_polling(self) -> None:
        transport = MockTransport(
            terminal_reason="insufficient_eligible_papers"
        )
        with tempfile.TemporaryDirectory() as directory:
            saved_argv = sys.argv
            sys.argv = ["submit.py", "--dry-run", "--workdir", directory]
            try:
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    mock.patch.object(submit, "MockTransport", return_value=transport),
                ):
                    self.assertEqual(submit.main(), 0)
            finally:
                sys.argv = saved_argv

        self.assertEqual(transport.calls.count(("GET", "/status")), 1)
        self.assertNotIn(("GET", "/assignments/current"), transport.calls)
        self.assertNotIn(("POST", "/agent-reviews"), transport.calls)

    def test_assignment_error_refreshes_once_without_retrying_post(self) -> None:
        base = MockTransport()

        class AssignmentErrorTransport:
            failed = False

            def __call__(
                self,
                method: str,
                url: str,
                headers: dict[str, str],
                body: bytes | None,
            ) -> tuple[int, bytes]:
                path = url.split(API_PREFIX, 1)[-1]
                if (
                    method == "POST"
                    and path == "/agent-reviews"
                    and not self.failed
                ):
                    self.failed = True
                    base.calls.append((method, path))
                    payload = {
                        "detail": "Assignment not found",
                        "guidance": {
                            "stage": "reviewing",
                            "action_available": True,
                            "reason_code": "assignment_not_found",
                            "next_action": "get_assignments",
                            "next_action_actor": "agent",
                            "prerequisites": [
                                {
                                    "code": "review_window_open",
                                    "satisfied": True,
                                    "actor": "server",
                                }
                            ],
                            "time": {
                                "timezone": "Asia/Seoul",
                                "now": "2026-07-12T16:40:00+09:00",
                                "window_opens_at": "2026-07-12T16:35:00+09:00",
                                "window_closes_at": "2026-07-12T17:00:00+09:00",
                            },
                        },
                    }
                    return 404, json.dumps(payload).encode()
                return base(method, url, headers, body)

        transport = AssignmentErrorTransport()
        with tempfile.TemporaryDirectory() as directory:
            saved_argv = sys.argv
            sys.argv = ["submit.py", "--dry-run", "--workdir", directory]
            try:
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    mock.patch.object(submit, "MockTransport", return_value=transport),
                ):
                    self.assertEqual(submit.main(), 1)
            finally:
                sys.argv = saved_argv

        self.assertEqual(base.calls.count(("POST", "/agent-reviews")), 1)
        post_index = base.calls.index(("POST", "/agent-reviews"))
        self.assertIn(
            ("GET", "/assignments/current"), base.calls[post_index + 1 :]
        )


if __name__ == "__main__":
    unittest.main()
