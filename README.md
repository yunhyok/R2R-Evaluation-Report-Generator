# R2R Evaluation Report Generator

전기 측정 결과, 머신러닝 prediction, 광학(육안·VLM) 라벨 등 여러 라벨 데이터셋을
`(sample, Row, Node)` 단위로 정렬하고, 인쇄소자별 공간 map과 사용자가 고른 비교
(자기 평가: confusion matrix·F1·κ / 교차 연관: χ²·Cramér's V·odds ratio 등)를 하나의
Excel workbook으로 생성하는 한국어 Windows 데스크톱 애플리케이션입니다.

## v0.5 단계형 워크플로

기본 화면은 다섯 단계를 순서대로 진행하는 위저드입니다(이전 단계를 수정하면 이후 단계는
무효화됩니다).

1. **데이터셋** — 파일을 필요한 만큼 추가하고 역할(전기 측정 기준 / 전기 ML 예측 / 광학 육안 /
   광학 VLM / 기타), 시트, Inspector 모델 열, 격자(기본 26 × 38)를 지정한 뒤
   **불러오기·정렬 검사**를 실행합니다. 첫 행이 기준 데이터셋이며, 날짜·kgf·SAM 서명으로 제안된
   샘플 정렬을 행마다 또는 **제안 전체 확인**으로 확정합니다.
2. **라벨 체계** — 데이터셋마다 자동 식별된 체계(`legacy_electrical`, `electrical_e5`,
   `ml_3class`, `optical_3`, …)를 확인합니다. 체계 밖 라벨이 있으면 진행이 막힙니다.
3. **비교 정의** — 비교를 0개 이상 추가합니다. *자기 평가*는 A(정답)·B(예측)를 공통 범주로
   매핑(프리셋 또는 직접 지정)하고, *교차 연관*은 원본 라벨 그대로 또는 매핑 후 대칭 지표와
   관심 2×2 셀(예: `E-Invalid × BAD`)을 지정합니다.
4. **출력 옵션** — 출력 경로, 공간 map/Joined_Data/색상 전용 사본 포함 여부, 제목. 프로파일
   JSON으로 저장·불러오기할 수 있습니다.
5. **생성** — 요약을 확인하고 Excel을 생성합니다. `<stem>.profile.json`이 함께 저장되며
   `--profile FILE`로 동일 리포트를 다시 만들 수 있습니다.

`--legacy-ui`는 v0.4의 두 입력 화면을 엽니다(측정·예측 비교, 단독 보고서).

## 지원 입력

| 출처 | 형식 | 식별 |
|---|---|---|
| R2R-TXT-Converter 측정 | CSV/XLSX `Name, Row, Node, Status` | 이름·좌표 |
| R2R-Machine-Learning 예측 | CSV/XLSX `name, row, node, prediction` (+ confidence, prob_*) | 이름·좌표 |
| ImageMarker 2.x 육안 라벨 | 측정 XLSX의 `Status` 덮어쓰기본 또는 `name,row,node,label` CSV | 이름·좌표 |
| Printed-Device-AI-Inspector VLM 라벨 | long/matrix CSV (`image_path`, `provider:model_id` 열) | 파일명 `<name>_rgb_<row>_<node>.png` |

라벨 체계와 매핑 프리셋은 `src/r2r_evaluation_report/schemes/label_schemes.json`에 있으며
`%APPDATA%\R2R Evaluation Report Generator\label_schemes.json`으로 추가·덮어쓸 수 있습니다.
지표 정의와 참고문헌은 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)의 "Profile reports" 절을
참조하세요.

---

아래는 v0.4까지의 두 입력 화면(`--legacy-ui`)에 대한 설명입니다.

## 다운로드

[정식 릴리스](https://github.com/yunhyok/R2R-Evaluation-Report-Generator/releases/latest)에서
Windows 설치 파일과 SHA-256 확인 파일을 받을 수 있습니다.
저장소 공개와 별개로 사용·수정·배포 조건은 [LICENSE](LICENSE)를 따릅니다.

## 사용자 흐름

1. Measurement 또는 Prediction의 `.csv` 또는 `.xlsx` 파일을 하나 이상 선택합니다.
   두 파일을 모두 선택하면 비교 보고서, 하나만 선택하면 해당 입력의 단독 보고서입니다.
2. 출력할 `.xlsx` 경로를 지정하고 **사전 검사**를 실행합니다.
3. 비교 보고서에서는 날짜·kgf·SAM 서명으로 제안된 연결을 검토하고 각 행의 **확인** 또는
   **제안 연결 전체 확인**을 선택합니다.
4. 비교 보고서에 새 raw status가 있으면 3-class, binary, 확장 Normal 규칙을 모두 선택합니다.
   단독 보고서는 연결·라벨 재분류 없이 입력 라벨을 그대로 표시합니다.
5. **Excel 생성**을 누르면 선택한 경로에 코드 포함 workbook과
   `<stem>-color-only.xlsx` 색상 전용 sibling workbook을 함께 생성한 뒤 각각 열 수 있습니다.

생성 중에는 입력과 규칙이 잠기며 취소할 수 있습니다. 두 workbook 후보를 모두
재개방 검증한 뒤에만 기존 출력 두 개를 교체하며, 취소·오류 시 기존 파일을 복원합니다.
프로세스가 두 파일 교체 사이에서 강제 종료되는 경우는 파일시스템 경계입니다. 남은
transaction backup이 있으면 자동 재실행을 막으므로, 먼저 백업을 보존·검토한 뒤 수동
복구 또는 제거가 필요할 수 있습니다.

## 입력 계약

| 입력 | 필수 열 | 선택 보존 열 |
|---|---|---|
| Measurement | `Name`, `Row`, `Node`, `Status` | provenance 열 |
| Prediction | `name`, `row`, `node`, `prediction` | `confidence`, `review_required`, `prob_Normal`, `prob_Open`, `prob_Short`, provenance 열 |

- 좌표는 정수 `Row 1–26`, `Node 1–38`이며 평가에 포함되는 샘플마다 중복 없는 988개가 필요합니다.
- 지원 형식은 `.csv`, `.xlsx`이며 `.xls`는 지원하지 않습니다.
- CSV는 UTF-8-SIG → UTF-8 → CP949 순서로 읽습니다.
- XLSX에 유효한 worksheet가 여러 개면 UI에서 선택해야 합니다.
- 두 입력을 비교할 때 대응 prediction이 없는 measurement 샘플과 미해결 라벨은 export를 차단합니다.
- 비교에서 prediction 전용 샘플은 평가에서 제외하고 `Mapping_Audit`에 기록합니다.
  예측 단독 보고서에서는 입력의 모든 샘플을 포함합니다.
- 모든 모드에서 중복·누락·범위 초과 좌표는 차단합니다. 단독 입력도 샘플별 988개 좌표가 필요합니다.
- [TXT Converter v1.3.0](https://github.com/yunhyok/R2R-TXT-Converter/tree/v1.3.0)의
  `_raw.csv` (`name,row,node,status`)와 `_merged.csv` (`Name,Row,Node,Status`)를 측정 입력으로
  사용할 수 있습니다. [R2R Machine Learning](https://github.com/yunhyok/R2R-Machine-Learning)의
  `predictions.csv` (`name,row,node,prediction`)는 예측 입력입니다.

## 평가 규칙

- 3-class: `Pass/No Active/None → Normal`, `Open → Open`, `Short → Short`,
  `No Gate Effect → Exclude`.
- Expanded Normal scenario: `Pass/No Active/None/No Gate Effect → Normal`, `Open → Open`, `Short → Short`.
  이는 원래 전기적 ground truth를 재라벨링하지 않는 이미지 관찰/리포팅 가정이며 raw/3-class/binary 결과를 보존합니다.
- 운영 binary 가정: measurement `Pass → Pass`, 그 외 `Fail`; prediction
  `Normal → Pass`, `Open/Short → Fail`; positive class는 `Fail`입니다.
- 정의할 수 없는 precision/recall/F1과 모든 target class가 없는 3-class macro-F1은
  `0`으로 대체하지 않고 `N/A`로 보고합니다.

세부 정의와 설계 근거는 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)에 있습니다.

## 출력 workbook

비교 보고서 시트 순서는 `README → Mapping_Audit → Joined_Data → R01…Rnn → Overall Summary`입니다.
각 report tab은 A3 landscape 4쪽으로 출력됩니다.

- Measurement map: `C8:AO34`, 실제 26 × 38 body `D9:AO34`
- Prediction map: `C43:AO69`, 실제 body `D44:AO69`
- Binary Agreement map: `C78:AO104`, 실제 body `D79:AO104`
- Expanded Normal scenario map: `C113:AO139`, 실제 body `D114:AO139`
- 오른쪽 패널: yield·class 분포·raw 교차표·3×3/2×2 matrix·정의와 제한
- `Joined_Data`: 결과 재현에 필요한 좌표·라벨·확률·agreement·source row와 Expanded Normal 필드를 보존
- `README`: 입력 경로, SHA-256, size, mtime, 최종 mapping profile과 운영 가정
- 코드 포함 workbook의 map body에는 짧은 상태 코드와 색상 fill이 있습니다.
- 색상 전용 workbook은 `D9:AO34`, `D44:AO69`, `D79:AO104`, `D114:AO139`의
  map body 값만 비우고 fill·테두리·축·legend·표·차트·감사 데이터는 유지합니다.

단독 보고서의 시트 순서는 `README → Source_Data → R01…Rnn → Overall Summary`입니다.
각 샘플은 A3 가로 한 페이지에 26×38 라벨 맵(`D9:AO34`)과 범례·개수·비율을 표시합니다.
요약에는 전체 및 샘플별 라벨 분포와 전체 분포 그래프가 있으며, F1·정확도·혼동행렬·일치도·
확장 Normal 비교는 생성하지 않습니다. 측정의 사용자 정의 라벨도 보존하며, 예측은 기존처럼
Normal/Open/Short만 허용합니다. 색상 전용 파일과 입력 출처·해시 기록은 모든 모드에서 유지합니다.

## 개발 및 검증

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m r2r_evaluation_report --self-test
.\.venv\Scripts\python.exe -m r2r_evaluation_report --profile run.profile.json --output run.xlsx
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

격리 installer 수명주기 검증은 disposable AppId 전용 installer에만 허용됩니다. v0.3.0의
실제 연구 데이터와 paired workbook, source UI DPI smoke, packaged self-test/GUI DPI smoke,
default-host packaged actual UI, installed actual UI DPI smoke, and installer lifecycle evidence
passed locally on 2026-08-26; 상세 해시는 [docs/VALIDATION.md](docs/VALIDATION.md)에
기록했습니다. 정식 배포를 위한 재검증 기록도 같은 문서에서 확인할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_installer.ps1 `
  -InstallerPath .\dist\installer\disposable\R2R-Evaluation-Report-Generator-0.3.0-disposable-setup.exe `
  -InstallRoot "$env:TEMP\R2REvaluationReportGenerator-Verification-manual"
```

The installed real-data/DPI harness is disposable-AppId-only and refuses reused roots or output
pairs. It runs hidden install/self-test/offscreen smoke at effective 100/125/150% and then calls
`scripts/verify_actual_ui.ps1` for each paired real-data output:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_installed_actual_ui.ps1 `
  -InstallerPath .\dist\installer\disposable\R2R-Evaluation-Report-Generator-0.3.0-disposable-setup.exe `
  -InstallRoot "$env:TEMP\R2REvaluationReportGenerator-Verification-manual" `
  -MeasurementPath C:\path\measurement.csv -PredictionPath C:\path\predictions.csv `
  -OutputPath C:\path\acceptance.xlsx
```

실제 연구 CSV/XLSX, 생성 workbook, `build/`, `dist/`, installer는 source repository에
commit하지 않습니다. Windows 코드 서명이 없는 installer는 SmartScreen 경고가 발생할
수 있으며, 이 경고는 기능 검증 실패와 별도로 취급합니다.
