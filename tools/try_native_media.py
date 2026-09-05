"""One-shot experiment: turn rendered XHS note images into native Obsidian embeds.

Why this exists:
- raw HTML <img> widgets fall back to source when clicked in Live Preview;
- native ![[image]] embeds behave like ordinary Obsidian images and are visible to image plugins;
- archived RAW must stay immutable, so editable copies live under Web/Xiaohongshu/_media/.

This is deliberately a post-render experiment, not a core renderer migration yet.
Run `python -m link_brain render --all` to restore the current renderer output.
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

from link_brain import storage
from link_brain.render import CONTENT_END, CONTENT_START, parse_frontmatter

MEDIA_RE = re.compile(
    r'<section class="lb-media"><div class="lb-carousel">(?P<body>.*?)</div>'
    r'(?:<div class="lb-video-badge">.*?</div>)?</section>',
    re.S,
)
IMG_RE = re.compile(r'<img\s+src="(?P<src>[^"]+)"[^>]*>', re.S)
NOTE_OPEN_RE = re.compile(r'<div class="lb-note(?: lb-no-media)?">\s*')
NOTE_CLOSE_RE = re.compile(r'\s*</div>\s*\Z')


def _safe_dir_name(value: str) -> str:
    value = re.sub(r'[^0-9A-Za-z._-]+', '_', value or '').strip('._')
    return value or 'unknown'


def _install_css(vault: Path) -> None:
    source = Path(__file__).resolve().parents[1] / 'link_brain' / 'assets' / 'link-brain-native-media.css'
    target = vault / '.obsidian' / 'snippets' / 'link-brain-native-media.css'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


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

    # Critical: never overwrite this copy. Once a plugin/user draws on it, it is user-owned.
    if not dest.exists():
        shutil.copy2(source, dest)
    return dest.relative_to(vault).as_posix()


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
    for i, match in enumerate(IMG_RE.finditer(media.group('body')), 1):
        rel = _editable_copy(path, match.group('src'), item_id, i, vault)
        if rel:
            rels.append(rel)
    if not rels:
        return False

    # Remove the renderer's outer lb-note wrapper for this experiment. The native media callout,
    # author row, Markdown body and comment section then become normal sizer children.
    layer = NOTE_OPEN_RE.sub('', layer, count=1)
    layer = NOTE_CLOSE_RE.sub('\n', layer)

    rows = ['> [!link-brain-media]']
    for i, rel in enumerate(rels):
        if i:
            rows.append('>')
        rows.append(f'> ![[{rel}]]')
    native = '\n'.join(rows)
    layer = layer[:media.start()] + '\n\n' + native + '\n\n' + layer[media.end():]

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
        paths = sorted(p for p in visible.glob('*.md') if p.is_file())

    changed = 0
    for path in paths:
        if path.is_file() and convert_note(path, vault):
            changed += 1
            print(f'[native-media] {path.name}')
    print(f'[native-media] converted={changed}; css=link-brain-native-media.css')
    print('[native-media] Obsidian 设置 → 外观 → CSS 片段：打开 link-brain-native-media')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
