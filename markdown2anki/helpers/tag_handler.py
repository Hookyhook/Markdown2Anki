import re

HEADING_RE = re.compile(r"^(#+)\s*(.*)$")


def handle_tags(new_heading: str, tags: list) -> list:
    """
    Given a heading line and the current tag stack, return the updated stack. The first two entries
    (base tag, file name) are fixed; a heading of level N replaces everything from depth N on.
    Only the leading ``#`` characters count, so ``# C# Basics`` is a level-1 heading named "C# Basics".
    """
    match = HEADING_RE.match(new_heading)
    if not match:
        return tags
    level = len(match.group(1))
    text = match.group(2).strip()
    fixed = min(2, len(tags))
    keep = fixed + level - 1
    tags = tags[:keep] if len(tags) > keep else list(tags)
    tags.append(text)
    return tags


def merge_tags(tags: list) -> str:
    """
    Merge tags into a single hierarchical tag: spaces become underscores, a leading single digit is
    zero-padded (9 -> 09) so tags sort naturally, parts are joined with "::".
    """
    parts = []
    for tag in tags:
        if not tag:
            continue
        if len(tag) >= 2 and tag[0].isdigit() and tag[0] != "0" and not tag[1].isdigit():
            tag = "0" + tag
        elif len(tag) == 1 and tag.isdigit() and tag != "0":
            tag = "0" + tag
        parts.append(tag.replace(". ", "_").replace(" ", "_"))
    return "::".join(parts)
