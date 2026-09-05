"""One-shot experiment: turn rendered XHS note images into native Obsidian embeds.

Native embeds keep image clicks/plugin handling inside normal Obsidian behavior. Editable
copies live under Web/Xiaohongshu/_media/ so RAW archive assets stay immutable.

This experiment also adds Xiaohongshu-style per-slide counters and real previous/next
fragment links. A normal `python -m link_brain render --all` restores the renderer output;
user/plugin edits under `_media/` are intentionally never overwritten.
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

from link_brain import storage
from link_brain.render import (
    CONTENT_END,
    CONTENT_START,
    ensure_css_snippet,
    parse_frontmatter,
)

MEDIA_RE = re.compile(
    r'<section class="lb-media"><div class="lb-carousel">(?P<body>.*?)</div>'
    r'(?:<div class="lb-video-badge">.*?</div>)?</section>',
    re.S,
)
IMG_RE = re.compile(r'<img\s+src="(?P<src>[^"]+)"[^>]*>', re.S)
NOTE_OPEN_RE = re.compile(r'<div class="lb-note(?: lb-no-media)?">\s*')
NOTE_CLOSE_RE = re.compile(r'\s*</div>\s*\Z')
CSS_MARKER = '/* link-brain native-media experiment: appended by tools/try_native_media.py */'


def _safe_dir_name(value: str) -> str:
    value = re.sub(r'[^0-9A-Za-z._-]+', '_', value or '').strip('._')
    return value or 'unknown'


def _install_css(vault: Path) -> None:
    """Append experiment CSS to the already-enabled managed link-brain snippet."""
    ensure_css_snippet()
    source = Path(__file__).resolve().parents[1] / 'link_brain' / 'assets' / 'link-brain-native-media.css'
    target = vault / '.obsidian' / 'snippets' / 'link-brain.css'
    base = target.read_text(encoding='utf-8')
    if CSS_MARKER in base:
        return
    experiment = source.read_text(encoding='utf-8')
    target.write_text(base.rstrip() + '\n\n' + CSS_MARKER + '\n' + experiment + '\n', encoding='utf-8')


def _editable_copy(note_path: Path, src: str, item_id: str, index: int, vault: Path) -> str | None:
    src = html.unescape(src).replace('\\', '/')
    source = (note_path.parent / src).resolve()
    vault_resolved = vault.resolve()
    try:
        source.relative_to(vault_resolved)
    except ValueError:
        return None
    if not source.is_file():
        return None

    dest_dir = storage.visible_dir() / '_media' / _safe_dir_name(item_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f'{index:02d}-{source.name}'

    # Once a plugin/user edits the copy it becomes user-owned; never overwrite it.
    if not dest.exists():
        shutil.copy2(source, dest)
    return dest.relative_to(vault).as_posix()


def _native_media_md(rels: list[str], item_id: str) -> str:
    """Build one horizontal native-image carousel with per-slide nav and `n / total`."""
    slug = _safe_dir_name(item_id)
    total = len(rels)
    rows = ['> [!link-brain-media]']

    for index, rel in enumerate(rels, 1):
        if index > 1:
            rows.append('>')

        anchor = f'lb-media-{slug}-{index}'
        bits = [f'<span id="{anchor}" class="lb-native-anchor"></span>']

        if index > 1:
            prev_anchor = f'lb-media-{slug}-{index - 1}'
            bits.append(
                f'<a class="lb-native-arrow lb-native-arrow-left" href="#{prev_anchor}" '
                f'aria-label="上一张" title="上一张">‹</a>'
            )

        bits.append(f'<span class="lb-native-counter">{index} / {total}</span>')
        bits.append(f'![[{rel}]]')

        if index < total:
            next_anchor = f'lb-media-{slug}-{index + 1}'
            bits.append(
                f'<a class="lb-native-arrow lb-native-arrow-right" href="#{next_anchor}" '
                f'aria-label="下一张" title="下一张">›</a>'
            )

        # Keep inline HTML and ![[embed]] in the same Markdown paragraph: the image remains
        # a native Obsidian embed while arrows/counter are only lightweight overlays.
        rows.append('> ' + ' '.join(bits))

    return '\n'.join(rows)


def convert_note(path: Path, vault: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    start = text.find(CONTENT_START)
    end = text.find(CONTENT_END)
    if start == -1 or end == -1 or end <= start:
        return False

    layer = text[start + len(CONTENT_START):end]
    media = MEDIA_RE.search(layer)
    if not media:
        return False

    fm = parse_frontmatter(text)
    link_brain = fm.get('link_brain') if isinstance(fm, dict) else None
    item_id = str((link_brain or {}).get('item_id') or path.stem)

    rels: list[str] = []
    for index, match in enumerate(IMG_RE.finditer(media.group('body')), 1):
        rel = _editable_copy(path, match.group('src'), item_id, index, vault)
        if rel:
            rels.append(rel)
    if not rels:
        return False

    native = _native_media_md(rels, item_id)

    # Replace media while match offsets are valid, then remove the old outer HTML wrapper.
    layer = layer[:media.start()] + '\n\n' + native + '\n\n' + layer[media.end():]
    layer = NOTE_OPEN_RE.sub('', layer, count=1)
    layer = NOTE_CLOSE_RE.sub('\n', layer)

    new_text = text[:start + len(CONTENT_START)] + layer + text[end:]
    path.write_text(new_text, encoding='utf-8')
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description='Try native/editable Obsidian image embeds on rendered XHS notes.')
    parser.add_argument('note', nargs='?', help='Optional visible note path/name; default converts all rendered XHS notes.')
    args = parser.parse_args()

    vault = storage.vault_root()
    visible = storage.visible_dir()
    _install_css(vault)

    if args.note:
        candidate = Path(args.note)
        if not candidate.is_absolute():
            candidate = visible / candidate
        paths = [candidate]
    else:
        paths = sorted(path for path in visible.glob('*.md') if path.is_file())

    changed = 0
    for path in paths:
        if path.is_file() and convert_note(path, vault):
            changed += 1
            print(f'[native-media] {path.name}')

    print(f'[native-media] converted={changed}; native carousel has arrows + page counter')
    print('[native-media] rollback layout/source: python -m link_brain render --all')
    print('[native-media] _media copies are never overwritten; plugin drawings/edits stay there')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
