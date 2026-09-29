# LRC 歌词查看器（Android）

一个专门用来接管 `.lrc` 文件的轻量查看器。用 Python + Kivy 写，**本地不需要安装
Android SDK / NDK**，APK 在 GitHub Actions 上编译。

---

## 一、先说清楚问题出在哪

`<文件管理器点开 .lrc 时找不到任何能打开的 App>` —— 这不是文件管理器坏了。

**Android 的文件关联只认 MIME 类型，不认扩展名。**

系统内置的 MimeTypeMap 里没有 `.lrc` 这条记录，于是文件管理器在发
`ACTION_VIEW` 时算出的类型是 `application/octet-stream`（未知二进制），
个别管理器干脆用 `*/*`。

而市面上的文本阅读器、记事本，通常只声明自己支持 `text/plain`。
`text/plain` 和 `application/octet-stream` 匹配不上，所以你在"打开方式"里
永远看不到它们 —— 这也解释了为什么 `.txt` 能打开、`.lrc` 就是不行。

被反复推荐的老办法是写 `<data android:pathPattern=".*\.lrc" />`，
但这条路在现代 Android 上基本已经死了：

- `pathPattern` 只有在同时指定 `scheme` 和 `host` 时才生效；
- Android 7 之后禁止 App 之间传递 `file://` URI，文件管理器一律改用 `content://`，
  而 `content://` 的路径长这样：`/document/primary%3AMusic%2Fxxx.lrc` ——
  后缀被 URL 编码了，路径里也没有真实的文件名；
- 唯一"保证能匹配上"的写法是 `mimeType="*/*"`，代价是这个 App 会出现在
  打开任何文件的候选列表里。

所以本项目的做法是：**分层声明，从精准到兜底**。

| 过滤器 | 声明的类型 | 作用 |
|---|---|---|
| ① | `file://` + `pathPattern` 匹配 `.lrc` | 老式文件管理器、`file://` 场景，最精准 |
| ② | `content://` / `file://` + `application/octet-stream` | **关键兜底** —— 现代文件管理器对未知扩展名给出的就是这个类型 |
| ③ | `content://` / `file://` + `text/plain` | 有些管理器会正确识别成文本 |
| ④ | 自定义 MIME `text/x-lrc` 等 | 精准接住，不和别的 App 抢 |

先试这四条。如果个别 ROM 依然不认，`android/intent_filters.xml` 末尾留了一段
注释掉的 `*/*` 过滤器，取消注释后能 100% 生效（代价是会显得很吵）。

---

## 二、跑起来

### 方式 A：云端出 APK（推荐，本地零 SDK）

1. 把整个目录推到自己的 GitHub 仓库（公开、私有都行，公开仓库的 Actions 免费额度不限）；
2. 打开仓库的 **Actions** 标签页 → 左侧选 **Build Android APK** → 点 **Run workflow**；
3. 等构建完成（第一次要下 Android SDK/NDK，约 40 分钟；之后有缓存，通常 5～10 分钟）；
4. 在该次运行的底部 **Artifacts** 里下载 `lrcviewer-debug-apk`，解压得到 `.apk`；
5. 传到手机安装（需要允许"安装未知来源应用"）。

> 调试版 APK 用的是 Android 默认调试签名，不影响安装，但**不能上架 Google Play**。
> 要上架请把 workflow 里的 `buildozer android debug` 换成
> `buildozer android release`，并在 `buildozer.spec` 里配好 keystore。

#### 构建失败了怎么排查

**先看 run 页面上的 Summary 区域** —— workflow 在失败时会把 `buildozer` 日志的
最后 200 行自动写进那里（`Surface build log on failure` 这一步），不用在折叠的
日志里一步步翻。

还有个 `Show toolchain versions` 步骤，会打印 Python / java / javac / git /
buildozer 的版本和关键 python 包（cython、pexpect…）。**buildozer 最典型的失败
形态就是"秒退"，而工具链版本对不上是头号原因**，先看这个输出往往就能定位。

两个刻意为之的设计，别改回去：

- `buildozer android update` **不写成 `|| true`**。它允许失败（历史上对非致命
  情况也会返回非 0），但输出会 `tee` 到日志文件里。写成 `|| true` 会把错误整段
  吞掉，结果只看到下一步莫名其妙地 9 秒就挂，根因完全查不到。
- 缓存拆成 `cache/restore` + `cache/save` 两步。单步 `actions/cache` 的 post
  步骤是 `post-if: success()`，**整个 job 成功才存缓存** —— 那样构建一失败，
  刚下完的 1.5 GB SDK/NDK 就白下了。拆开之后可以在"下完 SDK、还没开始构建"
  时就先存下来。（`cache@v5` 的 `save-always` 已被官方标记"不按预期工作"，别用。）

#### 报 `Aidl not found, please install it` / `license is not accepted`

首次构建实际就是这么挂的（run #1，第 9 步只跑了 9 秒就退出）。完整日志长这样：

```
Accept? (y/N): Skipping following packages as the license is not accepted:
Android SDK Build-Tools 37
The following packages can not be installed since their licenses or those of
the packages they depend on were not accepted:
build-tools;37.0.0
[=======================================] 100% Computing updates...
# Check that aidl can be executed
# build-tools folder not found .../android-sdk/build-tools
# Search for Aidl
# Aidl not found, please install it.
```

**这不是 aidl 缺失的问题，是上一行的"许可证没接受"导致的连锁反应**：许可证没接受
→ `build-tools` 整个包被跳过安装 → 没有 `build-tools/` 目录 → 自然找不到里面的
`aidl` → buildozer 在 `buildops.checkbin()` 里 `exit(1)`。

根因在 `buildozer.spec` 里：`android.accept_sdk_license` 的**默认值是 `False`**
（buildozer 自己的 `default.spec` 原话是 "If set to False, **the default**, you will
be shown the license when first running buildozer"）。默认值下 buildozer 只是把
sdkmanager 的输出丢到终端然后干等，CI 里没人能按 `y`，于是直接跳过。

本仓库已经设成 `android.accept_sdk_license = True`，**不要删掉它**。置 True 后
buildozer 会改用 pexpect（分配 pty）监听 `(y/N)` 提示并自动应答 `y` —— 见
`targets/android.py` 的 `_android_update_sdk()`。

workflow 里还额外加了一步 `Verify Android SDK toolchain` 兜底：无条件跑一次
`yes | sdkmanager --licenses`（幂等），并**复刻 buildozer 的 aidl 判定逻辑**
（取版本号最大的那个 build-tools 目录，无参数运行 aidl，返回码必须为 1）提前
报错。之所以要复刻，是因为 buildozer 的 `_check_aidl()` 用的
`_read_version_subdir()` 只看**目录名最大的那个版本**，不看里面有没有 aidl。

好处是 `licenses/` 目录就在 `~/.buildozer` 里，会被缓存带走，所以这一次接受了
之后，后续所有构建都不会再遇到许可证问题。

### 方式 B：桌面预览（调界面 / 改歌词解析时用）

**要求 Python 3.8 ～ 3.13，不能用 3.14。** 先确认一下版本：

```bash
python -V        # 必须是 3.8 ~ 3.13
```

然后建虚拟环境安装（不要装到全局环境里）：

```bash
py -3.13 -m venv .venv          # Windows：用 py 启动器指定一个 ≤3.13 的解释器
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py     # 或者 python main.py

# macOS / Linux
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

桌面版逻辑和 Android 版完全一样，只有"读文件"这一步从 `ContentResolver`
换成了 `open()`。会用 `samples/demo.lrc` 作为默认内容。

#### 装不上 Kivy？先看这个报错

```
ERROR: Could not find a version that satisfies the requirement
       kivy_deps.sdl2_dev~=0.8.0 (from versions: none)
ERROR: No matching distribution found for kivy_deps.sdl2_dev~=0.8.0
```

**这只说明一件事：你用的 Python 是 3.14。**

`kivy_deps.sdl2_dev` 是 Kivy **源码编译**时才需要的依赖，正常装预编译包根本
不会碰它。它之所以被触发，因果链是这样的：

1. Kivy 2.3.1 只发布了 `cp38 / cp39 / cp310 / cp311 / cp312 / cp313` 的
   Windows wheel —— 没有 `cp314`；
2. 于是在 Python 3.14 上 pip 找不到 wheel，退而求其次去下**源码包**准备自己编译；
3. 源码包的 `[build-system]` 里写着编译依赖，其中包括
   `kivy_deps.sdl2_dev~=0.8.0; sys_platform == "win32"`；
4. 而这个包同样只到 `cp313`，没有任何 cp314 版本 → `from versions: none`。

有意思的是同一组的 `gstreamer_dev` / `glew_dev` / `angle_dev` 都有 cp314 wheel，
**只有 sdl2_dev 没有**，所以你看到的报错里只会出现 `sdl2_dev` 这一个名字 ——
这和 "Python 版本过高" 的结论是完全对得上的。换成 Python ≤ 3.13 后，pip 直接
命中预编译 wheel，几秒钟装完，也不会再触发源码编译。

> `run.py` 已经内置了这个检查：版本不对时会直接打印上面这段原因和处理方法，
> 而不是让你对着一堆 pip 报错猜。

顺便说一句：这**只影响桌面预览**。APK 是在 GitHub Actions 的 Linux 上用
Python 3.11 构建的，跟本机 Python 版本没有任何关系（而且 `buildozer.android`
在 Windows 原生就跑不了，本来也只能在云端构建）。

#### 本仓库里已经有一个装好的 `.venv`

我在这台机器上用 Python 3.13 建了 `.venv` 并把 Kivy 2.3.1 装好了，
直接这样就能开界面（`.venv/` 已在 `.gitignore` 里，不会入库）：

```bash
.venv\Scripts\python run.py
```

如果哪天 pip 装不上（镜像源抽风、公司网络走代理等），还有个纯离线的兜底办法：
从 PyPI 的 JSON 接口拿 wheel 直链自己下下来，再让 pip 只从本地目录装 ——

```bash
pip install --no-index --find-links=<wheel 所在目录> kivy
```

`https://pypi.org/pypi/<包名>/<版本>/json` 里的 `urls[].url` 就是每个 wheel 的直链，
顺带还能用 `urls[].size` 校验文件有没有下全（下了一半的 wheel 会让 pip 报
"Wheel is invalid"，很难看出是网络问题）。

### 跑单元测试

解析逻辑（`lrc_parser.py`）是零依赖的纯 Python，可以脱离 Kivy 直接验证：

```bash
python -m unittest discover -s tests -v
```

覆盖时间标签精度、一行多标签、元数据、逐字标签剥离、CRLF、
GB18030/UTF-8-BOM 编码探测、纯文本歌词等 30 个用例。

---

## 三、装到手机后怎么确认关联生效

装完后有两种情况：

- **直接生效**：在文件管理器里点 `.lrc` 文件，图标会直接变成本应用（或弹出一层选择框）。
- **需要手动指一次**：点 `.lrc` → 选"打开方式 / 用其他应用打开"→ 在列表里找
  **「LRC 歌词查看器」** → 选"始终"。

如果列表里**没有**本应用，按这个顺序排查：

1. 确认装的是**最新构建**的那个 APK（一次失败构建很容易让人看错文件）；
2. 在系统设置 → 应用 → 找到本应用 → 确认它没有被"默认打开"设置屏蔽；
3. 换个文件管理器再试。不同 ROM 的文件管理器发给系统的 MIME 差别很大，
   用 **MT 管理器**、**Solid Explorer**、**Cx 文件浏览器** 交叉验证一下
   —— 如果某个管理器能看到本应用，就说明配置是对的，只是那个 ROM 的管理器比较特殊；
4. 打开 `android/intent_filters.xml`，把末尾注释掉的 `*/*` 过滤器取消注释，重新构建。

---

## 四、文件结构

```
LRC_Viewer/
├── main.py                      Kivy 界面 + Intent 处理入口
├── lrc_parser.py                纯 Python 的 LRC 解析器（零依赖、可单测）
├── android_file.py              Android 侧文件读取桥接（pyjnius / ContentResolver）
├── run.py                       本地一键预览（等同于 python main.py）
├── buildozer.spec               打包配置（含文件关联那两行关键配置）
├── android/
│   └── intent_filters.xml       ★ 文件关联过滤器，这个项目的核心
├── samples/demo.lrc             示例歌词，也是桌面端的默认内容
├── tests/test_lrc_parser.py     30 个单元测试
├── fonts/                       CI 在这里放中文字体（不入库）
└── .github/workflows/build_apk.yml   云端构建 APK
```

### 两个容易踩的坑（已在本项目里处理好）

**坑 1：中文全是方框。**
Kivy 自带的 Roboto 字体没有任何汉字字形，中文歌词会全部渲染成 ▯。
本项目在 `main.py` 里会在启动时按顺序找字体：APK 内置的思源黑体 →
`/system/fonts/NotoSansCJK-Regular.ttc` → 桌面系统的微软雅黑。
CI 构建时会自动下载思源黑体打进包里，所以正常情况一定有字。

**坑 2：装完之后桌面出现了两个图标。**
`python-for-android` 的 AndroidManifest 模板里，MAIN/LAUNCHER 过滤器是
**无条件写死**的，自定义的 `intent_filters` 只是**追加**在它后面。
所以 `android/intent_filters.xml` 里**绝不能**再写一遍 LAUNCHER，
本文件里也刻意不写 `<?xml ?>` 声明（内联到文档中间会导致 manifest 解析失败）。

---

## 五、已知局限

- **APK 约 30 MB。** 这是 Python 方案的天花板：Kivy 方案必须把 CPython 解释器和
  SDL2 一起打进包里。如果你更在意体积，可以考虑把界面换成原生实现（几百 KB），
  代价是不能用 Python 写。
- **只能查看，不能播放音频。** 需求是"歌词文本查看器"，所以刻意没做播放器。
- **不做 .lrc 编辑。** 目前是只读的。
- **不上架 Google Play。** 默认出的是 debug 包。上架还需要配 keystore、
  改 release 构建、准备应用图标和隐私政策（本应用不申请任何权限，这块反而简单）。
- **不需要任何存储权限。** 文件是文件管理器通过 URI 单次授权给应用的，
  走 ContentResolver 读取即可。这也是本方案比"申请 READ_EXTERNAL_STORAGE
  然后自己遍历目录"更好的地方。
