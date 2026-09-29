[app]

title = LRC 歌词查看器
package.name = lrcviewer
package.domain = org.lrcviewer

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,otf,ttf,lrc,txt,json

# tests/ 是本机跑单测用的，不用打进包里
source.exclude_dirs = tests,.github,.workbuddy,bin,.buildozer,.git,__pycache__

version = 0.1.0

# android recipe 提供 `from android import activity`，用来监听 onNewIntent /
# onActivityResult；pyjnius 是读 ContentResolver 的基础。
requirements = python3,kivy,pyjnius,android

orientation = portrait
fullscreen = 0

android.logcat_filters = *:S python:D
android.presplash_color = #0E1014

# --------------------------------------------------------------------------
# 文件关联 —— 本项目最核心的两行配置
# --------------------------------------------------------------------------
#
# 注意这里写的是 **相对路径**。buildozer 的实现是：
#     join(self.buildozer.root_dir, 配置值)
# 也就是说它会自己拼上项目根目录，所以不要加 %(source.dir)s 前缀，
# 加了会拼成 root_dir/./android/... 虽然多半也能用，但没必要。
#
# 另一个坑：p4a 是把该文件的"内容"原样内联进 <activity> 的，
# 所以那个文件里不能有 XML 声明、不能有包裹标签，也不能再写 MAIN/LAUNCHER。
# 详见 android/intent_filters.xml 里的注释。
android.manifest.intent_filters = android/intent_filters.xml

# singleTask：应用已经在运行时再从文件管理器打开一个 lrc，
# 系统会复用同一个窗口并回调 onNewIntent，而不是叠出第二个窗口。
android.manifest.launch_mode = singleTask

# 不需要任何权限。
# 文件是文件管理器通过 ACTION_VIEW 把 URI 授权给我们的，属于"单次授权"，
# 用 ContentResolver 读就够，不碰存储、也就不需要 READ_EXTERNAL_STORAGE，
# 上架时能少一堆隐私合规的麻烦。
# （如果坚持要用 android.permissions ，注意它必须是独立一行、不能写行内注释）

android.api = 35
android.minapi = 24

# 只打 arm64。2016 年之后的手机基本全是 arm64，
# 少一个架构能把构建时间砍掉近一半。
android.archs = arm64-v8a

android.allow_backup = True

p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 0
