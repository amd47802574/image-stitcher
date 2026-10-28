"""无头测试：生成测试图 -> 验证各种拼接模式 -> 输出到 temp。"""
import os
from PIL import Image, ImageDraw
import stitcher

OUT = os.path.join(os.path.dirname(__file__), "test_output")
os.makedirs(OUT, exist_ok=True)


def make_img(w, h, color, name):
    img = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(img)
    d.text((8, 8), name, fill=(0, 0, 0))
    return img


def main():
    # 三张不同尺寸、不同颜色的图
    a = make_img(100, 60, (255, 0, 0), "A 100x60")
    b = make_img(80, 100, (0, 255, 0), "B 80x100")
    c = make_img(120, 40, (0, 0, 255), "C 120x40")
    imgs = [a, b, c]

    results = {}

    # 1) 横向，不缩放，居中，间隙10
    out = stitcher.stitch(imgs, direction="horizontal", align="center", scale_mode="none", gap=10)
    assert out.size == (100 + 80 + 120 + 20, 100), out.size
    results["h_none_center_gap10"] = out

    # 2) 横向，统一高度到最大值100
    out = stitcher.stitch(imgs, direction="horizontal", align="start", scale_mode="unify", gap=0)
    # 统一高度到 100: A 100x60->167x100, B 80x100->80x100, C 120x40->300x100
    assert out.size == (167 + 80 + 300, 100), out.size
    results["h_unify_start"] = out

    # 3) 纵向，不缩放，左对齐
    out = stitcher.stitch(imgs, direction="vertical", align="start", scale_mode="none", gap=0)
    assert out.size == (120, 60 + 100 + 40), out.size
    results["v_none_start"] = out

    # 4) 纵向，统一宽度到最大值120
    out = stitcher.stitch(imgs, direction="vertical", align="end", scale_mode="unify", gap=5)
    # B 不变 80x100? 不，统一宽度120 -> B: 120 x 150; A: 120 x 72; C: 120 x 40
    assert out.size == (120, 72 + 150 + 40 + 10), out.size
    results["v_unify_end_gap5"] = out

    # 5) 透明背景 + PNG 保存
    out = stitcher.stitch(imgs, direction="horizontal", align="center", scale_mode="none",
                          gap=0, bg=(0, 0, 0, 0))
    assert out.mode == "RGBA"
    results["h_transparent"] = out

    # 保存样例
    for k, im in results.items():
        stitcher.save_result(im, os.path.join(OUT, k + ".png"))
    # JPG 自动转 RGB
    stitcher.save_result(results["h_none_center_gap10"], os.path.join(OUT, "sample.jpg"))

    print("ALL TESTS PASSED")
    print("生成的样例文件：")
    for k in results:
        print("  ", k, stitcher.save_result.__name__ if False else "")


if __name__ == "__main__":
    main()
