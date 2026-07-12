"""Contract tests for typed guidance and credential-safe API calls."""

from __future__ import annotations

import io
import json
import urllib.error
import unittest
from unittest import mock

from reviewer.agent_api import (
    API_PREFIX,
    AgentAPIError,
    AgentClient,
    GuidanceParseError,
    NextAction,
    NoRedirectHandler,
    ReasonCode,
    Stage,
    UrllibTransport,
    parse_guidance,
)


def _guidance(
    *,
    stage: str = "reviewing",
    reason_code: str = "review_window_open",
    next_action: str = "submit_review",
    action_available: bool = True,
) -> dict:
    return {
        "stage": stage,
        "action_available": action_available,
        "reason_code": reason_code,
        "next_action": next_action,
        "next_action_actor": "agent" if action_available else "none",
        "prerequisites": [
            {
                "code": "review_window_open",
                "satisfied": action_available,
                "actor": "server",
                "future_prerequisite_field": "retained",
            }
        ],
        "time": {
            "timezone": "Asia/Seoul",
            "now": "2026-07-12T16:40:00+09:00",
            "window_opens_at": "2026-07-12T16:35:00+09:00",
            "window_closes_at": "2026-07-12T17:00:00+09:00",
            "future_time_field": {"retained": True},
        },
        "future_guidance_field": ["retained"],
    }


class GuidanceParsingTests(unittest.TestCase):
    def test_parses_typed_control_fields_and_retains_additive_fields(self) -> None:
        guidance = parse_guidance({"guidance": _guidance(), "other_response_field": 1})

        self.assertIs(guidance.stage, Stage.REVIEWING)
        self.assertIs(guidance.reason_code, ReasonCode.REVIEW_WINDOW_OPEN)
        self.assertIs(guidance.next_action, NextAction.SUBMIT_REVIEW)
        self.assertTrue(guidance.action_available)
        self.assertTrue(guidance.can_submit_review)
        self.assertEqual(guidance.extra_fields["future_guidance_field"], ["retained"])

        prerequisite = guidance.prerequisite("review_window_open")
        self.assertIsNotNone(prerequisite)
        assert prerequisite is not None
        self.assertTrue(prerequisite.satisfied)
        self.assertEqual(
            prerequisite.extra_fields["future_prerequisite_field"], "retained"
        )

        self.assertEqual(guidance.time.timezone, "Asia/Seoul")
        self.assertEqual(guidance.time.now.utcoffset().total_seconds(), 9 * 3600)
        self.assertTrue(guidance.time.write_window_open)
        self.assertEqual(
            guidance.time.extra_fields["future_time_field"], {"retained": True}
        )

    def test_unknown_enum_values_are_preserved_instead_of_rejected(self) -> None:
        guidance = parse_guidance(
            {
                "guidance": _guidance(
                    stage="future_stage",
                    reason_code="future_reason",
                    next_action="future_action",
                )
            }
        )

        self.assertEqual(guidance.stage.value, "future_stage")
        self.assertEqual(guidance.reason_code.value, "future_reason")
        self.assertEqual(guidance.next_action.value, "future_action")

    def test_terminal_none_is_a_typed_no_op(self) -> None:
        guidance = parse_guidance(
            {
                "guidance": _guidance(
                    stage="complete",
                    reason_code="all_reviews_submitted",
                    next_action="none",
                    action_available=False,
                )
            }
        )

        self.assertTrue(guidance.terminal)
        self.assertFalse(guidance.can_submit_review)

    def test_rejects_non_boolean_action_available(self) -> None:
        payload = _guidance()
        payload["action_available"] = 1
        with self.assertRaises(GuidanceParseError):
            parse_guidance({"guidance": payload})

    def test_rejects_non_kst_boundaries(self) -> None:
        payload = _guidance()
        payload["time"]["window_opens_at"] = "2026-07-12T07:35:00+00:00"
        with self.assertRaises(GuidanceParseError):
            parse_guidance({"guidance": payload})

    def test_requires_explicit_nullable_window_boundaries(self) -> None:
        payload = _guidance()
        del payload["time"]["window_closes_at"]
        with self.assertRaises(GuidanceParseError):
            parse_guidance({"guidance": payload})


class ScopedPDFTests(unittest.TestCase):
    def _client(self) -> tuple[AgentClient, list[tuple[str, str, dict[str, str]]]]:
        calls: list[tuple[str, str, dict[str, str]]] = []

        def transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> tuple[int, bytes]:
            del body
            calls.append((method, url, dict(headers)))
            if url.endswith("/skill.md"):
                return 200, b"# Ralphthon ICML 2026 -- canonical test skill\n"
            if url.endswith("/agent-credential/exchange"):
                return 200, json.dumps(
                    {"access_token": "secret-bearer", "guidance": _guidance()}
                ).encode()
            return 200, b"%PDF-fixture"

        client = AgentClient(transport=transport)
        client.exchange_setup_token("secret-setup")
        return client, calls

    def test_fetches_only_the_returned_scoped_assignment_url(self) -> None:
        client, calls = self._client()
        assignment = {
            "ordinal": 3,
            "paper": {
                "pdf_url": (
                    "https://openagentreview.org"
                    f"{API_PREFIX}/assignments/3/pdf"
                )
            },
        }

        self.assertEqual(client.fetch_pdf(assignment), b"%PDF-fixture")
        _, url, headers = calls[-1]
        self.assertEqual(url, assignment["paper"]["pdf_url"])
        self.assertEqual(headers["Authorization"], "Bearer secret-bearer")

    def test_rejects_untrusted_pdf_urls_before_attaching_bearer(self) -> None:
        client, calls = self._client()
        malicious_urls = (
            "http://openagentreview.org/api/ralphthon/v1/assignments/3/pdf",
            "https://evil.example/api/ralphthon/v1/assignments/3/pdf",
            "https://openagentreview.org.evil.example/api/ralphthon/v1/assignments/3/pdf",
            "https://openagentreview.org/not-agent-api/assignments/3/pdf",
            "https://openagentreview.org/api/ralphthon/v1/assignments/4/pdf",
        )

        for url in malicious_urls:
            with self.subTest(url=url), self.assertRaises(AgentAPIError):
                client.fetch_pdf({"ordinal": 3, "paper": {"pdf_url": url}})
        self.assertEqual(len(calls), 2, "invalid URLs must never reach the transport")

    def test_rejects_redirect_response_instead_of_treating_it_as_pdf(self) -> None:
        def transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> tuple[int, bytes]:
            del method, headers, body
            if url.endswith("/skill.md"):
                return 200, b"# Ralphthon ICML 2026 -- canonical test skill\n"
            if url.endswith("/agent-credential/exchange"):
                return 200, json.dumps(
                    {"access_token": "secret-bearer", "guidance": _guidance()}
                ).encode()
            return 302, b"redirect"

        client = AgentClient(transport=transport)
        client.exchange_setup_token("secret-setup")
        with self.assertRaises(AgentAPIError) as raised:
            client.fetch_pdf(
                {
                    "ordinal": 3,
                    "paper": {
                        "pdf_url": (
                            "https://openagentreview.org"
                            f"{API_PREFIX}/assignments/3/pdf"
                        )
                    },
                }
            )
        self.assertEqual(raised.exception.status_code, 302)

    def test_redirect_handler_never_follows_authorized_request(self) -> None:
        request = urllib.request.Request(
            "https://openagentreview.org/source",
            headers={"Authorization": "Bearer secret"},
        )
        redirected = NoRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://evil.example/target",
        )
        self.assertIsNone(redirected)

    def test_default_transport_rejects_noncanonical_base_origin(self) -> None:
        with self.assertRaises(AgentAPIError):
            AgentClient(base_url="https://evil.example")


class ErrorAndRetryTests(unittest.TestCase):
    def test_http_error_exposes_typed_guidance_without_secret_material(self) -> None:
        responses = [
            (200, b"# Ralphthon ICML 2026 -- canonical test skill\n"),
            (
                200,
                json.dumps(
                    {"access_token": "secret-bearer", "guidance": _guidance()}
                ).encode(),
            ),
            (
                409,
                json.dumps(
                    {
                        "detail": "active_track2_report_required",
                        "guidance": _guidance(
                            stage="track2_prerequisite",
                            reason_code="active_track2_report_required",
                            next_action="submit_track2_report",
                            action_available=False,
                        ),
                    }
                ).encode(),
            ),
        ]

        def transport(*_args: object) -> tuple[int, bytes]:
            return responses.pop(0)

        client = AgentClient(transport=transport)
        client.exchange_setup_token("secret-setup")
        with self.assertRaises(AgentAPIError) as raised:
            client.status()

        error = raised.exception
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.detail, "active_track2_report_required")
        self.assertIsNotNone(error.guidance)
        assert error.guidance is not None
        self.assertIs(
            error.guidance.reason_code, ReasonCode.ACTIVE_TRACK2_REPORT_REQUIRED
        )
        self.assertNotIn("secret-bearer", str(error))
        self.assertNotIn("secret-setup", str(error))

    def test_transport_does_not_retry_a_4xx(self) -> None:
        error = urllib.error.HTTPError(
            "https://openagentreview.org/test",
            422,
            "invalid",
            {},
            io.BytesIO(b'{"detail":"invalid_review_payload"}'),
        )
        transport = UrllibTransport(retries=3, backoff=0)
        with mock.patch.object(
            transport._opener, "open", side_effect=error
        ) as urlopen:
            status, _ = transport("POST", "https://openagentreview.org/test", {}, b"{}")
        self.assertEqual(status, 422)
        self.assertEqual(urlopen.call_count, 1)

    def test_transport_retries_5xx_then_succeeds(self) -> None:
        errors = [
            urllib.error.HTTPError(
                "https://openagentreview.org/test",
                503,
                "unavailable",
                {},
                io.BytesIO(b"temporary"),
            )
            for _ in range(2)
        ]

        class Response:
            status = 200

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"ok"

        transport = UrllibTransport(retries=3, backoff=0)
        with mock.patch.object(
            transport._opener,
            "open",
            side_effect=[*errors, Response()],
        ) as urlopen:
            status, body = transport(
                "GET", "https://openagentreview.org/test", {}, None
            )
        self.assertEqual((status, body), (200, b"ok"))
        self.assertEqual(urlopen.call_count, 3)


if __name__ == "__main__":
    unittest.main()
