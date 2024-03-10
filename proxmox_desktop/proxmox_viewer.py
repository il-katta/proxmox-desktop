# Path: proxmox_viewer.py
import logging
import os
import subprocess
import tempfile
import time
from typing import Optional, List

from proxmoxer import ProxmoxAPI


class ProxmoxViewer:
    def __init__(self, host: Optional[str] = None, backend="local",
                 remote_viewer_path='/usr/bin/remote-viewer',
                 **kwargs):
        self.remote_viewer_path = remote_viewer_path
        # remove null value from kwargs
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        self._proxmox = ProxmoxAPI(host=host, service="PVE", backend=backend, **kwargs)
        self._restart_delay = 5

    def remote_viewer(self,
                      vmid: Optional[int] = None,
                      node: Optional[str] = None,
                      args: Optional[List[str]] = None,
                      restart: bool = False) -> None:
        start_time = time.time()
        if node is None:
            node = self._proxmox.nodes.get()[0]['node']
        logging.info(f"using node {node}")
        if vmid is None:
            vms = self._proxmox.nodes(node).qemu.get()
            for vm in vms:
                if vm['status'] == 'running':
                    vmid = vm['vmid']
                    break
        if vmid is None:
            raise ValueError("No running VM found")
        logging.info(f"using vmid {vmid}")
        vm_info = self._proxmox.nodes(node).qemu(vmid)
        if vm_info.status.current.get()['status'] != 'running':
            raise ValueError(f"VM {vmid} is not running")

        spiceproxy_data = vm_info.spiceproxy.post()

        tmppath = tempfile.mktemp()
        with open(tmppath, 'w') as f:
            f.write("[virt-viewer]\n")
            for k, v in spiceproxy_data.items():
                f.write(f"{k}={v}\n")
        if args is None:
            complete_args = []
        else:
            complete_args = args[:]
        args.append(tmppath)
        logging.info(f"exec '{self.remote_viewer_path}' {' '.join(complete_args)}")
        try:
            proc = subprocess.run([self.remote_viewer_path] + complete_args)
            proc.check_returncode()
        except subprocess.CalledProcessError:
            pass
        finally:
            if os.path.exists(tmppath):
                try:
                    os.remove(tmppath)
                except Exception:
                    pass

            if restart:
                logging.info(f"restarting remote viewer for vm {vmid}")
                now = time.time()
                if now - start_time < self._restart_delay:
                    time.sleep(self._restart_delay - (now - start_time))
                self.remote_viewer(vmid=vmid, node=node, args=args, restart=restart)
            else:
                logging.info(f"remote viewer for vm {vmid} finished")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('vmid', type=int)
    parser.add_argument('--node', default=None)
    parser.add_argument('--host', default=None)
    parser.add_argument('--backend', default="local")
    parser.add_argument('--user', default='root')
    parser.add_argument('--password', default=None)
    # https only backend
    parser.add_argument('--verify-ssl', type=bool, default=None)
    parser.add_argument('--timeout', type=int, default=None)
    # openssh only backend
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--identity_file', default=None)
    parser.add_argument('--forward-ssh-agent', type=bool, default=None)
    # paramiko only backend
    parser.add_argument('--private-key-file', type=bool, default=None)
    # others
    parser.add_argument('--remote-viewer-path', default='/usr/bin/remote-viewer')
    parser.add_argument('viewer_args', nargs=argparse.ZERO_OR_MORE, default=[
        '--full-screen',
        '--debug', '--spice-debug', '--kiosk', '--kiosk-quit=on-disconnect'
    ])
    cmd_args = parser.parse_args()
    vmid = cmd_args.vmid
    node = cmd_args.node
    viewer_args = cmd_args.viewer_args
    kwargs = vars(cmd_args)
    del kwargs['vmid']
    del kwargs['node']
    del kwargs['viewer_args']
    logging.basicConfig(level=logging.DEBUG)
    ProxmoxViewer(**kwargs).remote_viewer(
        vmid=vmid,
        node=node,
        args=viewer_args
    )


if __name__ == '__main__':
    main()
