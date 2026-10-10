"""Shared fixtures. Temporary folders live under data/test_tmp (the system temp folder is not always writable here)."""
import shutil
import uuid

import pytest

from swarmscope.ingest.packs import ROOT


@pytest.fixture
def tmp_path():
    d = ROOT / "data" / "test_tmp" / uuid.uuid4().hex[:10]
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)
