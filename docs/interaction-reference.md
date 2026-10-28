# 交互适配来源

参考项目：[duhaoze2007/Baifanyu-For-Win](https://github.com/duhaoze2007/Baifanyu-For-Win)，固定提交 `f92cbe942e154ee2971e8fa7e93d1061a302c2c1`。

参考其 README、`src/app.cpp`、`src/pet.cpp`、`src/artwork.cpp` 和 `src/app.manifest` 中的交互设计，在 Python / PySide6 中适配：

- 拖拽时按鼠标方向倾斜；保留大肥鱼原有拖拽动画、速度采样与重力开关。
- 慢放到左右边缘时以现有待机动画的头部裁剪、旋转 90° 显示扒边状态；快甩继续反弹，避免两种行为冲突。
- 只在人物可见像素上悬停时暂停溜达；延迟约半秒显示日期、实时时钟和本项目编写的关心话。任务状态和气泡隐藏偏好优先。
- 空闲时分段、短距离溜达；用户操作、手动动作、重要任务及减少动态设置优先，不抢占动画。
- Qt 统一使用逻辑坐标，Windows 在创建窗口前请求 PerMonitorV2。Qt 接管系统 DPI 消息，监听显示器、DPI 和工作区变化以清空绘制缓存、重新约束位置和运动边界。没有混用 Win32 物理鼠标坐标与 Qt 逻辑坐标。

代码许可为 MIT，保留 © 2026 Du Haoze（Windows port）和 © 2026 LIN428924379（original Android app）。完整上游许可（含其媒体例外）随附于 [Baifanyu-For-Win-LICENSE.txt](../assets/community-notices/Baifanyu-For-Win-LICENSE.txt)。未导入其美术、图标或音效；大肥鱼已有媒体仍遵循各自来源条款。

显示实现补充：人物窗口按当前帧 alpha 阈值裁切，忽略近乎透明的残留像素，维持原动画锚点；状态卡使用独立且鼠标穿透的工具窗口，避免气泡参与拖拽与边缘碰撞。
