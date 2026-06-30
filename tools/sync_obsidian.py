#!/usr/bin/env python3
"""옵시디언 노트를 MkDocs의 docs/ 안으로 동기화한다.

- SYNC에 지정한 소스 폴더의 .md 노트를 docs/ 대상 폴더로 복사한다.
- 옵시디언 임베드 ``![[그림.png]]`` 를 표준 마크다운 ``![](assets/그림.png)`` 로 바꾸고,
  참조된 이미지를 ATTACH_DIRS(예: ../사진)에서 찾아 docs 안으로 복사한다.
- 여러 번 실행해도 같은 결과가 나오도록(idempotent) 설계했다.

사용법:
    uv run python tools/sync_obsidian.py
    (또는)  python3 tools/sync_obsidian.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent          # study/  (git 저장소 루트)
VAULT = REPO.parent                                     # ASM/    (옵시디언 볼트 루트)

# 옵시디언 첨부 이미지를 찾을 위치(순서대로 탐색, 못 찾으면 볼트 전체를 재귀 탐색).
ATTACH_DIRS = [VAULT / "사진"]

# (소스 노트 폴더,  docs 안의 대상 폴더) 쌍. 항목을 추가하면 같이 동기화된다.
SYNC = [
    (REPO / "SWE", REPO / "docs" / "SWE"),
]

IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

# ![[파일명]]  또는  ![[파일명|크기/별칭]]
EMBED = re.compile(r"!\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]")

# ── 헬퍼 ───────────────────────────────────────────────────────────────────

def sanitize(filename: str) -> str:
    """URL/파일 경로에서 문제되는 공백 등을 정리한 안전한 파일 이름."""
    stem, ext = os.path.splitext(filename)
    stem = re.sub(r"\s+", "_", stem.strip())
    return stem + ext.lower()


def find_attachment(name: str) -> Path | None:
    """첨부 폴더 → 볼트 전체 순으로 이미지 파일을 찾는다."""
    name = name.strip()
    for d in ATTACH_DIRS:
        candidate = d / name
        if candidate.is_file():
            return candidate
    # fallback: 볼트 전체에서 같은 이름 검색
    for found in VAULT.rglob(name):
        if found.is_file():
            return found
    return None


def with_title(text: str, title: str) -> str:
    """문서 맨 앞에 파일명 기반 title frontmatter를 보장한다.

    MkDocs/awesome-nav는 nav 제목을 본문 첫 H1에서 가져오므로, 파일명이 그대로
    메뉴에 보이도록 title을 주입한다. 이미 title이 있으면 손대지 않는다(멱등).
    """
    esc = title.replace("\\", "\\\\").replace('"', '\\"')
    if text.startswith("---\n") or text.startswith("---\r\n"):
        nl = text.find("\n")
        head_end = text.find("\n---", nl)
        block = text[:head_end] if head_end != -1 else text
        if re.search(r"(?m)^title\s*:", block):
            return text                       # 이미 title 있음 → 유지
        return text[:nl + 1] + f'title: "{esc}"\n' + text[nl + 1:]
    return f'---\ntitle: "{esc}"\n---\n\n' + text


def convert(text: str, note_dest: Path, assets_dir: Path) -> tuple[str, list[str]]:
    """노트 본문의 임베드를 변환하고, 복사해야 할 이미지를 모은다."""
    missing: list[str] = []

    def repl(m: re.Match) -> str:
        target, opt = m.group(1).strip(), (m.group(2) or "").strip()
        ext = os.path.splitext(target)[1].lower()
        if ext not in IMG_EXTS:
            # 이미지가 아닌 임베드(노트 embed 등)는 그대로 둔다.
            return m.group(0)

        src = find_attachment(target)
        if src is None:
            missing.append(target)
            return m.group(0)

        safe = sanitize(target)
        dest = assets_dir / safe
        assets_dir.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)

        rel = os.path.relpath(dest, note_dest.parent)
        url = rel.replace(os.sep, "/").replace(" ", "%20")
        # 크기 지정(|300)이 숫자면 attr_list로 폭 지정
        if opt.isdigit():
            return f"![]({url}){{ width=\"{opt}\" }}"
        alt = opt if opt else ""
        return f"![{alt}]({url})"

    return EMBED.sub(repl, text), missing


# ── 메인 ───────────────────────────────────────────────────────────────────

def main() -> int:
    stage = "--stage" in sys.argv[1:]
    total_notes = 0
    changed_notes = 0
    total_imgs = 0
    all_missing: list[str] = []
    touched: list[Path] = []

    for src_dir, dest_dir in SYNC:
        if not src_dir.is_dir():
            print(f"건너뜀(소스 없음): {src_dir}")
            continue
        touched.append(dest_dir)
        assets_dir = dest_dir / "assets"
        for md in sorted(src_dir.rglob("*.md")):
            rel_md = md.relative_to(src_dir)
            # macOS는 한글 파일명을 NFD로 저장하기도 한다. nav(YAML, NFC)와
            # CI(리눅스, 정규화 구분)에서 어긋나지 않도록 NFC로 통일한다.
            rel_nfc = Path(unicodedata.normalize("NFC", str(rel_md)))
            note_dest = dest_dir / rel_nfc
            note_dest.parent.mkdir(parents=True, exist_ok=True)

            text = md.read_text(encoding="utf-8")
            new_text, missing = convert(text, note_dest, assets_dir)
            new_text = with_title(new_text, note_dest.stem)   # 파일명을 nav 제목으로

            # 변환 결과가 기존 파일과 동일하면 다시 쓰지 않는다(변경 없음 → 빠른 배포).
            old_text = note_dest.read_text(encoding="utf-8") if note_dest.exists() else None
            if old_text == new_text:
                print(f"= {rel_md} (변경 없음)")
            else:
                note_dest.write_text(new_text, encoding="utf-8")
                changed_notes += 1
                print(f"✓ {rel_md}")

            total_notes += 1
            n_imgs = len(EMBED.findall(text)) - len(missing)
            total_imgs += max(n_imgs, 0)
            all_missing += [f"{rel_md}: {x}" for x in missing]

    print(f"\n노트 {total_notes}개 중 {changed_notes}개 갱신, "
          f"{total_notes - changed_notes}개 변경 없음. 이미지 참조 {total_imgs}개 처리 완료.")

    if stage and touched:
        subprocess.run(
            ["git", "add", "--", *[str(p) for p in touched]],
            cwd=REPO, check=False,
        )
        print(f"git에 staged: {', '.join(str(p.relative_to(REPO)) for p in touched)}")

    if all_missing:
        print("\n⚠ 찾지 못한 이미지(원본 파일명 확인 필요):")
        for m in all_missing:
            print(f"   - {m}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
