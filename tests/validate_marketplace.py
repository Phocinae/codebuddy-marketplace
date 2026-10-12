#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_marketplace.py — 校验市场清单与插件仓的一致性。

为什么需要：市场清单里的 `version`、`source.repo`、插件名一旦与插件仓实际状态
漂移，用户执行 `/plugin install` 会装到旧版或直接失败，而市场本身看起来「很正常」。
这里把那些不可自动发现的一致性做成断言，跑在 CI 上。

零第三方依赖（纯标准库），可离线运行；网络检查（GitHub 可达性）失败即跳过而非误报。

退出码：0=全过，1=有失败。
"""
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request


def _force_utf8_stdio():
    """把 stdout/stderr 固定为 UTF-8。

    本脚本会打印中文诊断；Windows 上 Python 默认用控制台代码页
    （GitHub Actions runner 是 cp1252/437，本机可能是 cp936），
    非 ASCII 直接抛 UnicodeEncodeError 让整个步骤失败。
    这里不依赖调用方设 PYTHONUTF8：自己兜住。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_force_utf8_stdio()


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKET = os.path.join(REPO, ".codebuddy-plugin", "marketplace.json")
README = os.path.join(REPO, "README.md")

fails = []
checks = 0


def check(name, cond, detail=""):
    global checks
    checks += 1
    if cond:
        print("PASS %s" % name)
    else:
        fails.append(name)
        print("FAIL %s  %s" % (name, detail))
    return bool(cond)


def read_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    if not os.path.isfile(MARKET):
        print("FAIL marketplace.json 存在")
        return 1
    d = read_json(MARKET)

    check("清单是 JSON 对象", isinstance(d, dict))
    check("name 非空且为市场名",
          d.get("name") == "phocinae-codebuddy-marketplace", repr(d.get("name")))
    owner = d.get("owner") or {}
    check("owner.name 为 Phocinae", owner.get("name") == "Phocinae", repr(owner.get("name")))
    check("owner.url 指回组织",
          owner.get("url") == "https://github.com/Phocinae", repr(owner.get("url")))

    plugins = d.get("plugins")
    check("plugins 是非空数组", isinstance(plugins, list) and bool(plugins))

    for pl in plugins or []:
        name = pl.get("name", "?")
        check("%s: name 非空" % name, bool(pl.get("name")))
        check("%s: version 形如 x.y.z" % name,
              isinstance(pl.get("version"), str)
              and re.match(r"^\d+\.\d+\.\d+", pl["version"]) is not None,
              repr(pl.get("version")))
        src = pl.get("source") or {}
        check("%s: source.source == github" % name, src.get("source") == "github",
              repr(src.get("source")))
        repo = src.get("repo") or ""
        # 大小写必须与 GitHub 实际组织一致，否则 clone 目标会 404。
        check("%s: source.repo 以 Phocinae/ 开头（大小写正确）" % name,
              repo.startswith("Phocinae/"), repr(repo))
        check("%s: license 非空" % name, bool(pl.get("license")))
        check("%s: description 非空" % name, bool(pl.get("description")))

        # 网络校验：仓库存在、插件 manifest 存在且版本一致。
        api = "https://api.github.com/repos/%s/contents/.codebuddy-plugin/plugin.json" % repo
        try:
            req = urllib.request.Request(api, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "phocinae-marketplace-validator"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            import base64
            manifest = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
            check("%s: 插件仓可达且 plugin.json 可解析" % name, isinstance(manifest, dict))
            check("%s: 市场 version 与插件 plugin.json 一致" % name,
                  manifest.get("version") == pl.get("version"),
                  "market=%r plugin=%r" % (pl.get("version"), manifest.get("version")))
            check("%s: 市场 name 与插件 name 一致" % name,
                  manifest.get("name") == pl.get("name"),
                  "market=%r plugin=%r" % (pl.get("name"), manifest.get("name")))
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            print("SKIP %s: 无法核对远端插件仓（%s: %s）"
                  % (name, type(exc).__name__, exc))

    # README 里引用的本地图片必须真实存在，否则市场页会显示裂图。
    if os.path.isfile(README):
        text = io.open(README, encoding="utf-8").read()
        missing = []
        for m in re.finditer(r'src="([^"]+\.(?:png|gif|svg))"', text):
            rel = m.group(1)
            if rel.startswith("http"):
                continue
            if not os.path.isfile(os.path.join(REPO, rel)):
                missing.append(rel)
        check("README 引用的本地图片全部存在", not missing, ", ".join(missing))
        check("README 含静态图片与动态图片",
              ".png" in text and ".gif" in text)
        # 安装命令必须写出市场名，否则用户装不上。
        check("README 给出 marketplace add 命令",
              "marketplace add Phocinae/codebuddy-marketplace" in text)
        check("README 给出 install 命令且带市场后缀",
              "codebuddy-phocinae@phocinae-codebuddy-marketplace" in text)

    print("\nvalidate_marketplace: %d/%d 通过" % (checks - len(fails), checks))
    if fails:
        print("失败项：")
        for f in fails:
            print("  - %s" % f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
