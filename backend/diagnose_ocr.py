from __future__ import annotations

import argparse

from app.services.ocr_service import diagnose_ocr


def main():
    parser = argparse.ArgumentParser(description="글빛 서버의 로컬 OCR 준비 상태를 확인합니다.")
    parser.add_argument("--strict", action="store_true", help="OCR이 준비되지 않았으면 종료 코드 1을 반환합니다.")
    arguments = parser.parse_args()
    result = diagnose_ocr()
    print(f"OCR 상태: {result['status']}")
    print(result["message"])
    if result.get("languages"):
        print("사용 가능한 언어: " + ", ".join(result["languages"]))
    if arguments.strict and not result["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
