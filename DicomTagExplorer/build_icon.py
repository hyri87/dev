"""
Hyetoria 아이콘 생성 스크립트.
실행: python build_icon.py  →  assets/hyetoria.ico 생성
"""

import math
from PIL import Image, ImageDraw, ImageFilter

SIZE = 256


def make_frame(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    s   = size
    cx, cy = s / 2, s / 2

    # ── 배경 원 (진한 네이비) ──────────────────────────────────────────
    margin = s * 0.04
    d.ellipse([margin, margin, s - margin, s - margin],
              fill='#0d1b2a')

    # ── 바깥 테두리 링 (청록색) ───────────────────────────────────────
    ring_w = max(2, s * 0.035)
    d.ellipse([margin, margin, s - margin, s - margin],
              outline='#00c8c8', width=int(ring_w))

    # ── 내부 동심원 (희미한 그리드 느낌) ─────────────────────────────
    for r_frac in (0.30, 0.45):
        r = s * r_frac
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline='#1a3a4a', width=max(1, int(s * 0.012)))

    # ── 십자 (크로스) — 의료 느낌 ─────────────────────────────────────
    arm_w  = s * 0.13
    arm_l  = s * 0.38
    cross_color = '#00e5e5'

    # 세로
    d.rectangle([cx - arm_w / 2, cy - arm_l,
                 cx + arm_w / 2, cy + arm_l],
                fill=cross_color)
    # 가로
    d.rectangle([cx - arm_l, cy - arm_w / 2,
                 cx + arm_l, cy + arm_w / 2],
                fill=cross_color)

    # ── 십자 중앙 작은 원 (강조) ──────────────────────────────────────
    dot_r = s * 0.09
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
              fill='#ffffff')

    # ── 스캔라인 (DICOM 느낌의 가로선 3개) ───────────────────────────
    line_color = '#00a0a0'
    lw = max(1, int(s * 0.018))
    for y_off in (-s * 0.22, 0, s * 0.22):
        y = cy + y_off
        # 왼쪽 짧은 선
        d.line([(cx - s * 0.42, y), (cx - s * 0.17, y)],
               fill=line_color, width=lw)
        # 오른쪽 짧은 선
        d.line([(cx + s * 0.17, y), (cx + s * 0.42, y)],
               fill=line_color, width=lw)

    # ── 바깥 원 안쪽에 빛 번짐 (glow 대용 — 반투명 흰 테두리) ─────
    glow_r = s * 0.44
    glow_img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_img)
    gd.ellipse([cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r],
               outline=(0, 200, 200, 60), width=int(s * 0.06))
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=s * 0.025))
    img = Image.alpha_composite(img, glow_img)

    return img


def build_ico(output_path: str):
    sizes   = [256, 128, 64, 48, 32, 16]
    frames  = [make_frame(sz) for sz in sizes]

    # ICO 는 RGBA → RGB+A 를 지원하므로 그대로 저장
    frames[0].save(
        output_path,
        format='ICO',
        sizes=[(sz, sz) for sz in sizes],
        append_images=frames[1:],
    )
    print(f'아이콘 저장 완료: {output_path}')


if __name__ == '__main__':
    import os
    os.makedirs('assets', exist_ok=True)
    build_ico('assets/hyetoria.ico')
