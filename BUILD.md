# 공개 모드 로더 빌드

일반 사용자는 릴리즈의 실행용 ZIP을 받으세요. 이 문서는 공개 소스 빌드용입니다. Windows 64비트, Python 3.10.11 환경에서 검증합니다.

저장소 또는 실행용 ZIP의 최상위 폴더에서:

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --onefile --windowed --name EslabongCommunityLoader --paths source --add-data "source/package;package" --add-data "source/loader;external-loader" source/public_mod_loader.py
```

생성된 `dist/EslabongCommunityLoader.exe` 옆에 저장소의 `mods` 폴더를 복사하세요. 문서·`LICENSE`·`THIRD_PARTY_NOTICES.md`·`licenses/`도 함께 배포합니다.

```powershell
python source/test_public_loader.py
python source/public_mod_loader.py --settings
python source/public_mod_loader.py --game "실제 게임 폴더" --prepare-only --report "검사결과.json"
```

## 구조

- `source/public_mod_loader.py`: 공개 두 모드 선택, 변경 감지, 캐시, 준비 및 실행. 개인용 모듈을 import하지 않습니다.
- `source/external_pack.py`: 로컬 생성용 시작 팩·오버레이 팩과 프로젝트 설정의 손실 없는 읽기/쓰기.
- `source/loader/Bootstrap.gd`: 가장 앞선 autoload에서 사용자의 원본 팩과 모드 오버레이를 로드합니다.
- `source/loader/Preflight.gd`: 실제 세이브와 분리된 검사 프로필에서 리소스 내용 일치를 확인합니다.
- `source/mod_installer.py`: 기존 공개 리소스 매칭 코드. 로더는 순수 `plan()`만 사용하며 원본을 쓰는 설치 루틴은 호출하지 않습니다.
- `source/pck.py`, `source/gdc.py`: 사용자 소유 리소스와 토큰을 읽습니다. 키는 소유한 EXE에서 메모리 안에서만 찾으며 저장·배포하지 않습니다.
- `source/member_patch.py`, `source/translation_matching.py`: 기존 번역·표시 구문 재사용과 원래 언어 데이터 보호.
- `source/adaptive_relic.py`, `source/relic_hooks.py`, `source/structural_hooks.py`, `source/hook_tokens.py`, `source/relic_contract.py`: 유물 연결과 실제 API 검증.
- `source/package`: 검증된 공개 보완 데이터와 가역 변경 데이터. 원본 게임 코드 전체가 아닙니다.
- `mods/KoreanSupplement`, `mods/RelicPresets`: 사용자가 선택하는 외부 모드 데이터.

실행기 사본과 시작 팩은 각 사용자의 게임에서 로컬로 생성합니다. 원본 EXE·PCK·게임 DLL·`cache`·검사 로그·저장 파일은 배포 대상이 아닙니다. 배포 ZIP에는 공개 소스와 모드 데이터만 넣고, PyInstaller 내장 모듈 목록에도 개인용 기능이 없는지 확인합니다.

모드 payload의 해시는 패키지 매니페스트로 검증됩니다. 보조 코드를 수정할 때에는 해당 해시와 이전 버전 마이그레이션 자료도 함께 갱신·검증해야 합니다. 알 수 없는 사용자 수정은 덮어쓰지 않습니다.

업데이트 대응은 현재 리소스의 원문·표시 구문·함수 호출 관계에 근거합니다. 전혀 다른 엔진·바이트코드·API에 무조건 적용하는 방식이 아닙니다. 미래 구조가 맞지 않으면 안전하게 중단합니다.
