# Path: proxmox_viewer.py
import logging
import os
import tempfile
from typing import Optional, List
import subprocess

from proxmoxer import ProxmoxAPI


class ProxmoxViewer:
    def __init__(self, host: Optional[str] = None, backend="local",
                 remote_viewer_path='/usr/bin/remote-viewer',
                 **kwargs):
        self.remote_viewer_path = remote_viewer_path
        # remove null value from kwargs
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        self._proxmox = ProxmoxAPI(host=host, service="PVE", backend=backend, **kwargs)

    def remote_viewer(self,
                      vmid: Optional[int] = None,
                      node: Optional[str] = None,
                      args: Optional[List[str]] = None) -> None:
        if node is None:
            node = self._proxmox.nodes.get()[0]['node']
        if vmid is None:
            vms = self._proxmox.nodes(node).qemu.get()
            for vm in vms:
                if vm['status'] == 'running':
                    vmid = vm['vmid']
                    break
        if vmid is None:
            raise ValueError("No running VM found")

        vm_info = self._proxmox.nodes(node).qemu(vmid)
        if vm_info.status.current.get()['status'] != 'running':
            raise ValueError(f"VM {vmid} is not running")

        spiceproxy_data = vm_info.spiceproxy.post()

        if self.remote_viewer_path.endswith('spicy'):
            if args is None:
                args = []
            '''
            for k, v in spiceproxy_data.items():
                if k == 'ca':
                    tmppath = tempfile.mktemp(suffix='.pem')
                    with open(tmppath, 'w') as f:
                        f.write(v)
                    args.append(f"--spice-ca-file={tmppath}")
                elif k == 'tls-port':
                    args.append(f"--secure-port={v}")
                elif k == 'port':
                    args.append(f"--port={v}")
                # elif k == 'host':
                #    args.append(f"--host={v}")
                elif k == 'password':
                    args.append(f"--password={v}")
                elif k == 'proxy':
                    args.append(f"--uri={v.replace('http://', 'spice://')}")
                    # split url in parts, removing protocol
                    v = v.split('://')[1]
                    host = v.split(':')[0]
                    port = v.split(':')[1]
                    args.append(f"--host={host}")
                    args.append(f"--port={port}")
                elif k == 'host-subject':
                    args.append(f"--spice-host-subject={v}")
                else:
                    pass
            '''
            options = spiceproxy_data
            tmppath = tempfile.mktemp(suffix='.pem')
            with open(tmppath, 'w') as f:
                lines = options['ca'].split('\\n')
                for line in lines:
                    f.write(line + '\n')
            args.append(f"--spice-ca-file={tmppath}")
            args.append(f"--secure-port={options['tls-port']}")
            proxy = options['proxy']
            proxy = proxy.replace('pve-1.lan', 'pve-1.loopback.it')
            os.environ['SPICE_PROXY'] = proxy
            args.append(f"--host={options['host']}")
            # args.append(f"--port={port}")
            args.append(f"--spice-host-subject={options['host-subject']}")
            args.append(f"--password={options['password']}")
        else:
            tmppath = tempfile.mktemp()
            with open(tmppath, 'w') as f:
                f.write("[virt-viewer]\n")
                for k, v in spiceproxy_data.items():
                    f.write(f"{k}={v}\n")
            if args is None:
                args = [
                    '--spice-debug', '--full-screen',
                    # '--debug', '--kiosk', '--kiosk-quit=on-disconnect'
                ]
            args.append(tmppath)
        logging.info(f"exec '{self.remote_viewer_path}' {' '.join(args)}")
        # os.execv(self.remote_viewer_path, args)
        proc = subprocess.run([self.remote_viewer_path] + args)
        proc.check_returncode()
        # proc = subprocess.Popen([self.remote_viewer_path] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # proc.wait()


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
        '--debug', '--spice-debug',  '--kiosk', '--kiosk-quit=on-disconnect'
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
