# 素材来源与授权

代码使用根目录 LICENSE 的 MIT License，保留 Copyright (c) 2026 QCYTSN。完整发行包为混合授权，代码许可不自动适用于所有动画。

## 基础角色动画

来源：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)，固定提交 `549fff2ea33c2acfb16612c76912c6137da4a758`，目录 `dsh-pet/assets/webm/`。该固定来源随附的 MIT 文本保留在 `assets/dsh-pet-LICENSE.txt`；本仓库不授予超出来源声明的角色、商标等权利。

`assets/pet-manifest.json` 记录视频 SHA-256、帧区间和裁剪。1.0 版核验 14 个视频后，用 FFmpeg 7.1 / libvpx-vp9 解码透明 RGBA，按 `[100, 0, 412, 344]` 裁剪，使用 Pillow 13.0.0 导出 3,444 帧无损 WebP。保留原始 24 fps 帧序和现有播放时序；拖动与落地由同一视频分段。尺寸、透明通道逐帧核验一致。原视频为 640×360，不宣称有原生高清替代。

## 社区扩展动画（独立非商业条款）

89 组 `assets/pet/extra_*/` 序列来自 [luweiyabo/dsh-whale-pet](https://github.com/luweiyabo/dsh-whale-pet)，固定提交 `b61b445e6be05a732fc6738b825240aeffdf6769`。其媒体声明追溯至 PC2005-cloud/dsh-pet，允许用于开源项目、禁止商业使用。完整声明原样保留在 `assets/community-notices/THIRD_PARTY_ASSETS.md`。

这些媒体不由本仓库以 MIT 重新授权，再分发、修改和使用时须保留署名并遵守原条款。源路径和摘要见 `assets/pet-extra-manifest.json`；扩展帧保留完整透明 640×360 画布，运行时对基础裁剪帧补透明边距以对齐人物。

本版 95 个手动动作由 6 个基础动作和 89 组社区扩展动作组成。请勿将整个素材包作为 MIT 商用素材销售；商用请联系权利人取得明确授权。

## 光标、声音和界面图标

- `assets/cursor_grab.cur`、`assets/cursor_grabbing.cur` 原样复制自 Chromium `ui/resources/cursors/`，使用 BSD 3-Clause。许可证、来源和摘要见 `assets/cursors/`。
- `assets/sounds/` 提示音为上游项目程序生成的原创音频，沿用其 MIT 授权，不含第三方录音。
- `runtime/ui-icons/` 勾选与下拉箭头为项目绘制 SVG，沿用代码许可。

## 交互参考

拖拽倾斜、旋转裁剪头部扒边、悬停提示和空闲溜达的交互设计参考 [duhaoze2007/Baifanyu-For-Win](https://github.com/duhaoze2007/Baifanyu-For-Win)，固定提交 `f92cbe942e154ee2971e8fa7e93d1061a302c2c1`。该项目代码的 MIT 版权和完整许可保留在 `assets/community-notices/Baifanyu-For-Win-LICENSE.txt`。本项目使用自身已有动画实现这些效果，未引入该项目的立绘、图标或声音。详细适配见 `docs/interaction-reference.md`。

## 便携运行库

Windows Release 包含 Python 3.12.10、PySide6 Essentials / Qt 6.12、Shiboken6 和 Pillow 13.0.0。下载来源与摘要见 `RUNTIME-SOURCES.json`；许可证随 `.windows-runtime/LICENSE.txt` 和各依赖的 license/dist-info 目录提供。

画面增强为可关闭的本地像素处理，不改变原媒体许可。此仓库不包含旧版 `legacy/dafeiyu/` 角色素材。GitHub 与发行包均不包含用户任务记录。

本项目为非官方社区改编，与 OpenAI、DeepSeek、Chromium 和上游作者无官方隶属关系；名称、标志和角色相关权利属于各自权利人。
