import argparse
import json
import logging
import sys
from pathlib import Path

import echo.constants as ec
import echo.core as core
import echo.gutenberg as gutenberg
from echo.audio.assemble import FORMATS
from echo.audio.engines import EngineUnavailable, available_engines, engine_names
from echo.extractors import SUPPORTED_SUFFIXES
from echo.normalize import NORMALIZER_NAMES, NormalizerUnavailable
from echo.research import AGENTS, ResearchError, research

log = logging.getLogger(__name__)


def _coerce_playback_speed(arg: str) -> float:
    try:
        rate = float(arg)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid value: '{arg}' is not a valid number.")
    if rate < 0.5 or rate > 3:
        raise argparse.ArgumentTypeError(f"Invalid value: '{arg}' must be between 0.5 and 3")
    return rate


def _json_type(s: str) -> dict:
    """Parse a JSON object, tolerating shell-friendly quoting.

    Strict JSON is tried first; only if that fails do we apply the lenient
    single-quote rewrite (handy from PowerShell, where escaping double quotes is
    painful). The old version rewrote unconditionally, which meant correct JSON
    was rejected.
    """
    try:
        value = json.loads(s)
    except json.JSONDecodeError:
        try:
            lenient = s.replace('"', "").replace("'", '"').replace("\\\\", "/")
            value = json.loads(lenient)
        except json.JSONDecodeError as e:
            raise argparse.ArgumentTypeError(f"Invalid JSON string: {e}")
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("--meta must be a JSON object, e.g. '{\"title\": \"A Book\"}'")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Generate audiobooks from {', '.join(SUPPORTED_SUFFIXES)} files",
    )
    parser.add_argument("file_path", nargs="?", help="Path to the source document.")
    parser.add_argument("-o", "--output", dest="output", default=None, help="Path for the audio file.")

    gutenberg = parser.add_argument_group("Project Gutenberg")
    gutenberg.add_argument(
        "-g",
        "--gutenberg",
        dest="gutenberg",
        metavar="TITLE",
        default=None,
        help="Search Project Gutenberg for this title and convert the best match, instead of a local file.",
    )
    gutenberg.add_argument("--author", default=None, help="Narrow the Gutenberg search to this author.")
    gutenberg.add_argument(
        "--gutenberg-id", type=int, default=None, help="Convert this exact Project Gutenberg book id."
    )
    gutenberg.add_argument(
        "--language", default="en", help="Catalogue language code to search. (Default: en)"
    )
    gutenberg.add_argument(
        "--list-matches",
        action="store_true",
        help="Show what the Gutenberg search finds (with ids) and exit, without converting.",
    )
    gutenberg.add_argument(
        "--prefer",
        choices=("epub", "text"),
        default="epub",
        help="Which Gutenberg edition to download. EPUB keeps chapter structure. (Default: epub)",
    )

    research_group = parser.add_argument_group("Gemini Deep Research")
    research_group.add_argument(
        "-r",
        "--research",
        dest="research",
        metavar="TOPIC",
        default=None,
        help="Research this topic with Gemini Deep Research and narrate the report. Takes 2-15 minutes.",
    )
    research_group.add_argument(
        "--agent",
        choices=tuple(AGENTS),
        default=ec.RESEARCH_AGENT,
        help=f"Deep Research agent depth. (Default: {ec.RESEARCH_AGENT})",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Name for the run, used for the audio filename and title. Required with --research.",
    )
    parser.add_argument(
        "-e",
        "--engine",
        dest="engine",
        default=ec.DEFAULT_ENGINE,
        help=f"TTS engine: {', '.join(engine_names())}. (Default: {ec.DEFAULT_ENGINE})",
    )
    parser.add_argument(
        "-v",
        "--voice",
        dest="voice",
        default=None,
        help="Voice id for the chosen engine. (Default: the engine's own default)",
    )
    parser.add_argument(
        "-s",
        "--speed",
        dest="speed",
        type=_coerce_playback_speed,
        default=ec.DEFAULT_SPEED,
        help=f"Playback speed multiplier. (Default: {ec.DEFAULT_SPEED})",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=FORMATS,
        default=ec.DEFAULT_FORMAT,
        help=f"Output format. m4b carries chapter marks. (Default: {ec.DEFAULT_FORMAT})",
    )
    parser.add_argument(
        "-n",
        "--normalize",
        dest="normalizer",
        choices=NORMALIZER_NAMES,
        default=ec.NORMALIZER,
        help=f"LLM text normalization for narration. (Default: {ec.NORMALIZER})",
    )
    parser.add_argument(
        "-m",
        "--meta",
        dest="mp3_meta",
        type=_json_type,
        default={},
        help='Metadata, e.g. \'{"title": "A Book", "author": "An Author", "image_path": "cover.jpg"}\'',
    )
    parser.add_argument("--first-page", type=int, default=None, help="First PDF page to read (1-indexed).")
    parser.add_argument("--last-page", type=int, default=None, help="Last PDF page to read (inclusive).")
    parser.add_argument("--force-ocr", action="store_true", help="OCR every PDF page, ignoring its text layer.")
    parser.add_argument("--docling", action="store_true", help="Use Docling for extraction (needs `pip install docling`).")
    parser.add_argument("--save", action="store_true", help="Also write the narrated text to a .txt file.")
    parser.add_argument("--transcript", action="store_true", help="Also write an .srt transcript, if the engine reports timings.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore chunks left by an interrupted run.")
    parser.add_argument("--list-voices", action="store_true", help="List the chosen engine's voices and exit.")
    parser.add_argument("--list-engines", action="store_true", help="Show which engines are ready to use and exit.")
    parser.add_argument("--debug", action="store_true", help="Verbose logging.")
    return parser


def main(argv: list[str] = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format=ec.LOG_FORMAT,
        datefmt=ec.LOG_DATE_FORMAT,
        stream=sys.stdout,
    )

    if args.list_engines:
        for engine, ok, reason in available_engines():
            status = "ready" if ok else f"unavailable — {reason}"
            print(f"{engine.name:14} {engine.label:38} {status}")
        return 0

    if args.list_voices:
        core.print_voices(args.engine)
        return 0

    if args.list_matches:
        if not (args.gutenberg or args.author):
            build_parser().error("--list-matches needs --gutenberg TITLE (and optionally --author)")
        matches = gutenberg.search(args.gutenberg or "", args.author, language=args.language)
        if not matches:
            print("No matches. Try fewer words, or drop --author.")
            return 1
        print(f"{'id':>7}  {'downloads':>10}  formats            title — author")
        for book in matches:
            formats = ",".join(book.available_formats())
            print(f"{book.id:>7}  {book.download_count:>10,}  {formats:<18} {book.title} — {book.author}")
        print("\nConvert one with:  --gutenberg-id <id>")
        return 0

    chosen_sources = [bool(args.file_path), bool(args.gutenberg or args.gutenberg_id), bool(args.research)]
    if sum(chosen_sources) > 1:
        build_parser().error("Choose one source: a file path, a Gutenberg search, or --research.")

    if args.research:
        if not args.name:
            build_parser().error("--research needs --name; it names the audio file and the title.")
        try:
            found = research(args.research, args.name, agent=args.agent, keep=args.save,
                             on_progress=log.info)
        except (ResearchError, ValueError) as ex:
            log.error(str(ex))
            return 1
        args.file_path = str(found.path)
        args.mp3_meta = {**found.as_meta(), **args.mp3_meta}
        if found.notes_path:
            log.info(f"Kept the cited report at {found.notes_path}")

    if args.gutenberg or args.gutenberg_id:
        if args.file_path:
            build_parser().error("Give either a file path or a Gutenberg search, not both.")
        try:
            downloaded = gutenberg.fetch(
                title=args.gutenberg,
                author=args.author,
                book_id=args.gutenberg_id,
                language=args.language,
                prefer=args.prefer,
            )
        except (gutenberg.GutenbergError, ValueError) as ex:
            log.error(str(ex))
            return 1
        log.info(f"Converting '{downloaded.book.title}' by {downloaded.book.author}")
        args.file_path = str(downloaded.path)
        # Fill in metadata from the catalogue, without overriding anything given
        # explicitly on the command line.
        args.mp3_meta = {**downloaded.as_meta(), **args.mp3_meta}
        if not args.output:
            args.output = str(Path(downloaded.path).with_suffix(f".{args.fmt}").name)

    if not args.file_path:
        build_parser().error(
            "Give a file path, search Project Gutenberg with --gutenberg TITLE, or "
            "research a topic with --research TOPIC (or use --list-voices / --list-engines)"
        )

    if args.name and not args.output:
        # The name drives the audio filename, for any source.
        args.output = f"{args.name}.{args.fmt}"

    parser_configs = {
        "first_page": args.first_page,
        "last_page": args.last_page,
        "force_ocr": args.force_ocr,
        "use_docling": args.docling,
    }

    log.info(
        f"Source: {args.file_path}\nEngine: {args.engine}\nVoice: {args.voice or '(engine default)'}\n"
        f"Speed: {args.speed}\nFormat: {args.fmt}\nNormalizer: {args.normalizer}\n"
        f"Metadata: {args.mp3_meta}\n--------------------"
    )

    try:
        output_path = core.file_to_audio(
            args.file_path,
            output_path=args.output,
            mp3_meta=args.mp3_meta,
            voice=args.voice,
            speed=args.speed,
            engine=args.engine,
            fmt=args.fmt,
            normalizer=args.normalizer,
            write_text_file=args.save,
            write_transcript=args.transcript,
            parser_configs=parser_configs,
            resume=not args.no_resume,
        )
    except (NormalizerUnavailable, EngineUnavailable) as ex:
        # A missing model server or API key is a setup problem, not a crash.
        log.error(str(ex))
        return 1

    extras = [x for x, on in ((".txt", args.save), (".srt", args.transcript)) if on]
    log.info(f"Wrote {output_path}" + (f" (plus {', '.join(extras)})" if extras else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
