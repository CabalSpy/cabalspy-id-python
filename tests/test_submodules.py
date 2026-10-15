from __future__ import annotations

import cabalspy_id
from cabalspy_id import api, thesis


def test_api_subset_is_the_same_objects() -> None:
    for name in api.__all__:
        if name == "__version__":
            continue
        assert getattr(api, name) is getattr(cabalspy_id, name), name
    assert api.CabalSpyIDStream is cabalspy_id.CabalSpyIDStream
    assert "ThesisClient" not in api.__all__
    assert api.__version__ == cabalspy_id.__version__


def test_thesis_subset_is_the_same_objects() -> None:
    for name in thesis.__all__:
        if name == "__version__":
            continue
        assert getattr(thesis, name) is getattr(cabalspy_id, name), name
    assert thesis.ThesesStream is cabalspy_id.ThesesStream
    assert "CabalSpyIDAuth" not in thesis.__all__


def test_star_imports() -> None:
    ns_api: dict[str, object] = {}
    exec("from cabalspy_id.api import *", ns_api)
    assert ns_api["CabalSpyID"] is cabalspy_id.CabalSpyID
    ns_thesis: dict[str, object] = {}
    exec("from cabalspy_id.thesis import *", ns_thesis)
    assert ns_thesis["ThesisClient"] is cabalspy_id.ThesisClient


def test_trade_feed_subset_is_the_same_objects() -> None:
    from cabalspy_id import trade_feed

    for name in trade_feed.__all__:
        if name == "__version__":
            continue
        assert getattr(trade_feed, name) is getattr(cabalspy_id, name), name
    assert "ThesisClient" not in trade_feed.__all__
    ns: dict[str, object] = {}
    exec("from cabalspy_id.trade_feed import *", ns)
    assert ns["TradeFeedStream"] is cabalspy_id.TradeFeedStream
