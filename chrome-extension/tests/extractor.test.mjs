// Explanation contract: docs/EXPLAIN.md
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

await import("../extractor.js");

const extractor = globalThis.__muyiVideoExtractor;

test("Adapter review state outranks a stale legacy capture status", () => {
  assert.equal(typeof extractor.captureNeedsReview, "function");
  assert.equal(
    extractor.captureNeedsReview({
      status: "saved",
      adapter: {
        contract_version: "muyi.capture-adapter.v1",
        outcome: "needs_review",
        artifact_state: "link_pending",
      },
    }),
    true,
  );
  assert.equal(
    extractor.captureNeedsReview({
      status: "capture_pending",
      adapter: {
        contract_version: "muyi.capture-adapter.v1",
        outcome: "success",
        artifact_state: "link_collected",
      },
    }),
    false,
  );
});

test("douyin waterfall card rejects badges and duration while keeping real work data", () => {
  assert.equal(typeof extractor.normalizeDouyinSnapshot, "function");
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/user/example/search/kuku?type=general",
    href: "",
    elementId: "waterfall_item_7671621304952327458",
    titleCandidates: ["Tag: 置顶", "00:09", "一招去掉AI大众脸，剪辑教程来了"],
    authorTexts: ["3.3万", "@剪辑研究所"],
    likeTexts: ["3.3万"],
    metaTexts: ["Tag: 置顶", "· 7月19日", "3.3万", "@剪辑研究所"],
    cardText: "Tag: 置顶\n一招去掉AI大众脸，剪辑教程来了\n@剪辑研究所\n· 7月19日\n3.3万\n00:09",
  });

  assert.equal(result.page_title, "一招去掉AI大众脸，剪辑教程来了");
  assert.equal(result.author_name, "@剪辑研究所");
  assert.equal(result.like_count_text, "3.3万");
  assert.equal(result.published_at_text, "7月19日");
  assert.equal(result.external_id, "7671621304952327458");
  assert.equal(result.page_url, "https://www.douyin.com/video/7671621304952327458");
});

test("douyin profile modal vid identifies the exact work for media matching", () => {
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/user/example?from_tab_name=main&vid=7671621304952327458",
    href: "",
    elementId: "",
    titleCandidates: ["一招去掉 AI 大众脸"],
  });

  assert.equal(result.external_id, "7671621304952327458");
  assert.equal(result.page_url, "https://www.douyin.com/video/7671621304952327458");
});

test("douyin page variants keep one exact work identity before media resolution", () => {
  const cases = [
    {
      name: "搜索瀑布流",
      pageUrl: "https://www.douyin.com/search/舞蹈换装?aid=3c6e7b70-6b44-4c01-8277-e475aa81301a&type=general",
      elementId: "waterfall_item_7649756646901648691",
      expectedId: "7649756646901648691",
    },
    {
      name: "用户主页作品网格",
      pageUrl: "https://www.douyin.com/user/MS4wLjABAAAA-example",
      elementId: "waterfall_item_7648326443784572211",
      expectedId: "7648326443784572211",
    },
    {
      name: "个人主页弹层 modal_id",
      pageUrl: "https://www.douyin.com/user/MS4wLjABAAAA-example?modal_id=7671621304952327458",
      expectedId: "7671621304952327458",
    },
    {
      name: "个人主页弹层 vid",
      pageUrl: "https://www.douyin.com/user/MS4wLjABAAAA-example?vid=7671621304952327459",
      expectedId: "7671621304952327459",
    },
    {
      name: "独立作品详情",
      pageUrl: "https://www.douyin.com/video/7671621304952327460",
      expectedId: "7671621304952327460",
    },
    {
      name: "无刷新悬停卡片",
      pageUrl: "https://www.douyin.com/search/换装?type=video",
      elementId: "waterfall_item_7671621304952327461",
      expectedId: "7671621304952327461",
    },
  ];

  for (const item of cases) {
    const result = extractor.normalizeDouyinSnapshot({
      pageUrl: item.pageUrl,
      elementId: item.elementId || "",
      titleCandidates: [`${item.name}测试作品`],
    });
    assert.equal(result.external_id, item.expectedId, item.name);
    assert.equal(result.page_url, `https://www.douyin.com/video/${item.expectedId}`, item.name);
    assert.equal(result.source_identity_verified, true, item.name);
  }

  const staleSpaResult = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/video/7671621304952327462",
    elementId: "waterfall_item_7671621304952327463",
    titleCandidates: ["页面刚无刷新切换，旧卡还留在 DOM"],
  });
  assert.equal(staleSpaResult.external_id, "");
  assert.equal(staleSpaResult.source_identity_verified, false);
});

test("douyin modal identity outranks an unrelated anchor left behind in the player", () => {
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/user/kuku?modal_id=7671621304952327458",
    href: "https://www.douyin.com/video/7999999999999999999",
    elementId: "",
    titleCandidates: ["如何制作真人娃娃换装效果"],
  });

  assert.equal(result.external_id, "7671621304952327458");
  assert.equal(result.page_url, "https://www.douyin.com/video/7671621304952327458");
  assert.equal(result.source_identity_verified, true);
});

test("douyin search modal overrides its parent detail path but still checks the clicked player", () => {
  const oldId = "7677188771956611252";
  const activeId = "7689472634324585754";
  const parentUrl = `https://www.douyin.com/video/${oldId}/search/沧元图?type=general`;
  const modalUrl = `${parentUrl}&modal_id=${activeId}`;
  const result = extractor.normalizeDouyinSnapshot({ pageUrl: modalUrl, feedVideoId: activeId });
  assert.equal(result.external_id, activeId);
  assert.equal(result.source_identity_verified, true);
  assert.equal(result.page_url, `https://www.douyin.com/video/${activeId}`);
  const conflict = extractor.normalizeDouyinSnapshot({ pageUrl: modalUrl, feedVideoId: oldId });
  assert.equal(conflict.external_id, "");
  assert.equal(conflict.source_identity_verified, false);
  // Closing the modal exposes search cards, not the parent detail's old work.
  const card = extractor.normalizeDouyinSnapshot({ pageUrl: parentUrl, elementId: `waterfall_item_${activeId}` });
  assert.equal(card.external_id, activeId);
  const noWork = extractor.normalizeDouyinSnapshot({ pageUrl: parentUrl });
  assert.equal(noWork.source_identity_verified, false);
});

test("douyin waterfall identity outranks a neighboring work link", () => {
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/search/kuku",
    href: "https://www.douyin.com/video/7999999999999999999",
    elementId: "waterfall_item_7671621304952327458",
    titleCandidates: ["如何制作真人娃娃换装效果"],
  });

  assert.equal(result.external_id, "7671621304952327458");
  assert.equal(result.source_identity_verified, true);
});

test("douyin selection without one exact work identity stays unverified", () => {
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/user/kuku",
    href: "",
    elementId: "",
    titleCandidates: ["如何制作真人娃娃换装效果"],
  });

  assert.equal(result.external_id, "");
  assert.equal(result.source_identity_verified, false);
});

test("embedded Douyin share links are normalized independently from the container platform", () => {
  assert.equal(typeof extractor.normalizePlatformWorkUrl, "function");
  assert.deepEqual(
    extractor.normalizePlatformWorkUrl(
      "https://www.iesdouyin.com/share/video/7667949975325658404/?region=CN&mid=1",
    ),
    {
      page_url: "https://www.douyin.com/video/7667949975325658404",
      platform: "douyin",
      external_id: "7667949975325658404",
      source_identity_verified: true,
    },
  );
});

test("container pages stay on their own platform when no embedded work identity exists", () => {
  assert.deepEqual(
    extractor.normalizePlatformWorkUrl(
      "https://www.xingtu.cn/ad/creator/insight/content-market?keyword=ai%E8%A7%86%E9%A2%91",
    ),
    {
      page_url: "https://www.xingtu.cn/ad/creator/insight/content-market?keyword=ai%E8%A7%86%E9%A2%91",
      platform: "xingtu.cn",
      external_id: "",
      source_identity_verified: false,
    },
  );
});

test("douyin card never promotes a player duration or numeric metric into title or author", () => {
  const result = extractor.normalizeDouyinSnapshot({
    pageUrl: "https://www.douyin.com/search/kuku",
    href: "https://www.douyin.com/video/7670000000000000000",
    elementId: "",
    titleCandidates: ["00:09", "Tag: 置顶"],
    authorTexts: ["3.3万"],
    likeTexts: [],
    metaTexts: ["00:09", "3.3万"],
    cardText: "00:09\nTag: 置顶\n3.3万",
  });

  assert.equal(result.page_title, "");
  assert.equal(result.author_name, "");
});

test("douyin detail author is selected only for the exact work id", () => {
  assert.equal(typeof extractor.douyinAuthorName, "function");
  const candidates = [
    { videoId: "111", authorName: "相邻作品博主" },
    { videoId: "222", authorName: "当前作品博主" },
  ];

  assert.equal(extractor.douyinAuthorName("222", candidates), "当前作品博主");
  assert.equal(extractor.douyinAuthorName("333", candidates), "");
});

test("selected image becomes its own capture payload with the original image URL", () => {
  assert.equal(typeof extractor.normalizeImageSelectionSnapshot, "function");
  const result = extractor.normalizeImageSelectionSnapshot({
    pageUrl: "https://www.douyin.com/note/123",
    mediaUrl: "https://p.example.com/photos/original-01.webp",
    alt: "白色耳机产品渲染图",
    titleCandidates: ["Tag: 置顶", "白色耳机产品渲染图"],
    platform: "douyin",
    authorName: "@产品视觉研究所",
    externalId: "123",
  });

  assert.equal(result.content_kind, "image");
  assert.equal(result.media_url, "https://p.example.com/photos/original-01.webp");
  assert.equal(result.thumbnail_url, "https://p.example.com/photos/original-01.webp");
  assert.equal(result.page_title, "白色耳机产品渲染图");
  assert.equal(result.author_name, "@产品视觉研究所");
});

test("image capture picks the largest declared source for the selected responsive image", () => {
  const media = {
    tagName: "IMG", baseURI: "https://example.com/work",
    currentSrc: "https://example.com/preview.png", srcset: "/preview.png 320w, /original.png 1280w",
  };
  assert.equal(extractor.originalImageUrlFor(media), "https://example.com/original.png");
  assert.equal(extractor.originalImageUrlFor({ ...media, currentSrc: "https://example.com/other.png" }),
    "https://example.com/other.png");
  assert.equal(extractor.originalImageUrlFor({ ...media, currentSrc: "https://pbs.twimg.com/media/example?format=png&name=small" }),
    "https://pbs.twimg.com/media/example?format=png&name=orig");
  assert.equal(extractor.normalizeImageSelectionSnapshot({
    alt: "公开测试原图", page_title: "正在识别素材并收集，请稍候…",
  }).page_title, "公开测试原图");
});

test("option click can recognize a large CSS background image before the browser downloads its link", () => {
  const originalGetComputedStyle = globalThis.getComputedStyle;
  globalThis.getComputedStyle = (element) => ({
    display: "block",
    visibility: "visible",
    backgroundImage: element.backgroundImage || "none",
  });
  const card = {
    tagName: "DIV",
    backgroundImage: 'url("https://p.example.com/gallery/cover.webp")',
    parentElement: null,
    matches: () => false,
    querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 300, bottom: 400, width: 300, height: 400 }),
  };

  try {
    assert.equal(extractor.visibleMediaAt(card, 120, 180), card);
    assert.equal(extractor.mediaKindFor(card), "image");
    assert.equal(extractor.mediaUrlFor(card), "https://p.example.com/gallery/cover.webp");
  } finally {
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test("douyin title falls back to page metadata instead of keeping a player instruction", () => {
  const result = extractor.normalizeDouyinSnapshot({
    href: "https://www.douyin.com/video/7671621304952327458",
    titleCandidates: ["Tag: 置顶", "00:09", "点击按住可拖动视频"],
    fallbackTitleCandidates: ["一招去掉 AI 大众脸，剪辑教程来了"],
  });

  assert.equal(result.page_title, "一招去掉 AI 大众脸，剪辑教程来了");
});

test("x video links normalize to the exact status page used by the download workflow", () => {
  assert.equal(typeof extractor.normalizeXStatusUrl, "function");
  assert.equal(
    extractor.normalizeXStatusUrl("https://twitter.com/underwoodxie96/status/2088929000513278308/video/1?ref_src=twsrc%5Etfw"),
    "https://x.com/underwoodxie96/status/2088929000513278308",
  );
  assert.equal(
    extractor.normalizeXStatusUrl("https://x.com/MrLarus/status/2089318509591314449/photo/1"),
    "https://x.com/MrLarus/status/2089318509591314449",
  );
  assert.equal(extractor.externalIdFor("https://x.com/MrLarus/status/2089318509591314449"), "2089318509591314449");
});

test("x status url supplies the account handle when the card dom has no author", () => {
  assert.equal(typeof extractor.xAuthorHandleFor, "function");
  assert.equal(
    extractor.xAuthorHandleFor("https://x.com/PixelAigc/status/2089714325388943747"),
    "@PixelAigc",
  );
  assert.equal(extractor.xAuthorHandleFor("https://x.com/home"), "");
});

test("x video selects the matching Twitter CDN playlist instead of the temporary blob URL", () => {
  assert.equal(typeof extractor.xMediaStreamUrl, "function");
  const media = {
    currentSrc: "blob:https://x.com/temporary-player-url",
    src: "",
    poster: "https://pbs.twimg.com/amplify_video_thumb/2090312061058514944/img/PHxBUiEN5wWiTqkt.jpg",
  };
  const resources = [
    "https://video.twimg.com/amplify_video/1111111111111111111/pl/unrelated.m3u8?tag=21",
    "https://video.twimg.com/amplify_video/2090312061058514944/pl/master.m3u8?tag=21",
    "https://video.twimg.com/amplify_video/2090312061058514944/vid/avc1/1280x720/segment.m4s",
  ];

  assert.equal(
    extractor.xMediaStreamUrl(media, resources),
    "https://video.twimg.com/amplify_video/2090312061058514944/pl/master.m3u8?tag=21",
  );
});

test("a real HTTP media URL outranks a blob-only extraction with the same metadata", () => {
  assert.ok(
    extractor.completeness({ page_title: "示例", media_url: "https://video.twimg.com/example.mp4" })
      > extractor.completeness({ page_title: "示例", media_url: "blob:https://x.com/temporary" }),
  );
});

test("douyin blob player resolves the matching real media URL captured from detail data", () => {
  assert.equal(typeof extractor.douyinMediaStreamUrl, "function");
  const media = { currentSrc: "blob:https://www.douyin.com/temporary", src: "" };
  const candidates = [
    { videoId: "111", mediaUrl: "https://v3-web.douyinvod.com/video/other" },
    { videoId: "222", mediaUrl: "https://v3-web.douyinvod.com/video/selected" },
  ];

  assert.equal(
    extractor.douyinMediaStreamUrl(media, "222", candidates),
    "https://v3-web.douyinvod.com/video/selected",
  );
  assert.equal(extractor.douyinMediaStreamUrl(media, "333", candidates), "");
});

test("douyin player never trusts a direct stream that is not bound to the selected work id", () => {
  const media = {
    tagName: "VIDEO",
    currentSrc: "https://v3-web.douyinvod.com/video/stale-player-stream",
    src: "",
  };
  const candidates = [
    {
      videoId: "7672000000000000222",
      mediaUrl: "https://v3-web.douyinvod.com/video/selected-stream",
      coverUrl: "https://p3-pc.douyinpic.com/obj/selected-cover.jpeg",
    },
  ];

  assert.equal(
    extractor.douyinMediaStreamUrl(media, "7672000000000000222", candidates),
    "https://v3-web.douyinvod.com/video/selected-stream",
  );
  assert.equal(extractor.douyinMediaStreamUrl(media, "7672000000000000999", candidates), "");
});

test("douyin cover comes only from the candidate with the selected work id", () => {
  assert.equal(typeof extractor.douyinCoverUrl, "function");
  const candidates = [
    { videoId: "111", coverUrl: "https://p.example.com/111.jpg" },
    { videoId: "222", coverUrl: "https://p.example.com/222.jpg" },
  ];

  assert.equal(extractor.douyinCoverUrl("222", candidates), "https://p.example.com/222.jpg");
  assert.equal(extractor.douyinCoverUrl("333", candidates), "");
});

test("douyin visible card cover is accepted only when it is bound to the selected work", () => {
  assert.equal(typeof extractor.selectDouyinVisibleCover, "function");
  const candidates = [
    {
      videoId: "111",
      url: "https://p3.douyinpic.com/aweme/other-card.jpeg",
      width: 720,
      height: 1280,
    },
    {
      videoId: "222",
      url: "https://p3.douyinpic.com/aweme/selected-card.jpeg",
      width: 720,
      height: 1280,
    },
  ];

  assert.equal(
    extractor.selectDouyinVisibleCover("222", candidates),
    "https://p3.douyinpic.com/aweme/selected-card.jpeg",
  );
  assert.equal(extractor.selectDouyinVisibleCover("333", candidates), "");
});

test("douyin visible card cover rejects avatar and tiny decorative images", () => {
  const candidates = [
    {
      videoId: "222",
      url: "https://p3.douyinpic.com/aweme/avatar.jpeg",
      width: 640,
      height: 640,
      excluded: true,
    },
    {
      videoId: "222",
      url: "https://p3.douyinpic.com/aweme/badge.jpeg",
      width: 80,
      height: 80,
    },
    {
      videoId: "222",
      url: "https://p3.douyinpic.com/aweme/current-cover.jpeg",
      width: 640,
      height: 360,
    },
  ];

  assert.equal(
    extractor.selectDouyinVisibleCover("222", candidates),
    "https://p3.douyinpic.com/aweme/current-cover.jpeg",
  );
});

test("douyin DOM collector reads the visible cover from the exact selected waterfall card", () => {
  const videoId = "7671621304952327458";
  const anchor = { href: `https://www.douyin.com/video/${videoId}` };
  const cover = {
    currentSrc: "https://p3.douyinpic.com/aweme/current-visible-cover.jpeg",
    src: "",
    getBoundingClientRect: () => ({ width: 360, height: 640 }),
    closest: () => null,
  };
  const avatar = {
    currentSrc: "https://p3.douyinpic.com/aweme/author-avatar.jpeg",
    src: "",
    getBoundingClientRect: () => ({ width: 200, height: 200 }),
    closest: () => ({}),
  };
  const scope = {
    id: `waterfall_item_${videoId}`,
    matches: () => false,
    querySelectorAll(selector) {
      if (selector.includes('a[href*="/video/"]')) return [anchor];
      if (selector === "img[src]") return [avatar, cover];
      if (selector === "*") return [avatar, cover];
      return [];
    },
  };
  const media = {
    poster: "",
    getAttribute: () => "",
    closest: () => scope,
  };
  const previousLocation = globalThis.location;
  const previousGetComputedStyle = globalThis.getComputedStyle;
  globalThis.location = {
    href: "https://www.douyin.com/search/换装?type=general",
    hostname: "www.douyin.com",
  };
  globalThis.getComputedStyle = () => ({ display: "block", visibility: "visible", backgroundImage: "none" });
  try {
    assert.equal(
      extractor.douyinVisibleCoverUrl(media, videoId),
      "https://p3.douyinpic.com/aweme/current-visible-cover.jpeg",
    );
  } finally {
    if (previousLocation === undefined) delete globalThis.location;
    else globalThis.location = previousLocation;
    if (previousGetComputedStyle === undefined) delete globalThis.getComputedStyle;
    else globalThis.getComputedStyle = previousGetComputedStyle;
  }
});


test("nearest work link wins over an earlier neighboring status link", () => {
  const selected = "https://x.com/selected/status/2094494202587398616";
  const neighbor = "https://x.com/neighbor/status/2094494202587398617";
  const outer = { querySelectorAll: () => [{ href: neighbor }, { href: selected }] };
  const inner = { parentElement: outer, querySelectorAll: () => [{ href: selected }] };
  assert.equal(extractor.preferredLink(inner), selected);
});

test("ambiguous work links are rejected instead of using the first work", () => {
  const card = { querySelectorAll: () => [
    { href: "https://x.com/first/status/2094494202587398616" },
    { href: "https://x.com/second/status/2094494202587398617" },
  ] };
  assert.throws(() => extractor.preferredLink(card), /多个作品/);
});

test("X search video keeps its own post through twenty player wrappers", () => {
  const selected = "https://x.com/selected/status/2100176000005107728";
  const article = {
    matches: () => true,
    querySelectorAll: () => [{ href: selected }, { href: selected + "/analytics" }],
  };
  let media = article;
  for (let i = 0; i < 20; i++) {
    media = { parentElement: media, querySelectorAll: () => [], matches: () => false };
  }
  media.closest = () => article;
  const sandbox = { URL, location: { href: "https://x.com/search?q=fight", hostname: "x.com" }, document: { querySelector: () => null } };
  vm.runInNewContext(readFileSync(new URL("../extractor.js", import.meta.url), "utf8"), sandbox);
  assert.equal(sandbox.__muyiVideoExtractor.preferredLink(media), selected);
});

test("an unidentified X card never borrows a neighboring post or saves the search URL", () => {
  const outer = { querySelectorAll: () => [{ href: "https://x.com/neighbor/status/2100176000005107728" }] };
  const article = { parentElement: outer, matches: () => true, querySelectorAll: () => [] };
  const media = { parentElement: article, closest: () => article, querySelectorAll: () => [] };
  const sandbox = { URL, location: { href: "https://x.com/search?q=fight", hostname: "x.com" }, document: { querySelector: () => null } };
  vm.runInNewContext(readFileSync(new URL("../extractor.js", import.meta.url), "utf8"), sandbox);
  assert.throws(() => sandbox.__muyiVideoExtractor.preferredLink(media), /推文/);
});

test("X playlist survives resource timing eviction without borrowing another video's stream", () => {
  let report;
  const playlist = "https://video.twimg.com/amplify_video/2100159857609613312/pl/master.m3u8?tag=21";
  const sandbox = {
    location: { hostname: "x.com" },
    performance: { getEntriesByType: () => [] },
    PerformanceObserver: class { constructor(callback) { report = callback; } observe() {} },
    URL,
  };
  vm.runInNewContext(readFileSync(new URL("../extractor.js", import.meta.url), "utf8"), sandbox);
  report?.({ getEntries: () => [
    { name: playlist },
    { name: "https://video.twimg.com/amplify_video/9999999999999999999/vid/1280x720/other.mp4" },
    { name: "https://video.twimg.com/amplify_video/2100159857609613312/vid/avc1/12000/15000/480x270/part.m4s" },
  ] });
  assert.equal(sandbox.__muyiVideoExtractor.xMediaStreamUrl({
    poster: "https://pbs.twimg.com/amplify_video_thumb/2100159857609613312/img/cover.jpg",
    currentSrc: "blob:https://x.com/player",
  }), playlist);
});

test("X fragmented MP4 initialization header cannot outrank its playable master playlist", () => {
  const playlist = "https://video.twimg.com/amplify_video/2092807598437531648/pl/vMAE2yDLcS1bzBB2.m3u8?tag=29";
  assert.equal(extractor.xMediaStreamUrl({
    poster: "https://pbs.twimg.com/amplify_video_thumb/2092807598437531648/img/cover.jpg",
  }, [
    playlist,
    "https://video.twimg.com/amplify_video/2092807598437531648/aud/mp4a/0/0/64000/audio.mp4",
    "https://video.twimg.com/amplify_video/2092807598437531648/vid/avc1/0/0/1280x720/J9-bxCSuxxHByO4z.mp4",
  ]), playlist);
});

test("Douyin account total received likes must never become work likes", () => {
  for (const likeTexts of [[], ["获赞167.7万"], ["VibePaper 粉丝2.7万获赞167.7万"]]) {
    assert.equal(extractor.normalizeDouyinSnapshot({ likeTexts, metaTexts: ["获赞167.7万"] }).like_count_text, "");
  }
  assert.equal(extractor.normalizeDouyinSnapshot({ likeTexts: ["获赞167.7万", "1672"], metaTexts: ["获赞167.7万"] }).like_count_text, "1672");
});


test("an unplayed X video poster is collected as video without borrowing a neighbor or the cover URL", () => {
  const work = "https://x.com/selected/status/2100176000005107728";
  const poster = "https://pbs.twimg.com/amplify_video_thumb/2100176000005107729/img/cover.jpg";
  const article = { innerText: "视频示例标题", querySelector: () => null, querySelectorAll: (selector) => selector === "a[href]" ? [{href:work}] : [], getAttribute: () => "", matches: () => true };
  const media = { tagName:"IMG", src:poster, currentSrc:poster, alt:"视频封面", closest: () => article, parentElement:article, querySelectorAll: () => [], getAttribute: () => "" };
  const sandbox = { URL, location:{href:work,hostname:"x.com"}, document:{querySelector:()=>null}, innerWidth:1200, innerHeight:900 };
  vm.runInNewContext(readFileSync(new URL("../extractor.js", import.meta.url), "utf8"), sandbox);
  const result = sandbox.__muyiVideoExtractor.extractSelection(media);
  assert.equal(result.content_kind, "video");
  assert.equal(result.media_url, "");
  assert.equal(result.thumbnail_url, poster);
  assert.equal(result.external_id, "2100176000005107728");
  media.src = media.currentSrc = "https://pbs.twimg.com/media/normal-photo.jpg";
  assert.equal(sandbox.__muyiVideoExtractor.extractSelection(media).content_kind, "image");
  media.src = media.currentSrc = "https://pbs.twimg.com/profile_images/avatar.jpg";
  assert.equal(sandbox.__muyiVideoExtractor.xVideoPosterUrl(media), "");
});
