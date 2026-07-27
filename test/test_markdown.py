"""The markdown block parser — the layer that replaced structural guesswork."""

from echo.document import BlockKind
from echo.extractors.markdown import blocks_from_markdown, strip_inline_markdown


def kinds(md):
    return [(b.kind, b.text) for b in blocks_from_markdown(md)]


def test_atx_headings_carry_their_level():
    blocks = blocks_from_markdown("# One\n\n## Two\n\n###### Six\n")
    assert [(b.level, b.text) for b in blocks] == [(1, "One"), (2, "Two"), (6, "Six")]
    assert {b.kind for b in blocks} == {BlockKind.HEADING}


def test_setext_headings():
    blocks = blocks_from_markdown("Title Here\n==========\n\nSub\n---\n")
    assert [(b.kind, b.level, b.text) for b in blocks] == [
        (BlockKind.HEADING, 1, "Title Here"),
        (BlockKind.HEADING, 2, "Sub"),
    ]


def test_soft_wrapped_paragraph_becomes_one_block():
    blocks = blocks_from_markdown("The tortoise set\nout at dawn,\nquite late.\n")
    assert len(blocks) == 1
    assert blocks[0].kind == BlockKind.PARAGRAPH
    assert blocks[0].text == "The tortoise set out at dawn, quite late."


def test_tables_figures_and_code_are_not_spoken():
    md = (
        "Prose here.\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
        "![a caption](img.png)\n\n"
        "```python\nprint('hi')\n```\n\n"
        "More prose.\n"
    )
    blocks = blocks_from_markdown(md)
    by_kind = {b.kind for b in blocks}
    assert BlockKind.TABLE in by_kind
    assert BlockKind.FIGURE in by_kind
    assert BlockKind.CODE in by_kind
    spoken = [b.text for b in blocks if b.is_spoken]
    assert spoken == ["Prose here.", "More prose."]


def test_quotes_and_lists_lose_their_markers():
    blocks = blocks_from_markdown("> Speed is a story.\n\n- first item\n- second item\n")
    quote = next(b for b in blocks if b.kind == BlockKind.QUOTE)
    listing = next(b for b in blocks if b.kind == BlockKind.LIST)
    assert quote.text == "Speed is a story."
    assert ">" not in quote.text
    assert listing.text == "first item second item"
    assert not listing.text.startswith("-")


def test_horizontal_rule_is_dropped():
    assert blocks_from_markdown("---\n\nProse.\n")[0].text == "Prose."


def test_unclosed_code_fence_does_not_swallow_everything_as_prose():
    blocks = blocks_from_markdown("Prose.\n\n```\nnever closed\n")
    assert blocks[0].kind == BlockKind.PARAGRAPH
    assert blocks[-1].kind == BlockKind.CODE


class TestStripInlineMarkdown:
    def test_links_keep_their_text(self):
        assert strip_inline_markdown("see [the docs](http://x.y) now") == "see the docs now"

    def test_emphasis_and_code_markers_go(self):
        assert strip_inline_markdown("**bold** and *em* and `code`") == "bold and em and code"

    def test_images_and_footnote_refs_go(self):
        assert strip_inline_markdown("text ![alt](i.png) more[^3]") == "text  more"

    def test_underscores_inside_words_survive(self):
        # Voice ids like af_heart must not be mangled.
        assert strip_inline_markdown("af_heart") == "af_heart"
