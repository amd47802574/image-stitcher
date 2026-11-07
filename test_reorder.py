"""无头测试：reorder_block 拖拽重排纯函数（不依赖 Tk 显示）。"""
import app


def check(items, sel, target, direction, expect_items, expect_sel):
    got_items, got_sel = app.reorder_block(items, sel, target, direction)
    assert got_items == expect_items, f"{got_items} != {expect_items}"
    assert got_sel == expect_sel, f"{got_sel} != {expect_sel}"


def main():
    L = ["A", "B", "C", "D", "E"]

    # 1) 单张下移：A（索引0）拖到 D 行（索引3）下方
    check(L, [0], 3, +1, ["B", "C", "D", "A", "E"], [3])

    # 2) 单张上移：E（索引4）拖到 B 行（索引1）上方
    check(L, [4], 1, -1, ["A", "E", "B", "C", "D"], [1])

    # 3) 多选整块下移：B,C 拖到 E 行下方
    check(L, [1, 2], 4, +1, ["A", "D", "E", "B", "C"], [3, 4])

    # 4) 多选整块上移：D,E 拖到 A 行上方
    check(L, [3, 4], 0, -1, ["D", "E", "A", "B", "C"], [0, 1])

    # 5) 不连续多选整块移动：A,C 拖到 E 行下方
    check(L, [0, 2], 4, +1, ["B", "D", "E", "A", "C"], [3, 4])

    # 6) 边界：移到最前 / 最后
    check(L, [2], 0, -1, ["C", "A", "B", "D", "E"], [0])
    check(L, [2], 4, +1, ["A", "B", "D", "E", "C"], [4])

    # 7) 通用性：旋转角列表用同一函数同步重排，长度不变、新选中索引有序
    got, sel = app.reorder_block([1, 0, 2, 2, 0], [0, 4], 3, -1)
    assert len(got) == 5 and sel == sorted(sel), (got, sel)
    got2, sel2 = app.reorder_block(got, sel, 0, +1)
    assert len(got2) == 5, got2

    print("ALL REORDER TESTS PASSED")


if __name__ == "__main__":
    main()
