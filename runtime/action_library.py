"""Local action catalog, including optional converted community clips."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# key, name, category, speech
ACTION_CATALOG = (
    ("head_pat", "摸摸头", "互动", "摸摸也不能让我少干活哦～"),
    ("poke", "元气挥手", "互动", "我在这儿呢！"),
    ("tail", "吐泡泡", "互动", "给你吹个大泡泡～"),
    ("eat_token", "吃 Token", "美食", "开饭啦，今天的口粮是 Token！"),
    ("idle_stretch", "伸懒腰", "日常", "伸个懒腰，再陪你一会儿～"),
    ("idle_yawn", "打哈欠", "日常", "有一点点困，真的只有一点点。"),
    ("extra_rice", "吃白饭", "美食", "白饭收到，我开动啦！"),
    ("extra_cube", "玩魔方", "游戏", "让我研究一下这个小方块。"),
    ("extra_dance", "可爱宅舞", "舞蹈", "给你跳一小段～"),
    ("extra_nap", "打个小盹", "日常", "眯一下，你忙完了记得叫我。"),
    ("extra_hop", "开心跃动", "互动", "今天也要元气满满！"),
    ("extra_whale", "蓝鲸现世", "互动", "让你看看我的鲸鱼朋友！"),
    ("extra_crab", "螃蟹步", "游戏", "横着走也是一种本领。"),
    ("extra_ball", "变成球", "互动", "咕噜咕噜，变成一颗小球！"),
)


def load_pet_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    extra = path.with_name("pet-extra-manifest.json")
    if extra.exists():
        data = json.loads(extra.read_text(encoding="utf-8"))
        for name, clip in data.get("clips", {}).items():
            if name.startswith("extra_") and name not in manifest["clips"]:
                manifest["clips"][name] = clip
        if data.get("actions"):
            manifest["actionCatalog"] = [tuple(action) for action in data["actions"]]
        if data.get("frameCanvas"):
            manifest["maxFrameWidth"], manifest["maxFrameHeight"] = data["frameCanvas"]
            manifest["originalFrameRect"] = data["originalFrameRect"]
    manifest["manualActions"] = [key for key, *_ in manifest.get("actionCatalog", ACTION_CATALOG)
                                 if key in manifest["clips"]]
    return manifest


def actions_for(manifest: dict[str, Any], query: str = "", category: str = "全部") -> list[tuple[str, str, str, str]]:
    query = query.strip().casefold()
    query = {"跳舞": "extra_dance", "吃饭": "extra_rice", "睡觉": "extra_nap"}.get(query, query)
    catalog = manifest.get('actionCatalog', ACTION_CATALOG)
    return [action for action in catalog if action[0] in manifest["clips"]
            and (category == "全部" or action[2] == category)
            and (not query or query in " ".join(action[:3]).casefold())]
