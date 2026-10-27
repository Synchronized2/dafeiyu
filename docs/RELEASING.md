# 发布 Windows 便携版

使用 GitHub Releases 分发运行库与完整动画，不向 Git 提交 `.windows-runtime/`、`assets/pet/`、`.local/` 或 `dist/`。

1. 更新 `VERSION` 与 `CHANGELOG.md`，核对素材和运行库；来源记录在素材清单和 `RUNTIME-SOURCES.json`。
2. 下载素材后执行 `python -m unittest discover -s codex_tests -v`，检查 Windows 原生窗口与浅/深色选中态。
3. 使用完整便携环境的 Python 构建：

   ```powershell
   python scripts/build-release.py --runtime-root .windows-runtime --asset-root assets/pet
   ```

   输出到 `dist/`，生成素材 ZIP、完整 Windows ZIP、SHA256SUMS.txt。检查帧是否齐全，排除用户数据，写入 BUNDLE.json。

4. 构建脚本更新 `release-assets.json` 的版本、素材 URL、大小和 SHA-256。下载脚本只使用锁定清单。
5. 提交源码和文档，创建注释标签 `v<版本号>`，推送 `main` 与标签。
6. 创建草稿 Release，上传两个 ZIP 和 SHA256SUMS.txt。验证上传大小/摘要、压缩包完整性和解压后的启动/退出，再发布。

已发布的版本不要覆盖附件或移动标签，后续修改使用新版本号。

发布内容必须排除用户设置、日志、真实任务记录及任何凭据；保留第三方素材与运行库许可证。
