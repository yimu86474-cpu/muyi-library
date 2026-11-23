// Explanation contract: docs/EXPLAIN.md
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
await import("../extractor.js");
const extractor = globalThis.__muyiVideoExtractor;
const id = "6a83da6700000000250120da";
const other = "6a83da6700000000250120db";
const page = `https://www.xiaohongshu.com/explore/${id}?xsec_token=fixture`;
const mediaUrl = "https://sns-video-bd.xhscdn.com/stream/fixture.mp4";
await import("../xiaohongshu-media-bridge.js");
const bridge = globalThis.__muyiXiaohongshuBridge;

test("on-demand note bridge only returns matching note data and H264 media", () => {
  const timestamp = 1787183400000;
  const date = new Date(timestamp);
  const pad = part => String(part).padStart(2, "0");
  const publishedAt = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const note = { noteId: id, type: "video", title: "所选笔记", time: timestamp, interactInfo: { likedCount: "1.2万" }, user: { nickname: "测试作者" }, video: { media: { stream: { h264: [{ masterUrl: mediaUrl }], h265: [{ masterUrl: "https://invalid.example/wrong.mp4" }] } } } };
  assert.equal(bridge.noteCandidate(note, id).mediaUrl, mediaUrl);
  assert.equal(bridge.noteCandidate(note, id).likeCount, "1.2万");
  assert.equal(bridge.noteCandidate(note, id).publishedAt, publishedAt);
  assert.equal(bridge.noteCandidate(note, other), null);
  assert.equal(bridge.noteCandidate({ ...note, noteId: undefined }, id), null);
  assert.equal(bridge.noteCandidate({ ...note, type: "normal" }, id).mediaUrl, "");
  assert.equal(bridge.noteCandidate({ ...note, type: "unknown" }, id), null);
});

test("home feed selection keeps the selected note's visible like count", () => {
  const result = extractor.normalizeXiaohongshuSnapshot({
    pageUrl: page, href: page, tag: "img", mediaUrl: "https://sns-webpic-qc.xhscdn.com/cover.webp",
    candidate: { noteId: id, kind: "video", mediaUrl, likeCount: "197", publishedAt: "2026-08-20 10:30" },
  });
  assert.equal(result.like_count_text, "197");
  assert.equal(result.published_at_text, "2026-08-20 10:30");
});

test("detail bridge accepts an obfuscated stream group only when the same page actually played it", () => {
  const played = "https://sns-video-v6.xhscdn.com/stream/exact-played.mp4?sign=fixture";
  const note = {
    noteId: id,
    type: "video",
    title: "平台新流结构",
    video: { media: { stream: {
      EF4: [{ masterUrl: "https://sns-video-v6.xhscdn.com/stream/not-played.mp4" }],
      EF5: [{ masterUrl: played }],
    } } },
  };

  assert.equal(bridge.noteCandidate(note, id, "", [played]).mediaUrl, played);
  assert.equal(bridge.noteCandidate(note, id).mediaUrl, "");
});

test("XHS video cover becomes a video card with the same note's stream", () => {
  const result = extractor.normalizeXiaohongshuSnapshot({
    pageUrl: page, href: page, tag: "img", mediaUrl: "https://sns-webpic-qc.xhscdn.com/cover.webp",
    candidate: { noteId: id, kind: "video", mediaUrl, title: "本条视频", author: "作者" },
  });
  assert.equal(result.content_kind, "video");
  assert.equal(result.media_url, mediaUrl);
  assert.equal(result.external_id, id);
  assert.equal(result.page_url, page);
  assert.equal(result.source_identity_verified, true);
});

test("XHS cover with video badge but no stream stays a pending video, never an image", () => {
  const result = extractor.normalizeXiaohongshuSnapshot({ pageUrl: page, href: page, tag: "img", videoBadge: true, mediaUrl: "https://sns-webpic-qc.xhscdn.com/cover.webp" });
  assert.equal(result.content_kind, "video");
  assert.equal(result.media_url, "");
});

test("XHS image notes keep the selected image even with another note's cached video", () => {
  const result = extractor.normalizeXiaohongshuSnapshot({ pageUrl: "https://www.xiaohongshu.com/explore", href: page, tag: "img", mediaUrl: "https://sns-webpic-qc.xhscdn.com/image.webp", candidate: { noteId: other, kind: "video", mediaUrl } });
  assert.equal(result.content_kind, "image");
  assert.equal(result.media_url, "https://sns-webpic-qc.xhscdn.com/image.webp");
});

test("XHS conflicting detail and selected card identities cannot borrow the detail stream", () => {
  const result = extractor.normalizeXiaohongshuSnapshot({ pageUrl: page, href: `https://www.xiaohongshu.com/explore/${other}`, tag: "video", mediaUrl, candidate: { noteId: id, kind: "video", mediaUrl } });
  assert.equal(result.external_id, other);
  assert.equal(result.media_url, "");
  assert.equal(result.source_identity_verified, false);
});

test("XHS rejects unrelated, image, credential and fake CDN video sources", () => {
  for (const url of ["https://evil.invalid/clip.mp4", "https://sns-webpic-qc.xhscdn.com/cover.webp", "https://sns-video-bd.xhscdn.com.evil.invalid/a.mp4", "https://user:pass@sns-video-bd.xhscdn.com/a.mp4", "https://sns-video-bd.xhscdn.com:8443/a.mp4", "blob:https://www.xiaohongshu.com/test"]) {
    const result = extractor.normalizeXiaohongshuSnapshot({ pageUrl: page, href: page, tag: "video", mediaUrl: url });
    assert.equal(result.media_url, "", url);
  }
});

test("XHS note IDs are host-bound and support note detail URL variants", () => {
  assert.equal(extractor.xiaohongshuNoteId(`https://www.xiaohongshu.com/discovery/item/${id}`), id);
  assert.equal(extractor.xiaohongshuNoteId(`https://www.xiaohongshu.com/search_result/${id}`), id);
  assert.equal(extractor.xiaohongshuNoteId(`https://www.xiaohongshu.com/user/profile/${other}/${id}?xsec_token=fixture`), id);
  assert.equal(extractor.xiaohongshuNoteId(`https://www.xiaohongshu.com/user/profile/${other}`), "");
  assert.equal(extractor.xiaohongshuNoteId(`https://evil.invalid/explore/${id}`), "");
});

function pageFixture({ kind = "video", cachedId = id, stream = mediaUrl, badge = true, links = [page], pageUrl = 'https://www.xiaohongshu.com/explore', cardId = '', detail = false, feedItem = null } = {}) {
  const metas = [];
  const listeners = new Map();
  const card = {
    matches: () => false,
    getAttribute: name => name === 'data-note-id' ? cardId : null,
    querySelectorAll: selector => selector === 'a[href]' ? links.map(href => ({ href })) : selector === 'svg use' && badge ? [{ getAttribute: () => '#play-s' }] : [],
    querySelector: selector => selector.includes('.title') ? { innerText: '当前卡片' } : null,
  };
  const image = { tagName: 'IMG', currentSrc: 'https://sns-webpic-qc.xhscdn.com/cover.webp', closest: selector => selector.includes(detail ? '#noteContainer' : 'note-item') ? card : null };
  const doc = {
    addEventListener: (name, callback) => listeners.set(name, callback),
    dispatchEvent: event => listeners.get(event.type)?.(event),
    querySelectorAll: () => metas,
    createElement: () => {
      const node = { dataset: {}, remove: () => { const index = metas.indexOf(node); if (index >= 0) metas.splice(index, 1); } };
      return node;
    },
    documentElement: { appendChild: node => metas.push(node) },
  };
  const context = vm.createContext({ document: doc, location: { hostname: 'www.xiaohongshu.com', href: pageUrl, origin: 'https://www.xiaohongshu.com' }, URL, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } }, __INITIAL_STATE__: {
    note: { noteDetailMap: { [id]: { note: { noteId: cachedId, type: kind, title: '同笔记标题', video: { media: { stream: { h264: [{ masterUrl: stream }] } } } } } } },
    feed: { feeds: { value: feedItem ? [feedItem] : [] } },
  } });
  for (const file of ['xiaohongshu-media-bridge.js', 'extractor.js']) vm.runInContext(readFileSync(new URL('../' + file, import.meta.url), 'utf8'), context);
  return { context, image, metas };
}

test("home feed selection keeps its own access token for detail resolution", () => {
  const token = 'fixture-feed-token';
  const fixture = pageFixture({
    links: [page.split('?')[0]],
    feedItem: {
      id,
      xsecToken: token,
      noteCard: {
        type: 'video',
        displayTitle: '首页视频标题',
        user: { nickName: '首页作者' },
        cover: { urlDefault: 'https://sns-webpic-qc.xhscdn.com/feed-cover.webp' },
        video: { capa: { duration: 8 } },
      },
    },
  });

  delete fixture.context.__INITIAL_STATE__.note.noteDetailMap[id];
  const result = fixture.context.__muyiVideoExtractor.extractSelection(fixture.image);

  assert.equal(result.page_url, `https://www.xiaohongshu.com/explore/${id}?xsec_token=${token}&xsec_source=pc_feed`);
  assert.equal(result.content_kind, 'video');
  assert.equal(result.media_url, '');
  assert.equal(result.page_title, '首页视频标题');
  assert.equal(result.author_name, '首页作者');
});

test("actual extractor and on-demand bridge integrate: cover -> same-ID H264 video", () => {
  const { context, image, metas } = pageFixture({ stream: mediaUrl.replace('https:', 'http:') });
  assert.equal(metas.length, 0, 'no note read or published before a user selection');
  const result = context.__muyiVideoExtractor.extractSelection(image);
  assert.equal(result.content_kind, 'video');
  assert.equal(result.media_url, mediaUrl);
  assert.equal(result.thumbnail_external_id, id);
  assert.equal(result.page_url, page);
  assert.equal(result.page_title, '同笔记标题');
});

test("home, profile and search cards retain the signed link even behind a bare hidden link", () => {
  const signed = page + '&xsec_source=pc_feed';
  for (const source of ['/explore', '/user/profile/fixture', '/search_result?keyword=fixture']) {
    const fixture = pageFixture({ links: [page.split('?')[0], signed], pageUrl: 'https://www.xiaohongshu.com' + source });
    const result = fixture.context.__muyiVideoExtractor.extractSelection(fixture.image);
    assert.equal(result.page_url, signed);
    assert.equal(result.external_id, id);
  }
});

test("detail URL access parameters survive a bare same-note card link", () => {
  const fixture = pageFixture({ pageUrl: page, links: [page.split('?')[0]], detail: true });
  assert.equal(fixture.context.__muyiVideoExtractor.extractSelection(fixture.image).page_url, page);
});

test("profile card selects its signed user/profile work link instead of its hidden explore link", () => {
  const signed = `https://www.xiaohongshu.com/user/profile/${other}/${id}?xsec_token=fixture&xsec_source=pc_user`;
  const fixture = pageFixture({ pageUrl: `https://www.xiaohongshu.com/user/profile/${other}`, links: [page.split('?')[0], signed] });
  const result = fixture.context.__muyiVideoExtractor.extractSelection(fixture.image);
  assert.equal(result.external_id, id);
  assert.equal(result.page_url, signed);
  assert.equal(result.media_url, mediaUrl);
});

test("an identified card cannot borrow a neighboring note's signed link", () => {
  const bare = page.split('?')[0];
  const fixture = pageFixture({ cardId: id, links: [page.replace(id, other), bare] });
  const result = fixture.context.__muyiVideoExtractor.extractSelection(fixture.image);
  assert.equal(result.external_id, id);
  assert.equal(result.page_url, bare);
});

test("later page hydration upgrades the saved URL even when metadata completeness ties", async () => {
  const fixture = pageFixture({ links: [page.split('?')[0]] });
  fixture.context.setTimeout = callback => { fixture.context.location.href = page; callback(); };
  assert.equal((await fixture.context.__muyiVideoExtractor.extractBestSelection(fixture.image)).page_url, page);
});

test("image selection cannot switch to another note during async capture", async () => {
  const links = [page];
  const fixture = pageFixture({ links, kind: 'normal', badge: false });
  fixture.context.setTimeout = callback => { links[0] = page.replace(id, other); callback(); };
  await assert.rejects(fixture.context.__muyiVideoExtractor.extractBestSelection(fixture.image), /作品发生变化/);
});

test("actual extractor keeps images and refuses stale note data on a later selection", () => {
  const { context, image } = pageFixture({ kind: 'normal', badge: false });
  assert.equal(context.__muyiVideoExtractor.extractSelection(image).content_kind, 'image');
  const fixture = pageFixture();
  assert.equal(fixture.context.__muyiVideoExtractor.extractSelection(fixture.image).media_url, mediaUrl);
  fixture.context.__INITIAL_STATE__.note.noteDetailMap[id].note.noteId = other;
  const retry = fixture.context.__muyiVideoExtractor.extractSelection(fixture.image);
  assert.equal(retry.content_kind, 'video');
  assert.equal(retry.media_url, '');
  assert.equal(fixture.metas.length, 0);
});

test("declared video metadata is used only when its declared note URL matches the selection", () => {
  const { context, image } = pageFixture({ cachedId: other, badge: false });
  context.document.querySelector = selector => ({ content: selector.includes('og:url') ? page : mediaUrl });
  assert.equal(context.__muyiVideoExtractor.extractSelection(image).media_url, mediaUrl);
  context.document.querySelector = selector => ({ content: selector.includes('og:url') ? `https://www.xiaohongshu.com/explore/${other}` : mediaUrl });
  assert.equal(context.__muyiVideoExtractor.extractSelection(image).content_kind, 'image');
});
