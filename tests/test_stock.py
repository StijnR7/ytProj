"""Stock provider parsing (network mocked with each API's documented response shape)."""
import pytest

from ytfactory import stock


class FakeResp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


RESPONSES = {
    "api.pexels.com/v1/search": {"photos": [
        {"id": 1, "width": 4000, "height": 2600, "url": "https://pexels.com/photo/1", "photographer": "Ann", "alt": "coral reef",
         "src": {"original": "o.jpg", "large2x": "l2.jpg", "medium": "m.jpg", "small": "s.jpg"}},
        {"id": 2, "width": 900, "height": 1600, "url": "u", "photographer": "Bob", "src": {"original": "o2.jpg", "medium": "m2.jpg", "small": "s2.jpg"}},
    ]},
    "api.pexels.com/videos/search": {"videos": [
        {"id": 7, "duration": 12, "url": "https://pexels.com/video/7", "image": "thumb.jpg", "user": {"name": "Cam"},
         "video_files": [{"file_type": "video/mp4", "width": 640, "height": 360, "link": "small.mp4"},
                         {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "hd.mp4"},
                         {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "4k.mp4"}]},
    ]},
    "pixabay.com/api/videos/": {"hits": [
        {"id": 9, "duration": 8, "pageURL": "pg", "tags": "ocean, waves", "user": "pix",
         "videos": {"large": {"url": "", "width": 0}, "medium": {"url": "med.mp4", "width": 1920, "height": 1080, "thumbnail": "t.jpg"}}},
    ]},
    "pixabay.com/api/": {"hits": [
        {"id": 5, "pageURL": "pg", "tags": "shrimp", "previewURL": "p.jpg", "webformatURL": "w.jpg", "largeImageURL": "L.jpg",
         "imageWidth": 3000, "imageHeight": 2000, "user": "pix"}]},
    "api.openverse.org": {"results": [
        {"id": "a", "title": "Reef", "url": "r.jpg", "thumbnail": "rt.jpg", "creator": "Zed", "license": "by", "license_version": "2.0",
         "foreign_landing_url": "flickr", "width": 2000, "height": 1200},
        {"id": "b", "title": "NC", "url": "nc.jpg", "creator": "X", "license": "by-nc", "width": 2000, "height": 1200},
    ]},
    "images-api.nasa.gov": {"collection": {"items": [
        {"data": [{"nasa_id": "PIA1", "title": "Nebula", "center": "JPL"}], "links": [{"href": "https://x/PIA1~thumb.jpg", "render": "image"}]}]}},
}


@pytest.fixture
def fake_net(monkeypatch):
    def fake_get(url, **kw):
        for k in sorted(RESPONSES, key=len, reverse=True):
            if k in url:
                return FakeResp(RESPONSES[k])
        raise AssertionError(url)

    monkeypatch.setattr(stock.requests, "get", fake_get)
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    monkeypatch.setattr(stock, "wikimedia_search", lambda q, limit=12: [])


def test_providers_parse(fake_net):
    ph = stock.pexels_photos("reef")
    assert ph[0]["url"] == "l2.jpg" and ph[0]["credit"]["artist"] == "Ann"
    v = stock.pexels_videos("reef")
    assert v[0]["url"] == "hd.mp4" and v[0]["kind"] == "video"  # closest to 1920 wide
    pv = stock.pixabay_videos("ocean")
    assert pv[0]["url"] == "med.mp4"
    assert stock.pixabay_photos("shrimp")[0]["url"] == "L.jpg"
    ov = stock.openverse_photos("reef")
    assert [c["id"] for c in ov] == ["openverse-a"]  # non-commercial licence filtered out
    assert ov[0]["credit"]["license"] == "CC BY 2.0"
    n = stock.nasa_photos("nebula")
    assert n[0]["url"].endswith("~large.jpg")


def test_candidates_order_and_filters(fake_net):
    c = stock.candidates("reef", "broll", "any", 6, exclude={"pixabay-photo-5"}, log=lambda *_: None)
    ids = [x["id"] for x in c]
    assert ids[0].startswith("pexels-video") and "pixabay-video-9" in ids[:3]
    assert "pexels-photo-2" not in ids  # portrait / small dropped for full-screen b-roll
    assert "pixabay-photo-5" not in ids  # excluded (already used / rejected)
    a = stock.candidates("nebula", "archive", "photo", 6, log=lambda *_: None)
    assert not any(x["kind"] == "video" for x in a)


def test_no_keys_means_keyless_sources_only(fake_net, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY")
    monkeypatch.delenv("PIXABAY_API_KEY")
    c = stock.candidates("reef", "broll", "any", 6, log=lambda *_: None)
    assert all(x["id"].startswith(("openverse", "nasa", "wikimedia")) for x in c)
