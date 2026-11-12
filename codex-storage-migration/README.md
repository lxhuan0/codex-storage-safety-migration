# Codex Storage Migration

当前分享版本：`0.2.0-preview`。它比初版增加了真实执行与恢复工具；仍需在使用者自己的环境中做最小测试。

把 Codex 的数据从系统盘迁到其他本地磁盘，同时让每一步都能检查、停止和恢复。

这是一个给 Codex 使用的社区技能：它指导代理调查实际安装、制定方案、做最小测试、分项迁移和处理失败。第二版增加了受约束的 Windows 执行工具，能够在隔离目录中实际验证迁移和恢复。**它不承诺零风险，也不能替代迁移后的实际使用检查。** 路径、用户和盘符不绑定作者电脑。

## 能帮助什么

- 先列出大小和实际位置，再按释放空间的收益选择迁移对象。
- 区分历史/数据库、浏览器资料、运行环境、插件缓存、程序包和备份。
- 优先检查当前版本支持的路径设置，再考虑目录连接等方式。
- 用最小可恢复测试检验权限和运行行为，避免几十个任务连续长跑。
- 识别缓存变化、运行环境更新、安全软件干预和半途切换；恢复时保留迁移后的最新数据。
- 对符合条件的 Windows NTFS 普通目录执行：先复制核验，再切换路径，保留原件，支持中断续跑和最新数据迁回。

技能把“复制核验通过”“路径切换完成”“重启使用通过”和“原盘空间释放”分别记录。因此不会把一条 PASS 当成所有工作都完成。

## 安装

仓库中的 `skills/codex-storage-migration/` 是完整技能目录。将它复制到当前 Codex 支持的技能发现目录，例如 `~/.agents/skills/codex-storage-migration/`；具体位置以所用版本的技能文档为准。不要把整个仓库误放成技能目录。刷新技能列表或重新开启会话后，检查能否发现 `$codex-storage-migration`。

安装只添加技能，不会启动迁移，也不需要复制作者的个人配置。

## 使用示例

先对 Codex 说：

> 使用 $codex-storage-migration 调查我的 Codex 数据占用，目标是迁到另一块本地磁盘。先给出按大小排序的计划，不要改动文件。备份也放目标盘。

确定范围后可以说：

> 只对选中的最大一项做最小可恢复测试。测试通过后准备一个独立迁移入口，显示阶段进度，记录日志。其他项目暂时不动。

如果已经失败：

> 先检查原路径、保留原件、目标副本和迁移记录，判断停在哪一步。不要盲目重跑，不要用旧备份覆盖新的数据。

## 可独立使用的只读清单工具

完整工具集需要 Python 3.12+，无第三方依赖。先发现候选位置，再明确指定扫描目录，例如：

```console
python -B skills/codex-storage-migration/scripts/discover.py
python -B skills/codex-storage-migration/scripts/inventory.py --root "C:\Users\Example\.codex" --largest 10
```

结果只输出到终端；不读取文件正文，不迁移、不删除，不跟随符号链接或 Windows 重解析点。目录由使用者选择，不自动扫描全部磁盘。退出码 2 表示扫描有错误或指定根路径经由连接，不能把不完整结果理解成“占用为零”。子目录连接会单独列出并跳过，大小不包含其目标。

大小是逻辑文件大小，不是实际可释放空间；硬链接、稀疏文件、压缩、备用数据流和嵌套根目录会影响解释。工具不是权限/一致性验证器，也不能抵御扫描期间恶意替换路径。清单可能泄露私人路径，不要原样上传到 GitHub。

## 分项迁移与恢复

执行前让 Codex 阅读 [执行工具的约束和操作说明](skills/codex-storage-migration/references/executor.md)。这里用虚构路径说明顺序；不要直接照搬路径。

1. `prepare` 为一个明确目录准备独立工作包，不改源目录。工作包包含固定路径记录、工具副本和单项入口。
2. 关闭相关程序后，`apply` 冷态取快照，把原数据复制成目标盘的基线和活动副本，核验通过后才改名原目录并建立连接。
3. 重新打开应用，检查相关功能后，用 `mark-verified` 记录实际使用结果。此时完整原件仍保留在源盘。
4. 如果确认要释放源盘空间，再关闭程序，单独授权 `retire-original` 删除已核验的原件，保留目标盘的基线与活动数据。

如果切换中断，`recover-original` 可恢复尚未连接的完整原件。如果切换后有新数据，`return-latest` 会迁回活动副本的最新内容，而不是覆盖成旧备份。关键改名和日志记录之间的中断也有对应测试。入口每次只处理一个目录；失败不会自动反向覆盖，也不会重跑其他已完成项目。

**删除原件是单独的明确动作。** 不自动生成删除原件的 CMD，不因为文件复制 PASS 就删除。工具检查并拒绝变化的备份、不明的新源目录、不支持的链接或文件属性。保护软件删除脚本时，需要先查明拦截和现场状态，不自动关杀毒或换名字绕过。

## 支持范围

| 能力 | 当前范围 |
| --- | --- |
| 路径候选发现、只读清单 | Windows、macOS、Linux 的候选布局；实际安装仍需确认 |
| 自带执行工具 | Windows，本地固定 NTFS，明确选择的普通目录 |
| 复制检查 | 内容哈希、命名数据流、创建/写入时间、属性、所有者/组和有序 DACL 权限 |
| 权限语义 | 副本采用受保护 DACL，保留有效权限；不保留“继承或显式”的来源标记 |
| 中断恢复 | 复制、原件改名、目录连接、原件退休、最新数据迁回等阶段 |
| 不直接支持 | WindowsApps/MSIX 手动搬动、硬链接/嵌套连接、稀疏/压缩/加密/云占位文件、依赖拓扑的 worktree、SACL 审计或文件 ID 必须完全一致的场景 |
| 仍需现场验证 | 外来所有权/沙箱访问、真实登录和插件、原生依赖、版本更新和安全软件行为 |

进程检查与文件锁是辅助机制，无法证明所有写入者均已退出。工具要求调用者明确确认维护窗口，也会拒绝已知正在运行的相关程序。不会结束进程、创建账号、修改系统安全软件或批量放宽源目录权限。

## 测试和边界

```console
python -B -m unittest discover -s tests -v
```

测试使用新建的隔离目录，覆盖只读发现、Unicode/长路径、文件及目录命名流、只读属性、有效权限、复制后执行、关闭的 SQLite、关键阶段中断、拒绝覆盖新数据、损坏备份及空间不足。测试里的全局应用进程检查被隔离替代，因为运行中的 Codex 与新建模拟文件无关；另有测试检查进程阻止逻辑、真实进程枚举和文件占用。生产命令没有跳过进程检查的开关。

要在另一块本地 NTFS 卷做往返测试，显式设置 `CODEX_MIGRATION_TEST_TARGET_PARENT` 为该卷已有的测试父目录，再运行测试。测试只在其中新建自己命名的临时目录。没有指定第二卷时，对应测试会跳过，不会假装已经验证跨卷。

已提供 GitHub Actions，提交后可在 Windows/Ubuntu 与 Python 3.12/3.13 组合上运行测试。**CI 文件已配置不等于云端测试已经通过**；Ubuntu 只测发现、清单和平台拒绝逻辑，跳过 Windows 执行用例。具体本地验证结果见 [VALIDATION.json](VALIDATION.json)。

Windows 实践中的成功、失败与证据边界见 [经验记录](skills/codex-storage-migration/references/evidence-sources.md)，方法选择见 [平台说明](skills/codex-storage-migration/references/platforms.md)。当前配置项依据 [Codex 官方环境变量文档](https://learn.chatgpt.com/docs/config-file/environment-variables)核对；目录连接和复制语义依据 [Microsoft mklink](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mklink)及 [robocopy](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy)。产品升级后需要重新确认。

## 分享与贡献

上传本仓库源码即可，不要连同真实会话、认证资料、浏览器数据库、扫描清单、原始迁移日志或机器安全标识一起上传。报告问题时请提供脱敏后的系统/安装类型、版本、文件系统、阶段及错误信息。

本项目为社区整理，与 OpenAI 无隶属或背书关系。代码与文档采用 MIT 许可，见 [LICENSE](LICENSE)。

## English summary

A community Codex skill for evidence-driven, recoverable local storage relocation. Includes cross-platform discovery/inventory and a constrained Windows fixed-local-NTFS executor with independent jobs, copy-before-switch, explicit source retirement, interruption recovery, and latest-data return. Python 3.12+, standard library only. Tests use isolated fixtures, not production state. Install the inner `skills/codex-storage-migration` folder into your version's supported skill directory and invoke `$codex-storage-migration`. Read the executor contract before any real filesystem change.
