"""東京23区の境界を、そのまま描けるSVGパスにして書き出す。

**ブラウザにライブラリを足さない。** TopoJSON をここで解いて SVG の d 属性にし、
画面は `<path d="...">` を並べるだけにする（このリポジトリは外部CDN非依存）。

出どころ:
  『歴史的行政区域データセットβ版』（CODH作成） doi:10.20676/00000447
  CC BY 4.0 / 元データは国土数値情報 行政区域データ

    python3 analysis/export_map.py --src <topojsonのパス>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
# 23区の全国地方公共団体コード（N03_007）。多摩・島しょは除く
WARD_CODES = {str(c) for c in range(13101, 13124)}
VIEW = 1000.0  # SVG の横幅。緯度経度からこの座標系へ写す


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    """TopoJSON の量子化＋差分符号化を解いて、経度緯度の並びに戻す。"""
    t = topo.get("transform")
    out = []
    for arc in topo["arcs"]:
        pts = []
        x = y = 0
        for i, (dx, dy) in enumerate(arc):
            if t:
                x = dx if i == 0 else x + dx
                y = dy if i == 0 else y + dy
                pts.append((x * t["scale"][0] + t["translate"][0],
                            y * t["scale"][1] + t["translate"][1]))
            else:
                pts.append((dx, dy))
        out.append(pts)
    return out


def ring(arc_ids: list[int], arcs: list) -> list[tuple[float, float]]:
    """輪郭1本。負の番号は「その弧を逆向きに使う」の意味。"""
    pts: list[tuple[float, float]] = []
    for a in arc_ids:
        seq = arcs[~a][::-1] if a < 0 else arcs[a]
        pts.extend(seq[1:] if pts else seq)
    return pts


def project(lon: float, lat: float, box: tuple, scale: float, lat0: float) -> tuple[float, float]:
    """正距円筒に、緯度による横縮みの補正だけ入れる。23区の範囲なら十分。"""
    import math
    minx, miny, _, maxy = box
    x = (lon - minx) * math.cos(math.radians(lat0)) * scale
    y = (maxy - lat) * scale
    return round(x, 1), round(y, 1)


def main(argv: list[str] | None = None) -> None:
    import math
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=str(ROOT / "web/data/tokyo23.json"))
    args = ap.parse_args(argv)

    topo = json.loads(Path(args.src).read_text(encoding="utf-8"))
    arcs = decode_arcs(topo)
    geoms = topo["objects"]["city"]["geometries"]

    wards = []
    for g in geoms:
        code = str(g["properties"].get("N03_007") or "")
        if code not in WARD_CODES:
            continue
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        wards.append({
            "code": code,
            "name": g["properties"].get("N03_004"),
            "rings": [[ring(r, arcs) for r in poly] for poly in polys],
        })

    pts = [p for w in wards for poly in w["rings"] for r in poly for p in r]
    minx = min(p[0] for p in pts)
    maxx = max(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    maxy = max(p[1] for p in pts)
    lat0 = (miny + maxy) / 2
    scale = VIEW / ((maxx - minx) * math.cos(math.radians(lat0)))

    out = []
    for w in wards:
        d = []
        for poly in w["rings"]:
            for r in poly:
                xy = [project(x, y, (minx, miny, maxx, maxy), scale, lat0) for x, y in r]
                d.append("M" + "L".join(f"{x},{y}" for x, y in xy) + "Z")
        out.append({"code": w["code"], "name": w["name"], "d": "".join(d)})

    out.sort(key=lambda w: w["code"])
    height = round((maxy - miny) * scale, 1)
    doc = {
        "_about": "東京23区の境界を、そのまま描けるSVGパスにしたもの。ブラウザに地図ライブラリを足さないため。",
        "source": "『歴史的行政区域データセットβ版』（CODH作成） doi:10.20676/00000447",
        "source_url": "https://geoshape.ex.nii.ac.jp/city/",
        "license": "CC BY 4.0",
        "original": "国土数値情報 行政区域データ（国土交通省）",
        "viewBox": f"0 0 {VIEW:.0f} {height:.0f}",
        "wards": out,
    }
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    size = Path(args.out).stat().st_size / 1024
    print(f"{args.out}: {len(out)}区 / viewBox {doc['viewBox']} / {size:.0f} KB")


if __name__ == "__main__":
    main()
