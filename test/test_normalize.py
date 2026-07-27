"""Rules normalization, page-artifact detection, and Script assembly."""

import pytest

import echo.normalize as norm
from echo.document import Block, BlockKind, Document

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


def test_footnote_refs_are_stripped_without_eating_decimals():
    for raw, expected in footnote_fixes.items():
        assert norm.strip_footnote_refs(raw) == expected, f"raw string: {raw!r}"


class TestNormalizeForSpeech:
    def test_dash_runs_become_spoken_pauses(self):
        assert norm.normalize_for_speech("late — tortoises keep") == "late, tortoises keep"
        assert norm.normalize_for_speech("late--tortoises") == "late, tortoises"

    def test_ellipses_collapse(self):
        assert norm.normalize_for_speech("wait.... then") == "wait… then"

    def test_smart_quotes_are_flattened(self):
        assert norm.normalize_for_speech("“hello” and ’tis") == '"hello" and \'tis'

    def test_soft_hyphens_and_nbsp_go(self):
        assert norm.normalize_for_speech("co­operate now") == "cooperate now"

    def test_runs_of_spaces_collapse(self):
        assert norm.normalize_for_speech("a    b") == "a b"


class TestPageArtifacts:
    @staticmethod
    def _paged_doc(header: str, pages: int = 8) -> Document:
        blocks = []
        for page in range(1, pages + 1):
            blocks.append(Block(BlockKind.PARAGRAPH, header, page=page))
            blocks.append(Block(BlockKind.PARAGRAPH, f"Body text unique to page {page}.", page=page))
            blocks.append(Block(BlockKind.PARAGRAPH, str(page), page=page))
        return Document(blocks=blocks)

    def test_running_header_and_page_number_are_marked_unspoken(self):
        doc = self._paged_doc("A HISTORY OF TORTOISES")
        assert norm.mark_page_artifacts(doc) > 0
        spoken = [b.text for b in doc.spoken()]
        assert all("HISTORY OF TORTOISES" not in t for t in spoken)
        assert all(not t.isdigit() for t in spoken)
        assert len(spoken) == 8

    def test_a_repeated_line_in_the_body_is_left_alone(self):
        """The old frequency-based approach deleted recurring prose book-wide."""
        blocks = []
        for page in range(1, 9):
            blocks.append(Block(BlockKind.PARAGRAPH, "RUNNING HEADER", page=page))
            blocks.append(Block(BlockKind.PARAGRAPH, "He nodded.", page=page))
            blocks.append(Block(BlockKind.PARAGRAPH, "He nodded.", page=page))
            blocks.append(Block(BlockKind.PARAGRAPH, f"Tail of page {page}.", page=page))
        doc = Document(blocks=blocks)
        norm.mark_page_artifacts(doc)
        spoken = [b.text for b in doc.spoken()]
        assert spoken.count("He nodded.") == 16
        assert "RUNNING HEADER" not in spoken

    def test_short_documents_are_not_analysed(self):
        doc = self._paged_doc("HEADER", pages=2)
        assert norm.mark_page_artifacts(doc) == 0


class TestBuildScript:
    @staticmethod
    def _doc() -> Document:
        return Document(
            title="A Book",
            blocks=[
                Block(BlockKind.HEADING, "A Book", level=1),
                Block(BlockKind.PARAGRAPH, "Front matter prose."),
                Block(BlockKind.HEADING, "Chapter One", level=2),
                Block(BlockKind.PARAGRAPH, "First chapter prose."),
                Block(BlockKind.TABLE, "| a | b |"),
                Block(BlockKind.HEADING, "Chapter Two", level=2),
                Block(BlockKind.PARAGRAPH, "Second chapter prose."),
            ],
        )

    def test_chapters_split_at_headings(self):
        script = norm.build_script(self._doc())
        assert [c.title for c in script.chapters] == ["A Book", "Chapter One", "Chapter Two"]

    def test_chapter_titles_are_spoken_before_the_body(self):
        script = norm.build_script(self._doc())
        assert script.chapters[1].utterances[0].text.startswith("Chapter One.")

    def test_unspoken_blocks_do_not_reach_the_script(self):
        script = norm.build_script(self._doc())
        assert "| a | b |" not in script.as_text()

    def test_chapter_of_maps_utterances_back(self):
        script = norm.build_script(self._doc())
        assert script.chapter_of(0) == 0
        assert script.chapter_of(len(script.utterances()) - 1) == len(script.chapters) - 1
        with pytest.raises(IndexError):
            script.chapter_of(len(script.utterances()))

    def test_deeper_headings_stay_inside_their_chapter(self):
        doc = self._doc()
        doc.blocks.append(Block(BlockKind.HEADING, "A subsection", level=4))
        doc.blocks.append(Block(BlockKind.PARAGRAPH, "Subsection prose."))
        script = norm.build_script(doc, chapter_level=2)
        assert len(script.chapters) == 3
        assert "A subsection" in script.chapters[-1].utterances[0].text

    def test_navigation_sections_with_no_prose_are_skipped(self):
        doc = Document(
            title="A Book",
            blocks=[
                Block(BlockKind.HEADING, "Contents", level=2),
                Block(BlockKind.TABLE, "| Chapter 1 | 3 |"),
                Block(BlockKind.HEADING, "Chapter One", level=2),
                Block(BlockKind.PARAGRAPH, "Real prose."),
            ],
        )
        script = norm.build_script(doc)
        assert [c.title for c in script.chapters] == ["Chapter One"]

    def test_long_chapters_are_split_into_several_utterances(self):
        doc = Document(
            title="Long",
            blocks=[Block(BlockKind.PARAGRAPH, "Sentence number %d here." % i) for i in range(200)],
        )
        script = norm.build_script(doc, chunk_size=500)
        assert len(script.chapters) == 1
        assert len(script.chapters[0].utterances) > 5
        assert all(len(u.text) <= 500 for u in script.utterances())

    def test_an_empty_document_is_refused(self):
        with pytest.raises(ValueError):
            norm.build_script(Document(blocks=[Block(BlockKind.TABLE, "| a |")]))


class TestBylineHeadings:
    """Title-page bylines are marked up as headings but name nobody's chapter.
    Left alone, a single-story text ends up with its whole body filed under
    "By Charlotte Perkins Gilman"."""

    @staticmethod
    def _doc(byline: str) -> Document:
        return Document(
            title="A Story",
            blocks=[
                Block(BlockKind.HEADING, "A STORY", level=1),
                Block(BlockKind.HEADING, byline, level=2),
                Block(BlockKind.PARAGRAPH, "The story itself. " * 200),
            ],
        )

    @pytest.mark.parametrize(
        "byline",
        ["By Charlotte Perkins Gilman", "by Someone", "Translated by J. M. D. Meiklejohn", "Edited by A. Nother"],
    )
    def test_a_byline_does_not_name_a_chapter(self, byline):
        script = norm.build_script(self._doc(byline))
        assert [c.title for c in script.chapters] == ["A STORY"]

    def test_the_byline_is_still_spoken(self):
        script = norm.build_script(self._doc("By Charlotte Perkins Gilman"))
        assert "By Charlotte Perkins Gilman" in script.as_text()

    def test_a_real_chapter_starting_with_by_is_not_mistaken_for_a_byline(self):
        doc = Document(
            title="A Book",
            blocks=[
                Block(BlockKind.HEADING, "CHAPTER ONE", level=2),
                Block(BlockKind.PARAGRAPH, "One prose. " * 200),
                Block(BlockKind.HEADING, "Bygones", level=2),
                Block(BlockKind.PARAGRAPH, "Two prose. " * 200),
            ],
        )
        assert [c.title for c in norm.build_script(doc).chapters] == ["CHAPTER ONE", "Bygones"]


class TestSmallSectionCoalescing:
    """Real books open with a half-title, a title page and an author line. Left
    alone each becomes a two-second chapter before the book starts."""

    @staticmethod
    def _front_matter_doc() -> Document:
        return Document(
            title="A Book",
            blocks=[
                Block(BlockKind.HEADING, "A BOOK", level=2),
                Block(BlockKind.HEADING, "By Someone", level=2),
                Block(BlockKind.PARAGRAPH, "Translated by Another."),
                Block(BlockKind.HEADING, "INTRODUCTION", level=2),
                Block(BlockKind.PARAGRAPH, "Introductory prose. " * 60),
                Block(BlockKind.HEADING, "CHAPTER ONE", level=2),
                Block(BlockKind.PARAGRAPH, "Chapter one prose. " * 60),
            ],
        )

    def test_stub_sections_are_folded_away(self):
        script = norm.build_script(self._front_matter_doc(), min_chapter_chars=400)
        assert [c.title for c in script.chapters] == ["INTRODUCTION", "CHAPTER ONE"]

    def test_folding_loses_no_words(self):
        doc = self._front_matter_doc()
        script = norm.build_script(doc, min_chapter_chars=400)
        text = script.as_text()
        for fragment in ("A BOOK", "By Someone", "Translated by Another"):
            assert fragment in text, fragment

    def test_folding_can_be_switched_off(self):
        script = norm.build_script(self._front_matter_doc(), min_chapter_chars=0)
        # "By Someone" is absent whatever the threshold: a byline never names a
        # chapter (see TestBylineHeadings).
        assert [c.title for c in script.chapters] == ["A BOOK", "INTRODUCTION", "CHAPTER ONE"]
        assert "By Someone" in script.as_text()

    def test_a_trailing_fragment_folds_backwards(self):
        doc = Document(
            title="A Book",
            blocks=[
                Block(BlockKind.HEADING, "CHAPTER ONE", level=2),
                Block(BlockKind.PARAGRAPH, "Chapter one prose. " * 60),
                Block(BlockKind.HEADING, "THE END", level=2),
                Block(BlockKind.PARAGRAPH, "Finis."),
            ],
        )
        script = norm.build_script(doc, min_chapter_chars=400)
        assert [c.title for c in script.chapters] == ["CHAPTER ONE"]
        assert "Finis." in script.as_text()

    def test_uniformly_short_sections_keep_their_chapters(self):
        """A short document with real (if brief) chapters must not be flattened —
        the absolute threshold alone would collapse it into one."""
        doc = Document(
            title="Tiny",
            blocks=[
                Block(BlockKind.HEADING, "ONE", level=2),
                Block(BlockKind.PARAGRAPH, "Short."),
                Block(BlockKind.HEADING, "TWO", level=2),
                Block(BlockKind.PARAGRAPH, "Also short."),
            ],
        )
        script = norm.build_script(doc, min_chapter_chars=400)
        assert [c.title for c in script.chapters] == ["ONE", "TWO"]
        assert "Short." in script.as_text()
        assert "Also short." in script.as_text()

    def test_a_stub_must_be_small_relative_to_its_neighbours(self):
        """400 characters is a stub beside 30,000-character chapters and a real
        chapter beside 600-character ones."""
        long_body = "Long chapter prose. " * 200  # 4,000 chars
        doc = Document(
            title="Mixed",
            blocks=[
                Block(BlockKind.HEADING, "TITLE PAGE", level=2),
                Block(BlockKind.PARAGRAPH, "By Someone"),
                Block(BlockKind.HEADING, "CHAPTER ONE", level=2),
                Block(BlockKind.PARAGRAPH, long_body),
                Block(BlockKind.HEADING, "CHAPTER TWO", level=2),
                Block(BlockKind.PARAGRAPH, long_body),
            ],
        )
        script = norm.build_script(doc, min_chapter_chars=400)
        assert [c.title for c in script.chapters] == ["CHAPTER ONE", "CHAPTER TWO"]
        assert "By Someone" in script.as_text()


class TestNormalizerSelection:
    def test_off_is_the_default_and_is_a_no_op(self):
        normalizer = norm.get_normalizer("off")
        assert isinstance(normalizer, norm.RulesNormalizer)
        assert normalizer.normalize("Dr. Shell, 12kg") == "Dr. Shell, 12kg"

    def test_unknown_normalizer_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown normalizer"):
            norm.get_normalizer("wishful-thinking")

    def test_local_normalizer_resolves_without_contacting_anything(self):
        assert isinstance(norm.get_normalizer("local"), norm.LocalLLMNormalizer)


class TestLLMGuardrails:
    """The guardrails matter more than the feature: a model that quietly rewrites
    a book is worse than one that fails."""

    class _Fake(norm._GuardedNormalizer):
        def __init__(self, reply, **kw):
            super().__init__(**kw)
            self._reply = reply

        def _call_model(self, text):
            if isinstance(self._reply, Exception):
                raise self._reply
            return self._reply

    ORIGINAL = "Dr. Shell studied them for 12 years, and concluded patience is a metabolism."

    def test_a_reasonable_rewrite_is_accepted(self):
        good = "Doctor Shell studied them for twelve years, and concluded patience is a metabolism."
        n = self._Fake(good)
        assert n.normalize(self.ORIGINAL) == good
        assert (n.accepted, n.rejected) == (1, 0)

    def test_a_summary_is_rejected_for_length_drift(self):
        n = self._Fake("Shell studied tortoises.")
        assert n.normalize(self.ORIGINAL) == self.ORIGINAL
        assert n.rejected == 1

    def test_a_preamble_is_rejected(self):
        n = self._Fake("Here is the rewritten passage: " + self.ORIGINAL)
        assert n.normalize(self.ORIGINAL) == self.ORIGINAL

    def test_a_refusal_is_rejected(self):
        n = self._Fake("I cannot help with that request.")
        assert n.normalize(self.ORIGINAL) == self.ORIGINAL

    def test_an_empty_response_is_rejected(self):
        assert self._Fake("   ").normalize(self.ORIGINAL) == self.ORIGINAL

    def test_a_network_error_falls_back_to_the_original(self):
        assert self._Fake(RuntimeError("connection refused")).normalize(self.ORIGINAL) == self.ORIGINAL

    def test_blank_input_is_passed_straight_through(self):
        assert self._Fake("anything").normalize("") == ""
