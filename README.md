# R2R Evaluation Report Generator

측정 결과와 머신러닝 prediction을 `(sample, Row, Node)` 단위로 검증하고, 인쇄소자별
26 × 38 공간 map·confusion matrix·F1 표와 전체 요약을 하나의 Excel workbook으로
생성하는 한국어 Windows 데스크톱 애플리케이션입니다.

## 사용자 흐름

1. Measurement와 Prediction의 `.csv` 또는 `.xlsx` 파일을 선택합니다.
2. 출력할 `.xlsx` 경로를 지정하고 **사전 검사**를 실행합니다.
3. 날짜·kgf·SAM 서명으로 제안된 연결을 검토하고 각 행의 **확인** 또는
   **제안 연결 전체 확인**을 선택합니다.
4. 새 raw status가 있으면 3-class와 binary 규칙을 모두 선택합니다.
5. **Excel 생성**을 누른 뒤 통합문서 또는 출력 폴더를 엽니다.

생성 중에는 입력과 규칙이 잠기며 취소할 수 있습니다. 기존 출력은 성공적인 임시 파일
재개방 검증 후에만 교체되므로, 취소나 오류가 기존 workbook을 손상시키지 않습니다.

## 입력 계약

| 입력 | 필수 열 | 선택 보존 열 |
|---|---|---|
| Measurement | `Name`, `Row`, `Node`, `Status` | provenance 열 |
| Prediction | `name`, `row`, `node`, `prediction` | `confidence`, `review_required`, `prob_Normal`, `prob_Open`, `prob_Short`, provenance 열 |

- 좌표는 정수 `Row 1–26`, `Node 1–38`이며 평가에 포함되는 샘플마다 중복 없는 988개가 필요합니다.
- 지원 형식은 `.csv`, `.xlsx`이며 `.xls`는 지원하지 않습니다.
- CSV는 UTF-8-SIG → UTF-8 → CP949 순서로 읽습니다.
- XLSX에 유효한 worksheet가 여러 개면 UI에서 선택해야 합니다.
- 대응 prediction이 없는 measurement 샘플, 중복·누락·범위 초과 좌표, 미해결 라벨은 export를 차단합니다.
- prediction 전용 샘플은 평가에서 제외하고 `Mapping_Audit`에 기록합니다.

## 평가 규칙

- 3-class: `Pass/No Active/None → Normal`, `Open → Open`, `Short → Short`,
  `No Gate Effect → Exclude`.
- 운영 binary 가정: measurement `Pass → Pass`, 그 외 `Fail`; prediction
  `Normal → Pass`, `Open/Short → Fail`; positive class는 `Fail`입니다.
- 정의할 수 없는 precision/recall/F1과 모든 target class가 없는 3-class macro-F1은
  `0`으로 대체하지 않고 `N/A`로 보고합니다.

세부 정의와 설계 근거는 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)에 있습니다.

## 출력 workbook

시트 순서는 `README → Mapping_Audit → Joined_Data → R01…Rnn → Overall Summary`입니다.
각 report tab은 A3 landscape 3쪽으로 출력됩니다.

- Measurement map: `C8:AO34`, 실제 26 × 38 body `D9:AO34`
- Prediction map: `C43:AO69`, 실제 body `D44:AO69`
- Binary Agreement map: `C78:AO104`, 실제 body `D79:AO104`
- 오른쪽 패널: yield·class 분포·raw 교차표·3×3/2×2 matrix·정의와 제한
- `Joined_Data`: 결과 재현에 필요한 좌표·라벨·확률·agreement·source row만 보존
- `README`: 입력 경로, SHA-256, size, mtime, 최종 mapping profile과 운영 가정

## 개발 및 검증

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m r2r_evaluation_report --self-test
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

격리 installer 수명주기 검증은 disposable AppId 전용 installer에만 허용됩니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_installer.ps1 `
  -InstallerPath .\dist\installer\disposable\R2R-Evaluation-Report-Generator-0.1.0-disposable-setup.exe `
  -InstallRoot "$env:TEMP\R2REvaluationReportGenerator-Verification-manual"
```

실제 연구 CSV/XLSX, 생성 workbook, `build/`, `dist/`, installer는 source repository에
commit하지 않습니다. Windows 코드 서명이 없는 installer는 SmartScreen 경고가 발생할
수 있으며, 이 경고는 기능 검증 실패와 별도로 취급합니다.
