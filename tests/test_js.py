import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_ip_form_logic():
    result = subprocess.run(  # noqa: S603
        [shutil.which("node"), "--test", str(ROOT / "js" / "ip-form.test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
