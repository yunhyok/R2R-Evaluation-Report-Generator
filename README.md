# R2R Evaluation Report Generator

측정 결과와 머신러닝 prediction을 `(sample, Row, Node)` 단위로 검증하고, 인쇄소자별
26 × 38 공간 map·confusion matrix·F1 표와 전체 요약을 하나의 Excel workbook으로
생성하는 한국어 Windows 데스크톱 애플리케이션입니다.
측정 데이터 또는 예측 결과 하나만 선택하면 비교 지표 없이 라벨 맵·라벨별 개수와 비율을
정리한 단독 보고서를 생성합니다.

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
