# $ python -m unittest test.test_antigravity
# $ python -m unittest test.test_antigravity.GravityTestCase
# $ python -m unittest test.test_antigravity.GravityTestCase.test_method
# $ python -m unittest

import re

FOOTNOTE_REF = re.compile(r"([^\d][;,.?!)])\d{1,2}(\s)")

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
        fixed = FOOTNOTE_REF.sub(lambda x: x.group(1) + x.group(2), raw)
        assert expected == fixed, f"raw string: '{raw}'"
