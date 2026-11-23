import test from "node:test";
import assert from "node:assert/strict";

const metas = [];
globalThis.location = {
  href: "https://www.douyin.com/video/7672000000000000222",
  origin: "https://www.douyin.com",
};
globalThis.document = {
  documentElement: { append: (node) => metas.push(node) },
  createElement: () => ({ name: "", dataset: {} }),
  querySelectorAll: () => metas,
};
globalThis.fetch = undefined;
globalThis.XMLHttpRequest = undefined;

await import("../douyin-media-bridge.js");

test("douyin detail candidate binds the author to the same work id", () => {
  const bridge = globalThis.__muyiDouyinMediaBridge;
  assert.equal(typeof bridge?.detailCandidate, "function");
  const candidate = bridge.detailCandidate({
    aweme_detail: {
      aweme_id: "7672000000000000222",
      author: { nickname: "剪辑研究所" },
      video: {
        play_addr: { url_list: ["https://v3-web.douyinvod.com/video/selected"] },
        origin_cover: { url_list: ["https://p3-pc.douyinpic.com/obj/selected-cover.jpeg"] },
        cover: { url_list: ["https://p3-pc.douyinpic.com/obj/fallback-cover.jpeg"] },
      },
    },
  });

  assert.deepEqual(candidate, {
    videoId: "7672000000000000222",
    mediaUrl: "https://v3-web.douyinvod.com/video/selected",
    coverUrl: "https://p3-pc.douyinpic.com/obj/selected-cover.jpeg",
    authorName: "剪辑研究所",
  });
});

test("douyin bridge publishes the cover on the same id-bound candidate node", () => {
  const bridge = globalThis.__muyiDouyinMediaBridge;
  bridge.publish({
    awemeDetail: {
      awemeId: "7672000000000000333",
      author: { nickname: "导演小王" },
      video: {
        playAddrH264: { urlList: ["https://v3-web.douyinvod.com/video/333"] },
        dynamicCover: { urlList: ["https://p3-pc.douyinpic.com/obj/333.webp"] },
      },
    },
  });

  const published = metas.find((node) => node.dataset.videoId === "7672000000000000333");
  assert.equal(published?.dataset.mediaUrl, "https://v3-web.douyinvod.com/video/333");
  assert.equal(published?.dataset.coverUrl, "https://p3-pc.douyinpic.com/obj/333.webp");
  assert.equal(published?.dataset.authorName, "导演小王");
});
