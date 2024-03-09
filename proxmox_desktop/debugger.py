import os
import sys

__all__ = ['setup_debugger']


def setup_debugger():
    if os.getenv('PYCHARM_DEBUG_HOST', False):
        print("setting up pycharm debugger", file=sys.stderr)  # logging not yet setup
        try:
            import pydevd_pycharm
        except ImportError:
            sys.path.append(os.getenv('PYCHARM_PYDEV_PATH', '/usr/local/pydevd-pycharm.egg'))
            import pydevd_pycharm
        PYCHARM_DEBUG_HOST = os.getenv('PYCHARM_DEBUG_HOST')
        PYCHARM_DEBUG_PORT = int(os.getenv('PYCHARM_DEBUG_PORT'))
        print(f"connecting to pycharm debugger {PYCHARM_DEBUG_HOST}:{PYCHARM_DEBUG_PORT}", file=sys.stderr)
        pydevd_pycharm.settrace(
            PYCHARM_DEBUG_HOST,
            port=PYCHARM_DEBUG_PORT,
            stdoutToServer=True,
            stderrToServer=True
        )
