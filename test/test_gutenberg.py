"""Project Gutenberg search, ranking and download.

All network access is stubbed, so these run offline and deterministically. The
live API is exercised by hand (and by ``--list-matches``), not by the suite.
"""

import json

import pytest

import echo.gutenberg as gb

# A trimmed Gutendex payload, shaped exactly like the real one.
AURELIUS = {
    "id": 2680,
    "title": "Meditations",
    "authors": [{"name": "Marcus Aurelius, Emperor of Rome"}],
    "languages": ["en"],
    "download_count": 60197,
    "copyright": False,
    "formats": {
        "text/html": "https://www.gutenberg.org/ebooks/2680.html.images",
        "application/epub+zip": "https://www.gutenberg.org/ebooks/2680.epub3.images",
        "image/jpeg": "https://www.gutenberg.org/cache/epub/2680/pg2680.cover.medium.jpg",
        "application/octet-stream": "https://www.gutenberg.org/files/2680/2680-0.zip",
        "text/plain; charset=utf-8": "https://www.gutenberg.org/ebooks/2680.txt.utf-8",
    },
}


def book(**overrides) -> gb.GutenbergBook:
    payload = {**AURELIUS, **overrides}
    return gb.GutenbergBook.from_api(payload)


class TestNormalizeAuthor:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Austen, Jane", "Jane Austen"),
            ("Twain, Mark", "Mark Twain"),
            ("Doyle, Arthur Conan", "Arthur Conan Doyle"),
            ("Hugo, Victor", "Victor Hugo"),
        ],
    )
    def test_surname_first_is_swapped(self, raw, expected):
        assert gb.normalize_author(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "Marcus Aurelius, Emperor of Rome",  # epithet, not a given name
            "Anonymous",
            "Great Britain. War Office",
            "Dickens, Charles John Huffam",  # three trailing tokens: leave alone
            "Smith, John, Jr.",  # two commas
            "Lecky, William Edward Hartpole",
        ],
    )
    def test_ambiguous_names_are_left_alone(self, raw):
        assert gb.normalize_author(raw) == raw

    def test_empty_input(self):
        assert gb.normalize_author("") == ""
        assert gb.normalize_author(None) == ""


class TestBookRecord:
    def test_parses_the_api_payload(self):
        b = book()
        assert (b.id, b.title, b.download_count) == (2680, "Meditations", 60197)
        assert b.languages == ("en",)
        assert b.copyrighted is False

    def test_author_is_normalized_on_the_way_in(self):
        assert book(authors=[{"name": "Austen, Jane"}]).author == "Jane Austen"

    def test_several_authors_are_joined(self):
        b = book(authors=[{"name": "Austen, Jane"}, {"name": "Twain, Mark"}])
        assert b.author == "Jane Austen, Mark Twain"

    def test_missing_author_says_unknown(self):
        assert book(authors=[]).author == "Unknown"

    def test_label_is_scannable(self):
        assert book().label == "Meditations — Marcus Aurelius, Emperor of Rome  (#2680, 60,197 downloads)"

    def test_format_urls_resolve_by_logical_name(self):
        b = book()
        assert b.url_for("epub").endswith(".epub3.images")
        assert b.url_for("text").endswith(".txt.utf-8")
        assert b.url_for("cover").endswith(".jpg")

    def test_zip_bundles_are_never_offered(self):
        """application/octet-stream is a zip; the pipeline can't read it."""
        b = book(formats={"application/octet-stream": "https://x/2680-0.zip"})
        assert b.available_formats() == []
        assert b.url_for("text") is None

    def test_available_formats_is_ordered_by_preference(self):
        assert book().available_formats() == ["epub", "text", "html"]

    def test_a_text_only_record(self):
        b = book(formats={"text/plain; charset=us-ascii": "https://x/y.txt"})
        assert b.available_formats() == ["text"]
        assert b.url_for("epub") is None


class TestRanking:
    def test_all_title_terms_beats_partial(self):
        good = book(title="The Art of War")
        noise = book(title="Field Artillery Training. 1914")
        assert gb._title_relevance(good, "art of war") > gb._title_relevance(noise, "art of war")

    def test_stopwords_do_not_count_against_a_title(self):
        assert gb._title_relevance(book(title="Art War"), "the art of war") == 2

    def test_an_exact_title_is_not_privileged_over_a_subtitled_edition(self):
        """Gutenberg's canonical editions usually carry a subtitle; privileging an
        exact match promotes obscure reprints."""
        exact = book(title="Frankenstein")
        canonical = book(title="Frankenstein; Or, The Modern Prometheus")
        assert gb._title_relevance(exact, "frankenstein") == gb._title_relevance(canonical, "frankenstein")

    def test_unrelated_titles_score_zero(self):
        assert gb._title_relevance(book(title="A Campfire Girl's Test"), "art of war") == 0


class TestSearch:
    @staticmethod
    def _stub(monkeypatch, results):
        captured = {}

        def fake_get(url, binary=False):
            captured["url"] = url
            return json.dumps({"count": len(results), "results": results})

        monkeypatch.setattr(gb, "_get", fake_get)
        return captured

    def test_empty_query_is_refused(self):
        with pytest.raises(ValueError):
            gb.search("   ")

    def test_title_and_author_go_into_one_query(self, monkeypatch):
        captured = self._stub(monkeypatch, [AURELIUS])
        gb.search("meditations", "Marcus Aurelius")
        assert "meditations+Marcus+Aurelius" in captured["url"]
        assert "languages=en" in captured["url"]

    def test_results_are_ranked_by_title_then_epub_then_popularity(self, monkeypatch):
        noise = {**AURELIUS, "id": 1, "title": "War Office Report", "download_count": 999_999}
        no_epub = {
            **AURELIUS,
            "id": 2,
            "title": "The Art of War",
            "download_count": 500_000,
            "formats": {"text/plain; charset=utf-8": "https://x/y.txt"},
        }
        best = {**AURELIUS, "id": 3, "title": "The Art of War", "download_count": 13_426}
        self._stub(monkeypatch, [noise, no_epub, best])

        ranked = gb.search("art of war")
        assert [b.id for b in ranked] == [3, 2, 1]

    def test_author_filter_narrows_the_results(self, monkeypatch):
        other = {**AURELIUS, "id": 9, "authors": [{"name": "Austen, Jane"}]}
        self._stub(monkeypatch, [AURELIUS, other])
        assert [b.id for b in gb.search("meditations", "Aurelius")] == [2680]

    def test_the_author_filter_never_empties_the_results(self, monkeypatch):
        """Better to show near-misses than nothing at all."""
        self._stub(monkeypatch, [AURELIUS])
        assert len(gb.search("meditations", "Someone Else Entirely")) == 1

    def test_records_with_no_readable_format_are_dropped(self, monkeypatch):
        unreadable = {**AURELIUS, "id": 7, "formats": {"application/rdf+xml": "https://x/y.rdf"}}
        self._stub(monkeypatch, [unreadable])
        assert gb.search("meditations") == []

    def test_limit_is_respected(self, monkeypatch):
        many = [{**AURELIUS, "id": i} for i in range(30)]
        self._stub(monkeypatch, many)
        assert len(gb.search("meditations", limit=5)) == 5

    def test_non_json_is_reported_clearly(self, monkeypatch):
        monkeypatch.setattr(gb, "_get", lambda url, binary=False: "<html>down for maintenance</html>")
        with pytest.raises(gb.GutenbergError, match="isn't JSON"):
            gb.search("meditations")


class TestGet:
    def test_looks_up_by_id(self, monkeypatch):
        monkeypatch.setattr(
            gb, "_get", lambda url, binary=False: json.dumps({"results": [AURELIUS]})
        )
        assert gb.get(2680).title == "Meditations"

    def test_unknown_id_is_an_error(self, monkeypatch):
        monkeypatch.setattr(gb, "_get", lambda url, binary=False: json.dumps({"results": []}))
        with pytest.raises(gb.GutenbergError, match="no book with id"):
            gb.get(999_999_999)


class TestDownload:
    @staticmethod
    def _stub_bytes(monkeypatch, payload=b"EPUBDATA", cover=b"JPEGDATA"):
        calls = []

        def fake_get(url, binary=False):
            calls.append(url)
            return cover if ".jpg" in url else payload

        monkeypatch.setattr(gb, "_get", fake_get)
        return calls

    def test_prefers_epub_and_names_the_file_after_the_book(self, monkeypatch, tmp_path):
        self._stub_bytes(monkeypatch)
        result = gb.download(book(), dest_dir=tmp_path)
        assert result.fmt == "epub"
        assert result.path.name == "pg2680_meditations.epub"
        assert result.path.read_bytes() == b"EPUBDATA"
        assert result.cover_path and result.cover_path.exists()

    def test_text_can_be_requested(self, monkeypatch, tmp_path):
        self._stub_bytes(monkeypatch)
        assert gb.download(book(), dest_dir=tmp_path, prefer="text").path.suffix == ".txt"

    def test_falls_back_when_the_preferred_format_is_absent(self, monkeypatch, tmp_path):
        self._stub_bytes(monkeypatch)
        only_text = book(formats={"text/plain; charset=utf-8": "https://x/y.txt"})
        assert gb.download(only_text, dest_dir=tmp_path, prefer="epub").fmt == "text"

    def test_a_record_with_nothing_readable_is_an_error(self, monkeypatch, tmp_path):
        self._stub_bytes(monkeypatch)
        with pytest.raises(gb.GutenbergError, match="no downloadable text format"):
            gb.download(book(formats={}), dest_dir=tmp_path)

    def test_a_cached_download_is_not_fetched_again(self, monkeypatch, tmp_path):
        calls = self._stub_bytes(monkeypatch)
        gb.download(book(), dest_dir=tmp_path)
        first = len(calls)
        gb.download(book(), dest_dir=tmp_path)
        assert len(calls) == first, "the book should have come from the cache"

    def test_refresh_forces_a_re_download(self, monkeypatch, tmp_path):
        calls = self._stub_bytes(monkeypatch)
        gb.download(book(), dest_dir=tmp_path)
        gb.download(book(), dest_dir=tmp_path, refresh=True)
        assert len(calls) > 2

    def test_cover_art_can_be_skipped(self, monkeypatch, tmp_path):
        self._stub_bytes(monkeypatch)
        assert gb.download(book(), dest_dir=tmp_path, with_cover=False).cover_path is None

    def test_a_failed_cover_does_not_fail_the_book(self, monkeypatch, tmp_path):
        def fake_get(url, binary=False):
            if ".jpg" in url:
                raise gb.GutenbergError("cover 404")
            return b"EPUBDATA"

        monkeypatch.setattr(gb, "_get", fake_get)
        result = gb.download(book(), dest_dir=tmp_path)
        assert result.path.exists()
        assert result.cover_path is None

    def test_an_empty_payload_is_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gb, "_get", lambda url, binary=False: b"")
        with pytest.raises(gb.GutenbergError, match="returned no data"):
            gb.download(book(), dest_dir=tmp_path)

    def test_a_copyrighted_record_warns_but_proceeds(self, monkeypatch, tmp_path, caplog):
        import logging

        self._stub_bytes(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="echo.gutenberg"):
            gb.download(book(copyright=True), dest_dir=tmp_path)
        assert any("copyright" in m.lower() for m in caplog.messages)

    def test_metadata_is_ready_for_the_pipeline(self, monkeypatch, tmp_path):
        self._stub_bytes(monkeypatch)
        meta = gb.download(book(), dest_dir=tmp_path).as_meta()
        assert meta["title"] == "Meditations"
        assert meta["author"] == "Marcus Aurelius, Emperor of Rome"
        assert meta["image_path"].endswith(".jpg")


class TestFetch:
    def test_book_id_skips_the_search(self, monkeypatch, tmp_path):
        def fake_get(url, binary=False):
            if "gutendex" in url:
                return json.dumps({"results": [AURELIUS]})
            return b"EPUBDATA"

        monkeypatch.setattr(gb, "_get", fake_get)
        assert gb.fetch(book_id=2680, dest_dir=tmp_path).book.id == 2680

    def test_no_match_explains_what_to_try(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gb, "_get", lambda url, binary=False: json.dumps({"results": []}))
        with pytest.raises(gb.GutenbergError, match="Try fewer words"):
            gb.fetch("a book that does not exist", dest_dir=tmp_path)


class TestSlug:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Meditations", "meditations"),
            ("Pride and Prejudice", "pride_and_prejudice"),
            ("Moby Dick; Or, The Whale", "moby_dick_or_the_whale"),
            ("", "book"),
            ("!!!", "book"),
        ],
    )
    def test_slugs_are_filesystem_safe(self, raw, expected):
        assert gb._slug(raw) == expected

    def test_long_titles_are_truncated_without_a_trailing_underscore(self):
        slug = gb._slug("A " * 200)
        assert len(slug) <= 60
        assert not slug.endswith("_")
