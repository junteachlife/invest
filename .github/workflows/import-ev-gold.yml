name: 匯入 EV 黃金歷史資料（免註冊）
on:
  workflow_dispatch:
    inputs:
      year:
        description: '匯入年份（例如 2025）'
        required: true
        default: '2025'
      overwrite:
        description: '是否覆蓋既有月份（建議 false）'
        required: true
        type: boolean
        default: false
permissions:
  contents: write
concurrency:
  group: gold-historical-data
  cancel-in-progress: false
jobs:
  import:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: true
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Convert annual EV M15 data to monthly candles
        shell: bash
        env:
          YEAR: ${{ inputs.year }}
          OVERWRITE: ${{ inputs.overwrite }}
        run: |
          FILE="imports/xauusd/XAUUSD_M15_${YEAR}.json.gz"
          if [ ! -f "$FILE" ]; then
            echo "Missing $FILE. Download XAUUSD M15 $YEAR from https://evtradelabs.com/data and upload this file first."
            exit 1
          fi
          ARGS=()
          if [ "$OVERWRITE" = 'true' ]; then ARGS+=(--overwrite); fi
          python import_ev_gold.py "$FILE" --year "$YEAR" "${ARGS[@]}"
      - name: Commit historical candles
        run: |
          git config user.name 'github-actions[bot]'
          git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
          git add data/xauusd
          if git diff --cached --quiet; then
            echo 'No data changes'
          else
            git commit -m 'Import XAUUSD M15 yearly history from EV Trading Labs'
            git push
          fi
