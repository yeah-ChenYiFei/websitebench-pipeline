"""每条 known-difference 都要有测试守着 —— 否则"有意的偏差"和"没做完的 bug"分不开。

对应 scope/known-differences.json 里各条的 guarded_by。
这些测试直接读构建产物，不需要起站。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import Client

CLONE = Path(__file__).resolve().parent.parent
FRONTEND = CLONE / "frontend"
SCOPE = CLONE.parent / "scope"
BOUNDARY = "/_clone/out-of-scope"
NOT_FOUND = "/_clone/not-found"


def pages():
    return list(FRONTEND.rglob("index.html"))


def hrefs(html: str) -> list[str]:
    return re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.I)


@pytest.fixture(scope="module")
def kd():
    return {d["id"]: d for d in json.loads(
        (SCOPE / "known-differences.json").read_text(encoding="utf-8"))["known_differences"]}


def test_every_known_difference_has_a_guard(kd):
    missing = [k for k, v in kd.items() if not v.get("guarded_by")]
    assert not missing, f"这些差异没有测试守着: {missing}"


def test_player_is_placeholder(kd):
    assert "video_content_not_reproduced" in kd
    hits = [p for p in pages()
            if "cb-clone-player-placeholder" in p.read_text(encoding="utf-8", errors="replace")]
    assert len(hits) > 400, f"播放器占位只出现在 {len(hits)} 页，覆盖不足"
    # 占位处不得残留可播放的视频源
    for p in hits[:40]:
        h = p.read_text(encoding="utf-8", errors="replace")
        assert "<video" not in h.lower(), f"{p} 仍有 <video> 标签"
        assert not re.search(r'\.(m3u8|mpd|mp4)\b', h, re.I), f"{p} 仍引用视频文件"


def test_transcript_links_reach_boundary(kd):
    assert "class_transcripts_not_reproduced" in kd
    for p in pages()[:200]:
        for h in hrefs(p.read_text(encoding="utf-8", errors="replace")):
            assert not h.startswith("/transcript/"), f"{p} 仍指向逐字稿端点"


def test_blog_links_reach_boundary(kd):
    assert "source_blog_returns_403" in kd
    for p in pages()[:200]:
        for h in hrefs(p.read_text(encoding="utf-8", errors="replace")):
            assert not re.match(r"^/blog(/|$)", h), f"{p} 仍指向 /blog"



def test_member_profile_links_reach_boundary(kd):
    assert "third_party_member_pages_excluded" in kd
    for p in pages()[:200]:
        for h in hrefs(p.read_text(encoding="utf-8", errors="replace")):
            assert not re.match(r"^/(members|profile)/", h), f"{p} 指向第三方个人页 {h}"


def test_rss_links_reach_boundary(kd):
    assert "rss_feeds_excluded" in kd
    for p in pages()[:200]:
        for h in hrefs(p.read_text(encoding="utf-8", errors="replace")):
            assert not h.startswith("/rss"), f"{p} 仍指向 RSS"


def test_identity_provider_buttons_reach_boundary(kd):
    assert "third_party_oauth_excluded" in kd
    for p in pages()[:200]:
        for h in hrefs(p.read_text(encoding="utf-8", errors="replace")):
            assert not re.match(r"^/(facebook|google|apple)/", h), f"{p} 指向站外 IdP"



def test_auth_forms_are_wired(kd):
    """认证面的表单必须真的指向克隆 API —— 否则 UI 层是死的。"""
    assert "clone_authored_form_targets" in kd
    expect = {
        "trial/create-account": "/api/auth/register/start",
        "subscribe/create-account": "/api/auth/register/start",
        "forgot-password": "/api/auth/reset/start",
    }
    for route, endpoint in expect.items():
        f = FRONTEND / route / "index.html"
        assert f.is_file(), f"{route} 未构建"
        h = f.read_text(encoding="utf-8", errors="replace")
        assert f'data-cb-action="{endpoint}"' in h, f"{route} 的表单未接到 {endpoint}"
        assert "member[" not in h, f"{route} 仍有未归一的 member[...] 字段"


def test_no_html_shell_assets(kd):
    """交付的资产里不得有内容其实是 HTML 的文件。

    源站对不存在的图片返回 200 + 品牌化 404 页，下载器会据此记为成功。
    这类文件若混进交付物，就是一个坏图 + 一条虚假的资产声明。
    """
    assert "source_missing_images_return_soft_404" in kd
    bad = []
    for d in (CLONE / "static" / "assets",
              CLONE.parent / "source-assets" / "2026-08-28.creativebug-r1"):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                if f.read_bytes()[:600].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                    bad.append(f.name)
    assert not bad, f"{len(bad)} 个图片资产实际是 HTML: {bad[:5]}"


def test_coverage_required_items_reference_real_checkpoints():
    """coverage 里的 required_items 必须指向真实存在的检查点。

    台账之间对不上时，verify 只会说某个检查点无法解析，不会告诉你是
    coverage 引用错了 —— 这条把错位提前暴露在测试里。
    """
    import json as _json
    cov = _json.loads((SCOPE / "coverage.json").read_text(encoding="utf-8"))
    ids = {c["id"] for c in
           _json.loads((SCOPE / "checkpoints.json").read_text(encoding="utf-8"))["checkpoints"]}
    dangling = {d["id"]: [i for i in d["required_items"] if i not in ids]
                for d in cov["dimensions"]}
    dangling = {k: v for k, v in dangling.items() if v}
    assert not dangling, f"coverage 引用了不存在的检查点: {dangling}"


def test_hero_background_is_localized(kd):
    """首页 hero 的深色背景必须指向本地资产，不得为了分数被移除。"""
    assert "hero_video_absent_reveals_css_background" in kd
    f = FRONTEND / "index" / "index.html"
    h = f.read_text(encoding="utf-8", errors="replace")
    # url() 里带不带引号都算本地化 —— 构建期写出的是 url("/static/assets/...")，
    # 早先只认无引号写法，页面明明是对的却报红。
    assert re.search(r'#hero\s+\.hero\s*\{[^}]*background-image:\s*'
                     r'url\(\s*["\']?/static/assets/', h), \
        "hero 背景图缺失或未本地化"


def test_visual_contracts_declare_threshold(kd):
    """每条检查点的 visual_contract 必须把阈值冻在 0.94（§11），不得为达标而调低。"""
    assert "reference_frames_capture_dynamic_content" in kd
    import json as _json
    cps = _json.loads((SCOPE / "checkpoints.json").read_text(encoding="utf-8"))["checkpoints"]
    withc = [c for c in cps if "visual_contract" in c]
    assert withc, "没有任何检查点声明 visual_contract"
    bad = [c["id"] for c in withc if c["visual_contract"].get("threshold") != 0.94]
    assert not bad, f"这些检查点的阈值不是 0.94: {bad}"


def test_no_mobile_checkpoints_remain(kd):
    """移动端已按用户裁定（2026-08-29「我们不做移动端」）移出范围契约。

    守的是范围本身：契约里不得再出现 mobile 检查点，参考帧也不得留在比较目录里，
    否则相似度会拿一批已声明不做的东西继续算分。
    """
    import json as _json
    assert "mobile_viewport_out_of_scope" in kd

    cps = _json.loads((CLONE.parent / "scope" / "checkpoints.json").read_text(encoding="utf-8"))
    items = cps.get("checkpoints") or cps.get("items")
    mobile = [c["id"] for c in items if c.get("viewport") == "mobile"]
    assert not mobile, f"契约里仍有移动端检查点: {mobile}"

    ref = CLONE.parent.parent.parent / "incoming" / "cb-out" / "reference"
    if ref.is_dir():
        left = [p.name for p in ref.glob("*mobile*")]
        assert not left, f"比较目录里仍有移动端参考帧: {left}"


def test_undeclared_served_files_are_exactly_five(kd):
    """被服务但未进清单的文件必须恰好是已声明的那 5 个 —— 不多也不少。

    §11 要求台账里每个数字都能从产物里重新数出来。此前只声明了 favicon 一个，
    另外 4 个 SVG 字体文件是裸露的：数字对不上却没人守着。
    """
    import json as _json
    assert "five_served_files_not_declared_as_assets" in kd
    man = _json.loads((CLONE.parent / "source-assets" / "manifest.json").read_text(encoding="utf-8"))
    declared = {Path(a["runtime_path"]).name for a in man["assets"]}
    on_disk = {p.name for p in (CLONE / "static" / "assets").iterdir() if p.is_file()}
    extra = on_disk - declared
    missing = declared - on_disk
    assert not missing, f"清单声明了但磁盘上没有: {sorted(missing)[:5]}"
    assert len(extra) == 5, f"未声明却被服务的文件数变了: {len(extra)} -> {sorted(extra)}"
    for name in sorted(extra):
        assert name.endswith((".ico", ".svg")), f"未声明文件出现了新类型: {name}"


def test_unencoded_space_routes_actually_resolve(kd, server):
    """带空格的 collection 路由必须真的能打开 —— 而不是只检查 href 编码过了。

    旧测试只断言「前 200 页的 href 里不含空格」，从不请求这些路由，因此在
    3 条真实页面持续 404 的整段时间里恒绿。守护测试必须在陈述被违反时失败。
    """
    import json as _json
    import re as _re
    assert "source_unencoded_hrefs" in kd

    page = CLONE / "frontend" / "collections" / "index.html"
    if not page.is_file():
        pytest.skip("没有 collections 页")
    hrefs = {h for h in _re.findall(r'href="(/[^"]*%20[^"]*)"',
                                    page.read_text(encoding="utf-8", errors="replace"))}
    assert hrefs, "collections 页里没有百分号编码的 href，测试失去意义"

    c = Client(server)
    bad = [(h, c.get(h)[0]) for h in sorted(hrefs)]
    broken = [(h, code) for h, code in bad if code != 200]
    assert not broken, f"带空格的路由未能解析: {broken}"
