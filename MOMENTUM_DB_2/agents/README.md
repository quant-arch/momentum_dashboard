Agents for protecting old output and running the momentum notebook

1) monitor_freeze.py

Purpose: Monitor a folder and restore it from a backup if any changes occur until a specified cutoff date (inclusive).

Usage example (PowerShell):

    # from workspace root
    python MOMENTUM_DB_2\agents\monitor_freeze.py \
        "MOMENTUM_DB_2\Stocks_old\Nifty_500_2025_Apr_20_stocks_results" \
        --backup "MOMENTUM_DB_2\Stocks_old\Nifty_500_2025_Apr_20_stocks_results_frozen_backup" \
        --poll 30 \
        --cutoff 2026-05-31

Notes:
- The script creates a full backup (overwrite if exists) and monitors the target folder.
- On detecting changes, it moves the current folder to a timestamped `.changed_YYYYMMDD_HHMMSS` folder and restores the backup.
- Run this as a long-running process (tmux/screen/service) or as a scheduled task.

2) run_strategy_agent.py

Purpose: Execute the `Momentum Stocks Monthly.ipynb` notebook programmatically to produce the updated windows.

Usage example:

    python MOMENTUM_DB_2\agents\run_strategy_agent.py \
        "MOMENTUM_DB_2\Momentum Stocks Monthly.ipynb" \
        --output "MOMENTUM_DB_2\Momentum Stocks Monthly_executed.ipynb" \
        --timeout 1200

Notes:
- This uses `nbconvert`'s `ExecutePreprocessor`. Ensure `nbconvert` and `nbformat` are installed in the Python environment.
- The notebook will run in the notebook's directory context, so relative paths inside the notebook will resolve correctly.
- Review logs for any failures (TrueData connectivity, credentials, etc.).

Security & safety
- The monitor restores from backup; it does not change system ACLs. You may prefer to set OS-level file permissions if you want stricter enforcement.
- Test both scripts on a small sample folder first.

If you want, I can:
- Run the monitor for you now (start monitoring process).
- Execute the notebook now and confirm which files are created/updated.
- Make the monitor set file attributes to read-only on Windows for extra protection.
