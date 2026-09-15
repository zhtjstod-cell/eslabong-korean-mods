# 빌드 안내

일반 사용자는 [릴리즈](https://github.com/zhtjstod-cell/eslabong-korean-mods/releases/latest)의 설치 ZIP을 받으면 됩니다. 이 문서는 소스를 살펴보거나 설치기를 직접 빌드할 때만 필요합니다.

## 설치기 빌드

검증한 빌드 환경은 Windows 64비트, Python 3.10.11입니다. 저장소 최상위 폴더에서 실행합니다.

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --onefile --windowed --name EslabongMods --paths source --add-data "source/package;package" source/mod_installer.py
```

완성된 파일은 `dist/EslabongMods.exe`입니다. 배포 시 `LICENSE`, `THIRD_PARTY_NOTICES.md`, `licenses/`도 함께 제공하세요.

설치기 코드를 직접 실행할 수도 있습니다.

```powershell
python source/mod_installer.py
```

## 구성

- `source/mod_installer.py`: 설치 창, 게임 탐색, 리소스 매칭, 백업과 적용.
- `source/pck.py`: 사용자가 보유한 게임의 리소스 팩 읽기. 필요한 키는 해당 실행 파일에서 메모리 안에서만 확인하며 포함하거나 기록하지 않습니다.
- `source/gdc.py`, `source/relic_contract.py`, `source/member_patch.py`: 토큰 읽기, 리소스 구조, 함수·표시 구문 단위 매칭.
- `source/adaptive_relic.py`, `source/structural_hooks.py`, `source/hook_tokens.py`: 현재 주전 저장/불러오기 호출 위치와 필수 API/인자 수를 확인하는 가역 연결. 관련 없는 함수 본문은 변경하지 않습니다.
- `source/package/mods/KoreanSupplement/`: 표시용 이름 코드와 번역 데이터.
- `source/translation_matching.py`: 키·원문 매칭, 같은 분류 내 유일한 번역 재사용, 원래 한국어 보호 및 항목별 복구 기록.
- `PersonalNames.gd`, `DisplayText.gd`, `ScreenText.gd`: 직접 지정한 이름을 보호하는 이름 표시, 명칭·팀명·뉴스·표 머리글 등의 화면용 보조 코드.
- `source/package/mods/RelicPresets/RelicPresets.gd`: 유물 프리셋 및 소유 아이템 이동 처리.
- `source/package/data/`: 게임 코드의 전체 사본이 아닌 검증용 해시와 가역 변경 데이터.

배포된 게임 본체나 복호화 키가 저장소에 필요하지 않습니다. 변경 데이터에는 원본이 포함되지 않으므로, 게임을 보유하지 않은 상태에서 게임 코드를 재생성할 수 없습니다.

변경 데이터와 보조 파일에는 무결성 검사가 있습니다. 모드 코드만 고치고 매니페스트의 해당 해시를 갱신하지 않으면 설치가 중단됩니다. 기존 설치와의 마이그레이션·호환성 검증도 새 배포 전에 다시 수행해야 합니다.

추가 표시 수정은 순서가 있는 레이어로 관리합니다. 기존 레이어를 역순으로 정규화하고 선택한 구성을 정방향으로 적용합니다. 알려진 이전 보조 파일과 번역 기록은 명시된 해시·이전 항목으로만 전환하며, 알 수 없는 사용자 수정은 덮어쓰지 않습니다.

표시용 변경은 함수 전체 → 동일 서명 내 줄 매칭 → 독립적인 정확한 표시 줄 매칭 순으로 확인합니다. 유물은 별도 구조 매칭으로 연결하고 현재 게임의 장착 함수를 호출합니다. 실행 시 고유 ID·슬롯·용량·수량·품질·소유 이력을 검사하고 실패하면 복원합니다. 필수 API나 연결 구조가 없어지면 중단합니다. 번역 원문의 공백은 정규화하지만 숫자·자리표시자·문장 뜻을 유사도만으로 추측하지 않습니다.

현재 패키지는 번역 기록에 한국어 테이블의 내용 해시를 저장합니다. 게임 업데이트가 그 테이블을 별도로 바꿨다면 이전 소유 기록을 보수적으로 해제해 새로 제공된 한국어를 잘못 삭제하지 않습니다. 이 경우 남아 있는 같은 번역을 제거 시 원복할 수 없을 수 있습니다.

## 검증 범위

v1.2.0은 최신 게임 기반 비공개 테스트 입력에서 유물 관련 2,186개 검사와 1,000가지 장착 순열을 통과했습니다. 품질이나 소유 목록이 예기치 않게 바뀌는 경우의 복구도 포함합니다. 공개판 네 구성과 개인용 모드 병용, 제거, 반복 적용, 다른 함수·언어 보존을 검사했습니다. 배포 EXE도 별도로 검사합니다.

게임에서 추출한 테스트 입력, 개인 저장 파일과 로컬 테스트 경로는 공개 저장소에 포함하지 않습니다. 전체 플레이 화면의 시각 검증을 완료했다는 의미는 아닙니다.
