"""Markdown rendering, wikilink parsing and managed blocks.

One renderer serves both the editor's live preview and the read view, so what
you see while typing cannot diverge from what gets saved.

Every rendered document passes through `nh3`. Autoescaping stays on and no
template ever marks user content safe (CLAUDE.md rule 3).
"""
import hashlib
import re

# Closed set. An unknown namespace is left as plain text rather than treated as
# an error — people write [[TODO: something]] and it should not break a scan.
RECORD_NAMESPACES = frozenset(
    ["project", "workstream", "task", "person", "charge", "meeting", "risk",
     "milestone", "note", "location", "portfolio"]
)

WIKILINK = re.compile(r"\[\[([^\[\]|]+?)(?:\|([^\[\]]+?))?\]\]")
TAG = re.compile(r"(?:^|(?<=\s))#([a-zA-Z][\w/-]{1,49})")
FENCE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]+`", re.DOTALL)
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)

ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "em", "strong", "del",
    "ul", "ol", "li", "blockquote", "pre", "code", "a", "img", "table", "thead",
    "tbody", "tr", "th", "td", "span", "div", "input", "sup", "sub",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "class", "data-unresolved"},
    "img": {"src", "alt", "title"},
    "span": {"class"}, "div": {"class"},
    "code": {"class"}, "pre": {"class"},
    "input": {"type", "checked", "disabled"},
    "th": {"align"}, "td": {"align"},
}


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_code(text):
    """Blank out fenced and inline code so scanning ignores what is inside."""
    return FENCE.sub(lambda m: " " * len(m.group(0)), text)


def split_frontmatter(text):
    """Return (frontmatter_dict, body). Malformed YAML is tolerated, not fatal."""
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end():]
    try:
        import yaml

        data = yaml.safe_load(raw)
        return (data if isinstance(data, dict) else {"_raw": raw}), body
    except Exception:
        # A note with broken frontmatter still indexes; the file is the truth
        # and refusing to read it would lose the body as well.
        return {"_unparsed": raw}, body


def parse_links(text):
    """Every wikilink in the body, classified. Ignores anything inside code."""
    found = []
    for match in WIKILINK.finditer(_strip_code(text)):
        target = match.group(1).strip()
        alias = (match.group(2) or "").strip() or None
        namespace, _, remainder = target.partition(":")
        if remainder and namespace.lower() in RECORD_NAMESPACES:
            found.append({
                "kind": "record",
                "type": namespace.lower(),
                "ref": remainder.strip(),
                "text": alias or remainder.strip(),
                "raw": target,
            })
        else:
            found.append({
                "kind": "note",
                "type": None,
                "ref": target,
                "text": alias or target,
                "raw": target,
            })
    return found


def parse_tags(text, frontmatter=None):
    tags = {match.group(1) for match in TAG.finditer(_strip_code(text))}
    if frontmatter:
        declared = frontmatter.get("tags")
        if isinstance(declared, str):
            tags.update(part.strip() for part in declared.split(",") if part.strip())
        elif isinstance(declared, (list, tuple)):
            tags.update(str(part).strip() for part in declared if str(part).strip())
    return sorted(tags)


def _wikilinks_to_html(text, resolver):
    """Rewrite wikilinks to anchors before markdown runs.

    `resolver(link) -> (url, is_resolved)`. An unresolved link still renders,
    marked, because the standard wiki behaviour is to offer to create it.
    """
    def replace(match):
        target = match.group(1).strip()
        alias = (match.group(2) or "").strip() or None
        namespace, _, remainder = target.partition(":")
        if remainder and namespace.lower() in RECORD_NAMESPACES:
            link = {"kind": "record", "type": namespace.lower(), "ref": remainder.strip()}
            label = alias or remainder.strip()
        else:
            link = {"kind": "note", "type": None, "ref": target}
            label = alias or target
        url, resolved = resolver(link)
        marker = "" if resolved else ' class="pos-link-unresolved" data-unresolved="1"'
        return f'<a href="{url}"{marker}>{label}</a>'

    # Protect code spans: rebuild the string, skipping fenced regions.
    output, last = [], 0
    for fence in FENCE.finditer(text):
        output.append(WIKILINK.sub(replace, text[last:fence.start()]))
        output.append(fence.group(0))
        last = fence.end()
    output.append(WIKILINK.sub(replace, text[last:]))
    return "".join(output)


def render(text, resolver=None):
    """Markdown → sanitised HTML, wrapped as Markup.

    Returning `Markup` rather than a plain string is what lets templates write
    `{{ html }}` instead of `{{ html | safe }}`. That matters: `| safe` in a
    template is unreviewable, because you cannot tell from the template whether
    the value was sanitised. Here there is exactly one place that decides, and
    it is this function — which cannot return unsanitised output on any path
    (CLAUDE.md rule 3).
    """
    from html import escape

    from markupsafe import Markup

    body = split_frontmatter(text)[1]
    if resolver is not None:
        body = _wikilinks_to_html(body, resolver)

    try:
        import markdown as markdown_lib
    except ImportError:
        # Degrade to escaped plain text rather than rendering nothing. The page
        # stays readable and it is obvious what is missing.
        return Markup(f"<pre>{escape(body)}</pre>")

    html = markdown_lib.markdown(
        body,
        extensions=["extra", "sane_lists", "toc", "admonition", "nl2br"],
        output_format="html",
    )

    try:
        import nh3
    except ImportError:
        # Without a sanitiser we do not render user HTML at all. Failing closed
        # is the only acceptable direction.
        return Markup(f"<pre>{escape(body)}</pre>")

    return Markup(nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES))


def excerpt(text, length=200):
    body = split_frontmatter(text)[1]
    plain = re.sub(r"[#*`>\-\[\]]", " ", body)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:length] + ("…" if len(plain) > length else "")


def title_from(text, fallback="Untitled"):
    frontmatter, body = split_frontmatter(text)
    if frontmatter.get("title"):
        return str(frontmatter["title"])
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


# --- managed blocks ---------------------------------------------------------
#
# Regions the application refreshes from live data. Everything outside them is
# the author's and is never touched. See docs/NOTES_VAULT_SPEC.md §5A.

BLOCK_OPEN = "<!-- personalos:{name} -->"
BLOCK_CLOSE = "<!-- /personalos:{name} -->"


def _block_pattern(name):
    # Exact-match markers only. A near-miss must not silently capture the rest
    # of the file and overwrite it.
    return re.compile(
        r"(?P<open><!--\s*personalos:" + re.escape(name) + r"\s*-->)"
        r"(?P<body>.*?)"
        r"(?P<close><!--\s*/personalos:" + re.escape(name) + r"\s*-->)",
        re.DOTALL,
    )


def find_blocks(text):
    """Names of every well-formed managed block, ignoring any inside code."""
    scannable = _strip_code(text)
    opens = set(re.findall(r"<!--\s*personalos:([a-z0-9_-]+)\s*-->", scannable))
    closes = set(re.findall(r"<!--\s*/personalos:([a-z0-9_-]+)\s*-->", scannable))
    return sorted(opens & closes), sorted(opens ^ closes)


def replace_block(text, name, content):
    """Swap a managed block's contents. Returns (new_text, changed).

    A block whose closing marker is missing is skipped rather than guessed at —
    guessing would mean overwriting the remainder of somebody's file.
    """
    pattern = _block_pattern(name)
    match = pattern.search(text)
    if not match:
        return text, False

    replacement = f"{match.group('open')}\n{content.strip()}\n{match.group('close')}"
    if match.group(0) == replacement:
        return text, False
    return text[:match.start()] + replacement + text[match.end():], True


def refresh_blocks(text, blocks):
    """Apply several block replacements. Returns (new_text, [names changed])."""
    changed = []
    for name, content in blocks.items():
        text, did = replace_block(text, name, content)
        if did:
            changed.append(name)
    return text, changed
