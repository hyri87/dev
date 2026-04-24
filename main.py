"""
Entry point for the DICOM Viewer.
Run:  python main.py [filepath]
"""

import sys
from tkinterdnd2 import TkinterDnD
from ui.app import DicomViewerApp


def main():
    root = TkinterDnD.Tk()
    app = DicomViewerApp(root)

    # 커맨드라인 인수로 파일 경로가 전달되면 자동으로 열기
    # (Windows 파일 연결 또는 탐색기에서 "연결 프로그램"으로 실행 시)
    if len(sys.argv) > 1:
        root.after(100, lambda: app._load_file(sys.argv[1]))

    root.mainloop()


if __name__ == '__main__':
    main()
