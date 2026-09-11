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
- `source/package/mods/KoreanSupplement/`: 표시용 이름 코드와 번역 데이터.
- `source/package/mods/RelicPresets/RelicPresets.gd`: 유물 프리셋 및 소유 아이템 이동 처리.
- `source/package/data/`: 게임 코드의 전체 사본이 아닌 검증용 해시와 가역 변경 데이터.

배포된 게임 본체나 복호화 키가 저장소에 필요하지 않습니다. 변경 데이터에는 원본이 포함되지 않으므로, 게임을 보유하지 않은 상태에서 게임 코드를 재생성할 수 없습니다.

변경 데이터와 보조 파일에는 무결성 검사가 있습니다. 모드 코드만 고치고 매니페스트의 해당 해시를 갱신하지 않으면 설치가 중단됩니다. 기존 설치와의 마이그레이션·호환성 검증도 새 배포 전에 다시 수행해야 합니다.

## 검증 범위

초기 배포는 소유한 게임으로 만든 비공개 테스트 입력에서 유물 관련 2,164개 검사와 1,000가지 장착 순열을 통과했습니다. 설치기는 네 가지 모드 구성, 제거, 반복 적용, 기존 패치 전환, 불일치 보호를 검사했습니다. 배포 EXE를 Python 경로가 없는 환경과 한글·공백·괄호·앰퍼샌드가 있는 경로에서도 실행했습니다.

게임에서 추출한 테스트 입력, 개인 저장 파일과 로컬 테스트 경로는 공개 저장소에 포함하지 않습니다. 전체 플레이 화면의 시각 검증을 완료했다는 의미는 아닙니다.
