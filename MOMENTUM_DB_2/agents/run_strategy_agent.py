import argparse
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def execute_notebook(notebook_path, output_path=None, kernel_name='python3', timeout=600):
    notebook_path = os.path.abspath(notebook_path)
    if not os.path.exists(notebook_path):
        logging.error(f'Notebook not found: {notebook_path}')
        return False

    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)

    ep = ExecutePreprocessor(timeout=timeout, kernel_name=kernel_name)
    try:
        ep.preprocess(nb, {'metadata': {'path': os.path.dirname(notebook_path)}})
    except Exception as e:
        logging.error(f'Error executing notebook: {e}')
        return False

    if not output_path:
        base, ext = os.path.splitext(notebook_path)
        output_path = base + '_executed.ipynb'

    with open(output_path, 'w', encoding='utf-8') as f:
        nbformat.write(nb, f)

    logging.info(f'Executed notebook saved to: {output_path}')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Execute a Jupyter notebook (the momentum script)')
    parser.add_argument('notebook', help='Path to the notebook to execute')
    parser.add_argument('--output', help='Path to save executed notebook', default=None)
    parser.add_argument('--kernel', help='Kernel name', default='python3')
    parser.add_argument('--timeout', help='Execution timeout seconds', type=int, default=600)

    args = parser.parse_args()
    success = execute_notebook(args.notebook, output_path=args.output, kernel_name=args.kernel, timeout=args.timeout)
    if not success:
        raise SystemExit(1)
