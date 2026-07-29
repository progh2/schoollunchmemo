"""PyInstaller 진입 스크립트.

개발 중에는 `python -m app` 을 쓰면 되고, 이 파일은 패키징용이다.
PyInstaller가 `-m` 실행을 다루지 못해 별도 진입점이 필요하다.
"""

from app.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
