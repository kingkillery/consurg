"""Tests for consurg.sandbox.detect — backend auto-detection."""

from unittest.mock import patch

import pytest

from consurg.sandbox.detect import (
    SandboxBackendError,
    detect_backend,
    resolve_backend,
)


class TestDetectBackend:
    @patch("consurg.sandbox.detect._check_docker", return_value=True)
    def test_docker_preferred(self, _mock):
        assert detect_backend() == "docker"

    @patch("consurg.sandbox.detect._check_docker", return_value=False)
    @patch("consurg.sandbox.detect._check_seatbelt", return_value=True)
    def test_seatbelt_fallback(self, _m1, _m2):
        assert detect_backend() == "seatbelt"

    @patch("consurg.sandbox.detect._check_docker", return_value=False)
    @patch("consurg.sandbox.detect._check_seatbelt", return_value=False)
    @patch("consurg.sandbox.detect._check_wsl2", return_value=True)
    def test_wsl2_fallback(self, _m1, _m2, _m3):
        assert detect_backend() == "wsl2"

    @patch("consurg.sandbox.detect._check_docker", return_value=False)
    @patch("consurg.sandbox.detect._check_seatbelt", return_value=False)
    @patch("consurg.sandbox.detect._check_wsl2", return_value=False)
    def test_none_when_nothing_available(self, _m1, _m2, _m3):
        assert detect_backend() == "none"


class TestResolveBackend:
    def test_none_always_succeeds(self):
        assert resolve_backend("none") == "none"

    @patch("consurg.sandbox.detect.detect_backend", return_value="docker")
    def test_auto_delegates_to_detect(self, _mock):
        assert resolve_backend("auto") == "docker"

    @patch("consurg.sandbox.detect._check_docker", return_value=True)
    def test_specific_docker_available(self, _mock):
        assert resolve_backend("docker") == "docker"

    @patch("consurg.sandbox.detect._check_docker", return_value=False)
    def test_specific_docker_unavailable_raises(self, _mock):
        with pytest.raises(SandboxBackendError, match="not available"):
            resolve_backend("docker")

    def test_unknown_backend_raises(self):
        with pytest.raises(SandboxBackendError, match="Unknown"):
            resolve_backend("fakebox")

    @patch("consurg.sandbox.detect._check_seatbelt", return_value=True)
    def test_specific_seatbelt_available(self, _mock):
        assert resolve_backend("seatbelt") == "seatbelt"

    @patch("consurg.sandbox.detect._check_wsl2", return_value=True)
    def test_specific_wsl2_available(self, _mock):
        assert resolve_backend("wsl2") == "wsl2"
