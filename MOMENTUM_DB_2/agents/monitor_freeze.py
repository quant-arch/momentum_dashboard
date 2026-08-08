import argparse
import shutil
import os
import time
from datetime import datetime, date
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def copy_tree(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def now_date():
    return date.today()


def run_monitor(folder_to_protect, backup_dir, poll_interval=30, cutoff_date_str="2026-05-31"):
    cutoff = datetime.strptime(cutoff_date_str, "%Y-%m-%d").date()
    folder_to_protect = os.path.abspath(folder_to_protect)
    backup_dir = os.path.abspath(backup_dir)

    if not os.path.exists(folder_to_protect):
        logging.error(f"Folder to protect does not exist: {folder_to_protect}")
        return

    logging.info(f"Creating backup of {folder_to_protect} at {backup_dir}")
    copy_tree(folder_to_protect, backup_dir)

    logging.info("Initial backup complete. Starting monitoring loop.")

    def snapshot(root):
        state = {}
        for dirpath, _, filenames in os.walk(root):
            for f in filenames:
                p = os.path.join(dirpath, f)
                try:
                    st = os.stat(p)
                    state[os.path.relpath(p, root)] = (st.st_mtime, st.st_size)
                except Exception:
                    state[os.path.relpath(p, root)] = None
        return state

    backup_state = snapshot(backup_dir)

    while now_date() <= cutoff:
        try:
            current_state = snapshot(folder_to_protect)
            if current_state != backup_state:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                temp_save = folder_to_protect + f".changed_{ts}"
                logging.warning("Change detected in protected folder. Restoring from backup.")
                try:
                    # move current to temp location for inspection
                    if os.path.exists(temp_save):
                        shutil.rmtree(temp_save)
                    shutil.move(folder_to_protect, temp_save)
                    copy_tree(backup_dir, folder_to_protect)
                    logging.info(f"Restored {folder_to_protect} from backup. Original moved to {temp_save}")
                except Exception as e:
                    logging.error(f"Failed to restore backup: {e}")
                # refresh snapshot
                backup_state = snapshot(backup_dir)
            time.sleep(poll_interval)
        except KeyboardInterrupt:
            logging.info("Monitor interrupted by user. Exiting.")
            break
        except Exception as e:
            logging.error(f"Monitor error: {e}")
            time.sleep(poll_interval)

    logging.info(f"Cutoff reached ({cutoff}). Monitor exiting.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Monitor and protect a folder by restoring from backup when changes occur until cutoff date.')
    parser.add_argument('folder', help='Folder to protect (absolute or relative path)')
    parser.add_argument('--backup', help='Backup directory path (will be created/overwritten)', default=None)
    parser.add_argument('--poll', help='Polling interval seconds', type=int, default=30)
    parser.add_argument('--cutoff', help='Cutoff date YYYY-MM-DD (inclusive)', default='2026-05-31')

    args = parser.parse_args()
    backup_dir = args.backup if args.backup else args.folder.rstrip(os.sep) + '_frozen_backup'
    run_monitor(args.folder, backup_dir, poll_interval=args.poll, cutoff_date_str=args.cutoff)
