import hashlib
import warnings

import genanki

from .notes import Note, Cloze
from .helpers.tag_handler import handle_tags, merge_tags
from .helpers.text_formatting import remove_keyword_lines
from .helpers.image_processor import ImageProcessor
from .constants import FORMAT_WARNING_STRING, CODE_KEYWORDS, CLOZE_TAG, CODE_TAG


def file_to_preprocessed_cards(input_lines: list, file_name: str, base_tag: str) -> list:
    """
    Legacy entry point kept for the old scripts: parse the lines of a markdown file into rendered Note objects.
    Cards already marked ``ADDED`` are skipped. New code should use ``markdown2anki.parser`` and ``.build``.
    :param input_lines: list of lines from the input file
    :param file_name: name of the input file (its stem becomes the last tag part - e.g. "Python::FileName")
    :param base_tag: base tag for the package (e.g. "Python")
    :return: list of cards that need to be processed into different note types
    """
    from pathlib import Path
    from .parser import parse_lines, Diagnostic
    from .render import render_markdown

    diagnostics: list = []
    cards = parse_lines(input_lines, Path(file_name), base_tag, diagnostics=diagnostics)
    for diagnostic in diagnostics:
        if diagnostic.level == "error":
            print(f"ERROR: {diagnostic.message} (Filename: {file_name}, line {diagnostic.line})")

    card_list = []
    for card in cards:
        if card.added:
            continue
        note = Note(card.question, card.answer, [card.tag])
        note.front = render_markdown(card.question)
        note.back = render_markdown(card.answer)
        card_list.append(note)
    return card_list


def create_cards(card_list: list, image_processor: ImageProcessor) -> list:
    stored_notes = []
    for card in card_list:
        card: Note
        if "cloze" in card.get_initial_front().lower():
            if "image" in card.get_initial_front().lower():
                image_processor.process_image_occlusion(card.back, card.tags[0])
            else:
                cloze: Cloze = card.convert_to_cloze()
                image_processor.apply(cloze)
                stored_notes.append(cloze.get_basic_note_type())
        else:
            # Handle images
            image_processor.apply(card)

            # Create a new note with the question and answer
            for keyword in CODE_KEYWORDS:
                if keyword in card.get_initial_front() or keyword in card.get_initial_back():
                    card.tags.append(CODE_TAG)
                    card.set_front(remove_keyword_lines(card.front, CODE_KEYWORDS))
                    card.set_back(remove_keyword_lines(card.back, CODE_KEYWORDS))
                    break

            stored_notes.append(card.get_basic_note_type())

    return stored_notes


def create_package(note_list: list, image_processor: ImageProcessor, package_title: str, output: bool = True) -> None:
    """
    Create a new Anki package with the given cards and media files
    :param note_list: list of notes to be added to the package
    :param image_processor: ImageProcessor instance to handle images
    :param package_title: title of the package
    :param output: boolean to indicate if the output should be printed
    :return: None
    """
    # Create a new deck with given title
    deck_id = (1 << 30) + int(hashlib.sha1(package_title.encode('utf-8')).hexdigest()[:8], 16) % (1 << 30)
    deck = genanki.Deck(deck_id, package_title)

    for note in note_list:
        deck.add_note(note)

    package = genanki.Package(deck)
    package.media_files = image_processor.media_files

    with warnings.catch_warnings(record=True) as warning_list:
        package.write_to_file(f'{package_title}.apkg')

    # Output stats
    if output:
        print(f"PACKAGE SUMMARY")
        print(f"- Added {len(deck.notes)} notes to the deck")
        # calculate number of clozes
        num_clozes = sum(1 for note in note_list if isinstance(note, genanki.Note) and CLOZE_TAG in note.tags)
        print(f"- Added {num_clozes} cloze notes to the deck")

        print(f"- Added {len(image_processor.media_files)} media files to the deck")
        if image_processor.tags_mapped_to_images.keys():
            print("\nIMAGE OCCLUSIONS:")

            for key in image_processor.tags_mapped_to_images.keys():
                print(f"{key}")
                for image in image_processor.tags_mapped_to_images[key]:
                    print(f"- {image}")
        else:
            print("- No image occlusions available")

        if warning_list:
            print("")
            print("WARNINGS:")
            for warning in warning_list:
                if issubclass(warning.category, UserWarning) and str(warning.message).startswith(FORMAT_WARNING_STRING):
                    print(f"- Formatting Warning:{str(warning.message).replace(FORMAT_WARNING_STRING, '')}")
                else:
                    print(f"- Warning: {warning.message}")
