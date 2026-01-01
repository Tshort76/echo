import echo.clean as ec

footnote_fixes = {
    " 4.56 ": " 4.56 ",
    "4.5\n": "4.5\n",
    "gfg.5\n": "gfg.\n",
    "gfg.5 ": "gfg. ",
    "gfg.11 ": "gfg. ",
    "dfs?4\n": "dfs?\n",
    "dfs,5 ": "dfs, ",
    "dfs.5": "dfs.5",
}


def test_footnote_fixes():
    for raw, expected in footnote_fixes.items():
        fixed = ec.FOOTNOTE_REF.sub(lambda x: x.group(1) + x.group(2), raw)
        assert expected == fixed, f"raw string: '{raw}'"


def test_gemini_deep_research_formatting():
    with open("../resources/test/gemini_deep_research_output.txt", "r") as fp:
        gemini_dr_output = fp.read()

    txt = ec.clean_gemini_contents(gemini_dr_output)

    assert "Official Social Group" not in txt, "Table strip failed"
    assert "2.2 Population Metrics and Demographic Rigor" not in txt, "headings strip failed"
    assert "II." not in txt, "Roman numeral strip failed"
    assert "Bowman, S." not in txt, "SOURCES strip failed"
    assert "Conclusion:" in txt, "post SOURCES information removed"


md_contents = """
moral warfare, and a wider appreciation of nexus causality and misattribution arbitrage would help us all shed at least some of the destructive delusions that cost humanity so much.

# I SEEM TO BE METADATA
`01.01.2010`
Obliterating whole lineages — diatoms and dinosaurs

- list item 1
- list item 2
- list item 3

---
"""


# pip install pytest; pytest
