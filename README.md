# Software Center — Windows 本地软件下载器

Python + PySide6，Windows 10/11。主界面只做浏览 / 搜索 / 详情 / 下载 /
设置；管理台通过主窗口焦点下的 `Ctrl+Shift+F12` 唤出登录框（窗口级快捷键，
非全局热键），登录后进入独立管理台。

> 本仓库是 V1 实现，对应《Software Center V2 设计重构说明书》
> （2.0-Draft）。隐藏快捷键只藏入口、不算安全：安全压在登录认证上。
> 未在真实 Windows 桌面验收，见文末“实测状态”。

## 功能

- 用户面：目录浏览、分类 + 关键词筛选、卡片、详情、单任务下载、
  设置（下载目录，仅允许已存在目录）。
- 下载契约（六项全过才算成功）：任务正常结束 + 最终产物是普通文件 +
  写入字节 == 来源大小 + 落盘大小 == 目录 `size_bytes` +
  落盘 SHA-256 == 目录 `sha256` + 目标全程在下载目录内。
  临时文件与最终文件同目录，先验临时文件、再 `os.replace`；
  同名已存在拒绝下载（不覆盖、不改名）；失败清理临时产物、不显示成功。
- 路径安全：保留设备名按主名判定（`NUL` / `nul` / `NUL.txt` / `Nul .bin` /
  带目录前缀 / UNC / `\\?\` 前缀 / 冒号 ADS 全拒）；路径穿越、盘符、UNC、
  POSIX 绝对路径输入要挡；`file_name` 只来自目录字段且必须是纯文件名。
- 管理台：首次按快捷键走口令设置流程；无默认口令、无硬编码口令；
  口令 Argon2id 哈希存独立 `data/admin.json`；错 5 次锁 15 分钟且重启不清零；
  会话 15 分钟无操作自动退出；发布 / 回滚 / 改口令 / 删除要二次确认；
  全程审计 `data/admin_audit.log`（JSONL）。
- 管理功能：增删改查、上下架（`status`，下架不删除）、排序（`sort_order`，
  拖行排序）、分类（拖到分类换组）、图标（拖 PNG 换图标）、拖入文件自动算
  大小 + SHA-256 生成条目、拖到行上更新版本、拖入 `catalog.json` 导入、
  草稿 - 校验 - 发布与一键回滚、删除进 `trash` 保留 30 天；
  大小与 SHA-256 在表单中只读、禁止手填。
- 不做：自动安装、系统权限操作、账号体系、云端同步、远程目录下发、
  应用自更新、多管理员。

## 运行

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Linux 开发 / 测试：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -v
```

## 口令哈希 fallback

首选 `argon2-cffi`（Argon2id）。若环境缺失该库，自动降级为标准库
`hashlib.scrypt`，降级方案记录在 `admin.json` 的 `scheme` 字段中。
不降级到 MD5 / SHA 系列快速哈希或明文。

## 目录结构

```
run.py
src/sc/{app,catalog,config,downloader,models,verifier,pathsafe,auth,audit,admin_service}.py
src/sc/ui/{main_window,card_widget,detail_dialog,settings_dialog,admin_login_dialog,admin_window}.py
data/{catalog.json,sample_files/,icons/,backups/,trash/}
tests/
tools/build_test_catalog.py
```

`data/admin.json`（口令哈希）、`data/admin_audit.log`（审计）、
`data/catalog.draft.json`（草稿）、`data/backups/`、`data/trash/`、
`.sc_config.json` 均为本地运行产物，已加入 `.gitignore`，不提交。

## 实测状态（诚实记录）

- Linux + `QT_QPA_PLATFORM=offscreen`：完整 pytest 实测通过（见测试报告）。
- Windows 真机：**未测**。待在真实 Windows 桌面验收：登录、拖入、发布、
  下载整轮；`Ctrl+Shift+F12` 焦点行为；关闭 / 模态对话框行为；
  `NUL` 等设备名在 NTFS 下的真实表现；`explorer` 打开文件夹。
