// Explanation contract: docs/explain/douyin-page-capture-matrix.md
import test from "node:test";
import assert from "node:assert/strict";

await import("../extractor.js");
const extractor = globalThis.__muyiVideoExtractor;
const workId = "7679127581790096682";
const otherId = "7678641364720012587";

test("recommend feed identifies its work from the card data-e2e-vid without a work URL", () => {
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/?recommend=1",
    elementId: "slideMode",
    feedVideoId: workId,
  });
  assert.equal(result.external_id, workId);
  assert.equal(result.page_url, `https://www.douyin.com/video/${workId}`);
  assert.equal(result.source_identity_verified, true);
});

test("feed identity conflicts with a detail URL or waterfall ID fail closed", () => {
  for (const snapshot of [
    { pageUrl: `https://www.douyin.com/video/${otherId}` },
    { pageUrl: "https://www.douyin.com/?recommend=1", elementId: `waterfall_item_${otherId}` },
  ]) {
    const result = extractor.normalizeDouyinSnapshot({ ...snapshot, feedVideoId: workId });
    assert.equal(result.external_id, "");
    assert.equal(result.source_identity_verified, false);
  }
});

test("feed ID stays authoritative over unrelated sidebar links and rejects malformed IDs", () => {
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/?recommend=1",
    feedVideoId: workId,
    href: `https://www.douyin.com/video/${otherId}`,
  });
  assert.equal(result.external_id, workId);
  for (const feedVideoId of ["", "123", "undefined", `${workId}x`, `${workId},${otherId}`]) {
    assert.equal(extractor.normalizeDouyinSnapshot({
      pageUrl: "https://www.douyin.com/?recommend=1", feedVideoId,
    }).source_identity_verified, false);
  }
});

// Minimal browser boundary for the real extractor. Structure/attributes mirror the
// observed feed: active card > playerContainer > video-info, with a sibling sidebar.
function feedFixture() {
  const text = (innerText) => ({ innerText, getAttribute: () => null, closest: () => null });
  const title = text("第107集：这是一条无码的视频");
  const author = text("@徐导深iNG");
  const date = text("· 1天前");
  const like = text("492");
  const unrelated = text("另一条作品的详细标题与长评论，不属于这条视频，绝不能覆盖当前作品！");
  const cover = { ...text(""), currentSrc: "https://p3.douyinpic.com/aweme/feed-cover.jpeg",
    getBoundingClientRect: () => ({ width: 640, height: 360 }) };
  const unrelatedCover = { ...cover, currentSrc: "https://p3.douyinpic.com/aweme/other-cover.jpeg",
    getBoundingClientRect: () => ({ width: 1280, height: 720 }) };
  const info = {
    get innerText() { return `${author.innerText}\n${date.innerText}\n${title.innerText}`; },
    querySelectorAll(selector) {
      if (selector.includes('feed-video-nickname')) return [author];
      if (selector.includes('desc') || selector.includes('title')) return [title];
      return [author, date, title];
    },
  };
  const player = {
    querySelector: (selector) => selector === '[data-e2e="video-info"]' ? fixture.info : null,
    querySelectorAll(selector) {
      if (selector.includes('digg')) return [like];
      if (selector === "svg") return [];
      if (selector === "img[src]" || selector === "*") return [cover];
      return [unrelated, title, author, date];
    },
    contains: (node) => node === info || node === cover || node === media,
  };
  const scope = {
    id: "slideMode",
    getAttribute: (name) => name === "data-e2e-vid" ? fixture.id : name === "data-e2e" ? "feed-active-video" : null,
    matches: (selector) => selector.includes('feed-active-video'),
    contains: (node) => node === player || node === media || node === info,
    innerText: `${unrelated.innerText}\n${info.innerText}`,
    querySelector: (selector) => selector === '[data-e2e="video-info"]' ? fixture.info : null,
    querySelectorAll(selector) {
      if (selector.includes('a[href*="/video/"]')) return fixture.sidebarLinks || [];
      if (selector.includes('digg')) return [like];
      if (selector === "svg") return [];
      if (selector === "img[src]" || selector === "*") return [unrelatedCover, cover];
      if (selector.includes('feed-video-nickname')) return [text("旁边的博主"), author];
      return [unrelated, title, author, date];
    },
  };
  const media = {
    tagName: "VIDEO", poster: "", currentSrc: "blob:https://www.douyin.com/example", parentElement: player,
    getAttribute: () => null,
    closest(selector) {
      if (selector === ".playerContainer") return player;
      return selector.includes('feed-active-video') || selector.includes('feed-item') ? scope : null;
    },
  };
  const fixture = { id: workId, info, media, cover, title, author, like, player };
  return fixture;
}

async function withFeed(fixture, run) {
  const previous = Object.fromEntries(["location", "document", "getComputedStyle", "setTimeout"]
    .map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.assign(globalThis, {
    location: { href: "https://www.douyin.com/?recommend=1", hostname: "www.douyin.com" },
    document: { querySelectorAll: () => [], querySelector: () => ({ content: "网站旧标题不属于当前视频" }), title: "抖音-记录美好生活" },
    getComputedStyle: () => ({ display: "block", visibility: "visible", backgroundImage: "none" }),
  });
  try { return await run(fixture); }
  finally {
    for (const [key, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
}

test("actual feed DOM collection keeps identity title author likes and cover on the selected card", async () => {
  await withFeed(feedFixture(), ({ media, title, author, cover }) => {
    const result = extractor.extractSelection(media);
    assert.equal(result.external_id, workId);
    assert.equal(result.page_title, title.innerText);
    assert.equal(result.author_name, author.innerText);
    assert.equal(result.like_count_text, "492");
    assert.equal(result.published_at_text, "1天前");
    assert.equal(result.thumbnail_url, cover.currentSrc);
    assert.equal(result.thumbnail_external_id, workId);
    assert.equal(result.media_url, ""); // Blob is not promoted to a portable media URL.
  });
});

test("feed without video-info does not borrow a sidebar or page-level title", async () => {
  const fixture = feedFixture();
  fixture.info = null;
  await withFeed(fixture, ({ media }) => {
    const result = extractor.extractSelection(media);
    assert.equal(result.external_id, workId);
    assert.equal(result.page_title, "");
    assert.equal(result.author_name, "");
  });
});

test("feed video-info inside player controls retains the author and full description", async () => {
  const fixture = feedFixture();
  fixture.title.innerText = "第1集：原创怪谈惊悚剧：《雨夜之下》第一集\n#VidMuse #VidMuse光点计划 #雨夜之下 #规则怪谈 #悬疑 开始尝试新的类型，不知道各位喜不喜欢~";
  fixture.author.innerText = "@方块超会剪";
  fixture.title.closest = fixture.author.closest = () => ({});
  await withFeed(fixture, ({ media }) => {
    const result = extractor.extractSelection(media);
    assert.equal(result.author_name, "@方块超会剪");
    assert.equal(result.page_title, "第1集：原创怪谈惊悚剧：《雨夜之下》第一集 #VidMuse #VidMuse光点计划 #雨夜之下 #规则怪谈 #悬疑 开始尝试新的类型，不知道各位喜不喜欢~");
  });
});

test("feed missing its work attribute never borrows a sidebar video link", async () => {
  const fixture = feedFixture();
  fixture.id = "";
  fixture.sidebarLinks = [{ href: `https://www.douyin.com/video/${otherId}` }];
  await withFeed(fixture, ({ media }) => {
    const result = extractor.extractSelection(media);
    assert.equal(result.source_identity_verified, false);
    assert.equal(result.external_id, "");
  });
});

test("feed switching during asynchronous collection rejects a mixed identity", async () => {
  const fixture = feedFixture();
  await withFeed(fixture, async ({ media }) => {
    globalThis.setTimeout = (callback) => { fixture.id = otherId; callback(); };
    await assert.rejects(extractor.extractBestSelection(media), /作品发生变化/);
  });
});

test("a feed ID that loads after the initial sample may still be collected", async () => {
  const fixture = feedFixture();
  fixture.id = "";
  await withFeed(fixture, async ({ media }) => {
    globalThis.setTimeout = (callback) => { fixture.id = workId; callback(); };
    const result = await extractor.extractBestSelection(media);
    assert.equal(result.source_identity_verified, true);
    assert.equal(result.external_id, workId);
  });
});


test("a complete first sample is rechecked before submission", async () => {
  const fixture = feedFixture();
  fixture.media.currentSrc = "https://media.example.com/selected.mp4";
  await withFeed(fixture, async ({ media }) => {
    document.querySelectorAll = () => [{ dataset: { videoId: workId, mediaUrl: "https://media.example.com/selected.mp4" } }];
    assert.equal(extractor.completeness(extractor.extractSelection(media)), 6);
    globalThis.setTimeout = (callback) => { fixture.id = otherId; callback(); };
    await assert.rejects(extractor.extractBestSelection(media), /作品发生变化/);
  });
});

test("a media node removed while waiting cannot be submitted", async () => {
  await withFeed(feedFixture(), async ({ media }) => {
    media.isConnected = true;
    globalThis.setTimeout = (callback) => { media.isConnected = false; callback(); };
    await assert.rejects(extractor.extractBestSelection(media), /已离开页面/);
  });
});

test("work digg count inside the player is retained instead of falling back to author totals", async () => {
  const fixture = feedFixture();
  fixture.like.innerText = "1672";
  fixture.like.closest = () => fixture.player;
  await withFeed(fixture, ({ media }) => {
    assert.equal(extractor.extractSelection(media).like_count_text, "1672");
  });
});
